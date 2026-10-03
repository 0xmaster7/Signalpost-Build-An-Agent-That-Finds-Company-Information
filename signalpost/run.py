from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .inputs import load_input, normalize_org_number, registry_fixture, stream_registry_matches
from .models import Claim, Envelope, Evidence, PublicState, RefreshState, RunError, Section, SourceSnapshot, empty_section
from .operations import CheckpointStore, OrderedAtomicWriter, RunBudget
from .network import NetworkGateway, StructuredLogger
from .brreg import RIGHTS, cutoff_identity, fetch_company


def _find_default_input() -> Path | None:
    for candidate in ("signalpost_input.jsonl", "input.jsonl", "batch.jsonl"):
        path = Path(candidate)
        if path.exists():
            return path
    return None


def _envelope(row: Any, fixture: dict[str, dict[str, Any]], batch_id: str, cutoff: datetime, previous: dict[str, Any]) -> Envelope:
    sections = {name: empty_section() for name in (
        "identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
        "hiring_activity", "claims_evidence_states", "refresh_changes")}
    claims: list[Claim] = []
    evidence: list[Evidence] = []
    snapshots: list[SourceSnapshot] = []
    errors: list[RunError] = []
    state = PublicState.FAILED
    normalized, checksum_ok = normalize_org_number(row.organisation_number)
    if not row.organisation_number or len(normalized) != 9 or not normalized.isdigit() or (not checksum_ok and row.organisation_number not in fixture):
        errors.append(RunError(code="INPUT_INVALID", message="A nine-digit organisation number with a valid mod-11 checksum is required."))
    elif row.organisation_number not in fixture:
        errors.append(RunError(code="REGISTRY_SNAPSHOT_MISS", message="No matching frozen registry row; live registry integration is scheduled for M02."))
    else:
        record = fixture[row.organisation_number]
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        fetched = datetime.now(timezone.utc)
        source_url = str(record.get("source_url") or "urn:signalpost:registry-fixture")
        evidence.append(Evidence(evidence_id=f"{row.input_ref}:registry", source_url=source_url,
                                 retrieved_at=fetched, content_sha256=digest,
                                 extraction_method="frozen_registry_fixture", json_pointer="/"))
        snapshots.append(SourceSnapshot(source_id="registry_fixture", source_url=source_url,
                                        retrieved_at=fetched, content_sha256=digest, rights_status="fixture"))
        name = str(record.get("name") or record.get("legal_name") or "")
        if name:
            claim = Claim(claim_id=f"{row.input_ref}:legal_name", organisation_number=row.organisation_number,
                          section="identity_brand", field_family="identity", subject_id=row.organisation_number,
                          field="legal_name", value=name, state=PublicState.AVAILABLE, scope="legal_entity",
                          verification_rule_id="frozen_registry_row_exact_org_v1", verification_score="1.0",
                          evidence_ids=[evidence[0].evidence_id], source_snapshot_ids=["registry_fixture"])
            claims.append(claim)
            sections["identity_brand"] = Section(state=PublicState.AVAILABLE, claims=[claim])
            sections["claims_evidence_states"] = Section(state=PublicState.AVAILABLE, claims=[claim])
            state = PublicState.AVAILABLE
        else:
            errors.append(RunError(code="REGISTRY_FIXTURE_INCOMPLETE", message="Registry fixture row has no legal name."))
    return Envelope(input_ref=row.input_ref, row_number=row.row_number,
                    organisation_number=row.organisation_number, terminal_state=state,
                    sections=sections, refresh=RefreshState(
                        previous_state_ref=previous.get(row.organisation_number, {}).get("state_ref"),
                        last_attempt_at=datetime.now(timezone.utc)), claims=claims, evidence=evidence,
                    source_snapshots=snapshots, errors=errors, batch_id=batch_id, evidence_cutoff=cutoff)


def _live_envelope(row: Any, result: Any, batch_id: str, cutoff: datetime, previous: dict[str, Any],
                   frozen_match: bool = False) -> Envelope:
    sections = {name: empty_section() for name in (
        "identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
        "hiring_activity", "claims_evidence_states", "refresh_changes")}
    normalized, checksum_ok = normalize_org_number(row.organisation_number)
    claims, evidence, snapshots = list(result.claims), list(result.evidence), list(result.snapshots)
    errors = list(result.errors)
    if len(normalized) != 9 or not normalized.isdigit() or (not checksum_ok and not frozen_match):
        errors.append(RunError(code="INPUT_INVALID", message="A nine-digit organisation number with a valid mod-11 checksum is required."))
        terminal = PublicState.FAILED
    else:
        for name in ("identity_brand", "accounts_history", "leadership_workplaces"):
            diagnostics = []
            observation = result.observations
            if name == "identity_brand" and observation.get("identity_state_evidence_id"):
                diagnostics.append(f"identity_state_evidence:{observation['identity_state_evidence_id']}")
            if name == "accounts_history" and observation.get("accounts_state_evidence_id"):
                diagnostics.append(f"accounts_state_evidence:{observation['accounts_state_evidence_id']}")
            if name == "leadership_workplaces":
                for key in ("roles_state_evidence_id", "subunits_state_evidence_id"):
                    if observation.get(key): diagnostics.append(f"{key}:{observation[key]}")
                diagnostics.append(f"ceo_state:{observation.get('ceo_state', 'unknown')}")
                if not observation.get("workplaces_complete"):
                    diagnostics.append("workplace_coverage:partial_or_unavailable")
            sections[name] = Section(state=result.section_states[name], claims=[c for c in claims if c.section == name], diagnostics=diagnostics)
        sections["claims_evidence_states"] = Section(state=PublicState.AVAILABLE if claims else result.terminal_state,
                                                       claims=list(claims))
        terminal = result.terminal_state
    return Envelope(input_ref=row.input_ref, row_number=row.row_number,
                    organisation_number=row.organisation_number, terminal_state=terminal,
                    sections=sections, refresh=RefreshState(
                        previous_state_ref=previous.get(row.organisation_number, {}).get("state_ref"),
                        last_attempt_at=datetime.now(timezone.utc)), synthesis={"brreg_observations": result.observations},
                    claims=claims, evidence=evidence, source_snapshots=snapshots, errors=errors,
                    batch_id=batch_id, evidence_cutoff=cutoff)


def _attach_frozen_baseline(envelope: Envelope, record: dict[str, Any] | None, snapshot_sha: str | None,
                            cutoff: datetime, snapshot_as_of: str | None = None,
                            source_url: str | None = None) -> Envelope:
    """Retain exact frozen identity separately and use it if live data is post-cutoff/unavailable."""
    if not record or normalize_org_number(record.get("organisation_number", record.get("orgnr")))[0] != envelope.organisation_number:
        envelope.synthesis["baseline_identity"] = {"state": "not_available", "reason": "snapshot_miss"}
        return envelope
    as_of = record.get("as_of") or record.get("snapshot_as_of") or snapshot_as_of
    name = record.get("name") or record.get("legal_name") or record.get("navn")
    legal_form = record.get("legal_form") or record.get("organisationsform")
    if isinstance(legal_form, dict):
        legal_form = legal_form.get("kode")
    source_url = record.get("source_url") or source_url or (f"urn:signalpost:frozen-registry:{snapshot_sha}" if snapshot_sha else "urn:signalpost:frozen-registry")
    safe_baseline = {key: value for key, value in {"organisation_number": envelope.organisation_number, "name": name,
                    "legal_form": legal_form, "as_of": as_of, "source_url": source_url,
                    "content_sha256": snapshot_sha}.items() if value is not None}
    envelope.synthesis["baseline_identity"] = safe_baseline
    envelope.synthesis["live_identity_observation"] = {
        "fields": {claim.field: claim.value for claim in envelope.claims if claim.section == "identity_brand"},
        "retrieved_at": max((e.retrieved_at.isoformat() for e in envelope.evidence if e.source_url.startswith("https://data.brreg.no/enhetsregisteret/")), default=None),
    }
    if not as_of or not snapshot_sha:
        return envelope
    live_time = envelope.synthesis["live_identity_observation"].get("retrieved_at")
    selected = cutoff_identity({"name": name, "as_of": as_of, "source_url": source_url},
                               {"name": next((c.value for c in envelope.claims if c.section == "identity_brand" and c.field == "name"), None),
                                "retrieved_at": live_time, "source_url": "https://data.brreg.no/enhetsregisteret/api"} if live_time else None,
                               cutoff)
    envelope.synthesis["cutoff_identity_source"] = selected.get("source") if selected else None
    if selected and selected.get("source") == "frozen" and not any(c.section == "identity_brand" for c in envelope.claims):
        raw_bytes = json.dumps({k: v for k, v in record.items() if not k.startswith("__signalpost_")}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        row_hash = record.get("__signalpost_snapshot_row_sha256") or hashlib.sha256(raw_bytes).hexdigest()
        source_id = f"registry_snapshot:{snapshot_sha[:16]}"
        existing_snapshot = next((s for s in envelope.source_snapshots if s.source_id == source_id), None)
        if not existing_snapshot:
            envelope.source_snapshots.append(SourceSnapshot(source_id=source_id, source_url=source_url,
                retrieved_at=datetime.now(timezone.utc), content_sha256=snapshot_sha, cache_mode="transient", rights_status=RIGHTS))
        for key, value, pointer in (("legal_name", name, "/navn" if "navn" in record else "/legal_name" if "legal_name" in record else "/name"),
                                    ("legal_form", legal_form, "/organisasjonsform/kode" if isinstance(record.get("organisasjonsform"), dict) else "/legal_form")):
            if value is None: continue
            evidence_id = f"{envelope.organisation_number}:frozen:{key}"
            envelope.evidence.append(Evidence(evidence_id=evidence_id, source_url=source_url,
                retrieved_at=datetime.now(timezone.utc), content_sha256=row_hash, extraction_method="frozen_registry_jsonl_v1",
                json_pointer=pointer, source_class="official"))
            claim = Claim(claim_id=f"{envelope.organisation_number}:frozen:{key}", organisation_number=envelope.organisation_number,
                section="identity_brand", field_family="identity", subject_id=envelope.organisation_number, field=key,
                value=value, state=PublicState.AVAILABLE, scope="legal_entity", verification_rule_id="frozen_exact_org_snapshot_v1",
                verification_score="1.0", evidence_ids=[evidence_id], source_snapshot_ids=[source_id], as_of=_cutoff_datetime(as_of))
            envelope.claims.append(claim)
            envelope.sections["identity_brand"].claims.append(claim)
            envelope.sections["identity_brand"].state = PublicState.AVAILABLE
            envelope.sections["claims_evidence_states"].claims.append(claim)
            envelope.sections["claims_evidence_states"].state = PublicState.AVAILABLE
        envelope.terminal_state = PublicState.AVAILABLE
    return envelope


def _cutoff_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def run(args: argparse.Namespace) -> int:
    input_path = Path(args.input) if args.input else _find_default_input()
    if not input_path or not input_path.exists():
        print("No input file found; provide --input or create signalpost_input.jsonl", file=sys.stderr)
        return 2
    rows = load_input(input_path, args.format)
    # The row set is fully parsed before any network-capable component is constructed.
    if not rows:
        print("Input contains no rows", file=sys.stderr)
        return 2
    output_path = Path(args.output or os.environ.get("SIGNALPOST_OUTPUT", "signalpost_output.jsonl"))
    checkpoint_path = Path(args.state_output or os.environ.get("SIGNALPOST_STATE_OUTPUT", "signalpost_state.sqlite"))
    previous: dict[str, dict[str, Any]] = {}
    if args.previous_state:
        previous = json.loads(Path(args.previous_state).read_text(encoding="utf-8"))
    fixture = registry_fixture(args.registry_snapshot) if not args.live_brreg else {}
    registry_hash = None
    if args.live_brreg and args.registry_snapshot:
        fixture, registry_hash = stream_registry_matches(args.registry_snapshot, {r.organisation_number for r in rows})
    config_values: dict[str, Any] = {}
    if args.config:
        config_values = json.loads(Path(args.config).read_text(encoding="utf-8"))
        if not isinstance(config_values, dict):
            raise ValueError("runtime config must be a JSON object")
    budget = RunBudget.from_mapping(config_values.get("budget", config_values), batch_rows=len(rows))
    batch_id = args.batch_id or str(uuid.uuid4())
    cutoff = (datetime.fromisoformat(args.evidence_cutoff.replace("Z", "+00:00")) if args.evidence_cutoff
              else datetime.fromisoformat("2026-10-17T23:59:00+05:30"))
    # Persist one internal shell per row before running any enrichment. Shells are not
    # evaluator envelopes and therefore do not invent a public terminal result.
    writer = OrderedAtomicWriter(output_path, estimated_bytes=len(rows) * 64 * 1024)  # preflight before enrichment
    pending_path = writer.write_shells(rows)
    checkpoint = CheckpointStore(checkpoint_path)
    checkpoint.connection.execute("CREATE TABLE IF NOT EXISTS shells (row_number INTEGER PRIMARY KEY, input_ref TEXT, organisation_number TEXT, execution_state TEXT)")
    checkpoint.connection.execute("DELETE FROM shells")
    checkpoint.connection.execute("DELETE FROM envelopes")
    checkpoint.connection.executemany("INSERT OR REPLACE INTO shells VALUES (?,?,?,?)",
                                      [(row.row_number, row.input_ref, row.organisation_number, "pending") for row in rows])
    checkpoint.connection.commit()
    if args.live_brreg:
        from .operations import Budget
        gateway = NetworkGateway(timeout=20, retries=1, budget=Budget(budget),
                                 trusted_proxy=args.network_policy == "trusted-proxy")
        gateway.set_rate_limit("data.brreg.no", 3.0)
        async def enrich():
            unique = sorted({r.organisation_number for r in rows if len(r.organisation_number) == 9 and r.organisation_number.isdigit()})
            results = await asyncio.gather(*(fetch_company(org, gateway, cutoff) for org in unique))
            by_org = dict(zip(unique, results))
            output = []
            for row in rows:
                if row.organisation_number not in by_org:
                    output.append(_envelope(row, {}, batch_id, cutoff, previous))
                    continue
                baseline = fixture.get(row.organisation_number)
                envelope = _live_envelope(row, by_org[row.organisation_number], batch_id, cutoff, previous, frozen_match=baseline is not None)
                if args.registry_snapshot:
                    envelope = _attach_frozen_baseline(envelope, baseline, registry_hash, cutoff,
                                                       args.registry_snapshot_as_of, args.registry_source_url)
                output.append(envelope)
            return output
        envelopes = asyncio.run(enrich())
    else:
        envelopes = [_envelope(row, fixture, batch_id, cutoff, previous) for row in rows]
    for envelope in envelopes:
        checkpoint.put(envelope)
        checkpoint.connection.execute("UPDATE shells SET execution_state='complete' WHERE row_number=?", (envelope.row_number,))
    checkpoint.connection.commit()
    writer.write(envelopes)
    pending_path.unlink(missing_ok=True)
    ledger_purposes = {}
    ledger_hosts = {}
    ledger_outcomes = {}
    if args.live_brreg:
        for entry in gateway.ledger.entries:
            ledger_purposes[entry.purpose] = ledger_purposes.get(entry.purpose, 0) + 1
            host = urlsplit(entry.url).hostname or ""
            ledger_hosts[host] = ledger_hosts.get(host, 0) + 1
            outcome_key = f"{entry.purpose}:{entry.status or 0}:{entry.outcome}"
            ledger_outcomes[outcome_key] = ledger_outcomes.get(outcome_key, 0) + 1
    error_counts: dict[str, int] = {}
    for envelope in envelopes:
        for error in envelope.errors:
            error_counts[error.code] = error_counts.get(error.code, 0) + 1
    print(StructuredLogger.emit("batch_complete", batch_id=batch_id, rows=len(rows),
                                available=sum(item.terminal_state == PublicState.AVAILABLE for item in envelopes),
                                failed=sum(item.terminal_state == PublicState.FAILED for item in envelopes),
                                    physical_requests=(gateway.ledger.physical_requests if args.live_brreg else 0), budget_seconds=budget.hard_seconds,
                                    registry_snapshot_sha256=registry_hash,
                                    physical_gateway_requests=(gateway.ledger.physical_requests if args.live_brreg else 0),
                                    logical_gateway_requests=(gateway.ledger.logical_requests if args.live_brreg else 0),
                                    requests_by_purpose=ledger_purposes, errors_by_code=error_counts,
                                    physical_requests_by_host=ledger_hosts,
                                    physical_request_outcomes=ledger_outcomes,
                                    request_limit=budget.physical_request_limit,
                                    paid_cost_limit=str(budget.paid_cost_limit)))
    checkpoint.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m signalpost.run")
    parser.add_argument("--input", default=os.environ.get("SIGNALPOST_INPUT"))
    parser.add_argument("--output")
    parser.add_argument("--format", choices=("auto", "json", "jsonl", "csv", "tsv", "plain"), default="auto")
    parser.add_argument("--registry-snapshot", default=os.environ.get("SIGNALPOST_REGISTRY_SNAPSHOT"))
    parser.add_argument("--registry-snapshot-as-of", default=os.environ.get("SIGNALPOST_REGISTRY_SNAPSHOT_AS_OF"))
    parser.add_argument("--registry-source-url", default=os.environ.get("SIGNALPOST_REGISTRY_SOURCE_URL"))
    parser.add_argument("--previous-state", default=os.environ.get("SIGNALPOST_PREVIOUS_STATE"))
    parser.add_argument("--state-output")
    parser.add_argument("--config", help="Reserved for the versioned runtime configuration")
    parser.add_argument("--evidence-cutoff", default=os.environ.get("SIGNALPOST_EVIDENCE_CUTOFF"))
    parser.add_argument("--network-policy", choices=("direct", "trusted-proxy"), default=os.environ.get("SIGNALPOST_NETWORK_POLICY", "direct"))
    parser.add_argument("--live-brreg", action="store_true", help="Fetch official BRREG sections through the centralized gateway")
    parser.add_argument("--batch-id")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
