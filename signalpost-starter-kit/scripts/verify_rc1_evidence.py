#!/usr/bin/env python3
"""Packaging gate for durable RC1 historical evidence receipts."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/release/M09_RC1_DURABLE_EVIDENCE.json"


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
    print("RC1_DURABLE_EVIDENCE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
