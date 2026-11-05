from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from signalpost.models import Envelope
from signalpost.operations import OrderedAtomicWriter, PartialEnvelopePublisher


class KillBoundaryWriter(OrderedAtomicWriter):
    def __init__(self, output_path, ready_path):
        super().__init__(output_path)
        self.ready_path = ready_path
        self.block = False

    def write(self, envelopes, *, serializer=None):
        serialized = 0
        def at_boundary(envelope):
            nonlocal serialized
            serialized += 1
            if self.block and serialized == 2:
                self.ready_path.write_text("mid-write")
                time.sleep(60)
            return serializer(envelope) if serializer else envelope.model_dump(mode="json")
        super().write(envelopes, serializer=at_boundary)


async def main():
    input_path, output_path, ready_path = (Path(value) for value in sys.argv[1:4])
    mode = sys.argv[4]
    envelopes = [Envelope.model_validate_json(line) for line in input_path.read_text().splitlines()]
    writer = KillBoundaryWriter(output_path, ready_path)
    publisher = PartialEnvelopePublisher(writer, envelopes, max_updates=1000, max_seconds=0.02)
    if mode == "initial":
        ready_path.write_text("initial")
    else:
        changed = envelopes[0].model_copy(deep=True)
        changed.sections["identity_brand"].attempt_outcome = "updated"
        publisher.update(changed)
        if mode == "mid_write":
            writer.block = True
            publisher.flush(force=True)
        else:
            asyncio.create_task(publisher.run(asyncio.Event()))
            while json.loads(output_path.read_text().splitlines()[0])["sections"]["identity_brand"]["attempt_outcome"] != "updated":
                await asyncio.sleep(0.005)
            ready_path.write_text("periodic")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
