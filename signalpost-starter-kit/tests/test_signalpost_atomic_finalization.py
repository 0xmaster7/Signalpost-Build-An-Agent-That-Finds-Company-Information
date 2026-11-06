"""Offline regression tests for atomic finalization and cached emergency flushes."""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest

from test_signalpost_checkpoint_publication import envelope_fixture, shared_copy
from signalpost import models, operations
from signalpost.models import Claim, Envelope, PublicState
from signalpost.operations import CheckpointStore, OrderedAtomicWriter, PartialEnvelopePublisher


def status(company, state="completed"):
    return ("finalization", str(company), state, 0.25, None, None)


def test_thousand_finalized_rows_validate_once_commit_once_and_survive_reopen(tmp_path):
    path = tmp_path / "checkpoint.sqlite"
    store = CheckpointStore(path)
    rows = [envelope_fixture(i) for i in range(1, 1001)]
    # Reuse the already initialized index rather than rebuilding it per row.
    identity_index = store._get_identity_index()
    statements = []
    store.connection.set_trace_callback(statements.append)
    try:
        with patch.object(identity_index, "prepare", wraps=identity_index.prepare) as prepare, \
                patch.object(models, "validate_publication_graph", wraps=models.validate_publication_graph) as validate:
            store.put_finalized(iter(rows), (status(i) for i in range(1, 1001)))
        assert prepare.call_count == 1
        assert validate.call_count == 1000
        assert sum(item.startswith("BEGIN") for item in statements) == 1
        assert statements.count("COMMIT") == 1
        assert store.connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert store._identity_index is identity_index
        assert len(identity_index.rows) == 1000
    finally:
        store.close()
    resumed = CheckpointStore(path)
    try:
        assert resumed.rows() == rows
        assert set(resumed.shell_states().values()) == {"terminalized"}
        assert len(resumed.terminalized()) == 1000
        assert len(resumed.phase_statuses("finalization")) == 1000
        assert resumed.phase_status("finalization", "1000")["outcome"] == "completed"
    finally:
        resumed.close()


@pytest.mark.parametrize("table,condition", [
    ("envelopes", "NEW.row_number=2"),
    ("shells", "NEW.row_number=2"),
    ("phase_status", "NEW.company='2'"),
])
def test_sql_exception_rolls_back_envelopes_shells_statuses_and_index(tmp_path, table, condition):
    store = CheckpointStore(tmp_path / "checkpoint.sqlite")
    original = envelope_fixture()
    try:
        store.put(original)
        store.connection.execute("INSERT INTO shells VALUES (1,'row:1','923609016','baseline_done')")
        store.connection.commit()
        store.save_phase_status(*status(1, "failed")[:4])
        store.connection.execute(f"CREATE TRIGGER reject_finalization BEFORE INSERT ON {table} "
                                 f"WHEN {condition} BEGIN SELECT RAISE(ABORT,'rejected'); END")
        store.connection.commit()
        with pytest.raises(sqlite3.IntegrityError, match="rejected"):
            store.put_finalized([envelope_fixture(1, graph=False), envelope_fixture(2)], [status(1), status(2)])
        assert store.rows() == [original]
        assert store.shell_states() == {1: "baseline_done"}
        assert store.phase_status("finalization", "1")["outcome"] == "failed"
        assert store.phase_status("finalization", "2") is None
        assert set(store._identity_index.rows) == {1}
        assert set(store._identity_index.references["evidence"]) == {"evidence:1"}
        # Rollback must leave the live index usable for a subsequent retry.
        store.connection.execute("DROP TRIGGER reject_finalization")
        store.put_finalized([envelope_fixture(1, graph=False), envelope_fixture(2)], [status(1), status(2)])
        assert store.shell_states() == {1: "terminalized", 2: "terminalized"}
        assert set(store._identity_index.references["evidence"]) == {"evidence:2"}
    finally:
        store.close()


@pytest.mark.parametrize("kind", ["evidence", "snapshots"])
@pytest.mark.parametrize("existing", [False, True])
def test_batch_collisions_reject_before_writes(tmp_path, kind, existing):
    store = CheckpointStore(tmp_path / "checkpoint.sqlite")
    original = envelope_fixture()
    conflicting = shared_copy(original, 2)
    if kind == "evidence":
        conflicting.evidence[0].excerpt = "conflict"
    else:
        conflicting.source_snapshots[0].rights_status = "conflict"
    try:
        if existing:
            store.put(original)
        statements = []
        store.connection.set_trace_callback(statements.append)
        with pytest.raises(ValueError, match="conflicting"):
            store.put_finalized([conflicting] if existing else [original, conflicting], [status(2)])
        assert not any(item.startswith("BEGIN") for item in statements)
        assert store.rows() == ([original] if existing else [])
        assert store.shell_states() == {}
        assert store.phase_statuses("finalization") == {}
    finally:
        store.close()


def test_joint_identity_replacement_and_duplicate_rows(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoint.sqlite")
    original = envelope_fixture()
    try:
        store.put_finalized([original, shared_copy(original, 2)], [status(1)])
        revised = original.model_copy(deep=True)
        revised.evidence[0].excerpt = "replacement"
        store.put_finalized([revised, shared_copy(revised, 2)], [status(1)])
        assert store._identity_index.references["evidence"]["evidence:1"][1] == 2
        with pytest.raises(ValueError, match="duplicate row_number"):
            store.put_finalized([revised, revised], [status(1, "failed")])
        assert store.phase_status("finalization", "1")["outcome"] == "completed"
    finally:
        store.close()


def test_mutated_nested_provenance_is_still_validated(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoint.sqlite")
    row = envelope_fixture()
    row.claims.append(Claim(claim_id="bad", organisation_number=row.organisation_number,
        section="identity_brand", field_family="identity", subject_id=row.organisation_number,
        field="legal_name", value="Unproven", state=PublicState.AVAILABLE,
        evidence_ids=["missing"], source_snapshot_ids=["source:1"], scope="legal_entity",
        verification_rule_id="fixture_v1", verification_score="1.0"))
    try:
        with pytest.raises(ValueError, match="present evidence"):
            store.put_finalized([row], [status(1)])
        assert store.rows() == []
        assert store.shell_states() == {}
        assert store.phase_statuses("finalization") == {}
    finally:
        store.close()


@pytest.mark.parametrize("failure", ["encoding", "status_iteration"])
def test_preparation_exception_leaves_no_writes(tmp_path, failure):
    store = CheckpointStore(tmp_path / "checkpoint.sqlite")
    row = envelope_fixture()

    def broken_statuses():
        yield status(1)
        raise RuntimeError("status iteration failed")

    try:
        if failure == "encoding":
            with patch.object(Envelope, "model_dump_json", side_effect=RuntimeError("encoding failed")):
                with pytest.raises(RuntimeError, match="encoding failed"):
                    store.put_finalized([row], [status(1)])
        else:
            with pytest.raises(RuntimeError, match="status iteration failed"):
                store.put_finalized([row], broken_statuses())
        assert store.rows() == []
        assert store.shell_states() == {}
        assert store.phase_statuses("finalization") == {}
        assert store._identity_index.rows == {}
    finally:
        store.close()


def test_empty_batch_has_no_transaction(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoint.sqlite")
    try:
        statements = []
        store.connection.set_trace_callback(statements.append)
        store.put_finalized([], [])
        assert not any(item.startswith("BEGIN") for item in statements)
    finally:
        store.close()


def test_emergency_flush_uses_latest_validated_encoded_rows_without_revalidation(tmp_path):
    row = envelope_fixture()
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
    publisher = PartialEnvelopePublisher(writer, [row], max_updates=100)
    revised = envelope_fixture()
    revised.evidence[0].excerpt = "latest validated observation"
    assert not publisher.update(revised)
    revised.evidence[0].excerpt = "unvalidated caller mutation"
    with patch.object(models, "validate_publication_graph", side_effect=AssertionError("revalidation")), \
            patch.object(Envelope, "model_dump_json", side_effect=AssertionError("re-encoding")), \
            patch.object(publisher, "_serialize", side_effect=AssertionError("serialization")):
        assert publisher.flush(force=True)
    payload = json.loads(writer.output_path.read_text())
    assert payload["evidence"][0]["excerpt"] == "latest validated observation"
    assert Envelope.model_validate(payload)
