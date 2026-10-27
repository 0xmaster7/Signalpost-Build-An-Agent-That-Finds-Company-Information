import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from signalpost.models import Claim, PublicState
from signalpost.nav import ORIGIN, research_jobs


ORG = "987974249"
CHILD = "979586701"
OTHER = "111111111"
NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def vacancy(number):
    return f"{number:08x}-1234-1234-1234-123456789abc"


def ad(number=1, employer=ORG, **changes):
    result = {"uuid": vacancy(number), "status": "ACTIVE", "sistEndret": (NOW - timedelta(hours=1)).isoformat(),
        "ad_content": {"employer": {"orgnr": employer, "homepage": "https://example.no/"}, "title": "Engineer",
            "published": (NOW - timedelta(days=2)).isoformat(), "expires": (NOW + timedelta(days=10)).isoformat(),
            "contactList": [{"email": "private@example.no"}], "description": "Private application text"}}
    result.update(changes)
    return result


def summary(number=1, name="Unrelated trading alias", **changes):
    entry = {"uuid": vacancy(number), "status": "ACTIVE", "businessName": name,
        "sistEndret": (NOW - timedelta(hours=1)).isoformat()}
    entry.update(changes)
    return {"_feed_entry": entry}


def page(items, next_page=None):
    return {"items": items, "next_url": next_page}


def claim(field, value, subject=ORG, scope="legal_entity", state=PublicState.AVAILABLE):
    return Claim(claim_id=field, organisation_number=ORG, section="leadership_workplaces", field_family="workplace",
        subject_id=subject, field=field, value=value, state=state, scope=scope,
        verification_rule_id="brreg_json_pointer_v1", verification_score="1", evidence_ids=["registry-proof"],
        source_snapshot_ids=["registry-source"])


def targets(*claims):
    return {ORG: SimpleNamespace(claims=list(claims))}


class Gateway:
    def __init__(self, pages, details=None):
        self.pages = iter(pages)
        self.details = details or {}
        self.calls = []

    def set_rate_limit(self, *args):
        assert args == ("pam-stilling-feed.nav.no", 4.0)

    async def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert kwargs["allowed_hosts"] == {"pam-stilling-feed.nav.no"}
        assert kwargs["access_profile"] == "nav_feed_api"
        if kwargs["purpose"] == "nav_public_access":
            return 200, {}, b"eyJabc.def.ghi", url, "ok"
        assert kwargs["api_headers"]["Authorization"] == "Bearer eyJabc.def.ghi"
        if kwargs["purpose"] == "nav_feed":
            assert kwargs["api_headers"]["If-Modified-Since"] == "Thu, 17 Sep 2026 12:00:00 GMT"
            payload = next(self.pages)
        else:
            payload = self.details[url.rsplit("/", 1)[-1]]
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, tuple):
            status, outcome = payload
            return status, {}, b"", url, outcome
        return 200, {}, json.dumps(payload).encode(), url, "ok"


def research(gateway, target=None, **kwargs):
    with patch("signalpost.nav.datetime") as clock:
        clock.now.return_value = NOW
        return asyncio.run(research_jobs(target if target is not None else targets(), gateway, NOW,
            allow_current=True, **kwargs))


def test_full_window_finds_employer_alias_after_four_pages_once_for_batch():
    pages = [page([], f"/api/v1/feed/page-{number + 1}") for number in range(6)]
    pages.append(page([summary(1), summary(2)]))
    gateway = Gateway(pages, {vacancy(1): ad(1), vacancy(2): ad(2, OTHER)})
    target = {**targets(), OTHER: SimpleNamespace(claims=[])}
    results, audit, _ = research(gateway, target)
    assert set(results) == {ORG, OTHER}
    assert audit["pages"] == 7 and audit["complete"] and audit["feed_complete"]
    assert audit["matched_jobs"] == 2 and audit["indexed_employers"] == 2
    assert not audit["truncated"] and not audit["negative_coverage"]
    assert sum(kwargs["purpose"] == "nav_public_access" for _, kwargs in gateway.calls) == 1
    assert sum(kwargs["purpose"] == "nav_feed" for _, kwargs in gateway.calls) == 7


@pytest.mark.parametrize("shape", ["header", "item", "content_text", "json", "employer_header", "bare"])
def test_embedded_employer_index_reuses_page_provenance_without_detail_requests(shape):
    payload = ad()
    if shape == "header":
        item = {"_feed_entry": payload}
    elif shape == "item":
        item = {**summary(), "ad_content": payload["ad_content"]}
    elif shape == "content_text":
        item = {**summary(), "content_text": json.dumps(payload)}
    elif shape == "json":
        item = {**summary(), "json": payload["ad_content"]}
    elif shape == "employer_header":
        item = {"_feed_entry": {**summary()["_feed_entry"], **payload["ad_content"]}}
    else:
        item = payload
    gateway = Gateway([page([item])])
    results, audit, homepages = research(gateway)
    assert len(results[ORG].claims) == 5 and audit["details"] == 0
    assert audit["complete"]
    evidence = results[ORG].evidence[0]
    assert evidence.source_url == ORIGIN + "/api/v1/feed?pageSize=1000"
    assert evidence.json_pointer.startswith("/items/0")
    assert homepages[ORG] == [{"raw": "https://example.no/", "source": "nav_employer"}]
    published = json.dumps([obj.model_dump(mode="json") for obj in [*results[ORG].claims,
        *results[ORG].evidence, *results[ORG].snapshots]] + [audit])
    assert all(secret not in published for secret in ["private@example.no", "Private application text", "eyJabc"])


def test_sparse_employer_headers_fetch_only_exact_bound_employers():
    matching = summary(1, employer={"orgnr": ORG})
    unrelated = summary(2, employer={"orgnr": OTHER})
    gateway = Gateway([page([unrelated, matching])], {vacancy(1): ad()})
    results, audit, _ = research(gateway)
    assert results[ORG].claims and audit["details"] == 1
    assert audit["indexed_jobs"] == 2 and audit["complete"]


def test_names_prioritize_but_never_exclude_aliases_and_duplicate_ads_are_deduplicated():
    gateway = Gateway([page([summary(1), summary(2, "Official Name"), summary(1)])],
        {vacancy(1): ad(), vacancy(2): ad(2, OTHER)})
    results, audit, _ = research(gateway, targets(claim("name", "Official Name")))
    detail_urls = [url for url, kwargs in gateway.calls if kwargs["purpose"] == "nav_job"]
    assert detail_urls == [ORIGIN + "/api/v1/feedentry/" + vacancy(number) for number in (2, 1)]
    assert len(results[ORG].claims) == 5 and audit["matched_jobs"] == 1 and audit["complete"]


@pytest.mark.parametrize("budget,reason", [({"max_pages": 1}, "page_cap"),
    ({"max_requests": 2}, "request_cap"), ({"max_details": 1}, "detail_cap")])
def test_caps_keep_useful_observations_and_never_report_complete_coverage(budget, reason):
    embedded = {"_feed_entry": ad()}
    gateway = Gateway([page([embedded, summary(2), summary(3)], "/api/v1/feed/next-page"), page([])],
        {vacancy(2): ad(2), vacancy(3): ad(3)})
    results, audit, _ = research(gateway, **budget)
    assert results[ORG].claims
    assert audit["state"] == "partial" and not audit["complete"] and audit["truncated"]
    assert reason in audit["reason"] and not audit["negative_coverage"]


def test_internal_deadline_returns_previously_collected_evidence():
    class SlowGateway(Gateway):
        async def fetch(self, url, **kwargs):
            if kwargs["purpose"] == "nav_feed" and "next-page" in url:
                await asyncio.sleep(1)
            return await super().fetch(url, **kwargs)
    gateway = SlowGateway([page([{"_feed_entry": ad()}], "/api/v1/feed/next-page")])
    results, audit, _ = research(gateway, time_seconds=0.03)
    assert len(results[ORG].claims) == 5
    assert audit["state"] == "partial" and audit["reason"] == "deadline"
    assert audit["truncated"] and not audit["complete"]


def test_external_cancellation_returns_partial_observations():
    class CancelGateway(Gateway):
        async def fetch(self, url, **kwargs):
            if "next-page" in url:
                raise asyncio.CancelledError()
            return await super().fetch(url, **kwargs)
    gateway = CancelGateway([page([{"_feed_entry": ad()}], "/api/v1/feed/next-page")])
    results, audit, _ = research(gateway)
    assert results[ORG].claims and audit["reason"] == "cancelled" and audit["truncated"]


def test_outer_wait_for_receives_partial_results_instead_of_discarding_them():
    class SlowGateway(Gateway):
        async def fetch(self, url, **kwargs):
            if "next-page" in url:
                await asyncio.sleep(1)
            return await super().fetch(url, **kwargs)
    gateway = SlowGateway([page([{"_feed_entry": ad()}], "/api/v1/feed/next-page")])
    async def phase():
        return await asyncio.wait_for(research_jobs(targets(), gateway, NOW, allow_current=True, time_seconds=10), 0.03)
    with patch("signalpost.nav.datetime") as clock:
        clock.now.return_value = NOW
        results, audit, _ = asyncio.run(phase())
    assert results[ORG].claims and audit["reason"] == "cancelled" and audit["truncated"]


@pytest.mark.parametrize("next_url", ["https://evil.example/api/v1/feed/next", "//evil.example/api/v1/feed/next",
    ORIGIN + "/api/v1/feed/next?token=private", "/api/v1/feed/next#fragment", 123])
def test_invalid_continuation_never_receives_token_and_keeps_results(next_url):
    gateway = Gateway([page([{"_feed_entry": ad()}], next_url)])
    results, audit, _ = research(gateway)
    assert results[ORG].claims and audit["reason"] == "invalid_continuation"
    assert len(gateway.calls) == 2 and not audit["complete"]
    assert "private" not in json.dumps(audit)


def test_cycles_are_partial_and_pending_alias_details_are_still_used():
    gateway = Gateway([page([summary()], "/api/v1/feed/repeated"), page([], "/api/v1/feed/repeated")],
        {vacancy(1): ad()})
    results, audit, _ = research(gateway)
    assert results[ORG].claims and audit["pages"] == 2
    assert audit["reason"] == "pagination_cycle" and audit["truncated"]


@pytest.mark.parametrize("broken", [None, {"items": {}}, {"items": [] , "next_url": []}])
def test_malformed_later_page_keeps_prior_observations(broken):
    gateway = Gateway([page([{"_feed_entry": ad()}], "/api/v1/feed/next"), broken])
    results, audit, _ = research(gateway)
    assert results[ORG].claims and audit["state"] == "partial" and not audit["complete"]


def test_malformed_item_does_not_hide_valid_jobs_or_establish_negative_coverage():
    gateway = Gateway([page(["bad", {}, summary(uuid="bad-id"), {"_feed_entry": ad()}])])
    results, audit, _ = research(gateway)
    assert results[ORG].claims and audit["malformed_items"] == 3
    assert audit["feed_complete"] and not audit["complete"] and not audit["negative_coverage"]


def test_malformed_later_page_still_resolves_previously_queued_aliases():
    gateway = Gateway([page([summary()], "/api/v1/feed/next"), {"items": None}], {vacancy(1): ad()})
    results, audit, _ = research(gateway)
    assert results[ORG].claims and audit["details"] == 1
    assert audit["state"] == "partial" and audit["truncated"] and not audit["complete"]


@pytest.mark.parametrize("content", [None, [], {"employer": "bad"}])
def test_malformed_details_are_partial_instead_of_complete_empty_index(content):
    gateway = Gateway([page([summary()])], {vacancy(1): ad(ad_content=content)})
    results, audit, _ = research(gateway)
    assert not results and audit["detail_failures"] == 1
    assert audit["unresolved_entries"] == 1 and not audit["complete"] and audit["truncated"]


def test_detail_outage_and_uuid_mismatch_do_not_block_other_alias_jobs():
    gateway = Gateway([page([summary(1), summary(2), summary(3)])],
        {vacancy(1): OSError("eyJsecret.private.token"), vacancy(2): ad(4), vacancy(3): ad(3)})
    results, audit, _ = research(gateway)
    assert len(results[ORG].claims) == 5 and audit["detail_failures"] == 2
    assert audit["unresolved_entries"] == 2 and not audit["complete"]
    assert "eyJsecret" not in json.dumps(audit)


def test_gateway_budget_stops_unknown_detail_fanout_and_keeps_embedded_matches():
    gateway = Gateway([page([{"_feed_entry": ad()}, summary(2), summary(3)])],
        {vacancy(2): (0, "budget_exhausted")})
    results, audit, _ = research(gateway)
    assert results[ORG].claims and audit["reason"] == "gateway_budget"
    assert audit["details"] == 1 and audit["unresolved_entries"] == 2


def test_workplace_dictionary_lookup_requires_available_official_relation():
    relation = claim("workplace.overordnetEnhet", ORG, CHILD, "workplace")
    gateway = Gateway([page([{"_feed_entry": ad(employer=CHILD)}])])
    results, audit, _ = research(gateway, targets(relation))
    assert results[ORG].claims and audit["matched_jobs"] == 1
    assert "registry-proof" in results[ORG].claims[0].evidence_ids
    assert "registry-source" in results[ORG].claims[0].source_snapshot_ids
    unavailable = relation.model_copy(update={"state": PublicState.NOT_AVAILABLE})
    results, _, _ = research(Gateway([page([{"_feed_entry": ad(employer=CHILD)}])]), targets(unavailable))
    assert not results


@pytest.mark.parametrize("change", ["inactive", "expired", "future_published", "future_modified", "missing_expiry", "contact_title"])
def test_embedded_jobs_keep_strict_publication_gates(change):
    payload = ad()
    if change == "inactive":
        payload["status"] = "INACTIVE"
    elif change == "expired":
        payload["ad_content"]["expires"] = NOW.isoformat()
    elif change == "future_published":
        payload["ad_content"]["published"] = (NOW + timedelta(seconds=1)).isoformat()
    elif change == "future_modified":
        payload["sistEndret"] = (NOW + timedelta(seconds=1)).isoformat()
    elif change == "missing_expiry":
        del payload["ad_content"]["expires"]
    else:
        payload["ad_content"]["title"] = "Email private@example.no"
    results, _, _ = research(Gateway([page([{"_feed_entry": payload}])], {vacancy(1): payload}))
    assert not results


def test_later_inactive_event_removes_embedded_open_job():
    gateway = Gateway([page([{"_feed_entry": ad()}], "/api/v1/feed/next"),
        page([summary(status="INACTIVE")])])
    results, audit, _ = research(gateway)
    assert not results and audit["indexed_jobs"] == 0 and audit["complete"]


def test_feed_304_is_terminal_but_never_proves_absence_of_all_open_ads():
    results, audit, _ = research(Gateway([(304, "http_error")]))
    assert not results and audit["complete"] and audit["feed_complete"]
    assert not audit["negative_coverage"]


def test_embedded_page_changes_do_not_create_false_job_refresh_changes():
    from signalpost.history import claim_fingerprint
    first, _, _ = research(Gateway([page([{"_feed_entry": ad()}])]))
    second, _, _ = research(Gateway([page([summary(2, status="INACTIVE"), {"_feed_entry": ad()}])]))
    assert first[ORG].snapshots[0].content_sha256 != second[ORG].snapshots[0].content_sha256
    assert [claim_fingerprint(value.model_dump(mode="json")) for value in first[ORG].claims] == [
        claim_fingerprint(value.model_dump(mode="json")) for value in second[ORG].claims]
