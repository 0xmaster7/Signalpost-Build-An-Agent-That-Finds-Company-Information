import asyncio
import json
import os
import signal
import sqlite3
import time

import pytest

from signalpost import run


@pytest.mark.parametrize("row_count", [100, 1000])
@pytest.mark.parametrize("termination", ["deadline", "sigterm"])
def test_bounded_run_finalizes_checkpoint_and_replays(tmp_path, monkeypatch, capsys, row_count, termination):
    async def foundation(*args, **kwargs):
        if termination == "sigterm":
            os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(5)

    monkeypatch.setattr(run, "fetch_company", foundation)
    input_path = tmp_path / "input.txt"
    input_path.write_text("\n".join(f"{number:09d}" for number in range(1, row_count + 1)) + "\n")
    capture = tmp_path / "capture"
    budget = "30" if termination == "sigterm" else "0.5"

    def arguments(label):
        return ["--input", str(input_path), "--output", str(tmp_path / (label + ".jsonl")),
            "--state-output", str(tmp_path / (label + ".state.json")),
            "--checkpoint", str(tmp_path / (label + ".sqlite")), "--live-brreg", "--budget-seconds", budget]

    started = time.monotonic()
    assert run.main(arguments("live") + ["--record-http", str(capture)]) == 0
    assert time.monotonic() - started < 30
    receipt = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert receipt["output_cardinality"] == row_count
    assert receipt["scheduler_passes"]["bounded_stop"]["reason"] == termination
    connection = sqlite3.connect(tmp_path / "live.sqlite")
    assert connection.execute("SELECT COUNT(*) FROM shells WHERE execution_state='terminalized'").fetchone()[0] == row_count
    assert connection.execute("SELECT COUNT(*) FROM phase_status").fetchone()[0] == 11 * row_count
    connection.close()
    rows = [json.loads(line) for line in (tmp_path / "live.jsonl").read_text().splitlines()]
    assert all(not row["claims"] for row in rows)
    assert all(row["terminal_state"] in {"ambiguous", "failed"} for row in rows)
    assert json.loads((tmp_path / "live.jsonl.publication.json").read_text())["status"] == "committed"
    assert run.main(arguments("replay") + ["--replay-http", str(capture)]) == 0
    capsys.readouterr()
    assert (tmp_path / "live.jsonl").read_bytes() == (tmp_path / "replay.jsonl").read_bytes()
    assert (tmp_path / "live.state.json").read_bytes() == (tmp_path / "replay.state.json").read_bytes()
