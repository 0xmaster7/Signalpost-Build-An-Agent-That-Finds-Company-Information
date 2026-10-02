from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .inputs import load_input, normalize_org_number, registry_fixture
from .models import Claim, Envelope, Evidence, PublicState, RefreshState, RunError, Section, SourceSnapshot, empty_section
from .operations import CheckpointStore, OrderedAtomicWriter, RunBudget
from .network import StructuredLogger


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
    fixture = registry_fixture(args.registry_snapshot)
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
    envelopes = [_envelope(row, fixture, batch_id, cutoff, previous) for row in rows]
    for envelope in envelopes:
        checkpoint.put(envelope)
        checkpoint.connection.execute("UPDATE shells SET execution_state='complete' WHERE row_number=?", (envelope.row_number,))
    checkpoint.connection.commit()
    writer.write(envelopes)
    pending_path.unlink(missing_ok=True)
    print(StructuredLogger.emit("batch_complete", batch_id=batch_id, rows=len(rows),
                                available=sum(item.terminal_state == PublicState.AVAILABLE for item in envelopes),
                                failed=sum(item.terminal_state == PublicState.FAILED for item in envelopes),
                                    physical_requests=0, budget_seconds=budget.hard_seconds,
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
    parser.add_argument("--previous-state", default=os.environ.get("SIGNALPOST_PREVIOUS_STATE"))
    parser.add_argument("--state-output")
    parser.add_argument("--config", help="Reserved for the versioned runtime configuration")
    parser.add_argument("--evidence-cutoff", default=os.environ.get("SIGNALPOST_EVIDENCE_CUTOFF"))
    parser.add_argument("--network-policy", choices=("direct", "trusted-proxy"), default=os.environ.get("SIGNALPOST_NETWORK_POLICY", "direct"))
    parser.add_argument("--batch-id")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
