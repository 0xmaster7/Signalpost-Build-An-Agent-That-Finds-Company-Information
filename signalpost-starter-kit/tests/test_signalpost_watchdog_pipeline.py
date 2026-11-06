import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name != "posix", reason="independent deadline signals require POSIX")
@pytest.mark.parametrize("stalled_layer", ["company", "transport"])
def test_cli_deadline_publishes_all_rows_and_replays_without_source_calls(tmp_path, stalled_layer):
    root = Path(__file__).resolve().parents[2]
    source = tmp_path / "input.txt"
    source.write_text("\n".join(f"{number:09d}" for number in range(1, 201)) + "\n")
    script = """
import asyncio
import sys
import os
from signalpost import run
from signalpost import network
async def stalled(*args, **kwargs):
    await asyncio.Event().wait()
if os.environ['SIGNALPOST_TEST_STALLED_LAYER'] == 'company':
    run.fetch_company = stalled
    run.fetch_financial_statements = stalled
else:
    network.UrlLibTransport.request = stalled
    network.validate_public_host = lambda *args, **kwargs: ('8.8.8.8',)
sys.argv = ['signalpost', *sys.argv[1:]]
run.cli_main()
"""
    for label in ("live", "replay"):
        output = tmp_path / (label + ".jsonl")
        arguments = ["--input", str(source), "--output", str(output),
            "--state-output", str(tmp_path / (label + ".state")),
            "--checkpoint", str(tmp_path / (label + ".sqlite")),
            "--budget-seconds", "20",
            "--record-http" if label == "live" else "--replay-http", str(tmp_path / "capture")]
        completed = subprocess.run([sys.executable, "-c", script, *arguments], cwd=root,
            capture_output=True, text=True, timeout=25,
            env={**os.environ, "SIGNALPOST_TEST_STALLED_LAYER": stalled_layer})
        assert completed.returncode == 0, completed.stderr
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        assert len(rows) == 200
        assert all(not row["claims"] for row in rows)
        marker = json.loads(output.with_name(output.name + ".publication.json").read_text())
        assert marker["status"] == "committed"
        aggregate = json.loads(completed.stdout.splitlines()[-1])
        assert aggregate["event"] == "batch_complete"
        assert aggregate["runtime_seconds"] < 20
        assert len(aggregate["scheduler_passes"]["company_phases"]["finalization"]) == 200
    assert (tmp_path / "live.jsonl").read_bytes() == (tmp_path / "replay.jsonl").read_bytes()
    assert (tmp_path / "live.state").read_bytes() == (tmp_path / "replay.state").read_bytes()
