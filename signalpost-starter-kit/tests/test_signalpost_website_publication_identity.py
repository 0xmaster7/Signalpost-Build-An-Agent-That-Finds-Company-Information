import asyncio
from datetime import datetime, timezone

import pytest

from signalpost import run
from signalpost.models import Envelope, InputRow, PublicState
from signalpost.websites import (WebsiteResearchResult, _append_website_claim, _make_claim,
    _parse_page, research_company)


ORG = "987974249"


def claim(value="Storage racks"):
    page = _parse_page("https://example.no/products", 200, {"Content-Type": "text/html"},
        b"<html><body><h1>Storage racks</h1></body></html>", "https://example.no/products")
    return _make_claim(ORG, "product_or_service_heading", value, page, "page-evidence")


def test_repeated_semantic_claim_preserves_all_provenance_without_duplicate_ids():
    output = WebsiteResearchResult()
    first = claim()
    second = first.model_copy(update={"value": "ＳＴＯＲＡＧＥ RACKS", "evidence_ids": ["other-evidence"],
        "source_snapshot_ids": ["other-source"]})
    _append_website_claim(output, first)
    _append_website_claim(output, second)
    assert len(output.claims) == 1 and output.claims[0].value == "Storage racks"
    assert set(output.claims[0].evidence_ids) == {"page-evidence", "other-evidence"}
    assert "other-source" in output.claims[0].source_snapshot_ids


def test_conflicting_identifier_collision_is_not_silently_discarded():
    output = WebsiteResearchResult()
    first = claim()
    _append_website_claim(output, first)
    for changed in (first.model_copy(update={"value": "Different service"}),
            first.model_copy(update={"scope": "group"})):
        with pytest.raises(ValueError, match="conflicting semantics"):
            _append_website_claim(output, changed)
    assert len(output.claims) == 1


def test_repeated_shallow_phase_keeps_claim_identifiers_unique():
    html = ('<html><head><title>Example AS</title><script type="application/ld+json">'
        '{"@type":"Organization","legalName":"Example AS","identifier":"' + ORG + '"}'
        '</script></head><body><footer>Example AS</footer></body></html>').encode()

    class Gateway:
        def set_rate_limit(self, *args):
            pass

        async def robots_decision(self, *args, **kwargs):
            return "allowed", None

        async def fetch(self, url, **kwargs):
            return (200, {"Content-Type": "text/html"}, html, url, "ok") if url == "https://example.no/" else (404, {}, b"", url, "ok")

    async def check():
        profile = {"organisation_number": ORG, "name": "Example AS", "website_candidates": ["https://example.no/"]}
        gateway = Gateway()
        result = await research_company(profile, gateway, enable_keyless=False, phase="verify")
        for phase in ("shallow", "shallow", "jobs"):
            result = await research_company(profile, gateway, enable_keyless=False, phase=phase, previous=result)
            assert len(result.claims) == len({item.claim_id for item in result.claims})
        assert any(item.field == "verified_website_url" for item in result.claims)

    asyncio.run(check())


def test_invalid_optional_publication_retains_valid_official_envelope():
    row = InputRow(input_ref="one", row_number=1, organisation_number=ORG)
    cutoff = datetime.now(timezone.utc)
    envelope = run._envelope(row, {ORG: {"organisation_number": ORG, "name": "Example AS"}}, "test", cutoff, {})
    before = [item.model_dump() for item in envelope.claims]
    duplicate = envelope.claims[0].model_copy(deep=True)
    result = WebsiteResearchResult(claims=[duplicate, duplicate], state=PublicState.AVAILABLE)
    retained = run._merge_optional_website_result(envelope, result)
    assert [item.model_dump() for item in retained.claims] == before
    assert [item.model_dump() for item in envelope.claims] == before
    assert retained.sections["website_owned_profiles"].state == PublicState.FAILED
    assert retained.errors[-1].code == "WEBSITE_PUBLICATION_GRAPH_REJECTED"
    Envelope.model_validate(retained.model_dump())
