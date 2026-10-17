"""Wrapper contracts without network, package installation or company research."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def wrapper(tmp_path, ready=True):
    repo = tmp_path / "checkout with spaces"
    repo.mkdir()
    shutil.copy2(ROOT / "run.sh", repo / "run.sh")
    if ready:
        environment = repo / "signalpost-starter-kit" / ".venv"
        (environment / "bin").mkdir(parents=True)
        (environment / ".signalpost-ready.json").write_text("{}")
        python = environment / "bin" / "python"
        python.write_text('''#!/bin/sh
if [ "$1" = -I ]; then exit 0; fi
printf '%s\\0' "$@" > "$ARGUMENT_LOG"
printf 'evaluator stdout\\n'
printf 'evaluator stderr\\n' >&2
exit 37
''')
        python.chmod(0o755)
    return repo


def test_missing_environment_explains_setup(tmp_path):
    repo = wrapper(tmp_path, False)
    result = subprocess.run([str(repo / "run.sh"), "--help"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2 and "setup.sh" in result.stderr
    assert not result.stdout
    assert not (repo / ".signalpost-tools").exists()


def test_live_defaults_and_literal_arguments_preserve_streams_and_exit(tmp_path):
    repo = wrapper(tmp_path)
    log = tmp_path / "arguments"
    arguments = ["--input", "companies with spaces.jsonl", "--output", "literal $(touch unwanted).jsonl"]
    result = subprocess.run([str(repo / "run.sh"), *arguments], cwd=tmp_path,
                            env={**os.environ, "ARGUMENT_LOG": str(log)}, capture_output=True, text=True)
    assert result.returncode == 37
    assert result.stdout == "evaluator stdout\n" and result.stderr == "evaluator stderr\n"
    assert log.read_bytes().split(b"\0")[:-1] == [str(repo / "signalpost-starter-kit/run_signalpost.py").encode(),
        b"--live-brreg", b"--live-websites", *[a.encode() for a in arguments]]
    assert not (tmp_path / "unwanted").exists()


def test_explicit_snapshot_preserves_canonical_offline_arguments(tmp_path):
    repo = wrapper(tmp_path)
    log = tmp_path / "arguments"
    arguments = ["--registry-snapshot=/path with spaces/registry.jsonl", "--input", "batch.jsonl"]
    subprocess.run([str(repo / "run.sh"), *arguments], cwd=tmp_path,
                   env={**os.environ, "ARGUMENT_LOG": str(log)}, capture_output=True)
    assert log.read_bytes().split(b"\0")[1:-1] == [a.encode() for a in arguments]


def test_uninitialized_environment_is_not_silently_used(tmp_path):
    repo = wrapper(tmp_path)
    (repo / "signalpost-starter-kit/.venv/.signalpost-ready.json").unlink()
    result = subprocess.run([str(repo / "run.sh")], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2 and "setup.sh" in result.stderr


def test_run_has_no_installation_entrypoint():
    script = (ROOT / "run.sh").read_text()
    assert "uv sync" not in script and "pip install" not in script
    assert "curl " not in script and "wget " not in script


def test_stale_lock_stamp_requires_explicit_setup(tmp_path):
    repo = wrapper(tmp_path)
    python = repo / "signalpost-starter-kit/.venv/bin/python"
    python.unlink()
    python.symlink_to(sys.executable)
    result = subprocess.run([str(repo / "run.sh"), "--help"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2 and "out of date" in result.stderr
