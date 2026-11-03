"""Synthetic transport checks; never contact live sources or spawn OCR."""
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json

import pytest

from signalpost.brreg import fetch_company
from signalpost.network import NetworkGateway, UrlLibTransport
from signalpost.recording import HttpRecording, ReplayError
from signalpost.websites import _parse_page
from test_signalpost_http_recording import SyntheticTransport, live, no_live_network, replay


def test_explicit_method_parameters_and_missing_key_diagnostics(tmp_path, monkeypatch):
    gateway, _ = live(tmp_path, monkeypatch, [(200, {}, b"ok")])
    url = "https://company.example/?q=a%2Bb&q=c&blank="
    asyncio.run(gateway.fetch(url, use_robots=False))
    request = next(iter(gateway.http_recording.metadata["attempts"].values()))["request"]
    assert request["method"] == "GET"
    assert request["params"] == [["q", "a+b"], ["q", "c"], ["blank", ""]]
    gateway.http_recording.seal()
    offline = replay(tmp_path, monkeypatch)
    asyncio.run(offline.fetch(url, use_robots=False))
    offline.http_recording.assert_complete()
    with pytest.raises(ReplayError, match='"method":"GET"') as error:
        asyncio.run(offline.fetch(url, use_robots=False))
    missing = offline.replay_missing_requests[0]
    assert missing["position"] == 1
    assert missing["request"]["url"] == url
    assert missing["key"] in str(error.value)
    assert offline.http_recording.diagnostics()["missing_requests"] == [missing]
    with pytest.raises(ReplayError, match="replay incomplete"):
        offline.http_recording.assert_complete()


def test_every_physical_attempt_has_identical_replay_ledger_and_clock(tmp_path, monkeypatch):
    responses = [OSError("PRIVATE failure detail must not persist"), asyncio.TimeoutError(),
                 (429, {"Retry-After": "0"}, b"throttle"),
                 (302, {"Location": "/report.pdf"}, b"redirect"),
                 (200, {"Content-Type": "application/pdf"}, b"%PDF\x00\xffraw bytes")]
    transport = SyntheticTransport(responses)
    gateway = NetworkGateway(transport, record_http=str(tmp_path / "capture"), retries=3)
    monkeypatch.setattr(gateway, "_validate_host", lambda url: ("8.8.8.8",))

    async def fetch(instance):
        result = await instance.fetch("https://company.example/", use_robots=False)
        return result, instance.observed_at

    before = asyncio.run(fetch(gateway))
    assert len(transport.calls) == gateway.ledger.physical_requests == 5
    assert [entry.outcome for entry in gateway.ledger.entries] == [
        "transport_error", "timeout", "received", "received", "received"]
    assert before[0][2] == b"%PDF\x00\xffraw bytes"
    payloads = [json.loads(path.read_text())["payload"] for path in (tmp_path / "capture").glob("*-*.json")]
    assert len(payloads) == 5
    assert "PRIVATE" not in "".join(path.read_text() for path in (tmp_path / "capture").iterdir())
    assert before[1].isoformat() == next(payload["retrieved_at"] for payload in payloads
                                       if payload["response"] and payload["response"]["status"] == 200)
    gateway.http_recording.seal()
    offline = replay(tmp_path, monkeypatch)
    offline.retries = 3
    assert asyncio.run(fetch(offline)) == before
    assert [asdict(entry) for entry in offline.ledger.entries] == [asdict(entry) for entry in gateway.ledger.entries]
    offline.http_recording.assert_complete()


def test_attempt_order_is_start_order_and_crash_is_visible(tmp_path):
    capture = HttpRecording(tmp_path / "capture", replay=False)
    request = {"method": "GET", "url": "https://company.example/", "params": []}
    first = capture.begin(request, approved_ips=None)
    second = capture.begin(request, approved_ips=None)
    capture.save(request, response=(200, {}, b"second", request["url"]), outcome="received",
                 approved_ips=None, elapsed_ms=1, attempt=second)
    with pytest.raises(ReplayError, match="pending"):
        capture.seal()
    offline = HttpRecording(capture.root, replay=True)
    with pytest.raises(ReplayError, match="incomplete physical attempt"):
        offline.load(request)
    capture.save(request, response=(200, {}, b"first", request["url"]), outcome="received",
                 approved_ips=None, elapsed_ms=2, attempt=first)
    capture.seal()
    offline = HttpRecording(capture.root, replay=True)
    assert offline.load(request)["response"]["body"] == b"first"
    assert offline.load(request)["response"]["body"] == b"second"
    offline.assert_complete()


def test_unconsumed_requests_and_unsealed_captures_cannot_pass(tmp_path, monkeypatch):
    gateway, _ = live(tmp_path, monkeypatch, [(200, {}, b"one"), (200, {}, b"two")])
    for path in ["one", "two"]:
        asyncio.run(gateway.fetch("https://company.example/" + path, use_robots=False))
    offline = replay(tmp_path, monkeypatch)
    with pytest.raises(ReplayError, match='"capture_complete":false'):
        offline.http_recording.assert_complete()
    gateway.http_recording.seal()
    offline = replay(tmp_path, monkeypatch)
    asyncio.run(offline.fetch("https://company.example/one", use_robots=False))
    with pytest.raises(ReplayError, match="https://company.example/two"):
        offline.http_recording.assert_complete()


def test_execution_controls_and_identity_verify_fresh_bytes_without_output_copy(tmp_path):
    capture = HttpRecording(tmp_path / "capture", replay=False)
    controls = {"admitted": ["official:999999999"], "cancelled": [], "elapsed": 1.25}
    capture.record_execution("schedule", controls)
    capture.assert_identity("envelopes", b'{"newly_computed":"FACT"}\n')
    assert "FACT" not in (capture.root / "execution.json").read_text()
    capture.seal()
    offline = HttpRecording(capture.root, replay=True)
    assert offline.replay_execution("schedule") == controls
    assert offline.assert_identity("envelopes", b'{"newly_computed":"FACT"}\n') is None
    offline.assert_complete()
    with pytest.raises(ReplayError, match="identity mismatch"):
        offline.assert_identity("envelopes", b'{"newly_computed":"WRONG"}\n')
    with pytest.raises(ReplayError, match="missing execution control: missing-phase"):
        offline.replay_execution("missing-phase")
    with pytest.raises(ReplayError, match="cannot write"):
        offline._write("execution.json", {})


def test_coalesced_callers_receive_same_recorded_time_without_replay_sleeps(tmp_path, monkeypatch):
    class YieldingTransport:
        calls = 0

        async def request(self, url, headers, timeout):
            self.calls += 1
            await asyncio.sleep(0)
            return 200, {}, b"coalesced", url

    transport = YieldingTransport()
    gateway = NetworkGateway(transport, record_http=str(tmp_path / "capture"), retries=0)
    monkeypatch.setattr(gateway, "_validate_host", lambda url: ("8.8.8.8",))

    async def both(instance):
        async def one():
            result = await instance.fetch("https://company.example/", use_robots=False)
            return result, instance.observed_at
        return await asyncio.gather(one(), one())

    before = asyncio.run(both(gateway))
    assert before[0] == before[1]
    assert transport.calls == gateway.ledger.physical_requests == gateway.coalesced_requests == 1
    gateway.http_recording.seal()
    offline = replay(tmp_path, monkeypatch)
    assert asyncio.run(both(offline)) == before
    assert offline.coalesced_requests == offline.ledger.physical_requests == 1
    offline.http_recording.assert_complete()


def test_unexpected_transport_errors_are_accounted_but_fail_replay(tmp_path, monkeypatch):
    gateway, _ = live(tmp_path, monkeypatch, [RuntimeError("PRIVATE transport detail")])
    with pytest.raises(RuntimeError):
        asyncio.run(gateway.fetch("https://company.example/", use_robots=False))
    assert gateway.ledger.physical_requests == 1
    assert gateway.ledger.entries[0].outcome == "unexpected_error"
    assert "PRIVATE" not in "".join(path.read_text() for path in (tmp_path / "capture").iterdir())
    with pytest.raises(ReplayError, match="unreplayable"):
        gateway.http_recording.seal()
    offline = replay(tmp_path, monkeypatch)
    with pytest.raises(ReplayError):
        asyncio.run(offline.fetch("https://company.example/", use_robots=False))


def test_native_address_fallback_is_separately_recorded(tmp_path, monkeypatch):
    class PinnedTransport(UrlLibTransport):
        def __init__(self):
            self.addresses = []

        async def request(self, url, headers, timeout, approved_ips=None, max_bytes=None):
            self.addresses.append(approved_ips)
            if len(self.addresses) == 1:
                raise OSError("first address unavailable")
            return 200, {}, b"ok", url

    transport = PinnedTransport()
    gateway = NetworkGateway(transport, record_http=str(tmp_path / "capture"), retries=1)
    monkeypatch.setattr(gateway, "_validate_host", lambda url: ("2606:4700:4700::1111", "1.1.1.1"))
    before = asyncio.run(gateway.fetch("https://company.example/", use_robots=False))
    assert transport.addresses == [("1.1.1.1",), ("2606:4700:4700::1111",)]
    assert gateway.ledger.physical_requests == 2
    gateway.http_recording.seal()
    offline = replay(tmp_path, monkeypatch)
    offline.retries = 1
    assert asyncio.run(offline.fetch("https://company.example/", use_robots=False)) == before
    offline.http_recording.assert_complete()


def test_cancelled_attempt_is_persisted_once_and_replays_cancellation(tmp_path, monkeypatch):
    class HangingTransport:
        def __init__(self):
            self.entered = asyncio.Event()

        async def request(self, url, headers, timeout):
            self.entered.set()
            await asyncio.Event().wait()

    transport = HangingTransport()
    gateway = NetworkGateway(transport, record_http=str(tmp_path / "capture"), retries=0)
    monkeypatch.setattr(gateway, "_validate_host", lambda url: ("8.8.8.8",))

    async def cancel():
        task = asyncio.create_task(gateway.fetch("https://company.example/", use_robots=False))
        await transport.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    assert gateway.ledger.physical_requests == 1
    assert gateway.ledger.entries[0].outcome == "cancelled"
    attempt = next((tmp_path / "capture").glob("*-*.json"))
    assert json.loads(attempt.read_text())["payload"]["outcome"] == "cancelled"
    gateway.http_recording.seal()
    offline = replay(tmp_path, monkeypatch)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(offline.fetch("https://company.example/", use_robots=False))
    assert [asdict(item) for item in gateway.ledger.entries] == [asdict(item) for item in offline.ledger.entries]
    offline.http_recording.assert_complete()


@pytest.mark.parametrize("parameter", ["api_key", "token", "access_key", "sig", "X-Amz-Signature"])
def test_credential_queries_never_reach_capture_or_missing_diagnostics(tmp_path, monkeypatch, parameter):
    from signalpost.network import NetworkPolicyError

    gateway, transport = live(tmp_path, monkeypatch, [])
    with pytest.raises(NetworkPolicyError, match="credential-bearing"):
        asyncio.run(gateway.fetch(f"https://company.example/?{parameter}=PRIVATE", use_robots=False))
    assert not transport.calls
    assert "PRIVATE" not in "".join(path.read_text() for path in (tmp_path / "capture").iterdir())
    offline = replay(tmp_path, monkeypatch)
    with pytest.raises(NetworkPolicyError, match="credential-bearing"):
        asyncio.run(offline.fetch(f"https://company.example/?{parameter}=PRIVATE", use_robots=False))
    assert not offline.replay_missing_requests


def test_source_adapter_timestamps_and_real_extractor_facts_reexecute(tmp_path, monkeypatch):
    org = "999999999"
    body = json.dumps({"organisasjonsnummer": org, "navn": "Recorded Timestamp AS",
                       "organisasjonsform": {"kode": "AS"}}).encode()
    gateway, _ = live(tmp_path, monkeypatch, [(200, {}, b"User-agent: *\nAllow: /\n"),
        (200, {"Content-Type": "application/json"}, body),
        (200, {}, b'{"rollegrupper":[]}'),
        (200, {}, b'{"_embedded":{"underenheter":[]},"page":{"totalPages":1,"number":0}}')])
    cutoff = datetime(2030, 1, 1, tzinfo=timezone.utc)
    before = asyncio.run(fetch_company(org, gateway, cutoff, include_accounts=False))
    assert before.claims
    capture = gateway.http_recording
    capture.assert_identity("brreg-facts", json.dumps({
        "claims": [claim.model_dump(mode="json") for claim in before.claims],
        "evidence": [item.model_dump(mode="json") for item in before.evidence],
        "snapshots": [item.model_dump(mode="json") for item in before.snapshots],
    }, sort_keys=True).encode())
    capture.seal()
    offline = replay(tmp_path, monkeypatch)
    after = asyncio.run(fetch_company(org, offline, cutoff, include_accounts=False))
    offline.http_recording.assert_identity("brreg-facts", json.dumps({
        "claims": [claim.model_dump(mode="json") for claim in after.claims],
        "evidence": [item.model_dump(mode="json") for item in after.evidence],
        "snapshots": [item.model_dump(mode="json") for item in after.snapshots],
    }, sort_keys=True).encode())
    offline.http_recording.assert_complete()

    stamp = datetime(2026, 1, 2, tzinfo=timezone.utc)
    page = _parse_page("https://company.example/", 200, {"Content-Type": "text/html"},
                       b"<html><title>Company</title><body>Official company website and information</body></html>",
                       "https://company.example/", retrieved_at=stamp)
    assert page.retrieved_at == stamp
