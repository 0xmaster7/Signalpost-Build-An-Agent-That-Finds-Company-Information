from __future__ import annotations

import asyncio
import unittest

from signalpost.discovery import (
    MockSearchProvider, SearchHit, SearchQuery, SearchResponse,
    build_search_queries, discover_with_provider, normalize_search_hits,
)
from signalpost.websites import research_company


ORG = "123456789"
LEGAL = "ÆØÅ Industri AS"


class EmptyGateway:
    class Ledger:
        physical_requests = 0
        logical_requests = 0
    def __init__(self, pages=None):
        self.ledger = self.Ledger()
        self.pages = pages or {}
    def set_rate_limit(self, host, rate):
        pass
    async def robots_decision(self, url, user_agent, *, allowed_hosts=None):
        return "allowed", None
    async def fetch(self, url, *, purpose, user_agent, max_bytes, allowed_hosts):
        self.ledger.logical_requests += 1
        self.ledger.physical_requests += 1
        status, headers, body = self.pages.get(url, (404, {"Content-Type": "text/plain"}, b""))
        return status, headers, body[:max_bytes], url, "received"


class SearchDiscoveryTests(unittest.TestCase):
    def test_query_order_uses_only_exact_org_legal_name_and_verified_brand(self):
        queries = build_search_queries(organisation_number=ORG, legal_name=LEGAL,
            municipality="Oslo", verified_public_brand="A verified brand")
        self.assertEqual([query.query_id for query in queries], [
            "org_and_legal_name", "legal_name_and_municipality", "verified_brand_and_municipality"])
        self.assertIn(ORG, queries[0].text)
        self.assertIn("A verified brand", queries[2].text)
        self.assertEqual(len(build_search_queries(organisation_number=ORG, legal_name=LEGAL)), 1)

    def test_search_hit_reduces_to_safe_candidate_metadata_not_snippet_or_title(self):
        query = SearchQuery("org_and_legal_name", f'"{ORG}" "{LEGAL}"', ORG)
        response = SearchResponse((
            SearchHit("https://example.no", "r1", 1, "Factual title", f"ORG {ORG}; revenue 9000000"),
            SearchHit("http://127.0.0.1/secret", "r2", 2, "Unsafe", "snippet"),
            SearchHit("https://directory.example.com/listing", "r3", 3, "Directory", ""),
        ), "fixture", "v1", 1, 4.2, response_sha256="a" * 64)
        candidates = normalize_search_hits(query, response)
        self.assertEqual(len(candidates), 2)
        serialized = repr([candidate.as_website_candidate() for candidate in candidates])
        self.assertNotIn("9000000", serialized)
        self.assertNotIn("Factual title", serialized)
        self.assertNotIn("127.0.0.1", serialized)
        self.assertEqual(candidates[0].as_website_candidate()["source"], "search_provider")

    def test_provider_without_rights_or_reproducibility_is_never_called(self):
        provider = MockSearchProvider({"org_and_legal_name": (SearchHit("https://example.no", "r1", 1),)},
                                      rights_approved=False)
        queries = [SearchQuery("org_and_legal_name", "query", ORG)]
        candidates, audit = asyncio.run(discover_with_provider(provider, queries, EmptyGateway()))
        self.assertEqual(candidates, [])
        self.assertEqual(provider.calls, [])
        self.assertEqual(audit["status"], "provider_not_eligible")
        self.assertEqual(audit["physical_requests"], 0)

    def test_paid_provider_is_not_called_without_an_explicit_cost_cap(self):
        provider = MockSearchProvider({}, rights_approved=True, cost_per_query_usd="0.01")
        query = SearchQuery("org_and_legal_name", "query", ORG)
        candidates, audit = asyncio.run(discover_with_provider(provider, [query], EmptyGateway()))
        self.assertEqual(candidates, [])
        self.assertEqual(provider.calls, [])
        self.assertEqual(audit["status"], "provider_cost_cap_exceeded")

    def test_no_configured_provider_falls_back_to_bounded_keyless_candidate(self):
        query = SearchQuery("org_and_legal_name", f'"{ORG}" "{LEGAL}"', ORG)
        candidates, audit = asyncio.run(discover_with_provider(None, [query], EmptyGateway()))
        self.assertEqual(candidates, [])
        self.assertEqual(audit["status"], "disabled_no_provider")
        html = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><footer>{LEGAL}</footer></body></html>'''
        gateway = EmptyGateway({"https://aeoa-industri.no/": (200, {"Content-Type": "text/html"}, html.encode())})
        result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL}, gateway))
        self.assertEqual(result.audit["candidates"][0]["source"], "keyless_no")
        self.assertEqual(result.audit["candidates"][0]["decision"], "accepted")

    def test_mock_search_is_candidate_only_and_fetched_site_needs_exact_proof(self):
        query = SearchQuery("org_and_legal_name", f'"{ORG}" "{LEGAL}"', ORG)
        provider = MockSearchProvider({query.query_id: (
            SearchHit("https://example.no", "result-7", 1,
                "{LEGAL} is the exact company", f"Organisation number {ORG}; fact: annual turnover is 99m"),
        )}, rights_approved=True)
        candidates, audit = asyncio.run(discover_with_provider(provider, [query], EmptyGateway()))
        self.assertEqual(audit["physical_requests"], 0)
        self.assertEqual(audit["logical_requests"], 1)
        html = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><footer>{LEGAL}</footer></body></html>'''
        body = html.encode()
        gateway = EmptyGateway({"https://example.no/": (200, {"Content-Type": "text/html"}, body)})
        profile = {"organisation_number": ORG, "name": LEGAL,
            "discovery_candidates": [candidate.as_website_candidate() for candidate in candidates]}
        result = asyncio.run(research_company(profile, gateway, enable_keyless=False))
        self.assertEqual(result.audit["candidates"][0]["discovery"]["result_id"], "result-7")
        self.assertTrue(any(claim.field == "verified_website_domain" for claim in result.claims))
        evidence = {item.evidence_id: item for item in result.evidence}
        for claim in result.claims:
            for evidence_id in claim.evidence_ids:
                self.assertNotEqual(evidence[evidence_id].extraction_method, "search_result")
                self.assertNotIn("annual turnover", evidence[evidence_id].excerpt or "")
        self.assertTrue(any(item.extraction_method == "audited_exact_site_identity_proof_v1" for item in result.evidence))

    def test_wrong_same_name_search_candidate_stays_unverified(self):
        query = SearchQuery("org_and_legal_name", f'"{ORG}" "{LEGAL}"', ORG)
        candidate = {"raw": "https://same-name.example.com", "source": "search_provider",
                     "discovery": {"provider_id": "fixture", "result_id": "same-name"}}
        html = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"987654321"}}</script></head></html>'''
        gateway = EmptyGateway({"https://same-name.example.com/": (200, {"Content-Type": "text/html"}, html.encode())})
        result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL,
            "discovery_candidates": [candidate]}, gateway, enable_keyless=False))
        self.assertFalse(result.claims)
        self.assertNotEqual(result.audit["candidates"][0]["decision"], "accepted")

    def test_search_candidate_requires_strong_subject_scoped_org_proof(self):
        candidate = {"raw": "https://candidate.example.com", "source": "search_provider",
                     "discovery": {"provider_id": "fixture", "result_id": "weak-proof"}}
        html = f"<html><head><title>{LEGAL}</title></head><body><address>{LEGAL}, Storgata 4, 0123 Oslo</address></body></html>"
        gateway = EmptyGateway({"https://candidate.example.com/": (200, {"Content-Type": "text/html"}, html.encode())})
        profile = {"organisation_number": ORG, "name": LEGAL,
                   "business_address": {"adresse": ["Storgata 4"], "postnummer": "0123", "kommune": "Oslo"},
                   "discovery_candidates": [candidate]}
        result = asyncio.run(research_company(profile, gateway, enable_keyless=False))
        self.assertFalse(result.claims)
        self.assertEqual(result.audit["candidates"][0]["decision"], "ambiguous")
        self.assertEqual(result.audit["candidates"][0]["review_reason"], "search_candidate_requires_subject_scoped_org_proof")

    def test_search_result_from_company_directory_never_promotes_owned_domain(self):
        candidate = {"raw": "https://proff.no/company/target", "source": "search_provider",
                     "discovery": {"provider_id": "fixture", "result_id": "directory-listing"}}
        html = f'''<html><head><title>{LEGAL} | Company Profile</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><main>{LEGAL}</main></body></html>'''
        gateway = EmptyGateway({"https://proff.no/company/target": (200, {"Content-Type": "text/html"}, html.encode())})
        result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL,
            "discovery_candidates": [candidate]}, gateway, enable_keyless=False))
        self.assertFalse(result.claims)
        self.assertEqual(result.audit["candidates"][0]["decision"], "ambiguous")
        self.assertEqual(result.audit["candidates"][0]["review_reason"], "search_candidate_is_directory_or_third_party_profile")

    def test_search_timeout_is_a_miss_and_uses_no_retry(self):
        class TimeoutProvider(MockSearchProvider):
            async def search(self, query, gateway, *, timeout_seconds):
                self.calls.append(query.query_id)
                raise TimeoutError()
        provider = TimeoutProvider({}, rights_approved=True)
        candidates, audit = asyncio.run(discover_with_provider(provider,
            [SearchQuery("org_and_legal_name", "query", ORG)], EmptyGateway()))
        self.assertEqual(candidates, [])
        self.assertEqual(audit["queries"][0]["status"], "timeout")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(audit["logical_requests"], 1)
        self.assertEqual(audit["physical_requests"], 0)

    def test_timeout_preserves_gateway_physical_request_accounting(self):
        class LedgerTimeoutProvider(MockSearchProvider):
            async def search(self, query, gateway, *, timeout_seconds):
                gateway.ledger.physical_requests += 1
                gateway.ledger.logical_requests += 1
                raise TimeoutError()
        gateway = EmptyGateway()
        provider = LedgerTimeoutProvider({}, rights_approved=True)
        _, audit = asyncio.run(discover_with_provider(provider,
            [SearchQuery("org_and_legal_name", "query", ORG)], gateway))
        self.assertEqual(audit["physical_requests"], 1)
        self.assertEqual(audit["logical_requests"], 1)
        self.assertEqual(gateway.ledger.physical_requests, 1)


if __name__ == "__main__":
    unittest.main()
