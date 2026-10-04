#!/usr/bin/env python3
"""Run and validate the fixed, deterministic 100-company M02 live smoke."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import os
import resource
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from signalpost.models import PublicState
from signalpost.brreg import SUPPORTED_CURRENCY_CODES
from signalpost.history import SOURCE_POLICY_VERSION
from signalpost.run import main


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def unsupported_financial_claim(claim: dict) -> bool:
    """Detect invalid canonical metadata as well as unapproved metric names."""
    if claim.get("field") not in {"revenue", "operating_result", "profit_before_tax", "annual_result",
                                  "total_assets", "equity", "total_debt"}:
        return True
    currency = claim.get("currency")
    if not isinstance(currency, str) or currency not in SUPPORTED_CURRENCY_CODES:
        return True
    if claim.get("scope") not in {"legal_entity", "group"}:
        return True
    value = claim.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return True
    try:
        start = datetime.fromisoformat(str(claim.get("period_start", "")).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(claim.get("period_end", "")).replace("Z", "+00:00"))
    except ValueError:
        return True
    return start > end


def source_tree_provenance() -> tuple[str, bool, str]:
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
    diff = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT).split(b"\0")
    digest = hashlib.sha256(diff)
    for raw_path in sorted(item for item in untracked if item):
        path = ROOT / os.fsdecode(raw_path)
        digest.update(raw_path + b"\0" + path.read_bytes())
    return revision, bool(status.strip()), digest.hexdigest()


def main_cli() -> int:
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-websites", action="store_true",
                        help="Include the bounded exact-company website phase for RC1 release smoke.")
    parser.add_argument("--no-keyless-websites", action="store_true",
                        help="Disable the policy-bounded keyless .no candidate fallback.")
    args = parser.parse_args()
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/m02/foundation-input.jsonl"
    source_rows = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(source_rows) != 100 or len({row["organisation_number"] for row in source_rows}) != 100:
        raise SystemExit("fixed smoke fixture must contain 100 distinct companies")
    config = json.dumps({"budget": {"hard_seconds": 1800, "soft_seconds": 1350,
                                     "completion_reserve_seconds": 300, "paid_cost_limit": "0"}}, sort_keys=True).encode()
    captured = io.StringIO()
    run_started_utc = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="signalpost-m02-smoke-") as temporary:
        output = Path(temporary) / "output.jsonl"
        state = Path(temporary) / "state.sqlite"
        config_path = Path(temporary) / "config.json"
        config_path.write_bytes(config)
        command = ["--input", str(fixture), "--format", "jsonl", "--live-brreg", "--config", str(config_path),
                   "--output", str(output), "--state-output", str(state), "--batch-id", "m09-rc1-cold-100"]
        if args.live_websites:
            command.append("--live-websites")
        if args.no_keyless_websites:
            command.append("--no-keyless-websites")
        with contextlib.redirect_stdout(captured):
            exit_code = main(command)
        runtime_ms = int((time.monotonic() - started) * 1000)
        envelopes = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        output_sha256 = sha(output)
        state_sha256 = sha(state)
        events = [json.loads(line) for line in captured.getvalue().splitlines() if line.startswith("{")]
        event = next((item for item in reversed(events) if item.get("event") == "batch_complete"), {})

    row_count_ok = len(envelopes) == 100 and [row["input_ref"] for row in envelopes] == [f"row:{i}" for i in range(1, 101)]
    input_to_output_ok = row_count_ok and all(e["organisation_number"] == source_rows[index]["organisation_number"]
        for index, e in enumerate(envelopes))
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
    unsupported_financials = sum(unsupported_financial_claim(claim) for claim in financial)
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
    permitted_purposes = {"entity", "accounts", "roles", "subunits", "subunits_page"}
    if args.live_websites:
        permitted_purposes.update({"robots", "sitemap", "website_page"})
    all_requests_authorized = set(request_purposes) <= permitted_purposes \
        and "data.brreg.no" in set(event.get("physical_requests_by_host", {}))
    website_claims = [claim for env in envelopes for claim in env.get("claims", [])
                      if claim.get("state") == "available" and claim.get("field_family") in {"website", "jobs", "public_activity"}]
    wrong_company_website_claims = 0
    for env in envelopes:
        evidence_by_id_for_env = {item["evidence_id"]: item for item in env.get("evidence", [])}
        for claim in env.get("claims", []):
            if claim.get("state") != "available" or claim.get("field_family") not in {"website", "jobs", "public_activity"}:
                continue
            if claim.get("organisation_number") != env.get("organisation_number"):
                wrong_company_website_claims += 1
                continue
            if any(evidence_by_id_for_env.get(eid, {}).get("subject_organisation_number") != env.get("organisation_number")
                   for eid in claim.get("evidence_ids", [])):
                wrong_company_website_claims += 1
    validation = {
        "vendor_schema": all(len(e.get("sections", {})) == 7 for e in envelopes),
        "cardinality": row_count_ok and input_to_output_ok,
        "exact_identity_anchor_coverage": exact_identity_rows == 100,
        "available_claims_have_required_evidence": evidence_complete,
        "unsupported_financial_publications": unsupported_financials == 0,
        "wrong_company_accepted_domains": wrong_company_website_claims == 0,
        "only_authorized_source_classes": all_requests_authorized,
        "official_requests_made": event.get("physical_gateway_requests", 0) > 0,
    }
    hard_gates = [name for name, passed in validation.items() if passed is False]
    if unsupported_financials and "unsupported_financial_publications" not in hard_gates:
        hard_gates.append("unsupported_financial_publications")
    if len(envelopes) != 100:
        hard_gates.append("100_envelopes")
    if exit_code != 0:
        hard_gates.append("runner_exit_code")
    code_commit, working_tree_dirty, working_tree_diff_sha256 = source_tree_provenance()
    report = {
        "run_id": "m09-rc1-cold-100",
        "code_commit": code_commit, "working_tree_dirty": working_tree_dirty,
        "working_tree_diff_sha256": working_tree_diff_sha256,
        "measurement_kind": "live_brreg_and_bounded_website_smoke" if args.live_websites else "live_brreg_source_smoke",
        "enabled_source_classes": ["brreg_structured_api"] + (["exact_company_owned_website"] if args.live_websites else []),
        "config_sha256": hashlib.sha256(config).hexdigest(), "input_sha256": sha(fixture),
        "output_sha256": output_sha256, "state_output_sha256": state_sha256,
        "previous_state_sha256": None, "source_policy_version": SOURCE_POLICY_VERSION,
        "network_policy_version": "NetworkGateway policy as committed at code_commit",
        "network_policy": "direct", "external_cache_mode": "none; bundled Public Suffix List snapshot only",
        "model_provider": None, "model_usage": "none", "paid_api_usage": "none",
        "started_at_utc": run_started_utc, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_cutoff": event.get("evidence_cutoff"),
        "evidence_cutoff_source": event.get("evidence_cutoff_source"),
        "registry_snapshot_sha256": None, "input_rows": 100, "terminal_envelopes": len(envelopes),
        "runtime_ms": runtime_ms,
        "requests": {"strict_physical_total": event.get("physical_gateway_requests", 0),
                     "logical_total": event.get("logical_gateway_requests", 0), "by_class": request_purposes,
                     "by_host": event.get("physical_requests_by_host", {}),
                     "outcomes": event.get("physical_request_outcomes", {}),
                     "physical_limit": event.get("request_limit"),
                     "logical_limit": event.get("logical_request_limit")},
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
        "website_publication_observations": {"available_external_claims": len(website_claims),
            "wrong_company_publications_by_subject_and_evidence_binding": wrong_company_website_claims,
            "adjudication": "structural_provenance check; independent human precision estimate unavailable"},
        "manual_or_adjudicated_audit": {"accepted_external_domains_reviewed": 0, "high_risk_cases_reviewed": 0,
            "reviewer": "automated claim/evidence subject binding; no human adjudication",
            "failures": wrong_company_website_claims,
            "notes": "Release smoke checks subject and evidence organisation binding; prior M03 accepted-domain proof audit is separate."},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if hard_gates else 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
