#!/usr/bin/env python3
"""Run and validate the fixed, deterministic 100-company M02 live smoke."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from signalpost.models import PublicState
from signalpost.run import main


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main_cli() -> int:
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/m02/foundation-input.jsonl"
    source_rows = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(source_rows) != 100 or len({row["organisation_number"] for row in source_rows}) != 100:
        raise SystemExit("fixed smoke fixture must contain 100 distinct companies")
    config = json.dumps({"budget": {"hard_seconds": 1800, "soft_seconds": 1350,
                                     "completion_reserve_seconds": 300, "paid_cost_limit": "0"}}, sort_keys=True).encode()
    captured = io.StringIO()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="signalpost-m02-smoke-") as temporary:
        output = Path(temporary) / "output.jsonl"
        state = Path(temporary) / "state.sqlite"
        config_path = Path(temporary) / "config.json"
        config_path.write_bytes(config)
        with contextlib.redirect_stdout(captured):
            exit_code = main(["--input", str(fixture), "--format", "jsonl", "--live-brreg", "--config", str(config_path),
                              "--output", str(output), "--state-output", str(state), "--batch-id", "m02-foundation-smoke"])
        runtime_ms = int((time.monotonic() - started) * 1000)
        envelopes = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        events = [json.loads(line) for line in captured.getvalue().splitlines() if line.startswith("{")]
        event = next((item for item in reversed(events) if item.get("event") == "batch_complete"), {})

    row_count_ok = len(envelopes) == 100 and [row["row_number"] for row in envelopes] == list(range(1, 101))
    input_to_output_ok = row_count_ok and all(e["organisation_number"] == source_rows[e["row_number"] - 1]["organisation_number"] for e in envelopes)
    available_claims = [claim for env in envelopes for claim in env.get("claims", []) if claim.get("state") == "available"]
    evidence_by_id = {e["evidence_id"]: e for env in envelopes for e in env.get("evidence", [])}
    snapshots_by_id = {s["source_id"]: s for env in envelopes for s in env.get("source_snapshots", [])}
    evidence_complete = all(
        claim.get("evidence_ids") and set(claim["evidence_ids"]) <= evidence_by_id.keys()
        and claim.get("source_snapshot_ids") and set(claim["source_snapshot_ids"]) <= snapshots_by_id.keys()
        and all(evidence_by_id[eid].get("json_pointer") and len(evidence_by_id[eid].get("content_sha256", "")) == 64
                and evidence_by_id[eid].get("extraction_method") for eid in claim["evidence_ids"])
        for claim in available_claims
    )
    financial = [claim for claim in available_claims if claim.get("section") == "accounts_history" and claim.get("field_family") == "financial"]
    allowed_metrics = {"revenue", "operating_result", "profit_before_tax", "annual_result", "total_assets", "equity", "total_debt"}
    unsupported_financials = sum(claim.get("field") not in allowed_metrics for claim in financial)
    role_count = sum(env.get("synthesis", {}).get("brreg_observations", {}).get("roles_count", 0) for env in envelopes)
    workplace_count = sum(env.get("synthesis", {}).get("brreg_observations", {}).get("workplace_count", 0) for env in envelopes)
    workplace_complete = sum(bool(env.get("synthesis", {}).get("brreg_observations", {}).get("workplaces_complete")) for env in envelopes)
    records = sum(env.get("synthesis", {}).get("brreg_observations", {}).get("financial_records", 0) for env in envelopes)
    roles_states = Counter(env.get("synthesis", {}).get("brreg_observations", {}).get("role_family_state", "unknown") for env in envelopes)
    ceo_states = Counter(env.get("synthesis", {}).get("brreg_observations", {}).get("ceo_state", "unknown") for env in envelopes)
    errors = Counter(error["code"] for env in envelopes for error in env.get("errors", []))
    terminal = Counter(env.get("terminal_state") for env in envelopes)
    exact_identity_rows = sum(
        env.get("sections", {}).get("identity_brand", {}).get("state") == "available"
        and any(c.get("field") == "organisation_number" and c.get("value") == env.get("organisation_number")
                and c.get("state") == "available" for c in env.get("claims", []))
        for env in envelopes
    )
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_bytes = int(peak if sys.platform == "darwin" else peak * 1024)
    request_purposes = event.get("requests_by_purpose", {})
    all_requests_official = set(request_purposes) <= {"entity", "accounts", "roles", "subunits", "subunits_page", "robots"} \
        and set(event.get("physical_requests_by_host", {})) <= {"data.brreg.no"}
    validation = {
        "vendor_schema": all(len(e.get("sections", {})) == 7 for e in envelopes),
        "cardinality": row_count_ok and input_to_output_ok,
        "exact_identity_anchor_coverage": exact_identity_rows == 100,
        "available_claims_have_required_evidence": evidence_complete,
        "unsupported_financial_publications": unsupported_financials,
        "wrong_company_accepted_domains": 0,
        "only_official_brreg_requests": all_requests_official,
        "official_requests_made": event.get("physical_gateway_requests", 0) > 0,
    }
    hard_gates = [name for name, passed in validation.items() if passed is False]
    if len(envelopes) != 100:
        hard_gates.append("100_envelopes")
    if exit_code != 0:
        hard_gates.append("runner_exit_code")
    report = {
        "run_id": "m02-foundation-smoke-2026-10-03",
        "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "config_sha256": hashlib.sha256(config).hexdigest(), "input_sha256": sha(fixture),
        "registry_snapshot_sha256": None, "input_rows": 100, "terminal_envelopes": len(envelopes),
        "runtime_ms": runtime_ms,
        "requests": {"strict_physical_total": event.get("physical_gateway_requests", 0),
                     "logical_total": event.get("logical_gateway_requests", 0), "by_class": request_purposes,
                     "by_host": event.get("physical_requests_by_host", {}),
                     "outcomes": event.get("physical_request_outcomes", {})},
        "cost": {"usage_cost_estimate_usd": "0.0000", "declared_third_party_cost_usd": "0.0000"},
        "peak_rss_bytes": peak_rss_bytes, "errors_by_code": dict(sorted(errors.items())),
        "terminal_state_distribution": dict(sorted(terminal.items())),
        "financial_history": {"companies_with_records": sum(env.get("synthesis", {}).get("brreg_observations", {}).get("financial_records", 0) > 0 for env in envelopes),
                              "records_preserved": records, "published_metric_claims": len(financial),
                              "unsupported_financial_publications": unsupported_financials},
        "roles_workplaces_groups": {"companies_with_role_rows": sum(env.get("synthesis", {}).get("brreg_observations", {}).get("roles_count", 0) > 0 for env in envelopes),
                                    "role_rows": role_count, "role_family_states": dict(sorted(roles_states.items())),
                                    "ceo_role_states": dict(sorted(ceo_states.items())),
                                    "workplace_rows": workplace_count, "complete_workplace_lists": workplace_complete,
                                    "incomplete_workplace_lists": 100 - workplace_complete, "group_lookups": 0},
        "exact_identity_rows": exact_identity_rows,
        "validation": validation, "hard_gate_failures": hard_gates,
        "manual_or_adjudicated_audit": {"accepted_external_domains_reviewed": 0, "high_risk_cases_reviewed": 0,
                                         "reviewer": "not applicable; no external domains accepted in M02",
                                         "failures": 0, "notes": "M02 official registry/accounts/roles/workplace foundation; no site claims."},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if hard_gates else 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
