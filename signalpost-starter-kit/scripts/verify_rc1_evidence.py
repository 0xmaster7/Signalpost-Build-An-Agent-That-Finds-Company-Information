#!/usr/bin/env python3
"""Packaging gate for durable RC1 historical evidence receipts."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/release/M09_RC1_DURABLE_EVIDENCE.json"
POST_SOL_RECEIPT = ROOT / "docs/release/POST_SOL_REMEDIATION_LIVE_EVIDENCE_2026-10-07.json"
POST_SOL_REPORT = ROOT / "docs/release/POST_SOL_REMEDIATION_LIVE_SMOKE_2026-10-07.json"


def main() -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    required = {"source_sha", "input_sha256", "config_sha256", "runtime_seconds", "physical_requests",
        "logical_requests", "terminal_envelopes", "evidence_hashes", "release_report", "retention_note"}
    missing = sorted(required - data.keys())
    if missing:
        raise SystemExit("RC1 evidence manifest is missing: " + ", ".join(missing))
    for label, digest in [("input", data["input_sha256"]), ("config", data["config_sha256"]), *data["evidence_hashes"].items()]:
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SystemExit(f"RC1 evidence hash is invalid: {label}")
    if data["terminal_envelopes"] != data["input_rows"] or data["physical_requests"] > 2200:
        raise SystemExit("RC1 recorded cardinality or request count violates the release envelope")
    for relative in (data["release_report"], data["input_path"], "docs/release/M09_RC1_DURABLE_EVIDENCE.json"):
        if not (ROOT / relative).is_file():
            raise SystemExit(f"RC1 required packaged evidence is missing: {relative}")
    fixture_hash = hashlib.sha256((ROOT / data["input_path"]).read_bytes()).hexdigest()
    if fixture_hash != data["input_sha256"]:
        raise SystemExit("RC1 fixed cohort hash no longer matches the durable evidence receipt")

    receipt = json.loads(POST_SOL_RECEIPT.read_text(encoding="utf-8"))
    if not POST_SOL_REPORT.is_file():
        raise SystemExit("post-Sol live report is missing")
    required_live = {"source_sha", "branch", "input_sha256", "config_sha256", "release_report_sha256",
        "artifact_hashes", "physical_requests", "logical_requests", "runtime_seconds", "input_rows",
        "terminal_envelopes", "terminal_envelopes_validation", "historical_m09_report_rewritten"}
    missing_live = sorted(required_live - receipt.keys())
    if missing_live:
        raise SystemExit("post-Sol receipt is missing: " + ", ".join(missing_live))
    live_report = json.loads(POST_SOL_REPORT.read_text(encoding="utf-8"))
    live_report_hash = hashlib.sha256(POST_SOL_REPORT.read_bytes()).hexdigest()
    if receipt["release_report"] != str(POST_SOL_REPORT.relative_to(ROOT)) or receipt["release_report_sha256"] != live_report_hash:
        raise SystemExit("post-Sol report path or hash does not match its durable receipt")
    summary_path = ROOT / receipt.get("summary_report", "")
    if (not summary_path.is_file()
            or hashlib.sha256(summary_path.read_bytes()).hexdigest() != receipt.get("summary_report_sha256")):
        raise SystemExit("post-Sol summary report path or hash does not match its durable receipt")
    if (receipt["source_sha"] != "43dc4cb32d5a3b2f2e50796049c81b4a16ca383f"
            or live_report.get("code_commit") != receipt["source_sha"]
            or live_report.get("working_tree_dirty") is not False
            or receipt["working_tree_dirty_at_run"] is not False):
        raise SystemExit("post-Sol run source must be the clean authorized remediation SHA")
    if (receipt["input_rows"] != 100 or receipt["terminal_envelopes"] != 100
            or receipt["input_sha256"] != data["input_sha256"]
            or receipt["physical_requests"] > 2200 or receipt["runtime_seconds"] > 1800
            or live_report.get("hard_gate_failures") != []):
        raise SystemExit("post-Sol live result violates the fixed cohort or resource gates")
    if live_report_hash != receipt["release_report_sha256"] or live_report.get("config_sha256") != receipt["config_sha256"]:
        raise SystemExit("post-Sol report does not match its recorded configuration/hash")
    for label, digest in receipt["artifact_hashes"].items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SystemExit(f"post-Sol artifact hash is invalid: {label}")
    report_files = {item["path"]: item["sha256"]
        for item in live_report.get("preserved_artifacts", {}).get("artifact_files", [])}
    artifact_path_map = {
        "output": "run/output.jsonl", "state": "run/state.sqlite",
        "checkpoint": "run/state.sqlite.checkpoint.sqlite", "request_ledger": "request-ledger.json",
        "publication_marker": "run/output.jsonl.publication.json", "captured_stdout": "stdout.log",
    }
    for label, relative in artifact_path_map.items():
        if report_files.get(relative) != receipt["artifact_hashes"].get(label):
            raise SystemExit(f"post-Sol artifact hash disagrees with the run manifest: {label}")
    if (live_report.get("output_sha256") != receipt["artifact_hashes"]["output"]
            or live_report.get("state_output_sha256") != receipt["artifact_hashes"]["state"]
            or live_report.get("preserved_artifacts", {}).get("request_ledger_sha256")
                != receipt["artifact_hashes"]["request_ledger"]
            or receipt["terminal_envelopes_validation"] != live_report.get("validation")):
        raise SystemExit("post-Sol report counts or artifact hashes disagree with the durable receipt")
    if receipt["historical_m09_report_rewritten"] is not False:
        raise SystemExit("the original M09 report must remain historical and unchanged")
    verification = receipt.get("verification", {})
    if (verification.get("full_suite_tests") != 383
            or verification.get("offline_scale_rows") != [1000, 1200, 10000]
            or verification.get("offline_scale_gate") != "PASS"
            or verification.get("evidence_packaging_gate") != "PASS"):
        raise SystemExit("post-Sol receipt is missing its final deterministic gate results")
    print("RC1_DURABLE_EVIDENCE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
