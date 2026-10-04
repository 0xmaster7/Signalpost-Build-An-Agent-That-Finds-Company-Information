#!/usr/bin/env python3
"""Replay two recorded snapshots through the canonical Signalpost CLI."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "signalpost-starter-kit" / "run_signalpost.py"


def _registry_rows(manifest: dict, label: str) -> list[dict]:
    snapshot = manifest["snapshots"][label]
    rows = []
    for profile in manifest["profiles"]:
        org = str(profile["organisation_number"])
        entity_url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
        entity = snapshot.get("responses", {}).get(entity_url, {}).get("body")
        if not isinstance(entity, dict) or str(entity.get("organisasjonsnummer")) != org:
            raise ValueError(f"{label} snapshot lacks exact-org entity bytes for {org}")
        rows.append({"organisation_number": org, "name": entity.get("navn"),
                     "legal_form": (entity.get("organisasjonsform") or {}).get("kode"),
                     "source_url": entity_url})
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
                    encoding="utf-8")


def _run(input_path: Path, registry_path: Path, output_path: Path, state_path: Path,
         cutoff: str, previous_path: Path | None = None) -> tuple[list[dict], float]:
    command = [sys.executable, str(LAUNCHER), "--input", str(input_path), "--format", "jsonl",
               "--registry-snapshot", str(registry_path), "--output", str(output_path),
               "--state-output", str(state_path), "--checkpoint", str(state_path) + ".checkpoint.sqlite",
               "--evidence-cutoff", cutoff, "--batch-id", "m07-refresh-replay"]
    if previous_path:
        command.extend(["--previous-state", str(previous_path)])
    started = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=90,
                            env={**os.environ, "PYTHONPATH": str(ROOT)})
    elapsed_ms = (time.perf_counter() - started) * 1000
    if result.returncode:
        raise RuntimeError(f"canonical runner failed ({result.returncode}): {result.stderr[-2000:]}")
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    return rows, elapsed_ms


def _events(rows: list[dict]) -> list[dict]:
    return sorted((event for row in rows for event in row.get("refresh", {}).get("changes", [])),
                  key=lambda event: (event.get("organisation_number", ""), event.get("type", ""),
                                     event.get("field", ""), event.get("event_id", "")))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run recorded old/new snapshots through Signalpost M07 state handoff")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    input_rows = [{"organisation_number": str(row["organisation_number"])} for row in manifest["profiles"]]
    old_registry, new_registry = _registry_rows(manifest, "old"), _registry_rows(manifest, "new")
    expected = {(str(item["organisation_number"]), str(item["type"]), str(item["field"]))
                for item in manifest.get("expected_m07_changes", [])}
    with tempfile.TemporaryDirectory(prefix="signalpost-m07-replay-") as temp:
        root = Path(temp)
        input_path, old_path, new_path = root / "input.jsonl", root / "old-registry.jsonl", root / "new-registry.jsonl"
        old_out, new_out, repeat_out = root / "old-output.jsonl", root / "new-output.jsonl", root / "repeat-output.jsonl"
        old_state, new_state, repeat_state = root / "old-state.json", root / "new-state.json", root / "repeat-state.json"
        _write_jsonl(input_path, input_rows)
        _write_jsonl(old_path, old_registry)
        _write_jsonl(new_path, new_registry)
        old_rows, old_runtime = _run(input_path, old_path, old_out, old_state,
                                     manifest["snapshots"]["old"]["effective_at"])
        new_cutoff = manifest["snapshots"]["new"]["effective_at"]
        new_rows, new_runtime = _run(input_path, new_path, new_out, new_state, new_cutoff, old_state)
        repeated_rows, repeat_runtime = _run(input_path, new_path, repeat_out, repeat_state, new_cutoff, old_state)
        produced_events = _events(new_rows)
        repeated_events = _events(repeated_rows)
        produced = {(str(item.get("organisation_number")), str(item.get("type")), str(item.get("field")))
                    for item in produced_events}
        true_positive = len(expected & produced)
        false_positive = len(produced - expected)
        false_negative = len(expected - produced)
        provenance_complete = all(item.get("previous_state_ref") and item.get("current_state_ref")
            and item.get("previous_claim_fingerprint") and item.get("current_claim_fingerprint")
            and item.get("previous_evidence") and item.get("current_evidence")
            and item.get("provenance_complete") for item in produced_events)
        idempotent = [item.get("event_id") for item in produced_events] == [item.get("event_id") for item in repeated_events]
        output_cardinality = len(old_rows) == len(input_rows) and len(new_rows) == len(input_rows)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
        report = {
            "measurement_kind": "canonical_cli_two_snapshot_replay",
            "corpus": manifest.get("corpus", "recorded source snapshots"),
            "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
            "profiles": len(input_rows), "input_rows": len(input_rows),
            "old_terminal_envelopes": len(old_rows), "current_terminal_envelopes": len(new_rows),
            "expected_material_changes": len(expected), "produced_material_changes": len(produced_events),
            "true_positive": true_positive, "false_positive": false_positive, "false_negative": false_negative,
            "precision": precision, "recall": recall,
            "provenance_complete": provenance_complete,
            "provenance_complete_events": sum(bool(item.get("provenance_complete")) for item in produced_events),
            "idempotent_event_ids": idempotent,
            "duplicate_event_ids": len([item.get("event_id") for item in produced_events]) != len(set(item.get("event_id") for item in produced_events)),
            "output_cardinality": output_cardinality,
            "runtime_ms": {"baseline": round(old_runtime, 3), "refresh": round(new_runtime, 3),
                           "repeat_refresh": round(repeat_runtime, 3)},
            "refresh_replay_gate": False,
            "events": produced_events,
        }
        report["refresh_replay_gate"] = (false_positive == 0 and false_negative == 0 and provenance_complete
            and idempotent and not report["duplicate_event_ids"] and output_cardinality)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "events"}, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["refresh_replay_gate"] else 1)


if __name__ == "__main__":
    main()
