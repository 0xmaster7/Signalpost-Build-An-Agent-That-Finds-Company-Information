from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from signalpost.models import PublicState
from signalpost.network import NetworkPolicyError
from signalpost.brreg import fetch_company
from signalpost import run as run_module
from signalpost.websites import (
    MAX_ABSOLUTE_PAGES, MAX_DEFAULT_PAGES, MAX_DEPTH, MAX_INITIAL_PAGES, MAX_SITE_BYTES,
    PageRecord, _parse_page, _parse_sitemap, _profile_links, keyless_no_candidate,
    normalize_name, research_company, sanitize_registry_websites,
    verify_site_pages,
)


ORG = "123456789"
LEGAL = "ÆØÅ Industri AS"


def page(html: str, url: str = "https://example.no/") -> PageRecord:
    return _parse_page(url, 200, {"Content-Type": "text/html; charset=utf-8"}, html.encode(), url)


class Ledger:
    def __init__(self):
        self.physical_requests = 0
        self.logical_requests = 0
        self.entries = []


class FakeGateway:
    def __init__(self, pages: dict[str, tuple[int, dict[str, str], bytes]], robots_state="allowed", robots_error=None, fetch_error=None, crawl_delay=None):
        self.pages = pages
        self.ledger = Ledger()
        self.rates = {}
        self.robots_state = robots_state
        self.robots_error = robots_error
        self.fetch_error = fetch_error
        self.crawl_delay = crawl_delay

    def set_rate_limit(self, host: str, rate: float) -> None:
        self.rates[host] = rate

    async def robots_decision(self, url: str, user_agent: str, *, allowed_hosts=None):
        if self.robots_error:
            raise self.robots_error
        return self.robots_state, self.crawl_delay

    async def fetch(self, url: str, *, purpose, user_agent, max_bytes, allowed_hosts):
        if self.fetch_error:
            raise self.fetch_error
        self.ledger.logical_requests += 1
        self.ledger.physical_requests += 1
        status, headers, body = self.pages.get(url, (404, {"Content-Type": "text/plain"}, b""))
        self.ledger.entries.append(type("Entry", (), {"purpose": purpose, "url": url, "status": status, "outcome": "received"})())
        return status, headers, body[:max_bytes], url, "received"


class WebsiteIdentityTests(unittest.TestCase):
    def profile(self, **extra):
        return {"organisation_number": ORG, "name": LEGAL, "business_address": {
            "adresse": ["Storgata 4"], "postnummer": "0123", "kommune": "Oslo"}, **extra}

    def test_name_normalization_preserves_norwegian_letters_and_legal_suffix(self):
        self.assertEqual(normalize_name("  ÆØÅ  Industri, A.S. "), "æøå industri")
        self.assertEqual(normalize_name("ÆØÅ Industri"), normalize_name(LEGAL))

    def test_sanitizer_handles_missing_scheme_multiple_values_and_social_urls(self):
        candidates = sanitize_registry_websites("www.firma.no, https://firma.com/path; linkedin.com/company/firma")
        self.assertEqual([item["kind"] for item in candidates], ["website", "website", "profile"])
        self.assertEqual(candidates[0]["url"], "https://www.firma.no/")
        self.assertEqual(candidates[-1]["platform"], "linkedin")

    def test_sanitizer_rejects_email_credentials_and_unsafe_hostnames(self):
        self.assertEqual(sanitize_registry_websites("kontakt@example.no"), [])
        self.assertEqual(sanitize_registry_websites("https://user:pass@example.no/"), [])
        self.assertEqual(sanitize_registry_websites("http://localhost/"), [])

    def test_keyless_candidate_requires_distinctive_name(self):
        self.assertIsNone(keyless_no_candidate("Oslo Kommune AS"))
        self.assertEqual(keyless_no_candidate("ÆØÅ Industri Teknologi AS"), "https://aeoa-industri-teknologi.no/")

    def test_exact_structured_org_and_legal_name_accept(self):
        doc = page(f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@context":"https://schema.org","@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><footer>{LEGAL}</footer></body></html>''')
        result = verify_site_pages(self.profile(), [doc])
        self.assertEqual(result["decision"], "accepted")
        self.assertEqual(result["proof"]["method"], "subject_scoped_structured_org_number")

    def test_structured_identity_rejects_multiple_distinct_ids_but_normalizes_duplicates(self):
        cases = [
            ('target only', [ORG], "accepted"),
            ('rival only', ["987654321"], "rejected"),
            ('target and rival', [ORG, "987654321"], "ambiguous"),
            ('duplicate target', [ORG, ORG], "accepted"),
            ('formatted target duplicate', [ORG, "123 456 789"], "accepted"),
            ('multiple rival ids', [ORG, "987654321", "923609016"], "ambiguous"),
        ]
        for label, identifiers, expected in cases:
            with self.subTest(label=label):
                node = {"@type": "Organization", "legalName": LEGAL, "identifier": identifiers}
                doc = page(f'<title>Welcome</title><script type="application/ld+json">{json.dumps(node)}</script>')
                self.assertEqual(verify_site_pages(self.profile(), [doc])["decision"], expected)

    def test_nested_customer_does_not_conflict_with_exact_page_owner(self):
        node = {"@type": "Organization", "legalName": LEGAL, "identifier": ORG,
                "customer": {"@type": "Organization", "legalName": "Customer Rival AS", "identifier": "987654321"}}
        doc = page(f'<title>Welcome</title><script type="application/ld+json">{json.dumps(node)}</script>')
        self.assertEqual(verify_site_pages(self.profile(), [doc])["decision"], "accepted")

    def test_incidental_service_provider_footer_is_not_target_site_proof(self):
        doc = page('<title>Welcome</title><h1>Welcome</h1><footer>Rival AS org.nr. 987654321. '
                   'Website designed by ÆØÅ Industri AS org.nr. 123456789.</footer>',
                   "https://rival.example.no/")
        result = verify_site_pages(self.profile(), [doc])
        self.assertNotEqual(result["decision"], "accepted")

    def test_longer_company_name_cannot_borrow_target_registered_address(self):
        profile = {"organisation_number": "923609016", "name": "Acme AS", "registered_address": {
            "adresse": ["Main Street 1"], "postnummer": "0123", "kommune": "Oslo"}}
        doc = page("<title>Acme Services AS</title><h1>Acme Services AS</h1>"
            "<address>Main Street 1, 0123 Oslo</address>", "https://acme-services.example.no/")
        self.assertNotEqual(verify_site_pages(profile, [doc])["decision"], "accepted")

    def test_org_number_in_customer_context_is_not_identity(self):
        doc = page(f"<html><head><title>{LEGAL}</title></head><body><footer>Our customer {LEGAL}, organisation number {ORG}</footer></body></html>")
        result = verify_site_pages(self.profile(), [doc])
        self.assertNotEqual(result["decision"], "accepted")

    def test_org_number_outside_subject_scoped_blocks_is_not_identity(self):
        doc = page(f"<html><head><title>Welcome</title></head><body><main>Customer number {ORG}</main><footer>Independent business</footer></body></html>")
        self.assertEqual(verify_site_pages(self.profile(), [doc])["decision"], "ambiguous")

    def test_name_only_and_wrong_company_same_name_do_not_accept(self):
        doc = page(f"<html><head><title>{LEGAL}</title><script type='application/ld+json'>{{\"@type\":\"Organization\",\"name\":\"{LEGAL}\",\"identifier\":\"987654321\"}}</script></head></html>")
        self.assertEqual(verify_site_pages(self.profile(), [doc])["decision"], "rejected")
        self.assertEqual(verify_site_pages(self.profile(), [page(f'<title>{LEGAL}</title>')])["decision"], "ambiguous")

    def test_registry_exact_name_address_can_accept_but_keyless_needs_role(self):
        html = f"<html><head><title>{LEGAL}</title></head><body><address>{LEGAL}, Storgata 4, 0123 Oslo</address></body></html>"
        doc = page(html)
        self.assertEqual(verify_site_pages(self.profile(), [doc], candidate_source="registry_live")["decision"], "accepted")
        self.assertEqual(verify_site_pages(self.profile(), [doc], candidate_source="keyless_no")["decision"], "ambiguous")
        role_profile = self.profile(registered_roles=["Daglig leder: Kari Nordmann"])
        self.assertEqual(verify_site_pages(role_profile, [page(html + '<footer>Daglig leder: Kari Nordmann</footer>')], candidate_source="keyless_no")["decision"], "accepted")

    def test_keyless_no_org_acceptance_requires_address_and_company_contact_signal(self):
        html = f'<html><head><title>{LEGAL}</title></head><body><address>{LEGAL}, Storgata 4, 0123 Oslo</address><a href="mailto:post@example.no">Contact</a></body></html>'
        contact = page(html, "https://example.no/contact")
        result = verify_site_pages(self.profile(), [contact], candidate_source="keyless_no")
        self.assertEqual(result["decision"], "accepted")
        self.assertEqual(result["proof"]["method"], "legal_name_address_official_contact")
        self.assertEqual(verify_site_pages(self.profile(), [page(html.replace('<a href="mailto:post@example.no">Contact</a>', ''), "https://example.no/contact")], candidate_source="keyless_no")["decision"], "ambiguous")

    def test_wrong_postcode_does_not_match_exact_registered_address(self):
        doc = page(f"<title>{LEGAL}</title><address>{LEGAL}, Storgata 4, 0999 Oslo</address>")
        self.assertEqual(verify_site_pages(self.profile(), [doc])["decision"], "ambiguous")

    def test_shared_group_homepage_requires_target_subject_proof(self):
        html = f"<html><head><title>{LEGAL}</title></head><body><footer>{LEGAL}, Storgata 4, 0123 Oslo</footer></body></html>"
        self.assertEqual(verify_site_pages(self.profile(), [page(html)], shared_domain=True)["decision"], "ambiguous")
        with_org = page(f'''<html><head><title>Group</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body></body></html>''')
        self.assertEqual(verify_site_pages(self.profile(), [with_org], shared_domain=True)["decision"], "accepted")

    def test_group_legal_schema_blocks_incidental_subsidiary_footer_on_homepage(self):
        html = f'''<html><head><script type="application/ld+json">{{"@type":"Organization","legalName":"Example Group AS","identifier":"987654321"}}</script></head><body><footer>{LEGAL}, Storgata 4, 0123 Oslo</footer></body></html>'''
        self.assertNotEqual(verify_site_pages(self.profile(), [page(html)], candidate_source="registry_frozen")["decision"], "accepted")

    def test_conflicting_company_schema_on_page_blocks_acceptance(self):
        doc = page(f'''<html><head><script type="application/ld+json">[{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}},{{"@type":"Organization","name":"Other AS","identifier":"987654321"}}]</script></head><body><footer>{LEGAL}</footer></body></html>''')
        self.assertEqual(verify_site_pages(self.profile(), [doc])["decision"], "ambiguous")

    def test_sitemap_urls_are_discovery_data_without_dates(self):
        urls, indexes = _parse_sitemap(b'<urlset><url><loc>https://example.no/about</loc><lastmod>2099-01-01</lastmod></url></urlset>')
        self.assertEqual(urls, ["https://example.no/about"])
        self.assertEqual(indexes, [])

    def test_same_as_social_from_unrelated_schema_subject_is_not_promoted(self):
        doc = page('<html><head><script type="application/ld+json">{"@type":"Organization","name":"Other AS","identifier":"987654321","sameAs":"https://www.linkedin.com/company/other"}</script></head></html>')
        self.assertEqual(_profile_links(doc, ORG), [])

    def test_key_caps_are_explicit_and_bounded(self):
        self.assertEqual((MAX_INITIAL_PAGES, MAX_DEFAULT_PAGES, MAX_ABSOLUTE_PAGES, MAX_DEPTH, MAX_SITE_BYTES), (6, 10, 25, 2, 8 * 1024 * 1024))

    def test_live_crawl_obeys_default_page_request_cap(self):
        links = "".join(f'<a href="https://example.no/about/{i}">About {i}</a>' for i in range(20))
        home = f'''<html><head><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><footer>{LEGAL}</footer>{links}</body></html>'''
        pages = {"https://example.no/": (200, {"Content-Type": "text/html"}, home.encode())}
        for index in range(20):
            body = f"<html><head><title>About {index}</title></head><body><h1>Service {index}</h1><p>Service description with enough content for extraction.</p></body></html>".encode()
            pages[f"https://example.no/about/{index}"] = (200, {"Content-Type": "text/html"}, body)
        gateway = FakeGateway(pages)
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=["https://example.no"]), gateway, enable_keyless=False))
        self.assertLessEqual(result.audit["page_requests"], MAX_ABSOLUTE_PAGES)
        self.assertLessEqual(result.audit["page_count"], MAX_DEFAULT_PAGES)
        self.assertLessEqual(len(result.audit["pages"]), MAX_DEFAULT_PAGES)
        self.assertLessEqual(len(result.audit["pages"]), MAX_DEFAULT_PAGES)

    def test_integration_only_publishes_after_exact_proof_and_cites_proof(self):
        html = f'''<html><head><title>{LEGAL}</title><meta name="description" content="A specialist industrial company with a public verified website description."><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><footer>{LEGAL}</footer><a href="https://www.linkedin.com/company/example">LinkedIn</a></body></html>'''
        body = html.encode()
        gateway = FakeGateway({"https://example.no/": (200, {"Content-Type": "text/html"}, body)})
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=[{
            "raw": "https://example.no", "source": "registry_live", "rights_status": "NLOD-2.0", "source_url": "https://registry.example/row",
            "content_sha256": hashlib.sha256(b"registry-row").hexdigest(), "evidence_id": "candidate-evidence",
            "source_snapshot_id": "candidate-snapshot"}]), gateway))
        self.assertTrue(any(claim.field == "verified_website_domain" for claim in result.claims))
        self.assertTrue(any(claim.field == "company_owned_profile" for claim in result.claims))
        proof_ids = {item.evidence_id for item in result.evidence if item.extraction_method == "audited_exact_site_identity_proof_v1"}
        self.assertTrue(proof_ids)
        for claim in result.claims:
            self.assertTrue(set(claim.evidence_ids) <= {item.evidence_id for item in result.evidence})
            self.assertTrue(set(claim.source_snapshot_ids) <= {item.source_id for item in result.snapshots})
            if claim.field.startswith("verified_website") or claim.field == "company_owned_profile":
                self.assertTrue(set(claim.evidence_ids) & proof_ids)
        self.assertGreaterEqual(gateway.ledger.physical_requests, 1)

    def test_brreg_homepage_field_stays_candidate_only(self):
        class RegistryGateway:
            def __init__(self):
                self.ledger = Ledger()

            async def fetch(self, url, *, purpose, **kwargs):
                self.ledger.logical_requests += 1
                self.ledger.physical_requests += 1
                self.ledger.entries.append(type("Entry", (), {"purpose": purpose, "url": url, "status": 200, "outcome": "received"})())
                if purpose == "entity":
                    body = json.dumps({"organisasjonsnummer": ORG, "navn": LEGAL,
                        "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"}, "hjemmeside": "example.no"}).encode()
                elif purpose == "subunits":
                    body = b'{"_embedded":{"underenheter":[]},"page":{"number":0,"totalPages":1}}'
                else:
                    body = b"[]"
                return 200, {"Content-Type": "application/json"}, body, url, "ok"

        result = __import__("asyncio").run(fetch_company(ORG, RegistryGateway(), datetime.now(timezone.utc) + timedelta(days=1)))
        self.assertEqual(result.observations["website_candidates"][0]["source"], "registry_live")
        self.assertTrue(result.observations["website_candidates"][0]["evidence_id"])
        self.assertFalse(any(claim.field == "website" for claim in result.claims))
        self.assertFalse(any(claim.field == "verified_website_url" for claim in result.claims))

    def test_frozen_enk_private_registration_addresses_are_not_used_for_identity(self):
        profile = run_module._website_profile("923609016", frozen={"organisation_number": "923609016", "name": "Owner Name ENK",
            "legal_form": "ENK", "business_address": {"adresse": ["Private Home 1"], "postnummer": "0123", "kommune": "Oslo"},
            "postal_address": {"adresse": ["Private Box"]}}, frozen_sha="a" * 64)
        self.assertIsNone(profile["business_address"])
        self.assertIsNone(profile["postal_address"])

    def test_cli_merges_verified_website_claims_into_the_canonical_envelope(self):
        org = "923609016"
        name = "Integration Target AS"
        html = f'''<html><head><script type="application/ld+json">{{"@type":"Organization","legalName":"{name}","identifier":"{org}"}}</script></head><body><footer>{name}</footer><meta name="description" content="A verified company website description with enough detail for a useful profile."></body></html>'''
        gateway = FakeGateway({"https://example.no/": (200, {"Content-Type": "text/html"}, html.encode())})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            snapshot_path = root / "registry.jsonl"
            output_path = root / "output.jsonl"
            state_path = root / "state.sqlite"
            input_path.write_text(json.dumps({"organisation_number": org}) + "\n", encoding="utf-8")
            snapshot_path.write_text(json.dumps({"organisation_number": org, "name": name, "website": "https://example.no",
                "source_url": "https://registry.example/snapshot"}) + "\n", encoding="utf-8")
            with patch.object(run_module, "NetworkGateway", return_value=gateway):
                code = run_module.main(["--input", str(input_path), "--registry-snapshot", str(snapshot_path),
                    "--live-websites", "--output", str(output_path), "--state-output", str(state_path), "--batch-id", "m03-fixture"])
            envelope = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(code, 0)
            self.assertEqual(envelope["organisation_number"], org)
            self.assertEqual(envelope["sections"]["website_owned_profiles"]["state"], "available")
            self.assertTrue(any(claim["field"] == "verified_website_domain" for claim in envelope["claims"]))
            self.assertIn("website_research", envelope["synthesis"])
            self.assertFalse(any(snapshot["rights_status"] == "NLOD-2.0" and snapshot["source_url"] == "https://registry.example/snapshot"
                for snapshot in envelope["source_snapshots"]))

    def test_wrong_company_integration_emits_no_publication(self):
        html = b'<html><head><title>Other Company AS</title><script type="application/ld+json">{"@type":"Organization","name":"Other Company AS","identifier":"987654321"}</script></head></html>'
        gateway = FakeGateway({"https://example.no/": (200, {"Content-Type": "text/html"}, html)})
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=["https://example.no"]), gateway, enable_keyless=False))
        self.assertFalse(result.claims)
        self.assertNotEqual(result.state, PublicState.AVAILABLE)

    def test_split_json_ld_organization_nodes_never_form_exact_site_proof(self):
        html = f'''<html><head><title>Rival AS</title><script type="application/ld+json">{{"@graph":[
          {{"@type":"Organization","name":"Rival AS","identifier":"{ORG}"}},
          {{"@type":"Organization","legalName":"{LEGAL}"}}
        ]}}</script></head><body><footer>{LEGAL}</footer></body></html>'''
        gateway = FakeGateway({"https://example.no/": (200, {"Content-Type": "text/html"}, html.encode())})
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=["https://example.no"]), gateway, enable_keyless=False))
        self.assertFalse(result.claims)
        self.assertNotEqual(result.state, PublicState.AVAILABLE)

    def test_cli_split_json_ld_nodes_cannot_publish_target_domain(self):
        org = "923609016"
        name = "Integration Target AS"
        html = f'''<html><head><title>Rival AS</title><script type="application/ld+json">{{"@graph":[
          {{"@type":"Organization","name":"Rival AS","identifier":"{org}"}},
          {{"@type":"Organization","legalName":"{name}"}}
        ]}}</script></head><body><footer>{name}</footer></body></html>'''
        gateway = FakeGateway({"https://example.no/": (200, {"Content-Type": "text/html"}, html.encode())})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, snapshot_path = root / "input.jsonl", root / "registry.jsonl"
            output_path, state_path = root / "output.jsonl", root / "state.sqlite"
            input_path.write_text(json.dumps({"organisation_number": org}) + "\n", encoding="utf-8")
            snapshot_path.write_text(json.dumps({"organisation_number": org, "name": name, "website": "https://example.no"}) + "\n", encoding="utf-8")
            with patch.object(run_module, "NetworkGateway", return_value=gateway):
                code = run_module.main(["--input", str(input_path), "--registry-snapshot", str(snapshot_path),
                    "--live-websites", "--output", str(output_path), "--state-output", str(state_path), "--batch-id", "p0-jsonld"])
            envelope = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(code, 0)
        self.assertEqual(envelope["organisation_number"], org)
        self.assertNotEqual(envelope["sections"]["website_owned_profiles"]["state"], "available")
        self.assertFalse(any(claim["field"] in {"verified_website_url", "verified_website_domain"}
            for claim in envelope["claims"]))

    def test_multi_id_and_incidental_footer_cannot_publish_downstream_or_cli_claims(self):
        org = "923609016"
        name = "Integration Target AS"
        for label, html in (
            ("multi_id", f'''<html><head><title>Welcome</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{name}","identifier":["{org}","987654321"]}}</script></head><body><a href="/careers">Careers</a><a href="/news">News</a><script type="application/ld+json">{{"@type":"JobPosting","title":"Engineer","datePosted":"2026-09-20","validThrough":"2026-12-01","url":"/careers/engineer","hiringOrganization":{{"@type":"Organization","name":"{name}","identifier":"{org}"}}}}</script><script type="application/ld+json">{{"@type":"NewsArticle","headline":"{name} opens a new office","datePublished":"2026-09-20","url":"/news/office","about":{{"@type":"Organization","name":"{name}","identifier":"{org}"}}}}</script></body></html>'''),
            ("service_footer", f'''<html><head><title>Welcome</title></head><body><h1>Welcome</h1><footer>Rival AS org.nr. 987654321. Website designed by {name} org.nr. {org}.</footer><a href="/careers">Careers</a><script type="application/ld+json">{{"@type":"JobPosting","title":"Engineer","datePosted":"2026-09-20","url":"/careers/engineer","hiringOrganization":{{"@type":"Organization","name":"{name}","identifier":"{org}"}}}}</script></body></html>'''),
        ):
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                gateway = FakeGateway({"https://example.no/": (200, {"Content-Type": "text/html"}, html.encode())})
                profile = self.profile(organisation_number=org, name=name,
                    website_candidates=["https://example.no/"])
                research = __import__("asyncio").run(research_company(profile, gateway, enable_keyless=False))
                self.assertFalse(research.claims)
                root = Path(directory)
                input_path, snapshot_path = root / "input.jsonl", root / "registry.jsonl"
                output_path, state_path = root / "output.jsonl", root / "state.sqlite"
                input_path.write_text(json.dumps({"organisation_number": org}) + "\n", encoding="utf-8")
                snapshot_path.write_text(json.dumps({"organisation_number": org, "name": name,
                    "website": "https://example.no/"}) + "\n", encoding="utf-8")
                with patch.object(run_module, "NetworkGateway", return_value=gateway):
                    code = run_module.main(["--input", str(input_path), "--registry-snapshot", str(snapshot_path),
                        "--live-websites", "--output", str(output_path), "--state-output", str(state_path), "--batch-id", label])
                envelope = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
                self.assertEqual(code, 0)
                self.assertFalse(any(claim["section"] in {"website_owned_profiles", "hiring_activity"}
                    for claim in envelope["claims"]))

    def test_conflicting_visible_homepage_legal_identity_blocks_structured_target(self):
        html = f'''<html><head><title>Rival AS</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><h1>Rival AS</h1></body></html>'''
        gateway = FakeGateway({"https://example.no/": (200, {"Content-Type": "text/html"}, html.encode())})
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=["https://example.no"]), gateway, enable_keyless=False))
        self.assertFalse(result.claims)

    def test_frozen_website_candidate_row_hash_binds_to_whole_snapshot_hash(self):
        html = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><footer>{LEGAL}</footer></body></html>'''
        candidate = {"raw": "https://example.no/", "source": "registry_frozen",
            "source_url": "https://registry.example/snapshot", "content_sha256": "a" * 64,
            "source_snapshot_id": "registry_snapshot:" + "b" * 16, "source_snapshot_sha256": "b" * 64,
            "evidence_id": "frozen-website-candidate", "rights_status": "NLOD-2.0"}
        gateway = FakeGateway({"https://example.no/": (200, {"Content-Type": "text/html"}, html.encode())})
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=[candidate]), gateway, enable_keyless=False))
        evidence = next(item for item in result.evidence if item.evidence_id == "frozen-website-candidate")
        snapshot = next(item for item in result.snapshots if item.source_id == candidate["source_snapshot_id"])
        self.assertEqual(evidence.extraction_method, "frozen_registry_jsonl_v1")
        self.assertEqual(evidence.content_sha256, "a" * 64)
        self.assertEqual(snapshot.content_sha256, "b" * 64)

    def test_explicit_robots_disallow_blocks_website_candidate(self):
        gateway = FakeGateway({}, robots_state="disallowed")
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=["https://example.no"]), gateway, enable_keyless=False))
        self.assertIsNone(result.state)
        self.assertEqual(result.attempt_outcome, "robots_disallowed")
        self.assertIsNone(result.hiring_activity_state)
        self.assertEqual(result.hiring_attempt_outcome, "robots_disallowed")
        self.assertEqual(result.audit["candidates"][0]["decision"], "blocked_robots")
        self.assertFalse(result.claims)

    def test_social_registry_url_stays_profile_candidate_without_promotion(self):
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=["linkedin.com/company/example"]), FakeGateway({}), enable_keyless=False))
        self.assertFalse(result.claims)
        self.assertEqual(result.audit["candidates"][0]["kind"], "profile")
        self.assertEqual(result.audit["candidates"][0]["decision"], "candidate_only")

    def test_soft_404_parked_and_waf_pages_never_publish(self):
        cases = [
            b"<html><head><title>Domain for sale</title></head><body>Buy this domain today</body></html>",
            b"<html><head><title>404 Not Found</title></head><body>Page not found</body></html>",
            b"<html><head><title>Just a moment...</title></head><body>Verify you are human</body></html>",
        ]
        for body in cases:
            with self.subTest(body=body[:30]):
                gateway = FakeGateway({"https://example.no/": (200, {"Content-Type": "text/html"}, body)})
                result = __import__("asyncio").run(research_company(self.profile(website_candidates=["https://example.no"]), gateway, enable_keyless=False))
                self.assertFalse(result.claims)

    def test_two_independently_verified_domains_are_both_retained(self):
        html = f'''<html><head><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><footer>{LEGAL}</footer></body></html>'''
        headers = {"Content-Type": "text/html"}
        gateway = FakeGateway({
            "https://example.no/": (200, headers, html.encode()),
            "https://example.com/": (200, headers, html.encode()),
        })
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=["https://example.no", "https://example.com"]), gateway, enable_keyless=False))
        domains = {claim.value for claim in result.claims if claim.field == "verified_website_domain"}
        self.assertEqual(domains, {"example.no", "example.com"})
        evidence = {item.evidence_id: item for item in result.evidence}
        for claim in (item for item in result.claims if item.field == "verified_website_domain"):
            page_sources = [evidence[eid].source_url for eid in claim.evidence_ids if evidence[eid].extraction_method == "website_html_extract_v1"]
            self.assertEqual(len(page_sources), 1)
            self.assertTrue(page_sources[0].endswith(claim.value + "/"))

    def test_duplicate_candidates_redirecting_to_same_proof_emit_unique_evidence(self):
        html = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><footer>{LEGAL}</footer></body></html>'''
        class CanonicalizingGateway(FakeGateway):
            async def fetch(self, url, *, purpose, user_agent, max_bytes, allowed_hosts):
                status, headers, body = self.pages.get(url, (200, {"Content-Type": "text/html"}, html.encode()))
                final = "https://example.no/" if "example.no" in url else url
                self.ledger.logical_requests += 1
                self.ledger.physical_requests += 1
                self.ledger.entries.append(type("Entry", (), {"purpose": purpose, "url": url, "status": status, "outcome": "received"})())
                return status, headers, body[:max_bytes], final, "received"

        gateway = CanonicalizingGateway({})
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=[
            "https://example.no/", "https://www.example.no/"]), gateway, enable_keyless=False))
        evidence_ids = [item.evidence_id for item in result.evidence]
        snapshot_ids = [item.source_id for item in result.snapshots]
        claim_ids = [item.claim_id for item in result.claims]
        self.assertEqual(len(evidence_ids), len(set(evidence_ids)))
        self.assertEqual(len(snapshot_ids), len(set(snapshot_ids)))
        self.assertEqual(len(claim_ids), len(set(claim_ids)))
        self.assertEqual(result.audit["duplicate_accepted_proofs_deduplicated"], 1)

    def test_website_contact_personal_data_is_not_retained_as_claim_excerpt(self):
        html = f'''<html><head><meta name="description" content="Contact Jane Doe at jane@example.no or call 98765432 for details about our business."><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><footer>{LEGAL}</footer></body></html>'''
        gateway = FakeGateway({"https://example.no/": (200, {"Content-Type": "text/html"}, html.encode())})
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=["https://example.no"]), gateway, enable_keyless=False))
        self.assertFalse(any(claim.field == "website_description" for claim in result.claims))
        excerpts = " ".join(item.excerpt or "" for item in result.evidence)
        self.assertNotIn("jane@example.no", excerpts)
        self.assertNotIn("Jane Doe", excerpts)
        self.assertNotIn("98765432", excerpts)

    def test_robots_transport_failure_is_a_distinct_fail_closed_outcome(self):
        gateway = FakeGateway({}, robots_state="unreachable")
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=["https://example.no"]), gateway, enable_keyless=False))
        self.assertIsNone(result.state)
        self.assertEqual(result.attempt_outcome, "robots_unreachable")
        self.assertIsNone(result.hiring_activity_state)
        self.assertEqual(result.audit["candidates"][0]["decision"], "robots_unreachable")
        self.assertEqual([error.code for error in result.errors], ["ROBOTS_UNREACHABLE"])
        self.assertFalse(result.claims)

    def test_runner_keeps_unattempted_budget_deadline_and_robots_outcomes_out_of_public_state(self):
        org, name = "923609016", "Runner Target AS"
        for outcome, expected_attempt, expected_hiring_attempt, live in (("not_attempted", "not_attempted", "not_attempted", False),
                ("budget_skipped", "budget_skipped", "not_attempted", True),
                ("disallowed", "robots_disallowed", "not_attempted", True),
                ("unreachable", "robots_unreachable", "not_attempted", True)):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, snapshot = root / "input.jsonl", root / "registry.jsonl"
                output, state = root / "output.jsonl", root / "state.sqlite"
                source.write_text(json.dumps({"organisation_number": org}) + "\n", encoding="utf-8")
                snapshot.write_text(json.dumps({"organisation_number": org, "name": name,
                    "source_url": "https://registry.example/snapshot",
                    "website": "https://example.no/"}) + "\n", encoding="utf-8")
                argv = ["--input", str(source), "--registry-snapshot", str(snapshot), "--output", str(output),
                    "--state-output", str(state), "--batch-id", outcome]
                gateway = FakeGateway({}, robots_state=outcome if live else "allowed")
                if live:
                    argv.append("--live-websites")
                with patch.object(run_module, "NetworkGateway", return_value=gateway):
                    self.assertEqual(run_module.main(argv), 0)
                envelope = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
                self.assertIsNone(envelope["sections"]["website_owned_profiles"]["state"])
                self.assertIsNone(envelope["sections"]["hiring_activity"]["state"])
                self.assertEqual(envelope["sections"]["website_owned_profiles"]["attempt_outcome"], expected_attempt)
                self.assertEqual(envelope["sections"]["hiring_activity"]["attempt_outcome"], expected_hiring_attempt)
                self.assertFalse(any(claim["section"] in {"website_owned_profiles", "hiring_activity"}
                    for claim in envelope["claims"]))

    def test_preflight_dns_failure_is_unreachable_not_explicit_robots_disallow(self):
        gateway = FakeGateway({}, robots_error=NetworkPolicyError("hostname did not resolve"))
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=["https://example.no"]), gateway, enable_keyless=False))
        self.assertEqual(result.audit["candidates"][0]["decision"], "robots_unreachable")
        self.assertEqual(result.errors[0].code, "ROBOTS_UNREACHABLE")
        self.assertFalse(result.claims)

    def test_parent_domain_redirect_after_acquisition_is_rejected_by_gateway(self):
        gateway = FakeGateway({}, fetch_error=NetworkPolicyError("redirect host is outside the caller's source allowlist"))
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=["https://old-subsidiary.no"]), gateway, enable_keyless=False))
        self.assertFalse(result.claims)
        self.assertEqual(result.audit["candidates"][0]["decision"], "redirect_or_url_policy_rejected")

    def test_robots_crawl_delay_over_sixty_seconds_stops_after_homepage(self):
        home = f'''<html><head><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><footer>{LEGAL}</footer><a href="https://example.no/about">About</a></body></html>'''
        gateway = FakeGateway({"https://example.no/": (200, {"Content-Type": "text/html"}, home.encode())}, crawl_delay=61)
        result = __import__("asyncio").run(research_company(self.profile(website_candidates=["https://example.no"]), gateway, enable_keyless=False))
        self.assertEqual(result.audit["page_count"], 1)
        self.assertEqual(result.audit["page_requests"], 1)


if __name__ == "__main__":
    unittest.main()
