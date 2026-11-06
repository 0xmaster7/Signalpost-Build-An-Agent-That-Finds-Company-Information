"""Persistence regression checks: bounded encoding and atomic durable batches."""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest

from test_signalpost_checkpoint_publication import envelope_fixture, shared_copy
from signalpost import operations
from signalpost.models import Evidence, SourceSnapshot
from signalpost.operations import CheckpointStore, OrderedAtomicWriter, PartialEnvelopePublisher


def test_bulk_statuses_commit_once_preserve_existing_and_survive_reopen(tmp_path):
    path = tmp_path / "checkpoint.sqlite"
    store = CheckpointStore(path)
    try:
        store.save_phase_status("annual_documents", "existing", "completed", 3.0)
        statements = []
        store.connection.set_trace_callback(statements.append)
        store.save_phase_statuses(
            [("annual_documents", "existing", "not_attempted", 0.0, None, None)] +
            [("annual_documents", str(i), "deadline_skipped", 0.0, None, None)
             for i in range(1000)], only_missing=True)
        assert statements.count("BEGIN ") == 1
        assert statements.count("COMMIT") == 1
        assert store.connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert store.phase_status("annual_documents", "existing")["outcome"] == "completed"
    finally:
        store.close()
    resumed = CheckpointStore(path)
    try:
        assert len(resumed.phase_statuses("annual_documents")) == 1001
        assert resumed.phase_status("annual_documents", "999")["deadline_skipped"] is True
        resumed.save_phase_statuses([("annual_documents", "999", "failed", 2.0, None, "a" * 64)])
        status = resumed.phase_status("annual_documents", "999")
        assert status["reason"] == "source_reported_failure"
        assert status["traceback_sha256"] == "a" * 64
    finally:
        resumed.close()


def test_bulk_status_failure_rolls_back_entire_batch(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoint.sqlite")
    try:
        store.save_phase_status("annual_documents", "first", "completed")
        store.connection.execute("CREATE TRIGGER reject_status BEFORE INSERT ON phase_status "
                                 "WHEN NEW.company='reject' BEGIN SELECT RAISE(ABORT,'rejected'); END")
        store.connection.commit()
        with pytest.raises(sqlite3.IntegrityError, match="rejected"):
            store.save_phase_statuses([
                ("annual_documents", "first", "failed", 0.0, None, None),
                ("annual_documents", "reject", "not_attempted", 0.0, None, None)])
        assert store.phase_status("annual_documents", "first")["outcome"] == "completed"
        assert store.phase_status("annual_documents", "reject") is None
        statements = []
        store.connection.set_trace_callback(statements.append)
        store.save_phase_statuses([])
        assert statements == []
    finally:
        store.close()


def test_identity_signatures_encoded_once_and_shared_without_relaxing_collisions():
    original = envelope_fixture()
    original.evidence[0].excerpt = "large annual document " * 1000
    duplicate = shared_copy(original, 2)
    index = operations._EnvelopeIdentityIndex()
    evidence_dump = Evidence.model_dump
    snapshot_dump = SourceSnapshot.model_dump
    with patch.object(Evidence, "model_dump", autospec=True, side_effect=evidence_dump) as evidence_calls, \
            patch.object(SourceSnapshot, "model_dump", autospec=True, side_effect=snapshot_dump) as snapshot_calls:
        _, changes = index.prepare([original, duplicate])
        assert evidence_calls.call_count == 2
        assert snapshot_calls.call_count == 2
    index.apply(changes)
    for kind in ("evidence", "snapshots"):
        identifier = next(iter(index.rows[1][kind]))
        assert index.rows[1][kind][identifier] is index.rows[2][kind][identifier]
        assert index.references[kind][identifier][1] == 2
    conflicting = shared_copy(original, 3)
    conflicting.evidence[0].excerpt = "conflicting"
    with pytest.raises(ValueError, match="conflicting"):
        index.prepare([conflicting])
    empty = operations._EnvelopeIdentityIndex()
    with pytest.raises(ValueError, match="conflicting"):
        empty.prepare([original, conflicting])
    assert empty.rows == {}


def test_partial_flush_copies_cached_json_and_detaches_serializer_objects(tmp_path):
    rows = [envelope_fixture(i) for i in range(1, 4)]
    payloads = {row.row_number: row.model_dump(mode="json") for row in rows}
    encoded_rows = []
    original_dumps = json.dumps

    def count_encoding(value, *args, **kwargs):
        if isinstance(value, dict) and "input_ref" in value:
            encoded_rows.append(value["row_number"])
        return original_dumps(value, *args, **kwargs)

    writer = OrderedAtomicWriter(tmp_path / "partial.jsonl")
    with patch.object(operations.json, "dumps", side_effect=count_encoding):
        publisher = PartialEnvelopePublisher(writer, rows, serializer=lambda row: payloads[row.row_number])
        assert encoded_rows == [1, 2, 3]
        payloads[1]["evidence"][0]["excerpt"] = "caller mutation"
        publisher.flush(force=True)
        publisher.flush(force=True)
        assert encoded_rows == [1, 2, 3]
        assert json.loads(writer.output_path.read_text().splitlines()[0])["evidence"][0]["excerpt"] is None
        publisher.update(rows[1])
        publisher.flush(force=True)
        assert encoded_rows == [1, 2, 3, 2]
