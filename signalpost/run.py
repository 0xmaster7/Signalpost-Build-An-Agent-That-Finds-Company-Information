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
from .network import NetworkGateway, StructuredLogger, registered_domain
from .brreg import RIGHTS, cutoff_identity, fetch_company


def _website_profile(org: str, *, live_result: Any | None = None, frozen: dict[str, Any] | None = None,
                     frozen_sha: str | None = None, frozen_source_url: str | None = None) -> dict[str, Any]:
    """Build exact-org website inputs without promoting the registry URL itself."""
    profile: dict[str, Any] = {"organisation_number": org}
    if live_result:
        identity = live_result.observations.get("identity_profile") or {}
        profile.update(identity)
        profile["website_candidates"] = list(live_result.observations.get("website_candidates", []))
        profile["registered_roles"] = [str(claim.value) for claim in live_result.claims
            if claim.section == "leadership_workplaces" and claim.field == "role.role_description" and isinstance(claim.value, str)]
        parent = identity.get("parent_organisation_number") or live_result.observations.get("parent_organisation_number")
        if parent:
            profile["related_organisation_numbers"] = [str(parent)]
    if frozen and normalize_org_number(frozen.get("organisation_number", frozen.get("orgnr")))[0] == org:
        name = frozen.get("name") or frozen.get("legal_name") or frozen.get("navn")
        if not profile.get("name") and name:
            profile["name"] = name
        if not profile.get("legal_form"):
            form = frozen.get("legal_form") or frozen.get("organisationsform")
            profile["legal_form"] = form.get("kode") if isinstance(form, dict) else form
        profile.setdefault("historical_names", frozen.get("historical_names") or [])
        if str(profile.get("legal_form") or "").upper() == "ENK":
            profile["business_address"] = None
            profile["postal_address"] = None
        else:
            profile.setdefault("business_address", frozen.get("business_address") or frozen.get("forretningsadresse") or frozen.get("registered_address") or {})
            profile.setdefault("postal_address", frozen.get("postal_address") or frozen.get("postadresse") or {})
        row_hash = frozen.get("__signalpost_snapshot_row_sha256")
        if not row_hash:
            row_hash = hashlib.sha256(json.dumps({k:v for k,v in frozen.items() if not k.startswith("__signalpost_")},
                ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        source_url = frozen.get("source_url") or frozen_source_url
        raw_website = frozen.get("website") or frozen.get("website_url") or frozen.get("hjemmeside")
        if raw_website and source_url and frozen_sha:
            profile.setdefault("website_candidates", []).append({"raw": raw_website, "source": "registry_frozen",
                "source_url": source_url, "content_sha256": row_hash,
                "evidence_id": f"{org}:frozen-website-candidate:{row_hash[:12]}",
                "source_snapshot_id": f"registry_snapshot:{frozen_sha[:16]}"})
        elif raw_website:
            profile.setdefault("website_candidate_without_source_url", True)
    return profile


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
    if args.live_websites and not args.live_brreg and not args.registry_snapshot:
        print("--live-websites requires --live-brreg or --registry-snapshot for exact-company identity anchors", file=sys.stderr)
        return 2
    output_path = Path(args.output or os.environ.get("SIGNALPOST_OUTPUT", "signalpost_output.jsonl"))
    checkpoint_path = Path(args.state_output or os.environ.get("SIGNALPOST_STATE_OUTPUT", "signalpost_state.sqlite"))
    previous: dict[str, dict[str, Any]] = {}
    if args.previous_state:
        previous = json.loads(Path(args.previous_state).read_text(encoding="utf-8"))
    fixture = registry_fixture(args.registry_snapshot) if not (args.live_brreg or args.live_websites) else {}
    registry_hash = None
    if (args.live_brreg or args.live_websites) and args.registry_snapshot:
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
    gateway = None
    live_by_org: dict[str, Any] = {}
    if args.live_brreg or args.live_websites:
        from .operations import Budget
        gateway = NetworkGateway(timeout=20, retries=1, budget=Budget(budget),
                                 trusted_proxy=args.network_policy == "trusted-proxy")
        if args.live_brreg:
            gateway.set_rate_limit("data.brreg.no", 3.0)
        async def enrich():
            unique = sorted({r.organisation_number for r in rows if len(r.organisation_number) == 9 and r.organisation_number.isdigit()})
            by_org = {}
            if args.live_brreg:
                results = await asyncio.gather(*(fetch_company(org, gateway, cutoff) for org in unique))
                by_org = dict(zip(unique, results))
            output = []
            for row in rows:
                if args.live_brreg and row.organisation_number not in by_org:
                    output.append(_envelope(row, {}, batch_id, cutoff, previous))
                    continue
                baseline = fixture.get(row.organisation_number)
                if args.live_brreg:
                    result = by_org[row.organisation_number]
                    envelope = _live_envelope(row, result, batch_id, cutoff, previous, frozen_match=baseline is not None)
                    live_by_org[row.organisation_number] = result
                    if args.registry_snapshot:
                        envelope = _attach_frozen_baseline(envelope, baseline, registry_hash, cutoff,
                                                           args.registry_snapshot_as_of, args.registry_source_url)
                else:
                    envelope = _envelope(row, fixture, batch_id, cutoff, previous)
                output.append(envelope)
            if args.live_websites:
                from .websites import research_company, sanitize_registry_websites
                # Discover shared roots across input entities before evaluating any one company.
                profiles = {org: _website_profile(org, live_result=live_by_org.get(org), frozen=fixture.get(org),
                    frozen_sha=registry_hash, frozen_source_url=args.registry_source_url) for org in unique}
                root_owners: dict[str, set[str]] = {}
                for org, profile in profiles.items():
                    for candidate in profile.get("website_candidates", []):
                        raw = candidate.get("raw", "") if isinstance(candidate, dict) else candidate
                        for item in sanitize_registry_websites(raw):
                            if item["kind"] == "website":
                                root = registered_domain(urlsplit(item["url"]).hostname or "")
                                if root: root_owners.setdefault(root, set()).add(org)
                shared_roots = {root for root, owners in root_owners.items() if len(owners) > 1}
                website_results = await asyncio.gather(*(research_company(profile, gateway, shared_domains=shared_roots,
                    enable_keyless=not args.no_keyless_websites) for profile in profiles.values()))
                by_website_org = dict(zip(profiles, website_results))
                for envelope in output:
                    result = by_website_org.get(envelope.organisation_number)
                    if not result:
                        continue
                    envelope.claims.extend(result.claims)
                    envelope.evidence.extend(result.evidence)
                    envelope.source_snapshots.extend(result.snapshots)
                    section = envelope.sections["website_owned_profiles"]
                    section.claims.extend(result.claims)
                    section.state = result.state if not result.claims else PublicState.AVAILABLE
                    envelope.sections["claims_evidence_states"].claims.extend(result.claims)
                    if result.claims:
                        envelope.sections["claims_evidence_states"].state = PublicState.AVAILABLE
                    envelope.errors.extend(result.errors)
                    envelope.synthesis["website_research"] = result.audit
                    # Revalidate the complete canonical envelope and its evidence references.
                    envelope.__class__.model_validate(envelope.model_dump())
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
    if gateway:
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
                                physical_requests=(gateway.ledger.physical_requests if gateway else 0), budget_seconds=budget.hard_seconds,
                                    registry_snapshot_sha256=registry_hash,
                                    physical_gateway_requests=(gateway.ledger.physical_requests if gateway else 0),
                                    logical_gateway_requests=(gateway.ledger.logical_requests if gateway else 0),
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
    parser.add_argument("--live-websites", action="store_true", help="Discover and verify website candidates through the centralized gateway")
    parser.add_argument("--no-keyless-websites", action="store_true", help="Disable conservative one-candidate .no discovery")
    parser.add_argument("--batch-id")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
