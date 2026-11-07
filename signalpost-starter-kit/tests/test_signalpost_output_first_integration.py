"""Offline runner integration for primary output and interrupted secondary work."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from signalpost import history, run
from signalpost.inputs import parse_records
from signalpost.adapter import from_evaluator
from test_signalpost_output_commit import assert_contract, assert_output_marker

ROOT = Path(__file__).resolve().parents[2]


def complete_output(output, organisations):
    """Use the existing graph/schema/adapter checks with independent row identities."""
    payloads = [json.loads(line) for line in output.read_text().splitlines()]
    inputs = parse_records("\n".join(organisations), "plain")
    assert len(payloads) == len(inputs)
    assert [item["organisation_number"] for item in payloads] == organisations
    assert [item["input_ref"] for item in payloads] == [row.input_ref for row in inputs]
    canonical = []
    for payload, row in zip(payloads, inputs, strict=True):
        canonical.append(from_evaluator(payload, row_number=row.row_number))
    return assert_contract(output, canonical)


def output_only_marker(output):
    # Reuse the primary marker checks, including hashes and rejection as a pair.
    marker_path = output.with_name(output.name + ".publication.json")
    publisher = SimpleNamespace(marker_path=marker_path, writer=SimpleNamespace(output_path=output))
    marker = assert_output_marker(publisher)
    assert marker["row_count"] == len(output.read_text().splitlines())
    return marker


def test_output_only_resume_preserves_supported_baseline_claims(tmp_path, monkeypatch):
    source = tmp_path / "input.txt"
    source.write_text("923609016\n")
    snapshot = tmp_path / "registry.jsonl"
    snapshot.write_text(json.dumps({"organisasjonsnummer": "923609016", "navn": "Supported Fixture AS"}) + "\n")
    output = tmp_path / "output.jsonl"

    def interrupt_secondary(*args, **kwargs):
        raise run.OutputFirstDeadline()

    monkeypatch.setattr(run, "company_state", interrupt_secondary)
    arguments = ["--input", str(source), "--registry-snapshot", str(snapshot),
        "--registry-snapshot-as-of", "2025-01-01", "--evidence-cutoff", "2026-01-01T00:00:00Z",
        "--output", str(output), "--state-output", str(tmp_path / "state.json"),
        "--checkpoint", str(tmp_path / "checkpoint.sqlite"), "--budget-seconds", "30", "--output-first"]
    assert run.main(arguments) == 0
    original = complete_output(output, ["923609016"])[0]["claims"]
    assert original
    assert run.main([*arguments, "--resume"]) == 0
    resumed = complete_output(output, ["923609016"])[0]["claims"]
    assert resumed == original
    output_only_marker(output)


def incomplete_report(stdout, stderr, count):
    reports = [json.loads(line) for line in stdout.splitlines()]
    completed = [item for item in reports if item.get("event") == "batch_complete"]
    assert len(completed) == 1
    report = completed[0]
    assert report["rows"] == report["output_cardinality"] == count
    assert report["output_committed"] is True
    assert report["state_incomplete"] is True
    assert "output_committed:" in stderr
    assert "state_incomplete:" in stderr
    return report


@pytest.mark.parametrize("secondary", ["company_state", "canonical_fallback"])
def test_output_is_complete_before_secondary_deadline_and_outer_run_returns_zero(
        tmp_path, monkeypatch, capsys, secondary):
    organisations = ["923609016", "976390512", "923609016", "987974249"]
    source = tmp_path / "input.txt"
    source.write_text("\n".join(organisations) + "\n", encoding="utf-8")
    snapshot = tmp_path / "registry.jsonl"
    snapshot.write_text("\n".join(json.dumps({
        "organisasjonsnummer": org, "navn": name,
        "organisasjonsform": {"kode": "AS"},
    }, ensure_ascii=False) for org, name in [
        ("923609016", "Blåbær AS"), ("976390512", "Second Fixture AS"),
    ]) + "\n", encoding="utf-8")
    output = tmp_path / "output.jsonl"
    state = tmp_path / "state.json"
    observed = []

    def interrupt_secondary(*args, **kwargs):
        payloads = complete_output(output, organisations)
        output_only_marker(output)
        assert not state.exists()
        assert any(claim["value"] == "Blåbær AS" for claim in payloads[0]["claims"])
        assert payloads[0]["claims"] and payloads[2]["claims"]
        assert not payloads[3]["claims"]  # absent fixture stays a legal unknown
        observed.append(output.read_bytes())
        raise run.OutputFirstDeadline()

    if secondary == "canonical_fallback":
        def fail_legacy(*args, **kwargs):
            # The ordinary exception path calls history.company_state directly.
            complete_output(output, organisations)
            output_only_marker(output)
            observed.append(output.read_bytes())
            raise RuntimeError("injected legacy state failure")

        monkeypatch.setattr(run, "company_state", fail_legacy)
        monkeypatch.setattr(history, "company_state", interrupt_secondary)
    else:
        monkeypatch.setattr(run, "company_state", interrupt_secondary)

    assert run.main([
        "--input", str(source), "--registry-snapshot", str(snapshot),
        "--registry-snapshot-as-of", "2025-01-01",
        "--registry-source-url", "https://registry.example.test/snapshot",
        "--evidence-cutoff", "2026-01-01T00:00:00Z",
        "--output", str(output), "--state-output", str(state),
        "--checkpoint", str(tmp_path / "checkpoint.sqlite"),
        "--budget-seconds", "30", "--output-first",
    ]) == 0
    assert len(observed) == 1, "secondary deadline injection must actually run"
    assert output.read_bytes() == observed[0]
    complete_output(output, organisations)
    output_only_marker(output)
    assert not state.exists()
    captured = capsys.readouterr()
    report = incomplete_report(captured.out, captured.err, len(organisations))
    assert report["physical_requests"] == 0
    assert "injected legacy state failure" not in output.read_text()


@pytest.mark.skipif(os.name != "posix", reason="real watchdog signals require POSIX")
@pytest.mark.parametrize("stalled_layer", ["research", "secondary", "secondary_term"])
def test_cli_watchdog_stop_preserves_complete_output_contract_and_exits_zero(tmp_path, stalled_layer):
    organisations = [f"{number:09d}" for number in range(1, 21)] + ["000000001"]
    source = tmp_path / "input.txt"
    source.write_text("\n".join(organisations) + "\n")
    output = tmp_path / "output.jsonl"
    state = tmp_path / "state.json"
    script = r'''
import asyncio
import json
import signal
import socket
import sys
import time
from signalpost import network, run
stalled_layer = sys.argv[1]

def forbidden(*args, **kwargs):
    raise AssertionError('integration test attempted a real network connection')
socket.getaddrinfo = forbidden
socket.socket.connect = forbidden
network.validate_public_host = lambda *args, **kwargs: ('8.8.8.8',)

async def transport(self, url, headers, timeout, **kwargs):
    if stalled_layer == 'research':
        print('transport_stalled', file=sys.stderr, flush=True)
        await asyncio.Event().wait()
    return 404, {'Content-Type': 'application/json'}, b'{}', url
network.UrlLibTransport.request = transport

def slow_secondary(*args, **kwargs):
    print('secondary_entered', file=sys.stderr, flush=True)
    if stalled_layer == 'secondary_term':
        # Force the durable-output TERM handshake rather than the earlier stops.
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        signal.signal(signal.SIGUSR2, signal.SIG_IGN)
    time.sleep(30)
    raise AssertionError('watchdog failed to interrupt secondary work')
run.company_state = slow_secondary
sys.argv = ['signalpost', *sys.argv[2:]]
run.cli_main()
'''
    result = subprocess.run([
        sys.executable, "-c", script, stalled_layer,
        "--input", str(source), "--output", str(output),
        "--state-output", str(state), "--checkpoint", str(tmp_path / "checkpoint.sqlite"),
        "--budget-seconds", "5", "--output-first",
    ], cwd=ROOT, capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stderr
    payloads = complete_output(output, organisations)
    assert all(not payload["claims"] for payload in payloads)
    output_only_marker(output)
    assert not state.exists()
    incomplete_report(result.stdout, result.stderr, len(organisations))
    events = [json.loads(line) for line in result.stderr.splitlines() if line.startswith('{')]
    watchdog = [item for item in events if item.get("event") == "watchdog"]
    assert any(item["reason"] == "stop_research" for item in watchdog), result.stderr
    assert not any(item["reason"].startswith("force_exit") for item in watchdog), result.stderr
    if stalled_layer.startswith("secondary"):
        assert "secondary_entered" in result.stderr
    else:
        assert "transport_stalled" in result.stderr
    if stalled_layer == "secondary_term":
        exits = [item for item in watchdog if item["reason"] == "output_committed_exit"]
        assert len(exits) == 1, result.stderr
        assert exits[0]["durable_output_committed"] is True
        assert exits[0]["durable_pair_committed"] is False
