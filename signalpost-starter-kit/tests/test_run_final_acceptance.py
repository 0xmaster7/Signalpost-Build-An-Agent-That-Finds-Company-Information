"""Final acceptance orchestration fixtures; all subprocesses are mocked."""
import csv
import gzip
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_final_acceptance.py"
SPEC = importlib.util.spec_from_file_location("run_final_acceptance", SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def write_selection(directory, orgs):
    directory.mkdir(parents=True)
    payload = "".join(json.dumps({"organisation_number": org}) + "\n" for org in orgs).encode()
    (directory / "companies.jsonl").write_bytes(payload)
    (directory / "selection.json").write_text(json.dumps({"input_sha256": runner.hashlib.sha256(payload).hexdigest(),
        "sample_size": len(orgs)}))


@pytest.fixture
def registry_fixture(tmp_path):
    path = tmp_path / "registry.csv.gz"
    fields = ["organisasjonsnummer", "navn", "organisasjonsform.kode", "antallAnsatte", "konkurs", "underAvvikling",
        "underTvangsavviklingEllerTvangsopplosning", "slettedato"]
    rows = []
    for index in range(1600):
        rows.append({"organisasjonsnummer": f"{910000000 + index}", "navn": f"Test {index}",
            "organisasjonsform.kode": "AS", "antallAnsatte": "3", "konkurs": "nei", "underAvvikling": "nei"})
    rows[130]["antallAnsatte"] = "0"
    rows[131]["konkurs"] = "ja"
    rows[132]["organisasjonsform.kode"] = "ENK"
    import io
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    path.write_bytes(gzip.compress(text.getvalue().encode()))
    original = tmp_path / "original.json"
    fixed = [f"{910000000 + index}" for index in range(6)]
    original.write_text(json.dumps({"fixed_companies": fixed, "source_file_sha256": runner.digest(path)}))
    return path, original, fixed


def test_selection_is_deterministic_private_and_excludes_frozen_cohort(registry_fixture, tmp_path):
    registry, original, fixed = registry_fixture
    blocked = tmp_path / "blocked"
    write_selection(blocked, [f"{910000000 + index}" for index in range(10, 20)])
    one, two = tmp_path / "one", tmp_path / "two"
    first = runner.freeze_sample(registry, original, one, count=10, seed="a" * 64, exclusions=[blocked], fixed_six=True)
    second = runner.freeze_sample(registry, original, two, count=10, seed="a" * 64, exclusions=[blocked], fixed_six=True)
    orgs = runner.helper.read_input(one / "companies.jsonl", 10)
    assert first["input_sha256"] == second["input_sha256"]
    assert set(fixed) <= set(orgs)
    assert not set(orgs) & set(f"{910000000 + index}" for index in range(10, 20))
    assert not set(orgs) & {"910000130", "910000131", "910000132"}
    assert one.stat().st_mode & 0o077 == 0
    assert (one / "companies.jsonl").stat().st_mode & 0o077 == 0


def test_selection_refuses_existing_destination_and_bad_seed(registry_fixture, tmp_path):
    registry, original, _ = registry_fixture
    destination = tmp_path / "frozen"
    runner.freeze_sample(registry, original, destination, count=10, seed="b" * 64, exclusions=[], fixed_six=True)
    with pytest.raises(FileExistsError):
        runner.freeze_sample(registry, original, destination, count=10, seed="c" * 64, exclusions=[], fixed_six=True)
    with pytest.raises(runner.FinalGateError, match="seed_requires"):
        runner.freeze_sample(registry, original, tmp_path / "bad", count=10, seed="bad", exclusions=[], fixed_six=True)


def test_prepare_only_never_launches_and_freezes_all_four_cohorts(registry_fixture, tmp_path, monkeypatch):
    registry, original, _ = registry_fixture
    matched = tmp_path / "matched"
    write_selection(matched, [f"{910000000 + index}" for index in range(40, 140)])
    monkeypatch.setattr(runner, "EXPECTED_REGISTRY", runner.digest(registry))
    monkeypatch.setattr(runner, "EXPECTED_MATCHED", runner.digest(matched / "companies.jsonl"))
    monkeypatch.setattr(runner, "launch", lambda *args, **kwargs: pytest.fail("prepare-only launched run.sh"))
    root = tmp_path / "acceptance"
    argv = ["--root", str(root), "--repository", str(Path(__file__).resolve().parents[2]),
        "--registry", str(registry), "--original-selection", str(original), "--matched-selection", str(matched),
        "--seed", "d" * 64, "--prepare-only"]
    assert runner.main(argv) == 0
    manifest = json.loads((root / "acceptance.json").read_text())
    assert manifest["cohorts_frozen_before_outcomes"] is True
    assert manifest["budget_seconds"] == 1800
    assert {stage: runner.digest(root / f"{stage}-selection" / "companies.jsonl")
        for stage in ("smoke", "matched", "fresh", "scale")} == {
            stage: manifest[f"{stage}_input_sha256"] for stage in ("smoke", "matched", "fresh", "scale")}
    cohorts = [set(runner.helper.read_input(root / f"{stage}-selection" / "companies.jsonl", count))
        for stage, count in (("smoke", 10), ("matched", 100), ("fresh", 100), ("scale", 1000))]
    assert all(not cohorts[first] & cohorts[second] for first in range(4) for second in range(first + 1, 4))


def test_launch_invokes_run_sh_with_live_recording_and_private_caches(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_sh = repo / "run.sh"
    run_sh.write_text("#!/bin/sh\n")
    directory = tmp_path / "stage"
    source, config = tmp_path / "companies.jsonl", tmp_path / "config.json"
    source.write_text("{}\n")
    config.write_text("{}\n")
    seen = {}

    class Process:
        pid = 999991
        def wait(self, timeout=None):
            return 0

    def popen(command, **kwargs):
        seen.update(command=command, kwargs=kwargs)
        return Process()

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    runner.launch(repo, directory, source, config, "batch", 100, 1800)
    assert seen["command"][-2:] == ["--budget-seconds", "1800"]
    assert "--live-brreg" not in seen["command"]
    assert "--record-http" in seen["command"]
    env = seen["kwargs"]["env"]
    assert env["SIGNALPOST_OCR_CACHE"] == str(directory / "ocr-cache")
    assert env["SIGNALPOST_NAV_CACHE"] == str(directory / "nav-cache")
    assert oct((directory / "stdout.log").stat().st_mode & 0o777) == "0o600"


def test_scale_report_has_no_coverage_counts(tmp_path, monkeypatch):
    orgs = [f"{920000000 + index}" for index in range(1000)]
    with sqlite3.connect(tmp_path / "checkpoint.sqlite"):
        pass
    monkeypatch.setattr(runner, "scale_summary", lambda *args, **kwargs: {"status": "passed", "gate_pass": True,
        "execution_gate_pass": True, "gates": {}, "final_envelopes": 1000, "company_counts": {"finance_companies": 999},
        "quality_observations": {"coverage": 9}, "duplicate_count": 0, "missing_identifier_count": 0})
    monkeypatch.setattr(runner.helper, "summarize", lambda *args, **kwargs: pytest.fail("scale inspected coverage"))
    report = runner.sanitized_report(tmp_path, orgs, "scale", False)
    assert "company_counts" not in report and "quality_observations" not in report
    assert "scale_rows" in report


def test_new_root_policy_blocks_attempt_overwrite(tmp_path):
    root = tmp_path / "exists"
    root.mkdir()
    repository = tmp_path / "repo"
    repository.mkdir()
    args = type("Args", (), {"root": root, "repository": repository, "registry": None,
        "original_selection": None, "matched_selection": None})()
    with pytest.raises(runner.FinalGateError, match="must_be_new"):
        runner.prepare(args)


def test_final_configuration_preserves_breadth_request_capacity():
    config = runner.config_default(1800)["budget"]
    assert config["physical_request_limit"] >= 2 * 1100
    assert "official_details" in runner.helper.PHASES
    assert config["soft_seconds"] + config["completion_reserve_seconds"] == config["hard_seconds"]


def test_timing_report_includes_per_company_totals(tmp_path, monkeypatch):
    orgs = [str(920000000 + index) for index in range(1000)]
    with sqlite3.connect(tmp_path / "checkpoint.sqlite") as database:
        database.execute("CREATE TABLE phase_status (phase TEXT, company TEXT, payload TEXT)")
        database.executemany("INSERT INTO phase_status VALUES (?, ?, ?)", [
            ("official", orgs[0], json.dumps({"seconds": 2})),
            ("financial_statements", orgs[0], json.dumps({"seconds": 4})),
            ("official", orgs[1], json.dumps({"seconds": 10})),
            ("nav_batch", orgs[0], json.dumps({"seconds": 100})),
        ])
    monkeypatch.setattr(runner, "scale_summary", lambda *args, **kwargs: {})
    report = runner.sanitized_report(tmp_path, orgs, "scale", False)
    assert report["timing_percentiles"]["company_total_recorded_seconds_p50"] == 8
    assert report["timing_percentiles"]["company_total_recorded_seconds_p95"] == pytest.approx(9.8)


def test_public_phase_counts_are_disjoint(tmp_path, monkeypatch):
    counters = {"ran": 3, "failed": 1, "skipped": 7, "deadline_skipped": 4, "worker_seconds": 12}
    monkeypatch.setattr(runner.helper, "summarize", lambda *args, **kwargs: {
        "checkpoint": {"phase_counters": {"official_details": counters}},
        "phase_wall_seconds": {"official_details": 8},
    })
    report = runner.sanitized_report(tmp_path, ["920710514"], "smoke", False)
    assert report["phase_status_counts"]["official_details"] == {
        "ran": 2, "failed": 1, "skipped": 3, "deadline_skipped": 4,
        "company_seconds": 12, "wall_seconds": 8,
    }
