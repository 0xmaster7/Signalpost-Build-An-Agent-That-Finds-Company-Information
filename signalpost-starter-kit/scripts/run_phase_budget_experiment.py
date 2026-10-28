"""Run one matched treatment and one disjoint holdout without intervening tuning."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from datetime import datetime, timezone


MATCHED_HASH = "acd65b35b1a87ef35c77fa673e4a44b63bd3718b339bc69adddc152889692076"


def digest(filename):
    return hashlib.sha256(filename.read_bytes()).hexdigest()


def write(filename, value):
    temporary = filename.with_suffix(filename.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(filename)


def utc():
    return datetime.now(timezone.utc).isoformat()


def revision(repository):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()


def inputs(filename):
    rows = [json.loads(line) for line in filename.read_text().splitlines() if line.strip()]
    organisations = {row["organisation_number"] for row in rows}
    if len(rows) != 100 or len(organisations) != 100:
        raise ValueError("Each cohort requires 100 unique organisations")
    return organisations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--matched-input", required=True, type=Path)
    parser.add_argument("--holdout-selection", required=True, type=Path)
    parser.add_argument("--preregistration", type=Path)
    parser.add_argument("--record-http", action="store_true")
    args = parser.parse_args()
    root, repository = args.root.resolve(), args.repository.resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest_file = root / "experiment.json"
    if manifest_file.exists():
        raise SystemExit("Experiment already exists; do not overwrite or repeat a cohort")
    holdout_input = args.holdout_selection / "companies.jsonl"
    selection = json.loads((args.holdout_selection / "selection.json").read_text())
    if digest(args.matched_input) != MATCHED_HASH or digest(holdout_input) != selection["input_sha256"]:
        raise ValueError("Frozen input hash mismatch")
    if inputs(args.matched_input) & inputs(holdout_input):
        raise ValueError("Matched and holdout populations overlap")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repository).strip():
        raise ValueError("Treatment checkout has tracked modifications")
    source_sha = revision(repository)
    preregistration = args.preregistration or repository / "docs/release/PHASE_BUDGET_PREREGISTRATION_2026-10-27.md"
    config = root / "matched-budget.json"
    write(config, {"budget": {"hard_seconds": 2700, "soft_seconds": 2214,
        "completion_reserve_seconds": 486, "physical_request_limit": 2000,
        "financial_seconds": 180, "financial_requests_per_company": 1,
        "nav_seconds": 360, "wikidata_seconds": 12, "website_seconds": 480,
        "ocr_seconds": 900, "ocr_budget_share": 0.65}})
    manifest = {"status": "running", "started_at_utc": utc(), "source_sha": source_sha,
        "preregistration_sha256": digest(preregistration), "configuration_sha256": digest(config),
        "cohort_order": ["matched", "holdout"], "implementation_changes_between_runs": False,
        "cold_research_caches": True, "cold_ocr_caches": True, "concurrent_cohorts": False,
        "http_recording": args.record_http,
        "pass_criteria": {"companies_with_verified_website": 20, "companies_with_financial_claims": 95,
            "companies_with_fte": 50, "maximum_elapsed_seconds": 1200, "terminal_envelopes": 100},
        "input_hashes": {"matched": MATCHED_HASH, "holdout": digest(holdout_input)}, "runs": {}}
    write(manifest_file, manifest)
    for name, source in (("matched", args.matched_input), ("holdout", holdout_input)):
        if revision(repository) != source_sha or digest(config) != manifest["configuration_sha256"]:
            raise ValueError("Treatment changed between cohorts")
        if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repository).strip():
            raise ValueError("Treatment has uncommitted changes between cohorts")
        destination = root / name
        destination.mkdir()
        home = destination / "home"
        home.mkdir()
        source_copy = destination / "companies.jsonl"
        source_copy.write_bytes(source.read_bytes())
        if digest(source_copy) != manifest["input_hashes"][name]:
            raise ValueError("Cohort changed after registration")
        command = [str(repository / "run.sh"), "--input", str(source_copy),
            "--output", str(destination / "envelopes.jsonl"), "--state-output", str(destination / "state.json"),
            "--checkpoint", str(destination / "checkpoint.sqlite"), "--config", str(config)]
        if args.record_http:
            command.extend(["--record-http", str(destination / "http-capture")])
        record = {"status": "running", "started_at_utc": utc(), "command": command}
        manifest["runs"][name] = record
        write(manifest_file, manifest)
        environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8", "TZ": "UTC", "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
            "SIGNALPOST_OCR_CACHE": str(destination / "ocr-cache")}
        started = time.monotonic()
        with (destination / "stdout.log").open("wb") as stdout, (destination / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(["/usr/bin/time", "-v", "-o", str(destination / "resources.txt"), *command],
                cwd=root, env=environment, stdout=stdout, stderr=stderr, start_new_session=True)
            record["pid"] = process.pid
            write(manifest_file, manifest)
            try:
                code = process.wait(timeout=3000)
            except subprocess.TimeoutExpired:
                record["external_timeout"] = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    code = process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    code = process.wait()
        record.update(status="completed" if code == 0 else "failed", exit_code=code,
            elapsed_seconds=round(time.monotonic() - started, 3), completed_at_utc=utc(),
            source_sha_after=revision(repository))
        output = destination / "envelopes.jsonl"
        if output.exists():
            record["output_sha256"] = digest(output)
            record["terminal_rows"] = sum(bool(line.strip()) for line in output.read_text().splitlines())
        write(manifest_file, manifest)
    manifest.update(status="completed", completed_at_utc=utc())
    write(manifest_file, manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
