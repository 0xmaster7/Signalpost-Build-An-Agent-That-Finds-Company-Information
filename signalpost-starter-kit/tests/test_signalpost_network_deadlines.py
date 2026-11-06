"""Offline checks for physical deadlines and explicit official-host capacity."""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from signalpost import network


def public_dns(monkeypatch):
    monkeypatch.setattr(network, "validate_public_host", lambda *a, **k: ("8.8.8.8",))


def test_robots_retry_caps_transport_and_watchdog_but_preserves_capture_config(monkeypatch, tmp_path):
    public_dns(monkeypatch)
    timeouts = []
    waits = []
    original_wait = asyncio.wait_for

    async def wait(awaitable, timeout):
        waits.append(timeout)
        return await original_wait(awaitable, timeout)

    class Transport:
        async def request(self, url, headers, timeout):
            timeouts.append(timeout)
            if len(timeouts) == 1:
                raise asyncio.TimeoutError()
            return 200, {}, b"User-agent: *\nAllow: /", url

    monkeypatch.setattr(asyncio, "wait_for", wait)
    capture = tmp_path / "capture"
    live = network.NetworkGateway(Transport(), timeout=15, record_http=str(capture))
    result = asyncio.run(live.fetch("https://data.brreg.no/robots.txt", purpose="robots", use_robots=False))
    assert result[-1] == "ok"
    assert timeouts == waits == [10, 10]
    settings = [entry["request"]["timeout"] for entry in live.http_recording.metadata["attempts"].values()]
    assert sorted(settings) == [15, 30]
    live.http_recording.seal()
    replay = network.NetworkGateway(timeout=15, replay_http=str(capture))
    assert asyncio.run(replay.fetch("https://data.brreg.no/robots.txt", purpose="robots", use_robots=False)) == result
    replay.http_recording.assert_complete()
    assert replay.http_recording.hits == 2


def test_gateway_timeout_cancels_transport_and_releases_slots(monkeypatch):
    public_dns(monkeypatch)
    cancelled = []

    class Transport:
        async def request(self, url, headers, timeout):
            try:
                await asyncio.Future()
            finally:
                cancelled.append(True)

    gateway = network.NetworkGateway(Transport(), timeout=0.02, retries=0)
    result = asyncio.run(gateway.fetch("https://data.brreg.no/entity", use_robots=False))
    assert result[-1] == "timeout"
    assert cancelled == [True]
    assert gateway.ledger.entries[-1].outcome == "timeout"
    assert gateway._host_slots["data.brreg.no"].active == 0
    assert not gateway._inflight


@pytest.mark.parametrize("pinned", [False, True])
def test_transport_watchdog_releases_await_while_thread_remains(monkeypatch, pinned):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    seen = []

    def block(timeout):
        seen.append(timeout)
        started.set()
        try:
            release.wait(2)
            return 200, {}, b"", "https://data.brreg.no/"
        finally:
            finished.set()

    transport = network.UrlLibTransport()
    if pinned:
        monkeypatch.setattr(transport, "_pinned_request", lambda url, headers, timeout, *args: block(timeout))
    else:
        class Response:
            status = 200
            headers = {}

            def read(self, cap):
                return block(seen.pop())[2]

            def geturl(self):
                return "https://data.brreg.no/"

            def close(self):
                pass

        def open_response(request, timeout):
            seen.append(timeout)
            return Response()

        monkeypatch.setattr(transport._opener, "open", open_response)
    monkeypatch.setattr(network, "MAX_PHYSICAL_REQUEST_SECONDS", 0.05)

    async def run():
        try:
            with pytest.raises(asyncio.TimeoutError):
                await transport.request("https://data.brreg.no/", {}, 90,
                                        approved_ips=("8.8.8.8",) if pinned else None)
            assert started.is_set() and not finished.is_set()
            assert seen == [0.05]
        finally:
            release.set()

    asyncio.run(run())
    assert finished.is_set()


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_pinned_socket_connect_and_read_timeout_is_capped(monkeypatch, scheme):
    seen = []
    sock = SimpleNamespace(close=lambda: None)

    class Connection:
        def __init__(self, host, port, timeout):
            seen.append(timeout)
            self._context = SimpleNamespace(wrap_socket=lambda sock, **kwargs: sock)

        def connect(self):
            pass

        def request(self, *args, **kwargs):
            self.connect()

        def getresponse(self):
            return SimpleNamespace(status=200, getheaders=lambda: [], read=lambda cap: b"ok")

        def close(self):
            pass

    def connect(address, timeout):
        seen.append(timeout)
        return sock

    monkeypatch.setattr(network.http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(network.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(network.socket, "create_connection", connect)
    assert network.UrlLibTransport._pinned_request(f"{scheme}://data.brreg.no/", {}, 90, ("8.8.8.8",), 100)[2] == b"ok"
    assert seen == [10, 10]


def test_official_host_override_does_not_raise_websites_and_recovers_to_override(monkeypatch):
    public_dns(monkeypatch)

    class Transport:
        async def request(self, url, headers, timeout):
            return 200, {}, b"ok", url

    gateway = network.NetworkGateway(Transport())
    gateway.set_host_concurrency("DATA.BRREG.NO.", 8)

    async def run():
        await gateway.fetch("https://data.brreg.no/entity", use_robots=False)
        await gateway.fetch("https://example.com/", use_robots=False)
        official = gateway._host_slots["data.brreg.no"]
        assert official.limit == 8
        assert gateway._host_slots["example.com"].limit == 2
        await gateway._adapt_host_rate("data.brreg.no")
        assert official.limit == 4
        for _ in range(5):
            await gateway._recover_host_rate("data.brreg.no")
        assert official.limit == 5
        with pytest.raises(ValueError, match="before scheduling"):
            gateway.set_host_concurrency("data.brreg.no", 16)

    asyncio.run(run())


@pytest.mark.parametrize("workers", [8, 16])
def test_official_requests_use_selected_capacity_with_website_default(monkeypatch, workers):
    public_dns(monkeypatch)

    async def run():
        release = asyncio.Event()
        ready = asyncio.Event()
        active = {"data.brreg.no": 0, "example.com": 0}
        peaks = dict(active)

        class Transport:
            async def request(self, url, headers, timeout):
                host = network.urllib.parse.urlsplit(url).hostname
                active[host] += 1
                peaks[host] = max(peaks[host], active[host])
                if active == {"data.brreg.no": workers, "example.com": 2}:
                    ready.set()
                try:
                    await release.wait()
                    return 200, {}, b"ok", url
                finally:
                    active[host] -= 1

        gateway = network.NetworkGateway(Transport())
        gateway.set_host_concurrency("data.brreg.no", workers)
        tasks = [asyncio.create_task(gateway.fetch(f"https://{host}/{index}", use_robots=False))
                 for host in active for index in range(workers + 1)]
        try:
            await asyncio.wait_for(ready.wait(), 1)
            assert peaks == {"data.brreg.no": workers, "example.com": 2}
        finally:
            release.set()
            await asyncio.gather(*tasks)
        assert active == {"data.brreg.no": 0, "example.com": 0}
        assert peaks == {"data.brreg.no": workers, "example.com": 2}

    asyncio.run(run())


@pytest.mark.parametrize("workers", [0, 17, True, 8.5])
def test_invalid_host_capacity_is_rejected(workers):
    with pytest.raises(ValueError):
        network.NetworkGateway().set_host_concurrency("data.brreg.no", workers)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_is_rejected(timeout):
    with pytest.raises(ValueError):
        network.NetworkGateway(timeout=timeout)
