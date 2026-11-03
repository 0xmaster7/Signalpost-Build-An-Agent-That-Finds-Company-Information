import asyncio
import socket

import pytest

from signalpost.network import NetworkGateway, NetworkPolicyError


def test_dns_failure_is_a_replayable_policy_input_without_a_fake_http_response(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise socket.gaierror("fixture DNS failure")

    monkeypatch.setattr(socket, "getaddrinfo", unavailable)
    live = NetworkGateway(record_http=str(tmp_path / "capture"))
    with pytest.raises(NetworkPolicyError, match="hostname did not resolve"):
        asyncio.run(live.fetch("https://unresolvable.example/", use_robots=False))
    assert live.ledger.physical_requests == 0
    live.http_recording.seal()

    def forbidden(*args, **kwargs):
        raise AssertionError("replay attempted DNS")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    replay = NetworkGateway(replay_http=str(tmp_path / "capture"))
    with pytest.raises(NetworkPolicyError, match="hostname did not resolve"):
        asyncio.run(replay.fetch("https://unresolvable.example/", use_robots=False))
    assert replay.ledger.physical_requests == 0
    replay.http_recording.assert_complete()
