import asyncio
import base64
import hashlib
import json
import socket
import stat
import urllib.request

import pytest

from signalpost import network
from signalpost.network import NetworkGateway, NetworkPolicyError
from signalpost.recording import HttpRecording, ReplayError


class SyntheticTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def request(self, url, headers, timeout):
        self.calls.append((url, headers))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, response_headers, body = response
        return status, response_headers, body, url


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network access forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(urllib.request, "getproxies", forbidden)
    monkeypatch.setattr(network.UrlLibTransport, "request", forbidden)


def live(tmp_path, monkeypatch, responses, **kwargs):
    transport = SyntheticTransport(responses)
    gateway = NetworkGateway(transport, record_http=str(tmp_path / "capture"), retries=0, **kwargs)
    monkeypatch.setattr(gateway, "_validate_host", lambda url: ("8.8.8.8",))
    return gateway, transport


def replay(tmp_path, monkeypatch, **kwargs):
    async def no_sleep(*args, **kwargs):
        raise AssertionError("replay sleep forbidden")

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    return NetworkGateway(replay_http=str(tmp_path / "capture"), retries=0, **kwargs)


def test_pdf_robots_private_metadata_and_offline_replay(tmp_path, monkeypatch):
    metadata = {"run_started_at": "2026-10-01T00:00:00+00:00", "cutoff": "2026-09-01"}
    gateway, transport = live(tmp_path, monkeypatch, [
        (200, {}, b"User-agent: *\nAllow: /\nCrawl-delay: 1"),
        (200, {"Content-Type": "application/pdf", "Date": "original"}, b"%PDF-synthetic")],
        run_metadata=metadata)
    result = asyncio.run(gateway.fetch("https://company.example/report.pdf"))
    assert len(transport.calls) == 2
    assert stat.S_IMODE((tmp_path / "capture").stat().st_mode) == 0o700
    payloads = []
    for path in (tmp_path / "capture").iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        payloads.append(json.loads(path.read_text())["payload"])
    assert any(base64.b64decode(p["response"]["body"]) == b"%PDF-synthetic" for p in payloads if "response" in p)
    offline = replay(tmp_path, monkeypatch, run_metadata=metadata)
    assert asyncio.run(offline.fetch("https://company.example/report.pdf")) == result
    assert offline.http_recording.hits == 2
    assert offline.http_recording.metadata["run"] == metadata


def test_nav_public_token_body_but_no_request_credentials_and_exact_since(tmp_path, monkeypatch):
    gateway, _ = live(tmp_path, monkeypatch, [(200, {}, b"public-nav-token"), (200, {}, b"feed")])
    token = "https://pam-stilling-feed.nav.no/api/publicToken"
    feed = "https://pam-stilling-feed.nav.no/api/v1/feed?pageSize=10&last=a%2Bb"
    options = {"access_profile": "nav_feed_api", "use_robots": False}
    asyncio.run(gateway.fetch(token, purpose="nav_public_access", **options))
    headers = {"Authorization": "Bearer REQUEST-SECRET", "If-Modified-Since": "Thu, 01 Oct 2026 00:00:00 GMT"}
    asyncio.run(gateway.fetch(feed, purpose="nav_feed", api_headers=headers, **options))
    capture = "".join(p.read_text() for p in (tmp_path / "capture").iterdir())
    assert "REQUEST-SECRET" not in capture
    assert "Authorization" not in capture
    assert base64.b64encode(b"public-nav-token").decode() in capture
    offline = replay(tmp_path, monkeypatch)
    assert asyncio.run(offline.fetch(token, purpose="nav_public_access", **options))[2] == b"public-nav-token"
    assert asyncio.run(offline.fetch(feed, purpose="nav_feed", api_headers={**headers, "Authorization": "Bearer DIFFERENT"}, **options))[2] == b"feed"
    with pytest.raises(ReplayError):
        asyncio.run(offline.fetch(feed, purpose="nav_feed", api_headers={**headers, "If-Modified-Since": "different"}, **options))
    assert offline.replay_misses == 1


def test_params_variants_and_exhaustion(tmp_path, monkeypatch):
    gateway, _ = live(tmp_path, monkeypatch, [(200, {}, b"first"), (404, {}, b"second"), (200, {}, b"other")])
    urls = ["https://company.example/?q=a%2Bb&q=c", "https://company.example/?q=a%2Bb&q=c", "https://company.example/?q=a+b&q=c"]
    results = [asyncio.run(gateway.fetch(url, use_robots=False)) for url in urls]
    offline = replay(tmp_path, monkeypatch)
    assert [asyncio.run(offline.fetch(url, use_robots=False)) for url in urls] == results
    with pytest.raises(ReplayError):
        asyncio.run(offline.fetch(urls[0], use_robots=False))
    assert offline.replay_misses == 1


def test_company_robots_blocks_and_no_general_api_bypass(tmp_path, monkeypatch):
    gateway, transport = live(tmp_path, monkeypatch, [(200, {}, b"User-agent: *\nDisallow: /")])
    assert asyncio.run(gateway.fetch("https://company.example/private"))[4] == "robots_disallowed"
    assert len(transport.calls) == 1
    offline = replay(tmp_path, monkeypatch)
    assert asyncio.run(offline.fetch("https://company.example/private"))[4] == "robots_disallowed"
    for profile in ["brreg_structured_api", "brreg_document_api", "nav_feed_api", "wikidata_sparql_api"]:
        with pytest.raises(NetworkPolicyError):
            asyncio.run(offline.fetch("https://company.example/private", access_profile=profile))
    with pytest.raises(NetworkPolicyError):
        asyncio.run(offline.fetch("https://company.example/", allowed_hosts={"other.example"}))
    for url in ["http://127.0.0.1/", "http://localhost/", "http://metadata.internal/"]:
        with pytest.raises(NetworkPolicyError):
            asyncio.run(offline.fetch(url))


@pytest.mark.parametrize("mutation", ["corrupt", "missing", "symlink", "malformed", "request"])
def test_fail_closed_store_damage(tmp_path, monkeypatch, mutation):
    gateway, _ = live(tmp_path, monkeypatch, [(200, {}, b"original")])
    asyncio.run(gateway.fetch("https://company.example/", use_robots=False))
    path = next(p for p in (tmp_path / "capture").glob("*.json") if p.name != "manifest.json")
    wrapped = json.loads(path.read_text())
    if mutation == "missing":
        path.unlink()
    elif mutation == "symlink":
        path.unlink()
        path.symlink_to(tmp_path / "outside")
    elif mutation == "malformed":
        path.write_text("[]")
    else:
        if mutation == "request":
            wrapped["payload"]["request"]["purpose"] = "different"
            encoded = json.dumps(wrapped["payload"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            wrapped["sha256"] = hashlib.sha256(encoded).hexdigest()
        else:
            wrapped["payload"]["response"]["body"] = "damaged"
        path.write_text(json.dumps(wrapped))
    offline = replay(tmp_path, monkeypatch)
    with pytest.raises(ReplayError):
        asyncio.run(offline.fetch("https://company.example/", use_robots=False))
    assert offline.replay_misses + offline.replay_failures == 1


def test_http_errors_timeouts_and_redirects_replay_without_sleep(tmp_path, monkeypatch):
    transport = SyntheticTransport([OSError("synthetic"), (503, {"Retry-After": "0"}, b"busy"),
                                    (302, {"Location": "/next"}, b"redirect"), (200, {}, b"done")])
    gateway = NetworkGateway(transport, record_http=str(tmp_path / "capture"), retries=2)
    monkeypatch.setattr(gateway, "_validate_host", lambda url: ("8.8.8.8",))
    result = asyncio.run(gateway.fetch("https://company.example/", use_robots=False))
    offline = replay(tmp_path, monkeypatch)
    offline.retries = 2
    assert asyncio.run(offline.fetch("https://company.example/", use_robots=False)) == result
    assert offline.http_recording.hits == 4


def test_manifest_metadata_path_and_private_checks(tmp_path):
    root = tmp_path / "capture"
    capture = HttpRecording(root, replay=False, run_metadata={"cutoff": "original"})
    with pytest.raises(ReplayError):
        capture._path("../../outside")
    with pytest.raises(ReplayError):
        HttpRecording(root, replay=False)
    with pytest.raises(ReplayError):
        HttpRecording(root, replay=True, run_metadata={"cutoff": "new"})
    root.chmod(0o755)
    with pytest.raises(ReplayError):
        HttpRecording(root, replay=True)


@pytest.mark.parametrize("response,expected", [
    (asyncio.TimeoutError(), "timeout"),
    ((200, {"Content-Encoding": "gzip"}, b"broken"), "invalid_compression"),
    ((200, {}, b"oversized"), "response_too_large"),
    ((403, {}, b"denied"), "blocked"),
])
def test_all_outcomes_and_raw_bytes(tmp_path, monkeypatch, response, expected):
    gateway, _ = live(tmp_path, monkeypatch, [response])
    result = asyncio.run(gateway.fetch("https://company.example/", use_robots=False, max_bytes=8))
    assert result[4] == expected
    offline = replay(tmp_path, monkeypatch)
    assert asyncio.run(offline.fetch("https://company.example/", use_robots=False, max_bytes=8)) == result


def test_recording_refuses_query_credentials_without_persisting_them(tmp_path, monkeypatch):
    gateway, transport = live(tmp_path, monkeypatch, [])
    with pytest.raises(NetworkPolicyError):
        asyncio.run(gateway.fetch("https://company.example/?api_key=SECRET"))
    assert not transport.calls
    assert "SECRET" not in "".join(p.read_text() for p in (tmp_path / "capture").iterdir())


@pytest.mark.parametrize("rules,expected", [(b"User-agent: *\nDisallow: /", "robots_disallowed"),
                                            (b"outage", "ok")])
def test_documented_api_exception_only_for_robots_outage(tmp_path, monkeypatch, rules, expected):
    gateway, _ = live(tmp_path, monkeypatch, [(200 if expected == "robots_disallowed" else 503, {}, rules),
                                             (200, {}, b"entity")])
    url = "https://data.brreg.no/enhetsregisteret/api/enheter/999999999"
    options = {"access_profile": "brreg_structured_api", "purpose": "entity"}
    result = asyncio.run(gateway.fetch(url, **options))
    assert result[4] == expected
    offline = replay(tmp_path, monkeypatch)
    assert asyncio.run(offline.fetch(url, **options)) == result
