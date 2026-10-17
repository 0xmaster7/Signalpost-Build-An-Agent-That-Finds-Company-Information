"""Offline, evidence-bound coverage regressions; all company/source content is controlled."""
from __future__ import annotations
import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from signalpost.websites import _kind, _parse_page, _page_footprints, research_company
from signalpost.network import NetworkGateway
from signalpost import run

ORG = "923609016"
NAME = "ÆØÅ Industri AS"
CUT = datetime(2026, 10, 17, 23, 59, 59, tzinfo=timezone.utc)
HOME = "https://company.no/"

def html(schema, body="", head=""):
    return f'<html><head>{head}<script type="application/ld+json">{json.dumps(schema)}</script></head><body>{body}</body></html>'.encode()

def graph(employer=None, kind="https://schema.org/JobPosting"):
    employer = employer or {"@type": "Organization", "@id": "#employer", "name": NAME, "identifier": ORG}
    return {"@context": "https://schema.org", "@graph": [employer,
        {"@type": kind, "title": "Engineer", "url": "/jobs/engineer", "hiringOrganization": {"@id": "#employer"},
         "datePosted": "2026-10-01", "validThrough": "2026-11-30"},
        {"@type": "http://schema.org/NewsArticle", "headline": NAME + " opens a laboratory", "url": "/news/laboratory",
         "datePublished": "2026-10-02", "about": {"@id": "#employer"}}]}

class Gateway:
    def __init__(self, pages, cap=100):
        self.pages = pages; self.cap = cap; self.requested = []
        self.ledger = type("Ledger", (), {"logical_requests": 0, "physical_requests": 0, "entries": []})()
    def set_rate_limit(self, *args): pass
    async def robots_decision(self, *args, **kwargs): return "allowed", None
    async def fetch(self, url, **kwargs):
        self.ledger.logical_requests += 1
        if len(self.requested) >= self.cap: return 0, {}, b"", url, "budget_exhausted"
        self.requested.append(url); self.ledger.physical_requests += 1
        status, headers, body = self.pages.get(url, (404, {"Content-Type": "text/plain"}, b""))
        return status, headers, body, url, "received"

def page(schema):
    return _parse_page(HOME + "careers", 200, {"Content-Type": "text/html"}, html(schema), HOME + "careers")

def profile():
    return {"organisation_number": ORG, "name": NAME, "website_candidates": [{"raw": HOME, "source": "registry_frozen"}]}

class CoverageTests(unittest.TestCase):
    def footprints(self, schema):
        return _page_footprints(page(schema), org=ORG, legal_name=NAME, verified_names={NAME}, cutoff=CUT)

    def test_specific_routes_and_word_boundaries(self):
        self.assertEqual(_kind(HOME + "nb/om-oss/jobbe-i-enova/ledige-stillinger"), "careers")
        self.assertEqual(_kind(HOME + "about/news"), "news")
        self.assertEqual(_kind(HOME + "behandling/depresjon"), "other")
        self.assertEqual(_kind(HOME + "contact-us"), "contact")
        self.assertEqual(_kind(HOME + "kontaktinformasjon"), "contact")

    def test_namespace_and_exact_local_relationships_add_supported_families(self):
        for rows in (graph(), {**graph(), "@graph": list(reversed(graph()["@graph"]))}):
            jobs, activity, _ = self.footprints(rows)
            self.assertEqual([x["title"] for x in jobs], ["Engineer"])
            self.assertEqual(jobs[0]["status"], "open")
            self.assertEqual([x["title"] for x in activity], [NAME + " opens a laboratory"])

    def test_unknown_conflicting_or_rival_references_cannot_publish(self):
        bad = [graph({"@id": "#employer", "@type": "Organization", "name": "Rival AS", "identifier": "987654321"})]
        missing = graph(); missing["@graph"].pop(0); bad.append(missing)
        conflict = graph(); conflict["@graph"].append({"@id": "#employer", "@type": "Organization", "name": "Rival AS", "identifier": "987654321"}); bad.append(conflict)
        mixed = graph(); mixed["@graph"][0]["identifier"] = [ORG, "987654321"]; bad.append(mixed)
        for schema in bad:
            with self.subTest(schema=schema):
                jobs, activity, _ = self.footprints(schema)
                self.assertEqual(jobs, []); self.assertEqual(activity, [])
        jobs, _, _ = self.footprints(graph(kind="https://rival.no/JobPosting"))
        self.assertEqual(jobs, [])

    def test_identical_definitions_and_dates_remain_conservative(self):
        same = graph(); same["@graph"].append(dict(same["@graph"][0]))
        self.assertEqual(len(self.footprints(same)[0]), 1)
        future = graph(); future["@graph"][1]["datePosted"] = "2027-01-01"; future["@graph"][2]["datePublished"] = "2027-01-01"
        self.assertEqual(self.footprints(future)[:2], ([], []))
        undated = graph(); undated["@graph"][2].pop("datePublished")
        self.assertEqual(self.footprints(undated)[1], [])

    def test_downloaded_html_declared_as_feed_is_processed_once(self):
        root = html({"@type": "Organization", "name": NAME, "identifier": ORG},
            '<a href="/careers">Careers</a>', '<link rel="alternate" type="application/rss+xml" href="/careers">')
        gateway = Gateway({HOME: (200, {"Content-Type": "text/html"}, root),
            HOME + "careers": (200, {"Content-Type": "text/html"}, html(graph()))}, cap=3)
        result = asyncio.run(research_company(profile(), gateway, enable_keyless=False, evidence_cutoff=CUT))
        self.assertEqual(gateway.requested.count(HOME + "careers"), 1)
        self.assertTrue({"job_title", "activity_headline"} <= {c.field for c in result.claims})
        self.assertEqual(len(gateway.requested), 3)
        for claim in result.claims:
            self.assertTrue(set(claim.evidence_ids) <= {e.evidence_id for e in result.evidence})

    def test_breadth_reaches_jobs_and_activity_before_optional_sitemap_depth(self):
        links = '<a href="/careers">Careers</a><a href="/news">News</a>' + ''.join(f'<a href="/about/{i}">About</a>' for i in range(8))
        root = html({"@type": "Organization", "name": NAME, "identifier": ORG}, links)
        pages = {HOME: (200, {"Content-Type": "text/html"}, root),
            HOME + "sitemap.xml": (200, {"Content-Type": "application/xml"}, b'<sitemapindex><sitemap><loc>https://company.no/child.xml</loc></sitemap></sitemapindex>'),
            HOME + "careers": (200, {"Content-Type": "text/html"}, html(graph())),
            HOME + "news": (200, {"Content-Type": "text/html"}, html(graph()))}
        gateway = Gateway(pages, cap=4)
        result = asyncio.run(research_company(profile(), gateway, enable_keyless=False, evidence_cutoff=CUT))
        self.assertEqual(gateway.requested, [HOME, HOME + "sitemap.xml", HOME + "careers", HOME + "news"])
        self.assertTrue({"job_title", "activity_headline"} <= {c.field for c in result.claims})

    def test_contact_proof_precedes_redundant_about_pages_and_duplicate_candidate(self):
        root = html({}, ''.join(f'<a href="/about/{i}">About</a>' for i in range(8)) + '<a href="/contact">Contact</a>')
        contact = html({"@type": "Organization", "name": NAME, "identifier": ORG, "url": HOME}, '<h1>Contact</h1>')
        gateway = Gateway({HOME: (200, {"Content-Type": "text/html"}, root), HOME + "contact": (200, {"Content-Type": "text/html"}, contact)}, cap=2)
        company = profile(); company["website_candidates"] *= 2
        result = asyncio.run(research_company(company, gateway, enable_keyless=False, evidence_cutoff=CUT))
        self.assertEqual(gateway.requested, [HOME, HOME + "contact"])
        self.assertEqual(result.audit["candidate_count"], 1)
        self.assertTrue(any(c.field == "verified_website_url" for c in result.claims))

    def test_schema_only_owned_profile_uses_structured_source_locator(self):
        source = {"@type": "Organization", "name": NAME, "identifier": ORG,
                  "sameAs": ["https://www.linkedin.com/company/verified-company"]}
        gateway = Gateway({HOME: (200, {"Content-Type": "text/html"}, html(source))}, cap=1)
        result = asyncio.run(research_company(profile(), gateway, enable_keyless=False, evidence_cutoff=CUT))
        claims = [c for c in result.claims if c.field == "company_owned_profile"]
        self.assertEqual(len(claims), 1)
        evidence = {e.evidence_id: e for e in result.evidence}
        self.assertEqual(evidence[claims[0].evidence_ids[0]].json_pointer, "/structured_data/Organization/sameAs")
        self.assertEqual(gateway.requested, [HOME])

    def test_non_feed_xml_is_not_activity_and_larger_html_can_retry_at_page_cap(self):
        from signalpost.websites import _parse_feed
        self.assertEqual(_parse_feed(b'<document><item><title>Company news</title><link>https://company.no/news</link><pubDate>2026-10-01</pubDate></item></document>'), [])
        root = html({"@type": "Organization", "name": NAME, "identifier": ORG}, '<a href="/careers">Careers</a>',
                    '<link rel="alternate" type="application/rss+xml" href="/careers">')
        large = html(graph(), '<p>' + 'x ' * 140000 + '</p>')
        gateway = Gateway({HOME: (200, {"Content-Type": "text/html"}, root), HOME + "careers": (200, {"Content-Type": "text/html"}, large)}, cap=4)
        result = asyncio.run(research_company(profile(), gateway, enable_keyless=False, evidence_cutoff=CUT))
        self.assertEqual(gateway.requested.count(HOME + "careers"), 2)
        self.assertTrue(any(c.field == "job_title" for c in result.claims))

    def test_production_cli_final_evaluator_publishes_exact_supported_fields(self):
        class Transport:
            async def request(self, url, headers, timeout):
                if url == HOME:
                    return 200, {"Content-Type": "text/html"}, html({"@type": "Organization", "name": NAME, "identifier": ORG}, '<a href="/careers">Careers</a>'), url
                if url == HOME + "careers": return 200, {"Content-Type": "text/html"}, html(graph()), url
                return 404, {"Content-Type": "text/plain"}, b"", url
        gateways = []
        def factory(*args, **kwargs):
            gateway = NetworkGateway(*args, transport=Transport(), **kwargs); gateways.append(gateway); return gateway
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input").write_text(ORG + "\n")
            (root / "registry.jsonl").write_text(json.dumps({"organisation_number": ORG, "name": NAME, "website": HOME, "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/" + ORG}) + "\n")
            (root / "config.json").write_text(json.dumps({"budget": {"physical_request_limit": 3}}))
            with patch.object(run, "NetworkGateway", factory), patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), patch.object(NetworkGateway, "robots_decision", return_value=("allowed", None)):
                code = run.main(["--input", str(root / "input"), "--registry-snapshot", str(root / "registry.jsonl"), "--output", str(root / "output"), "--state-output", str(root / "state"), "--checkpoint", str(root / "checkpoint"), "--config", str(root / "config.json"), "--live-websites", "--no-keyless-websites", "--evidence-cutoff", CUT.isoformat()])
            self.assertEqual(code, 0)
            row = json.loads((root / "output").read_text())
            self.assertEqual(row["organisation_number"], ORG)
            self.assertTrue({"job_title", "activity_headline"} <= {c["field"] for c in row["claims"]})
            self.assertEqual(gateways[0].ledger.physical_requests, 3)
            for c in row["claims"]:
                self.assertEqual(c["organisation_number"], ORG)
                self.assertTrue(set(c["evidence_ids"]) <= {e["evidence_id"] for e in row["evidence"]})


class RegisteredBusinessDescriptionTests(unittest.IsolatedAsyncioTestCase):
    async def research(self, entity):
        from signalpost.brreg import fetch_company
        class Registry:
            async def fetch(self, url, **kwargs):
                if url.endswith("/roller"): body = {"rollegrupper": []}
                elif "/underenheter?" in url: body = {"page": {"number": 0, "totalElements": 0, "totalPages": 0}, "_links": {"self": {"href": url}}}
                elif "/regnskap/" in url: body = []
                else: body = entity
                return 200, {"Content-Type": "application/json"}, json.dumps(body).encode(), url, "ok"
        return await fetch_company(ORG, Registry(), CUT)

    async def test_registered_arrays_are_complete_exact_source_values(self):
        # Authentic public source shapes; line breaks are not separate business events.
        entity = {"organisasjonsnummer": ORG, "navn": NAME, "organisasjonsform": {"kode": "AS"},
                  "aktivitet": ["Utleie av fast eiendom.", "Investering i aksjer og verdipapirer."],
                  "vedtektsfestetFormaal": ["Kjøp, salg, utvikling, samt utleie av eiendom, herunder deltakelse i", "slik virksomhet, samt investering i andre selskaper forøvrig."]}
        result = await self.research(entity)
        facts = {c.field: c for c in result.claims if c.field_family == "business_description"}
        self.assertEqual(set(facts), {"registered_business_activity", "registered_purpose"})
        evidence = {e.evidence_id: e for e in result.evidence}
        for field, source in [("registered_business_activity", "aktivitet"), ("registered_purpose", "vedtektsfestetFormaal")]:
            claim = facts[field]
            self.assertEqual(claim.value, entity[source])
            self.assertEqual(evidence[claim.evidence_ids[0]].json_pointer, "/" + source)
            self.assertEqual(claim.scope, "legal_entity")
            self.assertIsNone(claim.as_of)
            self.assertEqual(claim.section, "identity_brand")
        self.assertFalse(any(c.field_family == "public_activity" for c in result.claims))

    async def test_missing_malformed_contact_and_wrong_identity_abstain(self):
        base = {"organisasjonsnummer": ORG, "navn": NAME, "organisasjonsform": {"kode": "AS"}}
        for value in (None, [], [" "], "description", {"text": "business"}, ["valid", 5], ["Contact person@example.no"], ["Call +4799999999"]):
            with self.subTest(value=value):
                result = await self.research({**base, "aktivitet": value, "vedtektsfestetFormaal": value})
                self.assertFalse(any(c.field_family == "business_description" for c in result.claims))
        result = await self.research({**base, "organisasjonsnummer": "987654321", "aktivitet": ["Rival business"]})
        self.assertFalse(any(c.field_family == "business_description" for c in result.claims))

    async def test_sole_trader_description_does_not_reintroduce_registration_address(self):
        result = await self.research({"organisasjonsnummer": ORG, "navn": NAME, "organisasjonsform": {"kode": "ENK"},
            "aktivitet": ["Veitransport av gods."], "forretningsadresse": {"adresse": ["Private road 10"], "postnummer": "1234"}})
        self.assertTrue(any(c.field == "registered_business_activity" for c in result.claims))
        self.assertFalse(any(c.field == "business_address" for c in result.claims))
        self.assertNotIn("Private road", json.dumps([c.model_dump(mode="json") for c in result.claims]))


class PhysicalAddressBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_address_fallback_requires_a_separate_physical_reservation(self):
        from signalpost.network import UrlLibTransport
        from signalpost.operations import Budget, RunBudget
        for cap in (1, 2):
            with self.subTest(cap=cap):
                calls = []
                def pinned(url, headers, timeout, addresses, max_bytes):
                    calls.append(addresses)
                    if len(calls) == 1: raise OSError("controlled first-address failure")
                    return 200, {}, b"supported response", url
                budget = Budget(RunBudget(physical_request_limit=cap))
                gateway = NetworkGateway(UrlLibTransport(), budget=budget, retries=1)
                with patch("signalpost.network.validate_public_host", return_value=("2001:4860:4860::8888", "8.8.8.8")), patch.object(UrlLibTransport, "_pinned_request", side_effect=pinned):
                    result = await gateway.fetch(HOME, use_robots=False, allowed_hosts={"company.no"})
                self.assertEqual(len(calls), cap)
                self.assertEqual(gateway.ledger.physical_requests, cap)
                self.assertEqual(budget.physical_requests_remaining, 0)
                self.assertEqual(calls[0], ("8.8.8.8",))
                if cap == 2:
                    self.assertEqual(calls[1], ("2001:4860:4860::8888",))
                    self.assertEqual(result[0], 200)
                else: self.assertEqual(result[-1], "budget_exhausted")

    async def test_transport_refuses_unledgered_multi_address_fanout(self):
        from signalpost.network import UrlLibTransport, NetworkPolicyError
        with self.assertRaises(NetworkPolicyError):
            UrlLibTransport._pinned_request(HOME, {}, 1, ("8.8.8.8", "1.1.1.1"), 100)


class WebsiteCompanyBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_company_caps_are_isolated_and_scope_is_reset(self):
        from signalpost.network import request_company_scope
        from signalpost.operations import Budget, RunBudget
        class Transport:
            async def request(self, url, headers, timeout):
                await asyncio.sleep(0)
                return 200, {}, b"source", url
        budget = Budget(RunBudget(physical_request_limit=10, per_company_physical_limit=1))
        gateway = NetworkGateway(Transport(), budget=budget, retries=0)
        async def company(org, host):
            with request_company_scope(org):
                first = await gateway.fetch(host + "/", use_robots=False)
                second = await gateway.fetch(host + "/careers", use_robots=False)
            return first[0], second[-1]
        with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)):
            rows = await asyncio.gather(company(ORG, "https://first.no"), company("976390512", "https://second.no"))
            outside = await gateway.fetch("https://outside.no/", use_robots=False)
        self.assertEqual(rows, [(200, "budget_exhausted"), (200, "budget_exhausted")])
        self.assertEqual(outside[0], 200)
        self.assertEqual(gateway.ledger.physical_requests, 3)

    async def test_company_budget_denial_does_not_poison_shared_host_robots(self):
        from signalpost.network import request_company_scope
        from signalpost.operations import Budget, RunBudget
        class Transport:
            async def request(self, url, headers, timeout):
                if url.endswith("robots.txt"): return 200, {}, b"User-agent: *\nAllow: /\n", url
                return 200, {}, b"source", url
        gateway = NetworkGateway(Transport(), budget=Budget(RunBudget(physical_request_limit=10, per_company_physical_limit=2)), retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)):
            with request_company_scope(ORG):
                await gateway.fetch("https://first.no/a", use_robots=False)
                await gateway.fetch("https://first.no/b", use_robots=False)
                self.assertEqual((await gateway.fetch("https://shared.no/a"))[-1], "budget_exhausted")
            with request_company_scope("976390512"):
                self.assertEqual((await gateway.fetch("https://shared.no/a"))[0], 200)
        self.assertEqual(gateway.ledger.physical_requests, 4)

    def test_production_batch_applies_company_caps_to_website_requests(self):
        class Transport:
            async def request(self, url, headers, timeout):
                host = url.split("/")[2]
                org, name = (ORG, NAME) if host == "first.no" else ("976390512", "Second Company AS")
                if url.endswith("/"):
                    return 200, {"Content-Type": "text/html"}, html({"@type": "Organization", "name": name, "identifier": org}, '<a href="/careers">Careers</a>'), url
                return 404, {}, b"", url
        gateways = []
        def factory(*args, **kwargs):
            gateway = NetworkGateway(*args, transport=Transport(), **kwargs); gateways.append(gateway); return gateway
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input").write_text(ORG + "\n976390512\n")
            (root / "registry").write_text("\n".join(json.dumps({"organisation_number": org, "name": name, "website": site,
                "source_url": "https://registry.example/snapshot"}) for org, name, site in [(ORG, NAME, "https://first.no/"), ("976390512", "Second Company AS", "https://second.no/")]) + "\n")
            (root / "config").write_text(json.dumps({"budget": {"physical_request_limit": 10, "per_company_physical_limit": 2}}))
            with patch.object(run, "NetworkGateway", factory), patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), patch.object(NetworkGateway, "robots_decision", return_value=("allowed", None)):
                code = run.main(["--input", str(root / "input"), "--registry-snapshot", str(root / "registry"), "--output", str(root / "output"), "--state-output", str(root / "state"), "--checkpoint", str(root / "checkpoint"), "--config", str(root / "config"), "--live-websites", "--no-keyless-websites", "--evidence-cutoff", CUT.isoformat()])
            self.assertEqual(code, 0)
            rows = [json.loads(line) for line in (root / "output").read_text().splitlines()]
            self.assertEqual([r["organisation_number"] for r in rows], [ORG, "976390512"])
            self.assertTrue(all(any(c["field"] == "verified_website_url" for c in r["claims"]) for r in rows))
            self.assertEqual(gateways[0].ledger.physical_requests, 4)
