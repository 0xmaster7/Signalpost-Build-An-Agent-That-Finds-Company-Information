from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from signalpost import operations
from signalpost.models import Claim, Envelope, Evidence, PublicState, RefreshState, Section, SourceSnapshot
from signalpost.operations import (CheckpointStore, OrderedAtomicWriter, PartialEnvelopePublisher,
                                   publish_paired_artifacts, validate_paired_publication)


def envelope_fixture(row_number=1, *, graph=True):
    observed_at = datetime(2026, 11, 5, tzinfo=timezone.utc)
    source_id = f"source:{row_number}"
    source_url = f"https://example.test/{row_number}"
    return Envelope(
        input_ref=f"row:{row_number}", row_number=row_number, organisation_number="923609016",
        terminal_state=PublicState.NOT_AVAILABLE,
        sections={name: Section(state=None, attempt_outcome="NOT_ATTEMPTED") for name in (
            "identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
            "hiring_activity", "claims_evidence_states", "refresh_changes")},
        refresh=RefreshState(), batch_id="checkpoint-fixture", evidence_cutoff=observed_at,
        created_at=observed_at,
        evidence=[Evidence(evidence_id=f"evidence:{row_number}", source_url=source_url,
            retrieved_at=observed_at, content_sha256="a" * 64, extraction_method="fixture",
            subject_organisation_number="923609016", source_snapshot_ids=[source_id])] if graph else [],
        source_snapshots=[SourceSnapshot(source_id=source_id, source_url=source_url,
            retrieved_at=observed_at, content_sha256="a" * 64)] if graph else [])


def shared_copy(envelope, row_number):
    copied = envelope.model_copy(deep=True)
    copied.row_number = row_number
    copied.input_ref = f"row:{row_number}"
    return copied


def output_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def store(tmp_path):
    checkpoint = CheckpointStore(tmp_path / "checkpoint.sqlite")
    yield checkpoint
    checkpoint.close()


@pytest.mark.parametrize("kind", ["evidence", "snapshots"])
def test_cross_row_identity_conflicts_reject_without_mutation(store, kind):
    original = envelope_fixture()
    store.put(original)
    changed = shared_copy(original, 2)
    if kind == "evidence":
        changed.evidence[0].excerpt = "conflicting observation"
    else:
        changed.evidence[0].evidence_id = "separate-evidence"
        changed.source_snapshots[0].rights_status = "changed"
    for action in (store.put, lambda row: store.save_phase("official", "company", {}, [row])):
        with pytest.raises(ValueError, match="conflicting"):
            action(changed)
    assert len(store.rows()) == 1
    assert store.phase_results("official") == {}
    store.put(shared_copy(original, 2))
    assert len(store.rows()) == 2


def test_replacement_releases_old_references_and_supports_joint_replacement(store):
    original = envelope_fixture()
    store.save_phase("official", "company", {}, [original, shared_copy(original, 2)])
    revised = original.model_copy(deep=True)
    revised.evidence[0].excerpt = "revised observation"
    with pytest.raises(ValueError, match="conflicting"):
        store.put(revised)
    store.save_phase("official", "company", {"revision": 2}, [revised, shared_copy(revised, 2)])
    assert store._identity_index.references["evidence"]["evidence:1"][1] == 2
    store.put(envelope_fixture(1, graph=False))
    with pytest.raises(ValueError, match="conflicting"):
        store.put(shared_copy(original, 3))
    store.put(envelope_fixture(2, graph=False))
    store.put(shared_copy(original, 3))
    assert set(store._identity_index.references["evidence"]) == {"evidence:1"}


def test_snapshot_observation_times_can_differ_but_evidence_times_cannot(store):
    original = envelope_fixture()
    store.put(original)
    duplicate = shared_copy(original, 2)
    duplicate.source_snapshots[0].retrieved_at += timedelta(seconds=1)
    store.put(duplicate)
    duplicate.evidence[0].retrieved_at += timedelta(seconds=1)
    with pytest.raises(ValueError, match="conflicting evidence"):
        store.put(duplicate)


def test_save_phase_sql_failure_rolls_back_result_rows_shells_and_index(store):
    original = envelope_fixture()
    store.put(original)
    store.connection.execute("INSERT INTO shells VALUES (1,'row:1','923609016','pending')")
    store.connection.execute("INSERT INTO shells VALUES (2,'row:2','923609016','pending')")
    store.connection.execute("CREATE TRIGGER reject_second BEFORE INSERT ON envelopes "
                             "WHEN NEW.row_number=2 BEGIN SELECT RAISE(ABORT,'fixture rejection'); END")
    store.connection.commit()
    replacement = envelope_fixture(1, graph=False)
    with pytest.raises(sqlite3.IntegrityError, match="fixture rejection"):
        store.save_phase("official", "company", {"saved": True}, [replacement, envelope_fixture(2)])
    assert store.phase_results("official") == {}
    assert store.shell_states() == {1: "pending", 2: "pending"}
    assert store.rows()[0] == original
    assert set(store._identity_index.references["evidence"]) == {"evidence:1"}
    conflicting = shared_copy(original, 3)
    conflicting.evidence[0].excerpt = "must still conflict"
    with pytest.raises(ValueError, match="conflicting"):
        store.put(conflicting)


def test_put_keeps_index_current_and_validation_does_not_commit(store):
    store.put(envelope_fixture())
    index = store._identity_index
    proposed = envelope_fixture(2)
    view = store.validate_phase_update([proposed])
    assert set(view) == {1, 2}
    assert set(store._identity_graphs) == {1}
    with pytest.raises(TypeError):
        view[3] = {}
    store.put(proposed)
    assert store._identity_index is index
    assert set(store._identity_graphs) == {1, 2}


def test_mutated_and_stored_invalid_graphs_are_revalidated(store, tmp_path):
    invalid = envelope_fixture()
    invalid.claims.append(Claim(claim_id="bad", organisation_number="923609016", section="identity_brand",
        field_family="identity", subject_id="923609016", field="legal_name", value="Unproven",
        state=PublicState.AVAILABLE, evidence_ids=["evidence:1"], source_snapshot_ids=["source:1"],
        scope="legal_entity", verification_rule_id="fixture_v1", verification_score="1.0"))
    invalid.claims[0].evidence_ids[:] = ["missing"]
    for action in (store.put, lambda row: store.validate_phase_update([row]),
                   lambda row: store.save_phase("official", "company", {}, [row])):
        with pytest.raises(ValueError):
            action(invalid)
    assert store.rows() == []
    store.connection.execute("INSERT INTO envelopes VALUES (?,?)", (1, invalid.model_dump_json()))
    store.connection.commit()
    resumed = CheckpointStore(store.path)
    try:
        with pytest.raises(ValueError):
            resumed.put(envelope_fixture(2))
        assert resumed._identity_index is None
    finally:
        resumed.close()


def test_thousand_incremental_updates_validate_linear_rows_and_use_point_status_lookup(store):
    statements = []
    store.connection.set_trace_callback(statements.append)
    with patch.object(operations, "_envelope_identity_graph", wraps=operations._envelope_identity_graph) as signatures:
        for row_number in range(1, 1001):
            envelope = envelope_fixture(row_number)
            store.validate_phase_update([envelope])
            store.put(envelope)
            store.save_phase_status("official", str(row_number), "completed")
            assert store.phase_status("official", str(row_number))["outcome"] == "completed"
        assert signatures.call_count == 2000
    assert sum(statement == "SELECT payload FROM envelopes" for statement in statements) == 1
    assert not any("SELECT company,payload FROM phase_status" in statement for statement in statements)
    assert store.phase_status("official", "missing") is None
    assert len(store._identity_graphs) == 1000


def test_resumed_index_loads_existing_validated_rows_once(store):
    for row_number in range(1, 11):
        store.put(envelope_fixture(row_number))
    resumed = CheckpointStore(store.path)
    try:
        with patch.object(operations, "_envelope_identity_graph", wraps=operations._envelope_identity_graph) as signatures:
            resumed.put(envelope_fixture(11))
            resumed.put(envelope_fixture(12))
            assert signatures.call_count == 12
    finally:
        resumed.close()


def test_initial_partial_is_ordered_complete_detached_and_flagged(tmp_path):
    from signalpost.adapter import to_evaluator
    rows = [envelope_fixture(row_number, graph=False) for row_number in (3, 1, 2)]
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
    PartialEnvelopePublisher(writer, rows, serializer=to_evaluator)
    published = output_rows(writer.output_path)
    assert [item["input_ref"] for item in published] == ["row:1", "row:2", "row:3"]
    assert all(not item["claims"] for item in published)
    assert all(section["attempt_outcome"] == "NOT_ATTEMPTED" for item in published
               for section in item["sections"].values())
    with pytest.raises(ValueError, match="incomplete"):
        validate_paired_publication(writer.output_path.with_name("output.jsonl.publication.json"))


def test_partial_update_caches_serialization_and_flushes_on_count_time_or_force(tmp_path):
    elapsed = [0.0]
    calls = []
    def serialize(envelope):
        calls.append(envelope.row_number)
        return envelope.model_dump(mode="json")
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
    publisher = PartialEnvelopePublisher(writer, [envelope_fixture(2), envelope_fixture(1)],
        serializer=serialize, max_updates=2, max_seconds=5, monotonic=lambda: elapsed[0])
    changed = envelope_fixture()
    changed.evidence[0].excerpt = "revision one"
    assert not publisher.update(changed)
    changed.evidence[0].excerpt = "caller mutation"
    assert output_rows(writer.output_path)[0]["evidence"][0]["excerpt"] is None
    assert publisher.update(envelope_fixture(2))
    assert output_rows(writer.output_path)[0]["evidence"][0]["excerpt"] == "revision one"
    assert calls == [2, 1, 1, 2]
    elapsed[0] = 6
    assert publisher.update(changed)
    elapsed[0] = 7
    assert not publisher.update(envelope_fixture(2))
    assert publisher.flush(force=True)
    assert not publisher.flush()
    assert calls == [2, 1, 1, 2, 1, 2]


def test_partial_rejects_cardinality_identity_graph_and_serialization_changes_atomically(tmp_path):
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
    publisher = PartialEnvelopePublisher(writer, [envelope_fixture(), envelope_fixture(2)], max_updates=1)
    before = writer.output_path.read_bytes()
    invalid = shared_copy(envelope_fixture(), 2)
    invalid.evidence[0].excerpt = "conflict"
    changed_identity = envelope_fixture()
    changed_identity.input_ref = "replacement input"
    for updates in ([envelope_fixture(3)], [changed_identity], [invalid], [envelope_fixture(), envelope_fixture()]):
        with pytest.raises(ValueError):
            publisher.update_rows(updates)
        assert writer.output_path.read_bytes() == before
    with patch.object(publisher, "_serialize", side_effect=ValueError("serializer failed")):
        with pytest.raises(ValueError, match="serializer failed"):
            publisher.update(envelope_fixture(1, graph=False))
    publisher.flush(force=True)
    assert writer.output_path.read_bytes() == before


def test_failed_partial_write_retains_last_complete_file_and_can_retry(tmp_path):
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
    publisher = PartialEnvelopePublisher(writer, [envelope_fixture(), envelope_fixture(2)], max_updates=1)
    before = writer.output_path.read_bytes()
    with patch.object(operations.os, "replace", side_effect=OSError("atomic replacement failed")):
        with pytest.raises(OSError, match="atomic replacement failed"):
            publisher.update(envelope_fixture(1, graph=False))
    assert writer.output_path.read_bytes() == before
    assert publisher.flush(force=True)
    assert output_rows(writer.output_path)[0]["evidence"] == []


def test_partial_runner_flushes_idle_updates_and_final_pair_retains_existing_semantics(tmp_path):
    async def exercise():
        writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
        publisher = PartialEnvelopePublisher(writer, [envelope_fixture()], max_updates=100, max_seconds=0.02)
        stop = asyncio.Event()
        runner = asyncio.create_task(publisher.run(stop))
        publisher.update(envelope_fixture(1, graph=False))
        deadline = asyncio.get_running_loop().time() + 2
        while output_rows(writer.output_path)[0]["evidence"]:
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.005)
        publisher.update(envelope_fixture())
        stop.set()
        await runner
        assert output_rows(writer.output_path)[0]["evidence"]
        state_writer = OrderedAtomicWriter(tmp_path / "state.json")
        marker = publish_paired_artifacts(writer, state_writer, [envelope_fixture()], b"{}\n")
        assert validate_paired_publication(marker)["status"] == "committed"
    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["initial", "mid_write", "periodic"])
def test_sigkill_keeps_complete_thousand_row_partial_artifact(tmp_path, mode):
    input_path = tmp_path / "envelopes.jsonl"
    input_path.write_text("".join(envelope_fixture(row_number, graph=False).model_dump_json() + "\n"
                                  for row_number in range(1, 1001)))
    output_path = tmp_path / "output.jsonl"
    ready_path = tmp_path / "ready"
    process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("partial_publication_kill_helper.py")),
                                str(input_path), str(output_path), str(ready_path), mode],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 15
        while not ready_path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not ready_path.exists():
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            pytest.fail(f"kill helper did not reach boundary: {stdout!r} {stderr!r}")
        os.kill(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)
        assert process.returncode == -signal.SIGKILL
        published = output_rows(output_path)
        assert [item["row_number"] for item in published] == list(range(1, 1001))
        assert all(Envelope.model_validate(item) for item in published)
        expected = "updated" if mode == "periodic" else None
        assert published[0]["sections"]["identity_brand"]["attempt_outcome"] == (expected or "NOT_ATTEMPTED")
        assert json.loads(output_path.with_name("output.jsonl.publication.json").read_text())["status"] == "partial"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
