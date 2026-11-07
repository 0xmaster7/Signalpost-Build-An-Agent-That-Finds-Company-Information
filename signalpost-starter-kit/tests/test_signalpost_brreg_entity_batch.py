"""Offline coverage of documented BRREG batch identity and response provenance."""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from signalpost.brreg import ACCOUNTS, BASE, fetch_company, preload_entity_batch
from signalpost.models import PublicState
from signalpost.network import _brreg_structured_api_url

NOW = datetime(2026, 11, 7, 9, 59, tzinfo=timezone.utc)
ORG = "100000008"
OTHER = "100000016"


def entity(org=ORG):
    return {"organisasjonsnummer": org, "navn": f"Company {org}",
            "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
            "hjemmeside": "https://example.org", "epostadresse": "office@example.org",
            "aktivitet": ["Consulting"], "historiskeNavn": [{"navn": "Old name"}],
            "konkurs": False, "antallAnsatte": 2,
            "forretningsadresse": {"kommune": "OSLO", "kommunenummer": "0301"}}


class Gateway:
    observed_at = NOW

    def __init__(self, batch_body=None, *, status=200, outcome="ok", final=None):
        self.batch_body = batch_body if batch_body is not None else {"_embedded": {"enheter": [entity()]}}
        self.status, self.outcome, self.final = status, outcome, final
        self.calls = []
        self.payload = None

    async def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if urlsplit(url).path == "/enhetsregisteret/api/enheter":
            if isinstance(self.batch_body, Exception):
                raise self.batch_body
            self.payload = (self.batch_body if isinstance(self.batch_body, bytes)
                            else json.dumps(self.batch_body, indent=2).encode())
            return self.status, {}, self.payload, self.final or url, self.outcome
        body = [] if url.startswith(ACCOUNTS) else entity(url.rsplit("/", 1)[1])
        return 200, {}, json.dumps(body).encode(), url, "ok"


def fetch(org, gateway, cutoff=NOW, **kwargs):
    return asyncio.run(fetch_company(org, gateway, cutoff, include_people=False, **kwargs))


def resolve(body, pointer):
    for key in pointer.removeprefix("/").split("/"):
        body = body[int(key)] if isinstance(body, list) else body[key]
    return body


def test_actual_response_provenance_and_all_entity_pointers():
    gateway = Gateway({"_embedded": {"enheter": [entity(OTHER), entity()]}})
    items = asyncio.run(preload_entity_batch([ORG, OTHER], gateway, NOW))
    result = fetch(ORG, gateway, include_accounts=False)
    assert len(gateway.calls) == 1
    item = items[ORG]
    assert item.payload == gateway.payload
    assert item.json_pointer == "/_embedded/enheter/1"
    digest = hashlib.sha256(gateway.payload).hexdigest()
    assert item.content_sha256 == digest
    for evidence in result.evidence:
        assert evidence.source_url == gateway.calls[0][0]
        assert evidence.content_sha256 == digest
        assert evidence.json_pointer.startswith(item.json_pointer + "/")
        assert resolve(item.response_body, evidence.json_pointer) is not None
    by_id = {e.evidence_id: e for e in result.evidence}
    for claim in result.claims:
        value = resolve(item.response_body, by_id[claim.evidence_ids[0]].json_pointer)
        assert claim.value == value
        assert str(claim.value) != f"Company {OTHER}"
    assert all(s.source_url == item.source_url and s.content_sha256 == digest for s in result.snapshots)
    assert result.terminal_state == PublicState.AVAILABLE


def test_foreign_missing_and_duplicate_rows_fall_back_to_single_entity():
    gateway = Gateway({"_embedded": {"enheter": [entity(OTHER), entity(), entity()]}})
    assert asyncio.run(preload_entity_batch([ORG, "100000024"], gateway, NOW)) == {}
    result = fetch(ORG, gateway, include_accounts=False)
    assert len(gateway.calls) == 2
    assert gateway.calls[-1][0] == f"{BASE}/enheter/{ORG}"
    assert next(c.value for c in result.claims if c.field == "name") == f"Company {ORG}"
    assert all(not e.json_pointer.startswith("/_embedded") for e in result.evidence)


@pytest.mark.parametrize("body,status,outcome,final", [
    (b"invalid", 200, "ok", None), ({"_embedded": {"enheter": {}}}, 200, "ok", None),
    ({}, 200, "ok", None), ({}, 429, "rate_limited", None),
    ({}, 200, "robots_disallowed", None), (OSError("offline"), 200, "ok", None),
    ({"_embedded": {"enheter": [entity()]}}, 200, "ok", "https://other.example/enheter"),
])
def test_unusable_batch_does_not_poison_single_entity_lookup(body, status, outcome, final):
    gateway = Gateway(body, status=status, outcome=outcome, final=final)
    assert asyncio.run(preload_entity_batch([ORG], gateway, NOW)) == {}
    result = fetch(ORG, gateway, include_accounts=False)
    assert len(gateway.calls) == 2
    assert result.terminal_state == PublicState.AVAILABLE


def test_chunking_deduplication_and_gateway_policy():
    gateway = Gateway({})
    orgs = [f"{100000000 + i:09d}" for i in range(201)]
    asyncio.run(preload_entity_batch([*orgs, orgs[0], "bad", None], gateway, NOW))
    assert len(gateway.calls) == 3
    for (url, kwargs), expected in zip(gateway.calls, (100, 100, 1)):
        query = parse_qs(urlsplit(url).query)
        assert len(query["organisasjonsnummer"][0].split(",")) == expected
        assert query["size"] == [str(expected)]
        assert kwargs["allowed_hosts"] == {"data.brreg.no"}
        assert kwargs["access_profile"] == "brreg_structured_api"
        assert _brreg_structured_api_url(url, "entity")


def test_accounts_stay_single_company_and_cached_entity_is_reusable():
    gateway = Gateway()
    asyncio.run(preload_entity_batch([ORG], gateway, NOW))
    fetch(ORG, gateway)
    fetch(ORG, gateway, include_accounts=False)
    assert [url for url, _ in gateway.calls[1:]] == [f"{ACCOUNTS}/{ORG}"]
    assert gateway.calls[1][1]["access_profile"] == "brreg_structured_api"


def test_mutated_row_identity_is_rechecked_before_cache_use():
    gateway = Gateway()
    items = asyncio.run(preload_entity_batch([ORG], gateway, NOW))
    items[ORG].response_body["_embedded"]["enheter"][0]["organisasjonsnummer"] = OTHER
    result = fetch(ORG, gateway, include_accounts=False)
    assert len(gateway.calls) == 2
    assert next(c.value for c in result.claims if c.field == "organisation_number") == ORG


def test_cutoff_gate_is_preserved_for_batch_observations():
    gateway = Gateway()
    asyncio.run(preload_entity_batch([ORG], gateway, NOW - timedelta(days=1)))
    strict = fetch(ORG, gateway, NOW - timedelta(days=1), include_accounts=False)
    assert strict.claims == []
    current = fetch(ORG, gateway, NOW - timedelta(days=1), include_accounts=False,
                    allow_current_identity_after_run_start=True)
    assert current.claims


@pytest.mark.parametrize("size", [0, 101, True, 1.5])
def test_invalid_chunk_size(size):
    with pytest.raises(ValueError):
        asyncio.run(preload_entity_batch([ORG], Gateway(), NOW, chunk_size=size))
