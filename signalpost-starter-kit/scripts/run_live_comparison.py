"""Run frozen implementations sequentially without source or outcome changes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def utc():
    return datetime.now(timezone.utc).isoformat()


def revision(repository):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ours-repo", type=Path, required=True)
    parser.add_argument("--arnav-repo", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    selection = json.loads((root / "selection" / "selection.json").read_text())
    source = root / "selection" / "companies.jsonl"
    if hashlib.sha256(source.read_bytes()).hexdigest() != selection["input_sha256"]:
        raise SystemExit("Frozen benchmark input changed")
    if (root / "execution.json").exists():
        raise SystemExit("Benchmark execution already exists; do not silently overwrite or rerun")
    for repository in (args.ours_repo, args.arnav_repo):
        dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repository)
        if dirty.strip():
            raise SystemExit("Benchmark sources must have no tracked modifications")
    (root / "home").mkdir(exist_ok=True)
    (root / "ours").mkdir(exist_ok=True)
    (root / "arnav").mkdir(exist_ok=True)
    budget = {"budget": {"hard_seconds": 2700, "soft_seconds": 2214, "completion_reserve_seconds": 486,
                         "physical_request_limit": 2000}}
    write(root / "matched-budget.json", budget)
    commands = {
        "ours": [str(args.ours_repo / "run.sh"), "--input", str(source), "--output", str(root / "ours" / "envelopes.jsonl"),
            "--state-output", str(root / "ours" / "state.json"), "--checkpoint", str(root / "ours" / "checkpoint.sqlite"),
            "--config", str(root / "matched-budget.json")],
        "arnav": [str(args.arnav_repo / ".venv" / "bin" / "python"), "-m", "signalpost", "--input", str(source),
            "--output-dir", str(root / "arnav" / "out"), "--cache-dir", str(root / "arnav" / "cache"),
            "--state-dir", str(root / "arnav" / "state")],
    }
    environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(root / "home"), "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8", "TZ": "UTC", "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    manifest = {"started_at_utc": utc(), "status": "running", "input_sha256": selection["input_sha256"],
        "sample_size": 100, "order": ["ours", "arnav"], "concurrent_runs": False, "cold_research_caches": True,
        "host": {"system": platform.system(), "machine": platform.machine(), "cpus": os.cpu_count()},
        "shared_request_cap": 2000, "shared_wall_cap_seconds": 2700, "shared_soft_seconds": 2214,
        "external_safety_timeout_seconds": 3000, "numerical_threads_per_process": 1,
        "sampling_download_included_in_research_request_counts": False,
        "sampling_source_requests": 1, "versions": {"ours": revision(args.ours_repo), "arnav": revision(args.arnav_repo)},
        "runs": {}}
    write(root / "execution.json", manifest)
    for name in manifest["order"]:
        repository = args.ours_repo if name == "ours" else args.arnav_repo
        command = ["/usr/bin/time", "-v", "-o", str(root / name / "resources.txt"), *commands[name]]
        record = {"status": "running", "started_at_utc": utc(), "command": commands[name],
                  "working_directory": str(root) if name == "ours" else str(repository)}
        manifest["runs"][name] = record
        write(root / "execution.json", manifest)
        started = time.monotonic()
        with (root / name / "stdout.log").open("wb") as stdout, (root / name / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(command, cwd=record["working_directory"], env=environment,
                stdout=stdout, stderr=stderr, start_new_session=True)
            record["pid"] = process.pid
            write(root / "execution.json", manifest)
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
            completed_at_utc=utc(), elapsed_seconds=round(time.monotonic() - started, 3),
            source_revision_after=revision(repository))
        output = root / name / "envelopes.jsonl" if name == "ours" else root / name / "out" / "envelopes.jsonl"
        if output.exists():
            record["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
            with output.open() as handle:
                record["terminal_rows_present"] = sum(1 for line in handle if line.strip())
        write(root / "execution.json", manifest)
    manifest.update(status="completed", completed_at_utc=utc())
    write(root / "execution.json", manifest)
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
