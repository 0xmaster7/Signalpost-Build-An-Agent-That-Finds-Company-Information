"""Offline subprocess for deterministic watchdog/SIGKILL publication boundaries."""
from __future__ import annotations

import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from signalpost import operations
from signalpost.adapter import to_evaluator
from signalpost.models import Envelope
from signalpost.operations import OrderedAtomicWriter, PartialEnvelopePublisher


def main():
    input_path, output_path, ready_path = map(Path, sys.argv[1:4])
    boundary = sys.argv[4]
    rows = [Envelope.model_validate_json(line) for line in input_path.read_text().splitlines()]
    writer = OrderedAtomicWriter(output_path)
    publisher = PartialEnvelopePublisher(writer, rows, serializer=to_evaluator, max_updates=10000, max_seconds=3600)
    for number in (0, len(rows) - 1):
        revised = rows[number].model_copy(deep=True)
        revised.evidence[0].excerpt = "latest validated observation – blåbær"
        publisher.update(revised)

    def block(label):
        ready_path.write_text(label)
        while True:
            time.sleep(1)

    # Ordinary termination cannot truncate work at these exact crash boundaries;
    # the parent escalates to SIGKILL like a watchdog with an expired grace period.
    signal.signal(signal.SIGTERM, lambda *_: None)
    if boundary == "preparing":
        original = writer.prepare_bytes

        def interrupt(chunks):
            def blocked_chunks():
                for index, chunk in enumerate(chunks):
                    yield chunk
                    if index == 1:
                        block("preparing")
            return original(blocked_chunks())

        writer.prepare_bytes = interrupt
    publisher.prepare_output()
    if boundary == "ready":
        block("ready")
    if boundary == "watchdog":
        def deadline(*_):
            publisher.commit_output_ready()
            block("secondary_blocked")
        signal.signal(signal.SIGTERM, deadline)
        ready_path.write_text("awaiting_deadline")
        while True:
            time.sleep(1)

    original_promote = operations._PreparedAtomicWrite.promote
    count = 0

    def promote(prepared):
        nonlocal count
        original_promote(prepared)
        count += 1
        if boundary == {1: "marker_invalidated", 2: "output_renamed", 3: "committed"}[count]:
            block(boundary)

    operations._PreparedAtomicWrite.promote = promote
    publisher.commit_output_ready()
    raise AssertionError("unrecognized crash boundary")


if __name__ == "__main__":
    main()
