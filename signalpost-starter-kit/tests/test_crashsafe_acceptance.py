"""Acceptance-wrapper fixtures only: no pipeline launch, network, SSH or OCR."""
import csv
import gzip
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_crashsafe_acceptance.py"
SPEC = importlib.util.spec_from_file_location("crashsafe_acceptance", SCRIPT)
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)
FIXED = [str(900000000 + index) for index in range(6)]


def jsonl(path, orgs):
    path.write_text("".join(json.dumps({"organisation_number": org}) + "\n" for org in orgs))


@pytest.fixture
def frame(tmp_path):
    registry = tmp_path / "registry.csv"
    columns = ["organisasjonsnummer", "navn", "organisasjonsform.kode", "antallAnsatte",
               "konkurs", "underAvvikling", "underTvangsavviklingEllerTvangsopplosning", "slettedato"]
    with registry.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for index in range(120):
            record = {"organisasjonsnummer": str(900000000 + index), "navn": f"Fixture {index} AS",
                "organisasjonsform.kode": "AS", "antallAnsatte": "3", "konkurs": "nei", "underAvvikling": "nei"}
            if index == 110:
                record["antallAnsatte"] = "0"
            if index == 111:
                record["konkurs"] = "ja"
            if index == 112:
                record["organisasjonsform.kode"] = "ENK"
            if index == 113:
                record["underTvangsavviklingEllerTvangsopplosning"] = "true"
            if index == 114:
                record["slettedato"] = "2025-01-01"
            writer.writerow(record)
    original_dir = tmp_path / "original"
    original_dir.mkdir()
    source = original_dir / "companies.jsonl"
    jsonl(source, [str(900000000 + index) for index in range(100)])
    selection = original_dir / "selection.json"
    acceptance.write(selection, {"fixed_companies": FIXED, "source_file_sha256": acceptance.digest(registry),
        "input_sha256": acceptance.digest(source), "seed": "f" * 64})
    return registry, selection


def metrics_db(path, orgs, missing=None, failed=None, table="company_phase_metrics", payload=False):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE shells(organisation_number TEXT,execution_state TEXT)")
        connection.executemany("INSERT INTO shells VALUES (?, 'terminalized')", [(org,) for org in orgs])
        connection.execute("CREATE TABLE envelopes(payload TEXT)")
        connection.executemany("INSERT INTO envelopes VALUES (?)", [('{}',) for _ in orgs])
        if payload:
            connection.execute(f"CREATE TABLE {table}(company TEXT,phase TEXT,payload TEXT)")
        else:
            fields = ",".join(key + " INTEGER" for key in acceptance.COUNTERS)
            connection.execute(f"CREATE TABLE {table}(company TEXT,phase TEXT,{fields},worker_seconds REAL,wall_seconds REAL)")
        for org in orgs:
            for phase in acceptance.PHASES:
                if (org, phase) == missing:
                    continue
                counters = {key: 0 for key in acceptance.COUNTERS}
                counters.update(ran=1, failed=int((org, phase) == failed), worker_seconds=0.1, wall_seconds=0.1)
                if payload:
                    connection.execute(f"INSERT INTO {table} VALUES (?,?,?)", (org, phase, json.dumps(counters)))
                else:
                    connection.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (org, phase, *(counters[key] for key in (*acceptance.COUNTERS, "worker_seconds", "wall_seconds"))))


def envelope(org):
    return {"organisation_number": org, "terminal_state": "available", "input_ref": org, "batch": {},
        "refresh": {}, "synthesis": {}, "operations": [], "run": {}, "sections": {name: {} for name in
            ("identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
             "hiring_activity", "claims_evidence_states", "refresh_changes")}, "claims": [
        {"claim_id": org + ":finance", "state": "available", "field": "revenue", "value": 0},
        {"claim_id": org + ":fte", "state": "available", "field": "full_time_equivalents", "value": 0},
        {"claim_id": org + ":web", "state": "available", "field": "verified_website_url", "value": "https://fixture.no"},
        {"claim_id": org + ":job", "state": "available", "field_family": "jobs", "scope": "job"}],
        "evidence": [], "source_snapshots": [], "errors": []}


def artifacts(directory, orgs, *, missing_metric=None, failed_phase=None, replay=False, missing_replay_key=None, rows=None):
    directory.mkdir(mode=0o700, exist_ok=True)
    rows = rows if rows is not None else [envelope(org) for org in orgs]
    (directory / "envelopes.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (directory / "state.json").write_text('{"fixture": true}\n')
    metrics_db(directory / "checkpoint.sqlite", orgs, missing_metric, failed_phase)
    batch = {"event": "batch_complete", "output_cardinality": len(orgs), "runtime_seconds": 2.5,
        "finalization_seconds": 0.1,
        "research_mode": "replay" if replay else "live", "actual_network_requests": 0 if replay else 3,
        "http_misses": 0, "http_failures": 0, "ocr_misses": 0,
        "capture_complete": True, "missing_requests": [], "unconsumed_requests": []}
    if missing_replay_key:
        batch.pop(missing_replay_key)
    (directory / "stdout.log").write_text(json.dumps(batch) + "\n")
    (directory / "stderr.log").write_text("")
    acceptance.write(directory / "invocation.json", {"exit_code": 0, "elapsed_seconds": 3, "external_timeout": False})


def base_args(tmp_path, frame):
    registry, original = frame
    return ["--root", str(tmp_path / "acceptance"), "--repository", str(tmp_path / "repo"),
        "--registry", str(registry), "--original-selection", str(original), "--seed", "a" * 64]


def frozen_identity(monkeypatch):
    monkeypatch.setattr(acceptance, "source_identity", lambda _: {"head": "frozen", "source_sha256": "source"})


def test_seeded_selection_has_fixed_six_four_active_random_and_receipt(frame, tmp_path):
    registry, original = frame
    receipt = acceptance.freeze_smoke(registry, original, tmp_path / "one", "a" * 64)
    again = acceptance.freeze_smoke(registry, original, tmp_path / "two", "a" * 64)
    orgs = acceptance.read_input(tmp_path / "one" / "companies.jsonl", 10)
    assert set(FIXED) < set(orgs)
    assert not set(str(900000000 + index) for index in range(110, 115)) & set(orgs)
    assert len([row for row in receipt["rows"] if not row["fixed_six_company_cohort"]]) == 4
    assert receipt["input_sha256"] == again["input_sha256"]
    assert receipt["registry_sha256"] == acceptance.digest(registry)
    assert (tmp_path / "one").stat().st_mode & 0o077 == 0
    assert (tmp_path / "one" / "input-receipt.json").stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        acceptance.freeze_smoke(registry, original, tmp_path / "one", "b" * 64)


def test_selection_requires_original_archived_hash_and_handles_gzip(frame, tmp_path):
    registry, original = frame
    compressed = tmp_path / "registry.csv.gz"
    compressed.write_bytes(gzip.compress(registry.read_bytes()))
    with pytest.raises(acceptance.GateError, match="hash_mismatch"):
        acceptance.freeze_smoke(compressed, original, tmp_path / "bad", "a" * 64)
    selection = json.loads(original.read_text())
    selection["source_file_sha256"] = acceptance.digest(compressed)
    acceptance.write(original, selection)
    assert acceptance.freeze_smoke(compressed, original, tmp_path / "gzip", "a" * 64)["sample_size"] == 10


@pytest.mark.parametrize("payload", [True, False])
def test_durable_metrics_adapters_and_missing_company_phase_fail(tmp_path, payload):
    orgs = FIXED[:2]
    complete = tmp_path / "complete.sqlite"
    metrics_db(complete, orgs, table="phase_metrics", payload=payload)
    assert acceptance.checkpoint_metrics(complete, orgs)["complete"]
    incomplete = tmp_path / "incomplete.sqlite"
    metrics_db(incomplete, orgs, missing=(orgs[0], "nav_apply"))
    result = acceptance.checkpoint_metrics(incomplete, orgs)
    assert not result["complete"]
    assert "required_company_phase_metrics_missing" in result["problems"]


def test_native_checkpoint_phase_status_reader_preserves_explicit_skips_and_private_failure_hash(tmp_path):
    path = tmp_path / "native.sqlite"
    metrics_db(path, FIXED[:2])
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE company_phase_metrics")
        connection.execute("CREATE TABLE phase_status(phase TEXT,company TEXT,payload TEXT)")
        for org in FIXED[:2]:
            for phase in acceptance.PHASES:
                state = "deadline_skipped" if phase == "website_shallow" else "completed"
                payload = {"status": "deadline_skipped" if state == "deadline_skipped" else "ran", "outcome": state,
                    "seconds": 0.2, "ran": state == "completed", "failed": False, "skipped": False,
                    "deadline_skipped": state == "deadline_skipped", "reason": "PRIVATE must not appear"}
                connection.execute("INSERT INTO phase_status VALUES (?,?,?)", (
                    "official" if phase == "official_foundation" else phase, org, json.dumps(payload)))
    report = acceptance.checkpoint_metrics(path, FIXED[:2])
    assert report["complete"]
    assert report["phase_counters"]["website_shallow"]["deadline_skipped"] == 2
    assert report["phase_counters"]["website_shallow"]["skipped"] == 2
    assert report["phase_counters"]["official_foundation"]["worker_seconds"] == 0.4
    assert report["phase_counters"]["official_foundation"]["wall_seconds"] is None
    assert "PRIVATE" not in json.dumps(report)
    with sqlite3.connect(path) as connection:
        payload.update(status="failed", outcome="failed", ran=True, failed=True, deadline_skipped=False,
                       traceback_sha256="a" * 64)
        connection.execute("UPDATE phase_status SET payload=? WHERE phase='official' AND company=?", (json.dumps(payload), FIXED[0]))
    report = acceptance.checkpoint_metrics(path, FIXED[:2])
    assert report["failed"] == 1
    assert report["phase_failure_fingerprints"] == [{"phase": "official_foundation", "traceback_sha256": "a" * 64}]


def test_excluded_frozen_cohorts_never_enter_four_additions(frame, tmp_path):
    registry, original = frame
    receipt = acceptance.freeze_smoke(registry, original, tmp_path / "excluded", "a" * 64, [original.parent])
    additions = [row["organisation_number"] for row in receipt["rows"] if not row["fixed_six_company_cohort"]]
    assert all(int(org) >= 900000100 for org in additions)
    assert receipt["excluded_cohorts"][0]["input_sha256"] == json.loads(original.read_text())["input_sha256"]


def test_isolated_phase_failure_is_reported_without_becoming_a_batch_abort(tmp_path):
    orgs = [str(900000000 + index) for index in range(10)]
    artifacts(tmp_path / "live", orgs, failed_phase=(orgs[0], "website_verify"))
    report = acceptance.summarize(tmp_path / "live", orgs, acceptance.PHASES)
    assert report["final_envelopes"] == 10 and report["aborted_inputs"] == 0
    assert report["phase_failed"] == 1 and report["gate_pass"]
    assert report["gates"]["durable_company_phase_metrics_complete"]
    assert not report["quality_observations"]["zero_phase_failures"]
    assert all(count == 10 for count in report["company_counts"].values())


def test_large_coverage_and_runtime_gates_block_complete_but_insufficient_run(tmp_path):
    orgs = [str(900000000 + index) for index in range(100)]
    rows = [envelope(org) for org in orgs]
    for row in rows[94:]:
        row["claims"] = [claim for claim in row["claims"] if claim.get("field") != "revenue"]
    artifacts(tmp_path / "large", orgs, rows=rows)
    report = acceptance.summarize(tmp_path / "large", orgs, acceptance.PHASES)
    assert report["final_envelopes"] == 100 and report["company_counts"]["finance_companies"] == 94
    assert not report["gates"]["finance_at_least_95"] and not report["gate_pass"]
    assert report["execution_gate_pass"]
    invocation = json.loads((tmp_path / "large" / "invocation.json").read_text())
    invocation["elapsed_seconds"] = 1200.001
    acceptance.write(tmp_path / "large" / "invocation.json", invocation)
    assert not acceptance.summarize(tmp_path / "large", orgs, acceptance.PHASES)["gates"]["runtime_within_1200_seconds"]


def test_aborted_partial_and_missing_finals_are_reported_separately(tmp_path):
    rows = [envelope(org) for org in FIXED]
    rows[0]["run"]["terminal_status"] = "aborted"
    rows[1]["run"]["terminal_status"] = "partial"
    artifacts(tmp_path / "statuses", FIXED, rows=rows[:-1])
    report = acceptance.summarize(tmp_path / "statuses", FIXED, acceptance.PHASES)
    assert report["aborted_inputs"] == report["partial_finals"] == 1
    assert not report["gates"]["zero_aborted_inputs"]
    assert not report["gates"]["exact_final_cardinality_and_order"]


def test_duplicate_claims_report_only_hashes_and_cross_company_conflict(tmp_path):
    rows = [envelope(FIXED[0]), envelope(FIXED[1])]
    claim = {"claim_id": "private-token-collision", "value": "Bearer super-private-value"}
    rows[0]["claims"].extend([claim, {**claim, "value": "second-secret"}])
    rows[1]["claims"].append(claim)
    result = acceptance.collision_evidence(rows)
    assert result["duplicate_count"] == 2
    assert result["conflicting_identifier_count"] >= 1
    assert "private" not in json.dumps(result) and "second-secret" not in json.dumps(result)
    artifacts(tmp_path / "duplicate", FIXED[:2], rows=rows)
    assert not acceptance.summarize(tmp_path / "duplicate", FIXED[:2], acceptance.PHASES)["gate_pass"]


@pytest.mark.parametrize("missing", ["http_misses", "http_failures", "ocr_misses", "actual_network_requests", "research_mode",
                                    "capture_complete", "missing_requests", "unconsumed_requests"])
def test_replay_missing_aggregate_keys_fails_even_equal_bytes(tmp_path, missing):
    orgs = FIXED[:2]
    live, replay = tmp_path / "live", tmp_path / "replay"
    artifacts(live, orgs)
    artifacts(replay, orgs, replay=True, missing_replay_key=missing)
    report = acceptance.summarize(replay, orgs, acceptance.PHASES, True, live)
    assert report["gates"]["exact_output_bytes_equal"]
    assert not report["gate_pass"]


def test_replay_requires_exact_bytes_and_zero_misses(tmp_path):
    orgs = FIXED[:2]
    live, replay = tmp_path / "live", tmp_path / "replay"
    artifacts(live, orgs)
    artifacts(replay, orgs, replay=True)
    assert acceptance.summarize(replay, orgs, acceptance.PHASES, True, live)["gate_pass"]
    with (replay / "envelopes.jsonl").open("a") as stream:
        stream.write("\n")
    assert not acceptance.summarize(replay, orgs, acceptance.PHASES, True, live)["gates"]["exact_output_bytes_equal"]
    (replay / "envelopes.jsonl").write_bytes((live / "envelopes.jsonl").read_bytes())
    batch = json.loads((replay / "stdout.log").read_text())
    batch["http_misses"] = 1
    (replay / "stdout.log").write_text(json.dumps(batch) + "\n")
    assert not acceptance.summarize(replay, orgs, acceptance.PHASES, True, live)["gate_pass"]


@pytest.mark.parametrize("bad_key,value", [("capture_complete", False), ("missing_requests", [{"key": "private-descriptor"}]),
                                         ("unconsumed_requests", [{"key": "private-descriptor"}])])
def test_replay_missing_or_unconsumed_keys_block_even_when_miss_counters_zero(tmp_path, bad_key, value):
    orgs = FIXED[:2]
    live, replay = tmp_path / "live", tmp_path / "replay"
    artifacts(live, orgs)
    artifacts(replay, orgs, replay=True)
    batch = json.loads((replay / "stdout.log").read_text())
    batch[bad_key] = value
    (replay / "stdout.log").write_text(json.dumps(batch) + "\n")
    report = acceptance.summarize(replay, orgs, acceptance.PHASES, True, live)
    assert not report["gate_pass"]
    assert "private-descriptor" not in json.dumps(report)


def test_prepare_only_never_launches_child(frame, tmp_path, monkeypatch, capsys):
    frozen_identity(monkeypatch)
    monkeypatch.setattr(acceptance.subprocess, "Popen", lambda *a, **k: pytest.fail("research launched"))
    assert acceptance.main(base_args(tmp_path, frame) + ["--prepare-only"]) == 0
    assert json.loads(capsys.readouterr().out)["research_launched"] is False
    assert not (tmp_path / "acceptance" / "smoke").exists()


def mocked_process(monkeypatch, *, fail_live=False, mutate_replay=False):
    calls = []

    class Process:
        pid = 98765

        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))
            directory = Path(kwargs["cwd"])
            source = Path(command[command.index("--input") + 1])
            orgs = acceptance.read_input(source, 10 if "smoke" in directory.name else 100)
            replay = "--replay-http" in command
            if fail_live:
                kwargs["stderr"].write(b'Traceback (most recent call last):\n  File "/private/secret.py", line 42, in project\nValueError: Bearer credential secret\n')
                return
            artifacts(directory, orgs, replay=replay)
            if mutate_replay and replay:
                with (directory / "envelopes.jsonl").open("a") as stream:
                    stream.write("\n")

        def wait(self, timeout=None):
            return 1 if fail_live else 0

    monkeypatch.setattr(acceptance.subprocess, "Popen", Process)
    return calls


def test_default_runs_only_smoke_then_replay_with_private_logs_fresh_checkpoints(frame, tmp_path, monkeypatch):
    frozen_identity(monkeypatch)
    calls = mocked_process(monkeypatch)
    args = base_args(tmp_path, frame)
    assert acceptance.main(args) == 0
    assert len(calls) == 2
    first, second = calls
    assert "--record-http" in first[0] and "--replay-http" in second[0]
    assert first[0][0].endswith("/run.sh")
    assert first[0][first[0].index("--checkpoint") + 1] != second[0][second[0].index("--checkpoint") + 1]
    assert first[1]["env"]["HOME"] != second[1]["env"]["HOME"]
    assert first[1]["env"]["SIGNALPOST_OCR_CACHE"] == second[1]["env"]["SIGNALPOST_OCR_CACHE"]
    assert (tmp_path / "acceptance" / "smoke" / "stdout.log").stat().st_mode & 0o077 == 0
    assert not (tmp_path / "acceptance" / "matched").exists()
    assert acceptance.main(args) == 1
    assert len(calls) == 2


def test_failed_smoke_stops_before_replay_reports_traceback_without_secrets(frame, tmp_path, monkeypatch, capsys):
    frozen_identity(monkeypatch)
    calls = mocked_process(monkeypatch, fail_live=True)
    assert acceptance.main(base_args(tmp_path, frame)) == 1
    assert len(calls) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["failed_stage"] == "smoke"
    assert report["report"]["failure_evidence"]["exception_types"] == ["ValueError"]
    assert report["report"]["failure_evidence"]["traceback_frames"] == [{"line": 42, "function": "project"}]
    assert "credential" not in json.dumps(report) and "/private/secret.py" not in json.dumps(report)


def test_large_stages_require_flag_and_persisted_smoke_replay_gate(frame, tmp_path, monkeypatch):
    frozen_identity(monkeypatch)
    calls = mocked_process(monkeypatch, mutate_replay=True)
    args = base_args(tmp_path, frame)
    assert acceptance.main(args) == 1
    assert len(calls) == 2
    assert acceptance.main(args + ["--stage", "matched", "--matched-selection", str(frame[1].parent)]) == 1
    assert acceptance.main(args + ["--stage", "matched", "--allow-100", "--matched-selection", str(frame[1].parent)]) == 1
    assert len(calls) == 2


def test_matched_and_holdout_order_hashes_disjointness_and_no_automatic_next_stage(frame, tmp_path, monkeypatch):
    frozen_identity(monkeypatch)
    calls = mocked_process(monkeypatch)
    args = base_args(tmp_path, frame)
    assert acceptance.main(args) == 0
    matched = args + ["--stage", "matched", "--allow-100", "--matched-selection", str(frame[1].parent)]
    assert acceptance.main(matched) == 0
    assert len(calls) == 4
    holdout = tmp_path / "holdout-input"
    holdout.mkdir()
    jsonl(holdout / "companies.jsonl", [str(800000000 + index) for index in range(100)])
    acceptance.write(holdout / "selection.json", {"input_sha256": acceptance.digest(holdout / "companies.jsonl"), "seed": "e" * 64})
    holdout_args = args + ["--stage", "holdout", "--allow-100", "--holdout-selection", str(holdout)]
    assert acceptance.main(holdout_args) == 1
    assert len(calls) == 4
    assert acceptance.main(holdout_args + ["--confirm-unobserved-holdout"]) == 0
    assert len(calls) == 6
    assert [Path(kwargs["cwd"]).name for _, kwargs in calls] == ["smoke", "smoke-replay", "matched", "matched-replay", "holdout", "holdout-replay"]


def test_changed_prerequisite_or_config_blocks_large_run(frame, tmp_path, monkeypatch):
    frozen_identity(monkeypatch)
    calls = mocked_process(monkeypatch)
    args = base_args(tmp_path, frame)
    assert acceptance.main(args) == 0
    root = tmp_path / "acceptance"
    with (root / "smoke-replay" / "envelopes.jsonl").open("a") as stream:
        stream.write("\n")
    assert acceptance.main(args + ["--stage", "matched", "--allow-100", "--matched-selection", str(frame[1].parent)]) == 1
    assert len(calls) == 2
    (root / "config.json").write_text('{"changed": true}')
    assert acceptance.main(args) == 1
    assert len(calls) == 2


def test_timeout_kills_process_group_once_and_does_not_retry(tmp_path, monkeypatch):
    calls, signals = [], []
    source = tmp_path / "companies.jsonl"
    jsonl(source, FIXED)
    config = tmp_path / "config.json"
    config.write_text("{}")

    class Process:
        pid = 12345

        def __init__(self, *args, **kwargs):
            calls.append(args)

        def wait(self, timeout=None):
            if timeout != 20:
                raise subprocess.TimeoutExpired("private command", timeout)
            return -15

    monkeypatch.setattr(acceptance.subprocess, "Popen", Process)
    monkeypatch.setattr(acceptance.os, "killpg", lambda *args: signals.append(args))
    acceptance.launch(tmp_path, tmp_path / "run", source, config, "batch", 1)
    report = json.loads((tmp_path / "run" / "invocation.json").read_text())
    assert report["external_timeout"] and report["exit_code"] == -15
    assert len(calls) == len(signals) == 1
