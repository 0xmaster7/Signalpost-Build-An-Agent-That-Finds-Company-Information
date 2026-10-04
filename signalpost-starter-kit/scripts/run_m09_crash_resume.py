#!/usr/bin/env python3
"""Kill and resume the real CLI at 25/50/90 percent durable checkpoints."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from run_m06_scale_gate import synthetic_org_number  # noqa: E402

LAUNCHER = ROOT / "signalpost-starter-kit" / "run_signalpost.py"
CUTOFF = "2026-10-04T00:00:00Z"


def semantic_rows(path: Path) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [{
        "input_ref": row["input_ref"],
        "organisation_number": row["organisation_number"],
        "terminal_state": row["terminal_state"],
        "claims": [{key: claim.get(key) for key in ("organisation_number", "section", "field_family", "subject_id",
            "field", "value", "state", "scope", "period_start", "period_end", "currency", "unit",
            "evidence_ids", "source_snapshot_ids")} for claim in row.get("claims", [])],
        "evidence": [{key: item.get(key) for key in ("evidence_id", "source_url", "content_sha256", "extraction_method",
            "json_pointer", "subject_organisation_number", "source_snapshot_ids")} for item in row.get("evidence", [])],
        "snapshots": [{key: item.get(key) for key in ("source_id", "source_url", "content_sha256", "rights_status")}
            for item in row.get("source_snapshots", [])],
    } for row in rows]


def run_case(percent: int, row_count: int = 100) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"signalpost-m09-crash-{percent}-") as temp:
        started = time.monotonic()
        root = Path(temp)
        hook = root / "hook"
        hook.mkdir()
        source, registry, config = root / "input.jsonl", root / "registry.jsonl", root / "config.json"
        output, state, checkpoint = root / "output.jsonl", root / "state.json", root / "checkpoint.sqlite"
        baseline_output, baseline_state = root / "baseline.jsonl", root / "baseline-state.json"
        orgs = [synthetic_org_number(i) for i in range(row_count)]
        source.write_text("".join(json.dumps({"organisation_number": org}) + "\n" for org in orgs), encoding="utf-8")
        registry.write_text("".join(json.dumps({"orgnr": org, "name": f"Crash Fixture {i:03d} AS"}) + "\n"
            for i, org in enumerate(orgs)), encoding="utf-8")
        config.write_text(json.dumps({"budget": {"hard_seconds": 1800, "soft_seconds": 1350,
            "completion_reserve_seconds": 300, "paid_cost_limit": "0"}}), encoding="utf-8")
        batch_id = f"m09-crash-{percent}"
        common = [sys.executable, str(LAUNCHER), "--input", str(source), "--format", "jsonl",
            "--registry-snapshot", str(registry), "--config", str(config), "--evidence-cutoff", CUTOFF,
            "--batch-id", batch_id]
        baseline = subprocess.run(common + ["--output", str(baseline_output), "--state-output", str(baseline_state),
            "--checkpoint", str(root / "baseline.sqlite")], cwd="/tmp", capture_output=True, text=True, timeout=60)
        if baseline.returncode:
            raise RuntimeError(f"uninterrupted reference run failed: {baseline.stderr[-2000:]}")
        threshold = max(1, row_count * percent // 100)
        (hook / "sitecustomize.py").write_text(
            "import os\nfrom signalpost.operations import CheckpointStore\n"
            "original = CheckpointStore.put\ncount = 0\n"
            "def intercepted(self, envelope):\n"
            " global count\n original(self, envelope)\n count += 1\n"
            f" if count >= {threshold}: os._exit(86)\n"
            "CheckpointStore.put = intercepted\n", encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(hook), str(ROOT)))}
        crashed = subprocess.run(common + ["--output", str(output), "--state-output", str(state),
            "--checkpoint", str(checkpoint)], cwd="/tmp", env=env, capture_output=True, text=True, timeout=60)
        if crashed.returncode != 86 or not checkpoint.exists():
            raise AssertionError(f"expected injected hard exit 86 at {percent}%, got {crashed.returncode}: {crashed.stderr[-1000:]}")
        resumed = subprocess.run(common + ["--output", str(output), "--state-output", str(state),
            "--checkpoint", str(checkpoint), "--resume"], cwd="/tmp", capture_output=True, text=True, timeout=60)
        if resumed.returncode:
            raise RuntimeError(f"resume failed at {percent}%: {resumed.stderr[-2000:]}")
        expected, actual = semantic_rows(baseline_output), semantic_rows(output)
        if expected != actual:
            raise AssertionError(f"resumed semantic output differs from uninterrupted run at {percent}%")
        refs = [row["input_ref"] for row in actual]
        if refs != [f"row:{index}" for index in range(1, row_count + 1)] or len(set(refs)) != row_count:
            raise AssertionError(f"resume output cardinality/order failed at {percent}%")
        return {"kill_after_durable_envelopes": threshold, "input_rows": row_count,
            "output_rows": len(actual), "distinct_organisations": len({row["organisation_number"] for row in actual}),
            "order_and_cardinality": "PASS", "semantic_match_to_uninterrupted": True,
            "crash_exit_code": crashed.returncode, "resume_exit_code": resumed.returncode,
            "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "registry_sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
            "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
            "runtime_seconds": round(time.monotonic() - started, 3),
            "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


def main() -> int:
    results = {str(percent): run_case(percent) for percent in (25, 50, 90)}
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip())
    print(json.dumps({"measurement_kind": "offline_real_process_crash_resume", "source_commit": revision,
        "source_tree_dirty": dirty,
        "network": "disabled", "cases": results, "gate_passed": all(item["semantic_match_to_uninterrupted"] for item in results.values())},
        sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
