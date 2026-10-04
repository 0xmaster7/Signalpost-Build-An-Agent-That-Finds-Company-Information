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
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from signalpost.models import Envelope
from signalpost.brreg import SUPPORTED_CURRENCY_CODES
from signalpost.history import SOURCE_POLICY_VERSION, validate_artifact
from signalpost.adapter import to_evaluator, validate_vendor_payload
import signalpost.run as run_module
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


def _request_ledger_snapshot(gateway: object | None) -> dict[str, object]:
    if gateway is None:
        return {"available": False, "physical_requests": None, "logical_requests": None, "entries": []}
    ledger = getattr(gateway, "ledger", None)
    entries = list(getattr(ledger, "entries", []))
    budget = getattr(gateway, "budget", None)
    config = getattr(budget, "config", None)
    budget_config = ({key: (str(value) if key == "paid_cost_limit" else value)
        for key, value in vars(config).items()} if config is not None else None)
    accounting = None
    if budget is not None:
        accounting = {
            "physical_requests_reserved": getattr(budget, "physical_requests", None),
            "logical_requests_reserved": getattr(budget, "logical_requests", None),
            "physical_requests_remaining": getattr(budget, "physical_requests_remaining", None),
            "logical_requests_remaining": getattr(budget, "logical_requests_remaining", None),
            "requests_by_company": getattr(budget, "requests_by_company", None),
            "elapsed_seconds": getattr(budget, "elapsed", None),
            "soft_expired": getattr(budget, "soft_expired", None),
            "hard_expired": getattr(budget, "hard_expired", None),
            "completion_reserve_active": getattr(budget, "reserve_active", None),
        }
    return {
        "available": ledger is not None,
        "physical_requests": getattr(ledger, "physical_requests", None),
        "logical_requests": getattr(ledger, "logical_requests", None),
        "coalesced_requests": getattr(gateway, "coalesced_requests", None),
        "budget_config": budget_config,
        "budget_accounting": accounting,
        "entries": [{key: getattr(entry, key, None) for key in
            ("request_id", "url", "purpose", "status", "bytes_received", "elapsed_ms", "outcome", "redirect_location")}
            for entry in entries],
    }


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temporary_path, path)


def _preserve_run_bundle(report_path: Path, temporary_dir: Path, *, label: str,
                         captured_stdout: str, gateway: object | None,
                         traceback_text: str | None = None) -> tuple[Path, dict[str, object]]:
    base = report_path.with_suffix("").with_name(report_path.stem + f".{label}-artifacts")
    artifact_dir = base
    suffix = 2
    while artifact_dir.exists():
        artifact_dir = base.with_name(base.name + f"-{suffix}")
        suffix += 1
    artifact_dir.mkdir(parents=True)
    run_dir = artifact_dir / "run"
    shutil.copytree(temporary_dir, run_dir)
    (artifact_dir / "stdout.log").write_text(captured_stdout, encoding="utf-8")
    if traceback_text is not None:
        (artifact_dir / "traceback.txt").write_text(traceback_text, encoding="utf-8")
    ledger = _request_ledger_snapshot(gateway)
    ledger_path = artifact_dir / "request-ledger.json"
    _atomic_json(ledger_path, ledger)
    files = []
    for path in sorted(item for item in artifact_dir.rglob("*") if item.is_file()):
        files.append({"path": str(path.relative_to(artifact_dir)), "sha256": sha(path), "bytes": path.stat().st_size})
    manifest = {"artifact_directory": artifact_dir.name, "files": files}
    _atomic_json(artifact_dir / "manifest.json", manifest)
    return artifact_dir, {"artifact_directory": artifact_dir.name,
        "artifact_manifest": "manifest.json", "artifact_files": files,
        "request_ledger_path": "request-ledger.json", "request_ledger_sha256": sha(ledger_path),
        "request_ledger": ledger}


def _run_preserving_failure(action, persist_failure):
    try:
        return action()
    except BaseException as failure:
        trace = traceback.format_exc()
        try:
            persist_failure(failure, trace)
        except BaseException as persistence_failure:
            failure.add_note(f"Failed to persist smoke diagnostics: {type(persistence_failure).__name__}: {persistence_failure}")
        raise


def _validate_evaluator_rows(envelopes: list[dict], source_rows: list[dict]) -> tuple[list[Envelope], int, list[dict[str, str]]]:
    """Reconstitute and validate canonical rows from the exact evaluator output."""
    canonical_rows = []
    adapter_roundtrips = 0
    failures = []
    for index, payload in enumerate(envelopes, start=1):
        try:
            validate_vendor_payload(payload)
            if payload.get("organisation_number") != source_rows[index - 1]["organisation_number"]:
                raise ValueError("organisation number does not match input")
            canonical = {key: value for key, value in payload.items() if key not in {"run", "batch"}}
            canonical.update({"row_number": index, "batch_id": payload["batch"]["batch_id"],
                "evidence_cutoff": payload["batch"]["evidence_cutoff"],
                "created_at": payload["run"]["created_at"]})
            envelope = Envelope.model_validate(canonical)
            serialized = to_evaluator(envelope)
            validate_vendor_payload(serialized)
            adapter_roundtrips += 1
            canonical_rows.append(envelope)
        except (KeyError, TypeError, ValueError) as exc:
            failures.append({"row": str(index), "reason": f"{type(exc).__name__}: {exc}"})
    return canonical_rows, adapter_roundtrips, failures


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
    code_commit, working_tree_dirty, working_tree_diff_sha256 = source_tree_provenance()
    run_metadata = {"source_commit": code_commit, "working_tree_dirty": working_tree_dirty,
        "working_tree_diff_sha256": working_tree_diff_sha256,
        "input_sha256": sha(fixture), "config_sha256": hashlib.sha256(config).hexdigest(),
        "input_rows": len(source_rows), "run_id": "m09-rc1-cold-100",
        "hard_seconds": 1800, "soft_seconds": 1350, "completion_reserve_seconds": 300,
        "physical_request_limit": 12 * len(source_rows) + 1000, "paid_cost_limit": "0"}
    captured = io.StringIO()
    run_started_utc = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    gateway_holder: list[object] = []
    artifact_bundle: dict[str, object]
    with tempfile.TemporaryDirectory(prefix="signalpost-m02-smoke-") as temporary:
        temporary_dir = Path(temporary)
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

        original_gateway_factory = run_module.NetworkGateway
        def tracked_gateway_factory(*factory_args, **factory_kwargs):
            gateway = original_gateway_factory(*factory_args, **factory_kwargs)
            gateway_holder.append(gateway)
            return gateway

        def execute_runner() -> int:
            with contextlib.redirect_stdout(captured):
                return main(command)

        def persist_failure(failure: BaseException, traceback_text: str) -> None:
            runtime_ms = int((time.monotonic() - started) * 1000)
            _artifact_dir, bundle = _preserve_run_bundle(args.output, temporary_dir, label="failure",
                captured_stdout=captured.getvalue(), gateway=gateway_holder[-1] if gateway_holder else None,
                traceback_text=traceback_text)
            ledger = bundle["request_ledger"]
            report = {**run_metadata, "measurement_kind": "live_smoke_failure",
                "status": "failed", "enabled_source_classes": ["brreg_structured_api"]
                    + (["exact_company_owned_website"] if args.live_websites else []),
                "started_at_utc": run_started_utc, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "runtime_ms": runtime_ms, "failure": {"type": type(failure).__name__,
                    "message": str(failure), "traceback_path": "traceback.txt"},
                "preserved_artifacts": {key: value for key, value in bundle.items() if key != "request_ledger"},
                "requests": ledger}
            _atomic_json(args.output, report)

        run_module.NetworkGateway = tracked_gateway_factory
        try:
            exit_code = _run_preserving_failure(execute_runner, persist_failure)
        finally:
            run_module.NetworkGateway = original_gateway_factory
        runtime_ms = int((time.monotonic() - started) * 1000)
        envelopes = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        output_sha256 = sha(output)
        state_sha256 = sha(state)
        state_artifact = validate_artifact(json.loads(state.read_text(encoding="utf-8")))
        events = [json.loads(line) for line in captured.getvalue().splitlines() if line.startswith("{")]
        event = next((item for item in reversed(events) if item.get("event") == "batch_complete"), {})
        _artifact_dir, artifact_bundle = _preserve_run_bundle(args.output, temporary_dir, label="artifacts",
            captured_stdout=captured.getvalue(), gateway=gateway_holder[-1] if gateway_holder else None)

    row_count_ok = len(envelopes) == 100 and [row["input_ref"] for row in envelopes] == [f"row:{i}" for i in range(1, 101)]
    input_to_output_ok = row_count_ok and all(e["organisation_number"] == source_rows[index]["organisation_number"]
        for index, e in enumerate(envelopes))
    canonical_rows, adapter_roundtrips, canonical_validation_failures = _validate_evaluator_rows(envelopes, source_rows)
    available_claims = [claim for env in envelopes for claim in env.get("claims", []) if claim.get("state") == "available"]
    duplicate_evidence_ids = sorted(
        f"row:{index}:{key}" for index, env in enumerate(envelopes, start=1)
        for key, count in Counter(item["evidence_id"] for item in env.get("evidence", [])).items() if count > 1)
    duplicate_snapshot_ids = sorted(
        f"row:{index}:{key}" for index, env in enumerate(envelopes, start=1)
        for key, count in Counter(item["source_id"] for item in env.get("source_snapshots", [])).items() if count > 1)
    evidence_ids_by_row = [set(item["evidence_id"] for item in env.get("evidence", [])) for env in envelopes]
    snapshot_ids_by_row = [set(item["source_id"] for item in env.get("source_snapshots", [])) for env in envelopes]
    cross_envelope_evidence_reuse = sum(count - 1 for count in Counter(
        item for row_ids in evidence_ids_by_row for item in row_ids).values() if count > 1)
    cross_envelope_snapshot_reuse = sum(count - 1 for count in Counter(
        item for row_ids in snapshot_ids_by_row for item in row_ids).values() if count > 1)
    evidence_complete = all(
        all(claim.state.value != "available" or claim.evidence_ids for claim in env.claims)
        for env in canonical_rows
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
    invalid_workplace_relations = 0
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
        for claim in env.get("claims", []):
            if claim.get("state") != "available" or claim.get("field_family") != "workplace":
                continue
            target = env.get("organisation_number")
            child = claim.get("subject_id")
            if not isinstance(child, str) or child == target:
                invalid_workplace_relations += 1
            if claim.get("field") == "workplace.overordnetEnhet" and claim.get("value") != target:
                invalid_workplace_relations += 1
            if claim.get("scope") != "workplace":
                invalid_workplace_relations += 1

    state_company_count = len(state_artifact.companies)
    state_keys_match_inputs = set(state_artifact.companies) == {row["organisation_number"] for row in source_rows}
    physical_requests = event.get("physical_gateway_requests", 0)
    logical_requests = event.get("logical_gateway_requests", 0)
    elapsed_seconds = event.get("runtime_seconds")
    budget_reserve_seconds = event.get("completion_reserve_remaining_seconds")
    ledger_snapshot = artifact_bundle["request_ledger"]
    ledger_counts_match = (ledger_snapshot.get("physical_requests") == physical_requests
        and ledger_snapshot.get("logical_requests") == logical_requests)
    resource_limits_respected = (isinstance(physical_requests, int) and physical_requests <= 2200
        and isinstance(elapsed_seconds, (int, float)) and elapsed_seconds <= 1800
        and isinstance(budget_reserve_seconds, (int, float)) and budget_reserve_seconds >= 0)
    validation = {
        "vendor_schema_and_adapter_roundtrip": adapter_roundtrips == len(envelopes) and not canonical_validation_failures,
        "cardinality": row_count_ok and input_to_output_ok,
        "state_artifact": state_company_count == 100 and state_keys_match_inputs,
        "exact_identity_anchor_coverage": exact_identity_rows == 100,
        "available_claims_have_required_evidence": evidence_complete,
        "unique_evidence_and_snapshot_ids": not duplicate_evidence_ids and not duplicate_snapshot_ids,
        "unsupported_financial_publications": unsupported_financials == 0,
        "wrong_company_accepted_domains": wrong_company_website_claims == 0,
        "valid_workplace_attribution": invalid_workplace_relations == 0,
        "only_authorized_source_classes": all_requests_authorized,
        "official_requests_made": event.get("physical_gateway_requests", 0) > 0,
        "request_ledger_matches_run_accounting": ledger_counts_match,
        "request_runtime_and_reserve_limits": resource_limits_respected,
    }
    hard_gates = [name for name, passed in validation.items() if passed is False]
    if unsupported_financials and "unsupported_financial_publications" not in hard_gates:
        hard_gates.append("unsupported_financial_publications")
    if len(envelopes) != 100:
        hard_gates.append("100_envelopes")
    if exit_code != 0:
        hard_gates.append("runner_exit_code")
    report = {
        "run_id": "m09-rc1-cold-100",
        "code_commit": code_commit, "working_tree_dirty": working_tree_dirty,
        "working_tree_diff_sha256": working_tree_diff_sha256,
        "measurement_kind": "live_brreg_and_bounded_website_smoke" if args.live_websites else "live_brreg_source_smoke",
        "enabled_source_classes": ["brreg_structured_api"] + (["exact_company_owned_website"] if args.live_websites else []),
        "config_sha256": hashlib.sha256(config).hexdigest(), "input_sha256": sha(fixture),
        "output_sha256": output_sha256, "state_output_sha256": state_sha256,
        "preserved_artifacts": {key: value for key, value in artifact_bundle.items() if key != "request_ledger"},
        "previous_state_sha256": None, "source_policy_version": SOURCE_POLICY_VERSION,
        "network_policy_version": "NetworkGateway policy as committed at code_commit",
        "network_policy": "direct", "external_cache_mode": "none; bundled Public Suffix List snapshot only",
        "model_provider": None, "model_usage": "none", "paid_api_usage": "none",
        "started_at_utc": run_started_utc, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_cutoff": event.get("evidence_cutoff"),
        "evidence_cutoff_source": event.get("evidence_cutoff_source"),
        "registry_snapshot_sha256": event.get("registry_snapshot_sha256"), "input_rows": 100, "terminal_envelopes": len(envelopes),
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
        "artifact_integrity": {"output_sha256": output_sha256, "state_sha256": state_sha256,
            "state_company_count": state_company_count, "state_keys_match_inputs": state_keys_match_inputs},
        "provenance_validation": {"canonical_envelopes_validated": len(canonical_rows),
            "canonical_envelope_failures": canonical_validation_failures,
            "available_claims": len(available_claims), "available_claims_with_required_evidence": evidence_complete,
            "claim_to_evidence_to_snapshot_checked_by_canonical_contract": True,
            "duplicate_evidence_ids_within_envelopes": duplicate_evidence_ids,
            "duplicate_snapshot_ids_within_envelopes": duplicate_snapshot_ids,
            "cross_envelope_evidence_id_reuse_count": cross_envelope_evidence_reuse,
            "cross_envelope_snapshot_id_reuse_count": cross_envelope_snapshot_reuse},
        "workplace_validation": {"invalid_workplace_attributions": invalid_workplace_relations},
        "resource_safety": {"physical_requests": physical_requests, "logical_requests": logical_requests,
            "runtime_seconds": elapsed_seconds, "hard_runtime_limit_seconds": 1800,
            "soft_deadline_seconds": 1350, "completion_reserve_seconds": 300,
            "completion_reserve_remaining_seconds": budget_reserve_seconds,
            "within_limits": resource_limits_respected, "request_ledger_matches_accounting": ledger_counts_match,
            "request_ledger": {key: value for key, value in ledger_snapshot.items() if key != "entries"}},
        "measurements": {"live_measured": ["row cardinality", "identity anchors", "requests", "claims and provenance",
            "financial and workplace observations", "state artifact", "runtime"],
            "deterministically_tested": ["adapter roundtrip", "canonical envelope provenance contract"],
            "simulated": [], "not_measured": ["human-adjudicated website precision", "population-wide recall"]},
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
    _atomic_json(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if hard_gates else 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
