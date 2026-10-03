from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from datetime import datetime, timezone

from signalpost.models import PublicState
from signalpost.websites import (
    PageRecord, _activity_record, _dedupe_activities, _date_value, _page_footprints,
    _parse_feed, _parse_page, research_company,
)

ORG = "123456789"
LEGAL = "ÆØÅ Industri AS"
CUTOFF = datetime(2026, 10, 3, tzinfo=timezone.utc)


class FakeGateway:
    class Ledger:
        physical_requests = 0
        logical_requests = 0

    def __init__(self, pages):
        self.pages = pages
        self.ledger = self.Ledger()
        self.requested = []

    def set_rate_limit(self, host, rate):
        pass

    async def robots_decision(self, url, user_agent, *, allowed_hosts=None):
        return "allowed", None

    async def fetch(self, url, *, purpose, user_agent, max_bytes, allowed_hosts):
        self.requested.append(url)
        self.ledger.logical_requests += 1
        self.ledger.physical_requests += 1
        status, headers, body = self.pages.get(url, (404, {"Content-Type": "text/plain"}, b""))
        return status, headers, body[:max_bytes], url, "received"


def page(body: str, url="https://company.no/careers", structured=None) -> PageRecord:
    raw = body.encode()
    return PageRecord(url, url, 200, "text/html", raw, hashlib.sha256(raw).hexdigest(), CUTOFF,
                      structured=structured or {})


def job(title="Engineer", url="/jobs/engineer", *, deadline="2026-01-01", employer=None):
    row = {"@type": "JobPosting", "title": title, "url": url, "datePosted": "2026-02-01",
           "validThrough": deadline, "jobLocation": {"address": {"addressLocality": "Oslo", "addressCountry": "NO"}},
           "employmentType": "FULL_TIME"}
    row["hiringOrganization"] = employer or {"@type": "Organization", "name": LEGAL, "identifier": ORG}
    return {"@context": "https://schema.org", **row}


class M05HiringActivityTests(unittest.TestCase):
    def test_expired_job_is_closed_and_never_counted_current(self):
        jobs, _, _ = _page_footprints(page("", structured=job()), org=ORG, legal_name=LEGAL,
            verified_names={LEGAL}, cutoff=CUTOFF)
        self.assertEqual(jobs[0]["status"], "closed")
        self.assertEqual(jobs[0]["deadline"].date().isoformat(), "2026-01-01")

    def test_closed_only_postings_do_not_make_current_jobs_available(self):
        home = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><a href="/careers">Careers</a></body></html>'''
        career = f'<html><head><title>Careers</title><script type="application/ld+json">{json.dumps(job())}</script></head><body><h1>Careers</h1></body></html>'
        gateway = FakeGateway({"https://company.no/": (200, {"Content-Type": "text/html"}, home.encode()),
            "https://company.no/careers": (200, {"Content-Type": "text/html"}, career.encode())})
        result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL,
            "website_candidates": [{"raw": "https://company.no/", "source": "registry_frozen"}]}, gateway,
            enable_keyless=False, evidence_cutoff=CUTOFF))
        self.assertGreater(result.audit["jobs"]["published_subjects"], 0)
        self.assertEqual(result.audit["jobs"]["current_subjects"], 0)
        self.assertEqual(result.audit["jobs"]["state"], "ambiguous")

    def test_real_company_site_does_not_scope_employerless_jobs_or_rival_articles(self):
        home = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><a href="/careers">Careers</a><a href="/news">News</a></body></html>'''
        employerless = job(deadline="2026-12-01")
        employerless.pop("hiringOrganization")
        careers = f'<html><head><title>Careers</title><script type="application/ld+json">{json.dumps(employerless)}</script></head><body><h1>Careers</h1></body></html>'
        rival_article = {"@type": "NewsArticle", "headline": "Rival update", "datePublished": "2026-09-20",
            "about": {"@type": "Organization", "name": "Rival AS", "identifier": "987654321"},
            "url": "https://company.no/news/rival"}
        news = f'<html><head><title>News</title><script type="application/ld+json">{json.dumps(rival_article)}</script></head><body><h1>News</h1></body></html>'
        gateway = FakeGateway({"https://company.no/": (200, {"Content-Type": "text/html"}, home.encode()),
            "https://company.no/careers": (200, {"Content-Type": "text/html"}, careers.encode()),
            "https://company.no/news": (200, {"Content-Type": "text/html"}, news.encode())})
        result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL,
            "website_candidates": [{"raw": "https://company.no/", "source": "registry_frozen"}]}, gateway,
            enable_keyless=False, evidence_cutoff=CUTOFF))
        self.assertFalse(any(claim.field_family in {"jobs", "public_activity"} for claim in result.claims))
        self.assertEqual(result.audit["jobs"]["identity_rejected"], 1)
        self.assertEqual(result.audit["activity"]["subject_rejected"], 1)

    def test_global_website_pass_stages_preserve_the_single_company_result(self):
        home = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><a href="/careers">Careers</a></body></html>'''
        career = f'<html><head><title>Careers</title><script type="application/ld+json">{json.dumps(job(deadline="2026-12-01"))}</script></head><body><h1>Careers</h1></body></html>'
        pages = {"https://company.no/": (200, {"Content-Type": "text/html"}, home.encode()),
            "https://company.no/careers": (200, {"Content-Type": "text/html"}, career.encode())}
        profile = {"organisation_number": ORG, "name": LEGAL,
            "website_candidates": [{"raw": "https://company.no/", "source": "registry_frozen"}]}
        staged_gateway = FakeGateway(pages)
        verified = asyncio.run(research_company(profile, staged_gateway, enable_keyless=False,
            evidence_cutoff=CUTOFF, phase="verify"))
        verify_claim_count = len(verified.claims)
        verify_state = verified.state
        shallow = asyncio.run(research_company(profile, staged_gateway, enable_keyless=False,
            evidence_cutoff=CUTOFF, phase="shallow", previous=verified))
        shallow_claim_count = len(shallow.claims)
        staged = asyncio.run(research_company(profile, staged_gateway, enable_keyless=False,
            evidence_cutoff=CUTOFF, phase="jobs", previous=shallow))
        single = asyncio.run(research_company(profile, FakeGateway(pages), enable_keyless=False,
            evidence_cutoff=CUTOFF))
        self.assertEqual({claim.claim_id for claim in staged.claims}, {claim.claim_id for claim in single.claims})
        self.assertEqual(staged.audit["jobs"]["published_subjects"], single.audit["jobs"]["published_subjects"])
        self.assertEqual(verify_claim_count, 0)
        self.assertGreater(shallow_claim_count, 0)
        self.assertEqual(verify_state, PublicState.AMBIGUOUS)

    def test_future_posted_job_is_not_published_at_cutoff(self):
        observation = job(deadline="2027-01-01")
        observation["datePosted"] = "2027-02-01"
        jobs, _, counts = _page_footprints(page("", structured=observation), org=ORG,
            legal_name=LEGAL, verified_names={LEGAL}, cutoff=CUTOFF)
        self.assertEqual(jobs, [])
        self.assertEqual(counts["job_future"], 1)

    def test_job_with_wrong_shared_ats_employer_is_rejected(self):
        wrong = job(employer={"@type": "Organization", "name": "Other Company AS", "identifier": "987654321"})
        jobs, _, counts = _page_footprints(page("", structured=wrong), org=ORG, legal_name=LEGAL,
            verified_names={LEGAL}, cutoff=CUTOFF)
        self.assertEqual(jobs, [])
        self.assertEqual(counts["job_identity_rejected"], 1)

    def test_job_without_hiring_organization_is_rejected(self):
        observation = job(deadline=None)
        observation.pop("hiringOrganization")
        jobs, _, counts = _page_footprints(page("", structured=observation), org=ORG, legal_name=LEGAL,
            verified_names={LEGAL}, cutoff=CUTOFF)
        self.assertEqual(jobs, [])
        self.assertEqual(counts["job_identity_rejected"], 1)

    def test_multiple_hiring_organizations_with_foreign_entity_are_rejected(self):
        observation = job(deadline=None, employer=[
            {"@type": "Organization", "name": LEGAL, "identifier": ORG},
            {"@type": "Organization", "name": "Subsidiary AS", "identifier": "987654321"},
        ])
        jobs, _, counts = _page_footprints(page("", structured=observation), org=ORG, legal_name=LEGAL,
            verified_names={LEGAL}, cutoff=CUTOFF)
        self.assertEqual(jobs, [])
        self.assertEqual(counts["job_identity_rejected"], 1)

    def test_duplicate_job_cards_collapse_by_target_title_location_and_url(self):
        html = f'''<article itemscope itemtype="https://schema.org/JobPosting"><span itemprop="hiringOrganization" itemscope itemtype="https://schema.org/Organization"><span itemprop="name">{LEGAL}</span><meta itemprop="identifier" content="{ORG}"></span><h2 itemprop="title">Engineer</h2><span itemprop="jobLocation"><span itemprop="addressLocality">Oslo</span><span itemprop="addressCountry">NO</span></span><a href="/jobs/engineer">Apply</a></article>'''
        observation = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Engineer", "url": "/jobs/engineer",
                       "jobLocation": {"address": {"addressLocality": "Oslo", "addressCountry": "NO"}}}
        jobs, _, _ = _page_footprints(page(html, structured={"a": job(deadline=None), "b": observation}),
            org=ORG, legal_name=LEGAL, verified_names={LEGAL}, cutoff=CUTOFF)
        self.assertEqual(len(jobs), 1)

    def test_no_careers_page_is_ambiguous_not_zero(self):
        html = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><a href="/about">About</a></body></html>'''
        gateway = FakeGateway({"https://company.no/": (200, {"Content-Type": "text/html"}, html.encode())})
        result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL,
            "website_candidates": [{"raw": "https://company.no/", "source": "registry_frozen"}]}, gateway,
            enable_keyless=False, evidence_cutoff=CUTOFF))
        self.assertEqual(result.audit["jobs"]["state"], "ambiguous")
        self.assertFalse(result.audit["jobs"]["explicit_zero"])

    def test_explicit_zero_on_exact_careers_page_is_recorded(self):
        home = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><a href="/careers">Careers</a></body></html>'''
        careers = "<html><head><title>Careers</title></head><body><h1>Careers</h1><p>There are currently no open positions.</p></body></html>"
        gateway = FakeGateway({"https://company.no/": (200, {"Content-Type": "text/html"}, home.encode()),
            "https://company.no/careers": (200, {"Content-Type": "text/html"}, careers.encode())})
        result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL,
            "website_candidates": [{"raw": "https://company.no/", "source": "registry_frozen"}]}, gateway,
            enable_keyless=False, evidence_cutoff=CUTOFF))
        self.assertTrue(result.audit["jobs"]["explicit_zero"])
        self.assertEqual(result.audit["jobs"]["state"], "not_available")

    def test_embedded_unapproved_ats_is_detected_but_never_requested(self):
        home = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><a href="/careers">Careers</a></body></html>'''
        careers = '<html><head><title>Careers</title></head><body><iframe src="https://shared-ats.example/acme"></iframe></body></html>'
        gateway = FakeGateway({"https://company.no/": (200, {"Content-Type": "text/html"}, home.encode()),
            "https://company.no/careers": (200, {"Content-Type": "text/html"}, careers.encode())})
        result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL,
            "website_candidates": [{"raw": "https://company.no/", "source": "registry_frozen"}]}, gateway,
            enable_keyless=False, evidence_cutoff=CUTOFF))
        self.assertTrue(any(item["host"] == "shared-ats.example" and not item["requested"] for item in result.audit["ats_origins"]))
        self.assertFalse(any("shared-ats.example" in url for url in gateway.requested))

    def test_company_site_job_is_not_joined_to_duplicate_shared_ats_listing(self):
        home = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><a href="/careers">Careers</a></body></html>'''
        posting = job(deadline="2026-12-01")
        career = f'<html><head><title>Careers</title><script type="application/ld+json">{json.dumps(posting)}</script></head><body><iframe src="https://shared-ats.example/acme"></iframe></body></html>'
        gateway = FakeGateway({"https://company.no/": (200, {"Content-Type": "text/html"}, home.encode()),
            "https://company.no/careers": (200, {"Content-Type": "text/html"}, career.encode())})
        result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL,
            "website_candidates": [{"raw": "https://company.no/", "source": "registry_frozen"}]}, gateway,
            enable_keyless=False, evidence_cutoff=CUTOFF))
        subjects = {claim.subject_id for claim in result.claims if claim.field_family == "jobs"}
        self.assertEqual(len(subjects), 1)
        self.assertFalse(any("shared-ats.example" in url for url in gateway.requested))

    def test_article_mentioning_other_companies_remains_anchored_to_exact_site_org(self):
        event = {"@type": "NewsArticle", "headline": "ÆØÅ Industri partners with Other AS",
                 "datePublished": "2026-09-20", "url": "https://company.no/news/1",
                 "description": "The company announced a dated collaboration."}
        jobs, activities, _ = _page_footprints(page("", "https://company.no/news/1", {"@graph": [event]}),
            org=ORG, legal_name=LEGAL, verified_names={LEGAL}, cutoff=CUTOFF)
        self.assertEqual(jobs, [])
        self.assertEqual(len(activities), 0)

    def test_article_subject_requires_exact_target_and_rejects_other_entities(self):
        date = "2026-09-20"
        target = {"@type": "NewsArticle", "headline": "ÆØÅ Industri public update", "datePublished": date,
                  "about": {"@type": "Organization", "name": LEGAL, "identifier": ORG}}
        foreign_articles = [
            {"@type": "NewsArticle", "headline": f"{entity} update", "datePublished": date,
             "about": {"@type": "Organization", "name": entity, "identifier": str(number)}}
            for entity, number in (("Customer AS", "987654321"), ("Competitor AS", "987654322"),
                                   ("Subsidiary AS", "987654323"))
        ]
        multi = {"@type": "NewsArticle", "headline": "Joint update", "datePublished": date,
                 "about": [target["about"], foreign_articles[0]["about"]]}
        for observation, expected in ((target, 1), *((item, 0) for item in foreign_articles), (multi, 0)):
            with self.subTest(headline=observation["headline"]):
                _, events, _ = _page_footprints(page("", structured=observation), org=ORG,
                    legal_name=LEGAL, verified_names={LEGAL}, cutoff=CUTOFF)
                self.assertEqual(len(events), expected)

    def test_future_undated_and_sitemap_dates_never_become_activity_dates(self):
        counts = {"activity_undated": 0, "activity_future": 0, "activity_outside_window": 0}
        self.assertIsNone(_activity_record(ORG, "No date", "https://company.no/n", None, None, None, CUTOFF, 365, counts))
        self.assertIsNone(_activity_record(ORG, "Future", "https://company.no/f", datetime(2027, 1, 1, tzinfo=timezone.utc), None, None, CUTOFF, 365, counts))
        self.assertEqual(counts["activity_undated"], 1)
        self.assertEqual(counts["activity_future"], 1)
        self.assertEqual(_date_value("2026-01-01"), datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_rss_and_atom_explicit_publication_dates_parse_but_no_lastmod_is_consulted(self):
        rss = b'<rss><channel><item><title>Release</title><link>https://company.no/news/1</link><pubDate>Tue, 15 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>'
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Launch</title><link href="https://company.no/news/2"/><published>2026-09-16T08:00:00Z</published></entry></feed>'
        self.assertEqual(_parse_feed(rss)[0]["published"], "Tue, 15 Sep 2026 10:00:00 GMT")
        self.assertEqual(_parse_feed(atom)[0]["published"], "2026-09-16T08:00:00Z")
        sitemap = b'<urlset><url><loc>https://company.no/news/3</loc><lastmod>2026-09-17</lastmod></url></urlset>'
        self.assertEqual(_parse_feed(sitemap), [])

    def test_syndicated_duplicate_events_are_deduplicated(self):
        counts = {"activity_undated": 0, "activity_future": 0, "activity_outside_window": 0}
        date = datetime(2026, 9, 20, tzinfo=timezone.utc)
        one = _activity_record(ORG, "Launch", "https://company.no/news/1", date, "Summary", None, CUTOFF, 365, counts)
        two = _activity_record(ORG, "Launch", "https://company.no/syndicated/launch", date, "Summary", None, CUTOFF, 365, counts)
        self.assertEqual(len(_dedupe_activities([one, two])), 1)

    def test_exact_site_feed_activity_publishes_with_explicit_date_and_source_evidence(self):
        home = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><a href="/news">News</a></body></html>'''
        news = '<html><head><title>News</title><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head><body><h1>News</h1></body></html>'
        feed = f'<rss><channel><item><title>{LEGAL} factory opened</title><link>https://company.no/news/opening</link><pubDate>Tue, 15 Sep 2026 10:00:00 GMT</pubDate><description>A company-owned update.</description></item></channel></rss>'.encode()
        gateway = FakeGateway({"https://company.no/": (200, {"Content-Type": "text/html"}, home.encode()),
            "https://company.no/news": (200, {"Content-Type": "text/html"}, news.encode()),
            "https://company.no/feed.xml": (200, {"Content-Type": "application/rss+xml"}, feed)})
        result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL,
            "website_candidates": [{"raw": "https://company.no/", "source": "registry_frozen"}]}, gateway,
            enable_keyless=False, evidence_cutoff=CUTOFF))
        claims = [claim for claim in result.claims if claim.field_family == "public_activity"]
        date_claim = next(claim for claim in claims if claim.field == "source_published_at")
        self.assertEqual(date_claim.value["source_value"], "Tue, 15 Sep 2026 10:00:00 GMT")
        self.assertEqual(date_claim.value["precision"], "second")
        self.assertIsNotNone(date_claim.as_of)
        self.assertTrue(any(item.extraction_method == "website_feed_extract_v1" for item in result.evidence))
        self.assertIn("https://company.no/feed.xml", gateway.requested)

    def test_blocked_or_failed_source_does_not_become_zero_jobs(self):
        class BlockedGateway(FakeGateway):
            async def robots_decision(self, url, user_agent, *, allowed_hosts=None):
                return "blocked", None
        gateway = BlockedGateway({})
        result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL,
            "website_candidates": [{"raw": "https://company.no/", "source": "registry_frozen"}]}, gateway,
            enable_keyless=False, evidence_cutoff=CUTOFF))
        self.assertEqual(result.audit["jobs"]["state"], "ambiguous")
        self.assertFalse(result.audit["jobs"]["explicit_zero"])
        self.assertEqual(result.hiring_activity_state.value, "ambiguous")
        self.assertEqual(gateway.requested, [])

    def test_location_and_activity_summary_minimize_personal_contact_data(self):
        observation = job(deadline=None)
        observation["jobLocation"] = {"address": {"streetAddress": "Owner home 1", "addressLocality": "Oslo",
            "addressRegion": "Oslo", "addressCountry": {"name": "Norway"}}}
        jobs, _, _ = _page_footprints(page("", structured=observation), org=ORG,
            legal_name=LEGAL, verified_names={LEGAL}, cutoff=CUTOFF)
        self.assertEqual(jobs[0]["location"], "Oslo, Norway")
        self.assertNotIn("Owner home", jobs[0]["location"])
        counts = {"activity_undated": 0, "activity_future": 0, "activity_outside_window": 0}
        event = _activity_record(ORG, "Public launch", "https://company.no/news/1",
            datetime(2026, 9, 20, tzinfo=timezone.utc), "Contact 12345678 press@example.no",
            None, CUTOFF, 365, counts)
        self.assertIsNone(event["summary"])

    def test_published_claims_are_atomic_target_scoped_and_provenanced(self):
        posting = job(deadline="2026-12-01")
        home = f'''<html><head><title>{LEGAL}</title><script type="application/ld+json">{{"@type":"Organization","legalName":"{LEGAL}","identifier":"{ORG}"}}</script></head><body><a href="/careers">Careers</a></body></html>'''
        career = f'<html><head><title>Careers</title><script type="application/ld+json">{json.dumps(posting)}</script></head><body><h1>Careers</h1></body></html>'
        gateway = FakeGateway({"https://company.no/": (200, {"Content-Type": "text/html"}, home.encode()),
            "https://company.no/careers": (200, {"Content-Type": "text/html"}, career.encode())})
        result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL,
            "website_candidates": [{"raw": "https://company.no/", "source": "registry_frozen"}]}, gateway,
            enable_keyless=False, evidence_cutoff=CUTOFF))
        claims = [claim for claim in result.claims if claim.section == "hiring_activity"]
        self.assertIn("job_title", [claim.field for claim in claims])
        self.assertTrue(all(claim.organisation_number == ORG and claim.scope == "job" for claim in claims))
        evidence = {item.evidence_id for item in result.evidence}
        snapshots = {item.source_id for item in result.snapshots}
        for claim in claims:
            self.assertTrue(set(claim.evidence_ids) <= evidence)
            self.assertTrue(set(claim.source_snapshot_ids) <= snapshots)


if __name__ == "__main__":
    unittest.main()
