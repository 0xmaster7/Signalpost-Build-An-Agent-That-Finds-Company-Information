import asyncio
import json
from urllib.parse import parse_qs, urlsplit

from signalpost.public_discovery import wikidata_candidates
from signalpost.websites import research_company


ORG = "987974249"


class Gateway:
    def set_rate_limit(self, *args):
        pass

    async def robots_decision(self, *args, **kwargs):
        return "unreachable", None


def profile():
    return {"organisation_number": ORG, "name": "Example AS", "website_candidates": [{
        "raw": "https://example.no/", "source": "registry_live", "rights_status": "NLOD-2.0",
        "source_url": f"https://data.brreg.no/enhetsregisteret/api/enheter/{ORG}",
        "content_sha256": "a" * 64}]}


def test_registry_url_only_survives_unreachable_website_without_content_attribution():
    result = asyncio.run(research_company(profile(), Gateway(), enable_keyless=False, phase="verify"))
    assert [(claim.field, claim.value) for claim in result.claims] == [("registry_declared_website_url", "https://example.no/")]
    assert result.claims[0].field_family != "owned_web"
    assert result.phase_state["accepted_pages"] == []
    assert result.hiring_activity_state is None
    assert all(item.source_url.startswith("https://data.brreg.no/") for item in result.evidence)


def test_shared_registry_reference_never_promotes_owned_site():
    result = asyncio.run(research_company(profile(), Gateway(), shared_domains={"example.no"}, enable_keyless=False))
    assert [claim.field for claim in result.claims] == ["shared_website"]
    assert result.phase_state.get("accepted_pages", []) == []


def test_nonofficial_and_inferred_candidates_cannot_publish_registry_declarations():
    for source in ("registry_email", "workplace_contact", "wikidata", "keyless_no", "search_provider"):
        target = profile()
        target["website_candidates"][0]["source"] = source
        result = asyncio.run(research_company(target, Gateway(), enable_keyless=False))
        assert not result.claims
    target = profile()
    target["website_candidates"][0]["source_url"] = "https://untrusted.example/"
    assert not asyncio.run(research_company(target, Gateway(), enable_keyless=False)).claims


def test_wikidata_one_batch_request_candidate_only_and_bounded():
    class WikidataGateway:
        calls = []

        async def fetch(self, url, **kwargs):
            self.calls.append((url, kwargs))
            rows = [{"org": {"value": org}, "item": {"value": "http://www.wikidata.org/entity/Q1"},
                     "website": {"value": "https://example.no/"}} for org in (ORG, "111111111")]
            body = json.dumps({"results": {"bindings": rows}}).encode()
            return 200, {}, body, url, "ok"

    gateway = WikidataGateway()
    result, audit = asyncio.run(wikidata_candidates([ORG, ORG, 'bad" }'], gateway))
    assert len(gateway.calls) == 1
    assert set(result) == {ORG}
    query = parse_qs(urlsplit(gateway.calls[0][0]).query)["query"][0]
    assert query.count('"' + ORG + '"') == 1
    assert 'bad"' not in query
    assert audit["state"] == "completed"
    assert result[ORG][0]["source"] == "wikidata"
    assert not result[ORG][0].get("evidence_id")


def test_wikidata_outage_never_fabricates_candidates():
    class FailingGateway:
        async def fetch(self, *args, **kwargs):
            raise OSError("offline")

    result, audit = asyncio.run(wikidata_candidates([ORG], FailingGateway()))
    assert result == {} and audit["state"] == "failed"


def test_conflicting_identity_cannot_fall_back_to_a_registry_url():
    from signalpost.websites import WebsiteResearchResult, _publish_registry_references
    from datetime import datetime, timezone
    target = profile()
    candidate = {"url": "https://example.no/", "kind": "website", "source": "registry_live",
                 "source_ref": target["website_candidates"][0]}
    for decision, reason in (("rejected_conflicting_identity", ""), ("ambiguous", "conflicting_structured_company_identity")):
        result = WebsiteResearchResult(audit={"candidates": [{"url": candidate["url"], "decision": decision, "review_reason": reason}]})
        _publish_registry_references(ORG, [candidate], result, set(), datetime.now(timezone.utc), True)
        assert not result.claims


def test_historical_cutoff_cannot_publish_a_current_registry_declaration():
    from datetime import datetime, timezone
    target = profile()
    target["website_candidates"][0]["retrieved_at"] = "2026-10-26T00:00:00Z"
    result = asyncio.run(research_company(target, Gateway(), enable_keyless=False,
        evidence_cutoff=datetime(2026, 10, 17, tzinfo=timezone.utc)))
    assert not result.claims


def test_conflict_diagnostic_survives_later_identity_page_http_failure():
    class ConflictingGateway(Gateway):
        async def robots_decision(self, *args, **kwargs):
            return "allowed", None

        async def fetch(self, url, **kwargs):
            if url == "https://example.no/":
                body = ('<html><head><script type="application/ld+json">'
                    '{"@context":"https://schema.org","@type":"Organization","name":"Example AS",'
                    '"identifier":["987974249","111111111"]}</script></head>'
                    '<body><h1>Example AS</h1><a href="/about">About us</a></body></html>').encode()
                return 200, {"Content-Type": "text/html"}, body, url, "ok"
            return 404, {}, b"", url, "http_error"
    result = asyncio.run(research_company(profile(), ConflictingGateway(), enable_keyless=False, phase="verify"))
    assert not result.claims
    assert "conflict" in result.audit["candidates"][0]["review_reason"]
