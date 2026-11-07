"""Offline tests for the narrowly scoped BRREG collection access profile."""
import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

import pytest

from signalpost.brreg import preload_entity_batch
from signalpost.network import NetworkGateway, NetworkPolicyError, _brreg_structured_api_url

BASE = "https://data.brreg.no/enhetsregisteret/api/enheter"
ORG = "100000008"
OTHER = "100000016"
PROFILE = "brreg_structured_api"


def batch_url(orgs=(ORG,), **kwargs):
    return BASE + "?" + urlencode({"organisasjonsnummer": ",".join(orgs), "size": len(orgs), **kwargs})


@pytest.mark.parametrize("orgs", [(ORG,), (ORG, OTHER), tuple(f"{i:09d}" for i in range(100))])
@pytest.mark.parametrize("encoded", [False, True])
def test_accepts_only_bounded_exact_batches(orgs, encoded):
    url = batch_url(orgs)
    if not encoded:
        url = url.replace("%2C", ",")
    assert _brreg_structured_api_url(url, "entity")
    assert _brreg_structured_api_url(url.replace("data.brreg.no", "data.brreg.no:443"), "entity")


@pytest.mark.parametrize("query", [
    "", f"organisasjonsnummer={ORG}", "size=1", "organisasjonsnummer=&size=0",
    f"organisasjonsnummer={ORG}&size=", f"organisasjonsnummer={ORG}&size=2",
    f"organisasjonsnummer={ORG}&size=01", f"organisasjonsnummer={ORG}&size=+1",
    f"organisasjonsnummer={ORG}&size=1.0", f"organisasjonsnummer={ORG}&size=１",
    f"organisasjonsnummer={ORG}&size=1&size=1",
    f"organisasjonsnummer={ORG}&organisasjonsnummer={OTHER}&size=2",
    f"organisasjonsnummer={ORG}&size=1&page=0", f"organisasjonsnummer={ORG}&size=1&sort=navn",
    f"organisasjonsnummer={ORG}&size=1&extra=", f"organisasjonsnummer={ORG}&size=1&",
    f"organisasjonsnummer={ORG},{ORG}&size=2", f"organisasjonsnummer={ORG},&size=2",
    f"organisasjonsnummer=,{ORG}&size=2", f"organisasjonsnummer={ORG};{OTHER}&size=2",
    "organisasjonsnummer=12345678&size=1", "organisasjonsnummer=1234567890&size=1",
    "organisasjonsnummer=１２３４５６７８９&size=1", "organisasjonsnummer=١٢٣٤٥٦٧٨٩&size=1",
    f"organisasjonsnummer=%20{ORG}&size=1", f"organisasjonsnummer={ORG}%00&size=1",
    "organisasjonsnummer=%FF&size=1", f"organisasjonsnummer={ORG}&size=1;page=0",
    urlencode({"organisasjonsnummer": ",".join(f"{i:09d}" for i in range(101)), "size": 101}),
])
def test_rejects_unbounded_or_ambiguous_queries(query):
    url = BASE + "?" + query
    assert not _brreg_structured_api_url(url, "entity")
    gateway = NetworkGateway(Transport([]), retries=0)
    with pytest.raises(NetworkPolicyError):
        asyncio.run(gateway.fetch(url, purpose="entity", access_profile=PROFILE))
    assert gateway.ledger.physical_requests == 0


INVALID_URLS = [
    batch_url().replace("https:", "http:"), batch_url().replace("data.brreg.no", "other.example"),
    batch_url().replace("data.brreg.no", "data.brreg.no.evil.example"),
    batch_url().replace("data.brreg.no", "data.brreg.no."),
    batch_url().replace("data.brreg.no", "data.brreg.no:8443"),
    batch_url().replace("data.brreg.no", "data.brreg.no:invalid"),
    batch_url().replace("data.brreg.no", "user@data.brreg.no"),
    batch_url().replace("data.brreg.no", "@data.brreg.no"),
    batch_url().replace("data.brreg.no", ":@data.brreg.no"),
    batch_url().replace("enheter?", "enheter/?"), batch_url().replace("enheter?", "%65nheter?"),
    batch_url() + "#fragment", batch_url() + "#", "\n" + batch_url(),
    batch_url().replace("data.brreg.no", "data.brreg.\nno"),
]


@pytest.mark.parametrize("url", INVALID_URLS)
def test_rejects_nonexact_urls_before_canonicalization(url):
    assert not _brreg_structured_api_url(url, "entity")
    gateway = NetworkGateway(Transport([]), retries=0)
    with pytest.raises(NetworkPolicyError):
        asyncio.run(gateway.fetch(url, purpose="entity", access_profile=PROFILE))
    assert gateway.ledger.physical_requests == 0


@pytest.mark.parametrize("purpose", ["accounts", "roles", "group", "subunits", "subunits_page", "page", "robots"])
def test_collection_is_entity_only(purpose):
    assert not _brreg_structured_api_url(batch_url(), purpose)


class Transport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def request(self, url, headers, timeout):
        self.calls.append(url)
        assert self.replies, f"unexpected request: {url}"
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, response_headers, body = reply
        return status, response_headers, body, url


@pytest.fixture
def gateway_factory(monkeypatch):
    monkeypatch.setattr("signalpost.network.validate_public_host", lambda *args, **kwargs: ("195.43.63.68",))

    def create(replies):
        transport = Transport(replies)
        return NetworkGateway(transport, retries=0), transport

    return create


@pytest.mark.parametrize("robots", [(503, {}, b""), OSError("offline robots")])
def test_structured_batch_survives_only_robots_outage(gateway_factory, robots):
    gateway, transport = gateway_factory([robots, (200, {}, b'{"_embedded":{"enheter":[]}}')])
    result = asyncio.run(gateway.fetch(batch_url(), purpose="entity", access_profile=PROFILE,
                                      allowed_hosts={"data.brreg.no"}))
    assert result[-1] == "ok"
    assert transport.calls == ["https://data.brreg.no/robots.txt", batch_url()]
    assert gateway.ledger.physical_requests == 2


@pytest.mark.parametrize("robots,profile,outcome", [
    ((200, {}, b"User-agent: *\nDisallow: /enhetsregisteret/api/enheter"), PROFILE, "robots_disallowed"),
    ((403, {}, b""), PROFILE, "robots_unusable"),
    ((503, {}, b""), None, "robots_unreachable"),
])
def test_explicit_disallow_and_normal_fail_closed_remain(gateway_factory, robots, profile, outcome):
    gateway, transport = gateway_factory([robots])
    result = asyncio.run(gateway.fetch(batch_url(), purpose="entity", access_profile=profile))
    assert result[-1] == outcome
    assert transport.calls == ["https://data.brreg.no/robots.txt"]


@pytest.mark.parametrize("destination", [batch_url() + "&page=1", batch_url() + "#fragment",
    "#", batch_url().replace("data.brreg.no", "data.brreg.\nno"),
    batch_url().replace("data.brreg.no", "data.brreg.no."), BASE,
    "https://other.example/enhetsregisteret/api/enheter?organisasjonsnummer=100000008&size=1"])
def test_redirect_cannot_expand_batch_profile(gateway_factory, destination):
    gateway, transport = gateway_factory([(503, {}, b""), (302, {"Location": destination}, b"")])
    with pytest.raises(NetworkPolicyError):
        asyncio.run(gateway.fetch(batch_url(), purpose="entity", access_profile=PROFILE))
    assert len(transport.calls) == 2


def test_existing_individual_profiles_still_apply():
    for path, purpose in [(f"enheter/{ORG}", "entity"), (f"enheter/{ORG}/roller", "roles"),
                          (f"konsernstruktur/{ORG}", "group"),
                          (f"underenheter?overordnetEnhet={ORG}", "subunits")]:
        assert _brreg_structured_api_url("https://data.brreg.no/enhetsregisteret/api/" + path, purpose)
    assert _brreg_structured_api_url(f"https://data.brreg.no/regnskapsregisteret/regnskap/{ORG}", "accounts")
    assert not _brreg_structured_api_url(BASE, "entity")


def test_preload_uses_profile_with_real_gateway_and_retains_provenance(gateway_factory):
    payload = json.dumps({"_embedded": {"enheter": [{"organisasjonsnummer": ORG}]}}).encode()
    gateway, transport = gateway_factory([(503, {}, b""), (200, {}, payload)])
    loaded = asyncio.run(preload_entity_batch([ORG], gateway, datetime.now(timezone.utc)))
    assert loaded[ORG].payload == payload
    assert loaded[ORG].source_url == transport.calls[-1]
    assert loaded[ORG].json_pointer == "/_embedded/enheter/0"
    assert gateway.ledger.physical_requests == 2


def test_valid_collection_redirect_remains_allowed(gateway_factory):
    destination = f"?size=1&organisasjonsnummer={ORG}"
    gateway, transport = gateway_factory([(503, {}, b""),
        (302, {"Location": destination}, b""), (200, {}, b"{}")])
    result = asyncio.run(gateway.fetch(batch_url(), purpose="entity", access_profile=PROFILE))
    assert result[-1] == "ok"
    assert transport.calls[-1] == BASE + destination
    assert gateway.ledger.physical_requests == 3


def test_explicit_robots_disallow_also_applies_after_valid_redirect(gateway_factory):
    destination = batch_url((OTHER,))
    rules = f"User-agent: *\nDisallow: /enhetsregisteret/api/enheter?organisasjonsnummer={OTHER}&size=1\n"
    gateway, transport = gateway_factory([(200, {}, rules.encode()),
        (302, {"Location": destination}, b"")])
    result = asyncio.run(gateway.fetch(batch_url(), purpose="entity", access_profile=PROFILE))
    assert result[-1] == "robots_disallowed"
    assert transport.calls == ["https://data.brreg.no/robots.txt", batch_url()]
