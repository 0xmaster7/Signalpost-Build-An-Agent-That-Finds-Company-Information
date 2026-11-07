"""Output is the primary durable contract; paired state is a later commit."""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from test_signalpost_checkpoint_publication import envelope_fixture, shared_copy
from signalpost import models, operations
from signalpost.adapter import to_evaluator, validate_vendor_payload
from signalpost.models import Claim, Envelope, PublicState
from signalpost.operations import (OrderedAtomicWriter, PartialEnvelopePublisher,
                                   publish_paired_artifacts, validate_paired_publication)
from signalpost.synthesis import validate_synthesis_schema


def fact_row(number=1, *, value="Blåbær AS"):
    row = envelope_fixture(number)
    claim = Claim(claim_id=f"claim:{number}", organisation_number=row.organisation_number,
        section="identity_brand", field_family="identity", subject_id=row.organisation_number,
        field="legal_name", value=value, state=PublicState.AVAILABLE,
        evidence_ids=[f"evidence:{number}"], source_snapshot_ids=[f"source:{number}"],
        scope="legal_entity", verification_rule_id="fixture_v1", verification_score="1.0")
    row.claims.append(claim)
    for section in ("identity_brand", "claims_evidence_states"):
        row.sections[section].state = PublicState.AVAILABLE
        row.sections[section].attempt_outcome = "completed"
        row.sections[section].claims.append(claim)
    row.terminal_state = PublicState.AVAILABLE
    return Envelope.model_validate(row.model_dump())


def marker_for(writer):
    return writer.output_path.with_name(writer.output_path.name + ".publication.json")


def assert_contract(path, canonical_rows):
    payloads = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(payloads) == len(canonical_rows)
    assert [item["input_ref"] for item in payloads] == [row.input_ref for row in canonical_rows]
    assert len({item["input_ref"] for item in payloads}) == len(canonical_rows)
    for payload, row in zip(payloads, canonical_rows, strict=True):
        validate_vendor_payload(payload)
        validate_synthesis_schema(payload["synthesis"])
        # Reconstruct the internal metadata omitted by the evaluator edge, then
        # validate the entire canonical graph and round-trip through its adapter.
        restored = Envelope.model_validate({
            **{key: payload[key] for key in ("input_ref", "organisation_number", "terminal_state",
                "sections", "claims", "evidence", "source_snapshots", "refresh", "synthesis", "errors", "operations")},
            "row_number": row.row_number, "batch_id": payload["batch"]["batch_id"],
            "evidence_cutoff": payload["batch"]["evidence_cutoff"], "created_at": payload["run"]["created_at"],
        })
        assert to_evaluator(restored) == payload
        assert payload == to_evaluator(row)
    return payloads


def assert_output_marker(publisher):
    marker = json.loads(publisher.marker_path.read_text())
    assert marker["status"] == "output_committed"
    assert marker["output_committed"] is True
    assert marker["state_incomplete"] is True
    assert marker["canonical_pair_committed"] is False
    assert marker["output_sha256"] == hashlib.sha256(publisher.writer.output_path.read_bytes()).hexdigest()
    assert marker["marker_sha256"] == operations._publication_marker_digest(marker)
    assert "state_sha256" not in marker
    with pytest.raises(ValueError, match="incomplete"):
        validate_paired_publication(publisher.marker_path)
    return marker


def test_commit_output_uses_freshest_validated_encoded_rows_before_secondary_state(tmp_path):
    rows = [fact_row(i) for i in range(1, 4)]
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
    publisher = PartialEnvelopePublisher(writer, reversed(rows), serializer=to_evaluator, max_updates=100)
    revised = fact_row(3, value="Newest supported legal name")
    assert not publisher.update(revised)
    rows[2] = revised.model_copy(deep=True)
    revised.claims[0].value = "caller mutation must not be published"
    # Commit must use cached bytes even if all validation/row encoding and reads
    # are unavailable. Hashing happens while streaming, never by rereading output.
    with patch.object(models, "validate_publication_graph", side_effect=AssertionError("revalidation")), \
            patch.object(publisher, "_serialize", side_effect=AssertionError("encoding")), \
            patch.object(Envelope, "model_dump_json", side_effect=AssertionError("encoding")), \
            patch.object(Path, "read_bytes", side_effect=AssertionError("reread")):
        assert publisher.commit_output() == publisher.marker_path
    assert_contract(writer.output_path, rows)
    assert_output_marker(publisher)
    assert not (tmp_path / "state.json").exists()
    # Secondary failures must not downgrade the output commit, including the
    # runner's unconditional final flush during shutdown.
    assert publisher.flush(force=True) is False
    assert_output_marker(publisher)
    state = OrderedAtomicWriter(tmp_path / "state.json")
    paired = publish_paired_artifacts(writer, state, rows, b"{}\n", serializer=to_evaluator)
    assert validate_paired_publication(paired)["status"] == "committed"


def test_secondary_preparation_failure_preserves_primary_commit(tmp_path):
    rows = [fact_row()]
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
    state_writer = OrderedAtomicWriter(tmp_path / "state.json")
    publisher = PartialEnvelopePublisher(writer, rows, serializer=to_evaluator)
    publisher.commit_output()
    original = writer.output_path.read_bytes()
    with patch.object(state_writer, "prepare_bytes", side_effect=OSError("secondary fsync failed")):
        with pytest.raises(OSError):
            publish_paired_artifacts(writer, state_writer, rows, b"{}\n", serializer=to_evaluator,
                preserve_output_commit=True)
    assert writer.output_path.read_bytes() == original
    assert_output_marker(publisher)
    assert_contract(writer.output_path, rows)
    paired = publish_paired_artifacts(writer, state_writer, rows, b"{}\n", serializer=to_evaluator,
        preserve_output_commit=True)
    assert validate_paired_publication(paired)["status"] == "committed"
    assert_contract(writer.output_path, rows)


def test_secondary_marker_failure_restores_primary_output_and_marker(tmp_path):
    original_rows = [fact_row()]
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
    publisher = PartialEnvelopePublisher(writer, original_rows, serializer=to_evaluator)
    publisher.commit_output()
    latest = [fact_row(value="Secondary refreshed name")]
    replace = os.replace
    failed = False

    def fail_marker_once(source, destination):
        nonlocal failed
        if Path(destination) == publisher.marker_path and not failed:
            failed = True
            raise OSError("secondary marker rename failed")
        return replace(source, destination)

    with patch.object(operations.os, "replace", side_effect=fail_marker_once):
        with pytest.raises(OSError):
            publish_paired_artifacts(writer, OrderedAtomicWriter(tmp_path / "state.json"), latest,
                b"{}\n", serializer=to_evaluator, preserve_output_commit=True)
    assert failed
    assert_output_marker(publisher)
    assert_contract(writer.output_path, original_rows)


@pytest.mark.parametrize("count", [0, 1, 1000])
def test_ready_promotion_does_no_row_work_and_only_three_renames(count, tmp_path):
    rows = [fact_row(i) for i in range(1, count + 1)]
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
    publisher = PartialEnvelopePublisher(writer, rows, serializer=to_evaluator)
    before = writer.output_path.read_bytes(), publisher.marker_path.read_bytes()
    publisher.prepare_output()
    assert publisher.output_ready
    assert before == (writer.output_path.read_bytes(), publisher.marker_path.read_bytes())
    original_replace = os.replace
    original_fsync = os.fsync
    with patch.object(publisher, "prepare_output", side_effect=AssertionError("linear flush")), \
            patch.object(writer, "prepare_bytes", side_effect=AssertionError("linear flush")), \
            patch.object(publisher, "_rows", object()), \
            patch.object(publisher, "_payloads", object()), \
            patch.object(publisher, "_encoded_rows", object()), \
            patch.object(publisher, "_ordered_numbers", object()), \
            patch.object(publisher, "_serialize", side_effect=AssertionError("serialization")), \
            patch.object(operations.json, "dumps", side_effect=AssertionError("JSON encoding")), \
            patch.object(operations.hashlib, "sha256", side_effect=AssertionError("hashing")), \
            patch.object(operations.os, "fdopen", side_effect=AssertionError("file contents")), \
            patch.object(operations.os, "replace", wraps=original_replace) as replace, \
            patch.object(operations.os, "fsync", wraps=original_fsync) as fsync:
        publisher.commit_output_ready()
    assert replace.call_count == fsync.call_count == 3
    assert not publisher.output_ready
    assert_output_marker(publisher)
    assert_contract(writer.output_path, rows)
    assert not list(tmp_path.glob(".*.tmp"))


def test_update_invalidates_ready_but_rejected_updates_preserve_it(tmp_path):
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
    publisher = PartialEnvelopePublisher(writer, [fact_row(), fact_row(2)], serializer=to_evaluator, max_updates=100)
    publisher.prepare_output()
    prepared_files = list(tmp_path.glob(".*.tmp"))
    assert len(prepared_files) == 3
    bad_identity = fact_row()
    bad_identity.input_ref = "foreign row"
    bad_graph = fact_row()
    bad_graph.claims[0].evidence_ids[:] = ["missing"]
    conflict = shared_copy(fact_row(), 2)
    conflict.evidence[0].excerpt = "collision"
    bad_section = fact_row()
    bad_section.sections["identity_brand"].claims = []
    bad_schema = fact_row()
    bad_schema.synthesis = {"unexpected": "field"}
    for bad in (bad_identity, bad_graph, conflict, bad_section, bad_schema):
        with pytest.raises(ValueError):
            publisher.update(bad)
        assert publisher.output_ready
        assert all(path.exists() for path in prepared_files)
    latest = fact_row(2)
    latest.evidence[0].excerpt = "newest"
    assert not publisher.update(latest)
    assert not publisher.output_ready
    assert not any(path.exists() for path in prepared_files)
    before = writer.output_path.read_bytes(), publisher.marker_path.read_bytes()
    with pytest.raises(RuntimeError, match="prepare_output"):
        publisher.commit_output_ready()
    assert before == (writer.output_path.read_bytes(), publisher.marker_path.read_bytes())
    publisher.commit_output()
    assert_contract(writer.output_path, [fact_row(), latest])


def test_failed_repreparation_preserves_previous_ready_snapshot(tmp_path):
    publisher = PartialEnvelopePublisher(OrderedAtomicWriter(tmp_path / "output.jsonl"), [fact_row()], serializer=to_evaluator)
    publisher.prepare_output()
    staged = set(tmp_path.glob(".*.tmp"))
    with patch.object(publisher._marker, "prepare_bytes", side_effect=OSError("marker failure")):
        with pytest.raises(OSError, match="marker failure"):
            publisher.prepare_output()
    assert publisher.output_ready
    assert set(tmp_path.glob(".*.tmp")) == staged
    publisher.commit_output_ready()
    assert_output_marker(publisher)
    assert_contract(publisher.writer.output_path, [fact_row()])


@pytest.mark.parametrize("failure", ["stream", "fsync", "marker"])
def test_failed_preparation_keeps_canonical_files_and_cleans_temps(failure, tmp_path):
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
    publisher = PartialEnvelopePublisher(writer, [fact_row()], serializer=to_evaluator)
    before = writer.output_path.read_bytes(), publisher.marker_path.read_bytes()
    if failure == "stream":
        def fail(chunks):
            def broken():
                yield next(iter(chunks))
                raise OSError("stream failure")
            return original(broken())
        original = writer.prepare_bytes
        target, name, error = writer, "prepare_bytes", fail
    elif failure == "marker":
        target, name, error = publisher._marker, "prepare_bytes", OSError("marker failure")
    else:
        target, name, error = operations.os, "fsync", OSError("fsync failure")
    with patch.object(target, name, side_effect=error):
        with pytest.raises(OSError):
            publisher.prepare_output()
    assert not publisher.output_ready
    assert before == (writer.output_path.read_bytes(), publisher.marker_path.read_bytes())
    assert not list(tmp_path.glob(".*.tmp"))
    publisher.commit_output()
    assert_output_marker(publisher)


@pytest.mark.parametrize("failed_step", [1, 2, 3])
@pytest.mark.parametrize("paired", [False, True])
def test_failed_promotion_keeps_full_contract_marker_truthful_and_can_retry(failed_step, paired, tmp_path):
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl")
    publisher = PartialEnvelopePublisher(writer, [fact_row()], serializer=to_evaluator, max_updates=100)
    if paired:
        publish_paired_artifacts(writer, OrderedAtomicWriter(tmp_path / "state.json"), [fact_row()], b"{}\n", serializer=to_evaluator)
    original = writer.output_path.read_bytes()
    latest = fact_row()
    latest.evidence[0].excerpt = "latest"
    publisher.update(latest)
    publisher.prepare_output()
    replace = os.replace
    calls = 0
    def fail(source, destination):
        nonlocal calls
        calls += 1
        if calls == failed_step:
            raise OSError("rename failure")
        replace(source, destination)
    with patch.object(operations.os, "replace", side_effect=fail):
        with pytest.raises(OSError, match="rename failure"):
            publisher.commit_output_ready()
    assert not publisher.output_ready
    assert not list(tmp_path.glob(".*.tmp"))
    assert_contract(writer.output_path, [latest if failed_step == 3 else fact_row()])
    initial_status = "committed" if paired else "partial"
    assert json.loads(publisher.marker_path.read_text())["status"] == (initial_status if failed_step == 1 else "publishing_output")
    if paired and failed_step == 1:
        assert validate_paired_publication(publisher.marker_path)["status"] == "committed"
    if failed_step < 3:
        assert writer.output_path.read_bytes() == original
    publisher.commit_output()
    assert_output_marker(publisher)
    assert_contract(writer.output_path, [latest])


def test_marker_alias_is_rejected_before_canonical_file_is_changed(tmp_path):
    output = tmp_path / "output.jsonl"
    output.write_bytes(b"previous canonical output\n")
    marker = output.with_name(output.name + ".publication.json")
    marker.symlink_to(output)
    with pytest.raises(ValueError, match="distinct path"):
        PartialEnvelopePublisher(OrderedAtomicWriter(output), [fact_row()], serializer=to_evaluator)
    assert output.read_bytes() == b"previous canonical output\n"
    assert marker.is_symlink()


def test_release_cleans_ready_files_and_metrics_expose_conservative_reserve(tmp_path):
    publisher = PartialEnvelopePublisher(OrderedAtomicWriter(tmp_path / "output.jsonl"), [fact_row()], serializer=to_evaluator)
    assert publisher.prepared_rows == 1
    assert publisher.prep_seconds > 0
    assert publisher.per_row_prep_seconds == publisher.prep_seconds
    assert publisher.flush_seconds > 0
    publisher.update(fact_row())
    assert publisher.prepared_rows == 2
    assert publisher.per_row_prep_seconds == publisher.prep_seconds / 2
    publisher.prepare_output()
    assert publisher.flush_seconds > 0
    publisher.prep_seconds, publisher.prepared_rows, publisher.flush_seconds = 4.0, 2, 3.0
    assert publisher.reserve_estimate(1) == 10
    assert publisher.reserve_estimate(1800) == 180
    for value in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            publisher.reserve_estimate(value)
    publisher.release()
    assert not publisher.output_ready
    assert not list(tmp_path.glob(".*.tmp"))
    with pytest.raises(RuntimeError, match="released"):
        publisher.commit_output()


@pytest.mark.parametrize("boundary", ["preparing", "ready", "marker_invalidated", "output_renamed", "committed", "watchdog"])
def test_forced_watchdog_termination_preserves_thousand_evaluator_rows(tmp_path, boundary):
    rows = [fact_row(i) for i in range(1, 1001)]
    input_path, output_path, ready_path = (tmp_path / name for name in ("input.jsonl", "output.jsonl", "ready"))
    input_path.write_text("".join(row.model_dump_json() + "\n" for row in rows))
    helper = Path(__file__).with_name("output_commit_kill_helper.py")
    process = subprocess.Popen([sys.executable, str(helper), str(input_path), str(output_path), str(ready_path), boundary],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    def await_boundary(expected=None):
        deadline = time.monotonic() + 20
        while process.poll() is None and time.monotonic() < deadline:
            if ready_path.exists() and (expected is None or ready_path.read_text() == expected):
                return
            time.sleep(0.01)
        if process.poll() is None:
            process.kill()
        stdout, stderr = process.communicate(timeout=5)
        pytest.fail(f"helper failed to reach {boundary}/{expected}: {stdout!r} {stderr!r}")
    try:
        await_boundary()
        process.terminate()
        if boundary == "watchdog":
            await_boundary("secondary_blocked")
        process.kill()
        process.communicate(timeout=5)
        assert process.returncode == -signal.SIGKILL
        if boundary in {"output_renamed", "committed", "watchdog"}:
            for number in (0, len(rows) - 1):
                rows[number].evidence[0].excerpt = "latest validated observation – blåbær"
        assert_contract(output_path, rows)
        marker = json.loads(marker_for(OrderedAtomicWriter(output_path)).read_text())
        if boundary in {"committed", "watchdog"}:
            assert marker["status"] == "output_committed"
            assert marker["output_sha256"] == hashlib.sha256(output_path.read_bytes()).hexdigest()
            assert marker["marker_sha256"] == operations._publication_marker_digest(marker)
        else:
            assert marker["status"] == ("publishing_output" if boundary in {"marker_invalidated", "output_renamed"} else "partial")
        assert marker["state_incomplete"] is True
        assert marker["canonical_pair_committed"] is False
        with pytest.raises(ValueError, match="incomplete"):
            validate_paired_publication(marker_for(OrderedAtomicWriter(output_path)))
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
