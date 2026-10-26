import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from signalpost.models import Claim, PublicState
from signalpost.nav import ORIGIN, employer_bindings, job_observation, research_jobs
from signalpost.network import NetworkGateway, NetworkPolicyError


ORG = "987974249"
CHILD = "979586701"
VACANCY = "12345678-1234-1234-1234-123456789abc"
NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


def payload():
    return {"uuid": VACANCY, "status": "ACTIVE", "sistEndret": (NOW - timedelta(hours=1)).isoformat(),
        "ad_content": {"employer": {"orgnr": ORG, "name": "Example AS", "homepage": "https://example.no/"},
            "title": "Engineer", "published": (NOW - timedelta(days=1)).isoformat(),
            "expires": (NOW + timedelta(days=20)).isoformat(), "contactList": [{"email": "private@example.no"}],
            "description": "Private contact text is not published"}}


def observe(value, bindings=None):
    return job_observation(ORG, value, json.dumps(value).encode(), ORIGIN + "/api/v1/feedentry/" + VACANCY,
                           NOW, bindings or {ORG: []}, NOW)


def test_nav_jobs_do_not_need_a_website_and_do_not_publish_contacts():
    result = observe(payload())
    assert len(result.claims) == 5
    assert all(claim.field_family == "jobs" and claim.scope == "job" for claim in result.claims)
    assert result.evidence[0].json_pointer == "/"
    published = json.dumps([item.model_dump(mode="json") for item in [*result.claims, *result.evidence, *result.snapshots]])
    assert "private@example" not in published and "Private contact" not in published
    assert "nav.no" in published


@pytest.mark.parametrize("change", ["wrong_employer", "absent_employer", "inactive", "expired", "future_publication", "future_modified", "missing_expiry", "contact_title"])
def test_nav_rejects_unconfirmed_or_noncurrent_postings(change):
    value = payload()
    if change == "wrong_employer":
        value["ad_content"]["employer"]["orgnr"] = "111111111"
    elif change == "absent_employer":
        del value["ad_content"]["employer"]["orgnr"]
    elif change == "inactive":
        value["status"] = "INACTIVE"
    elif change == "expired":
        value["ad_content"]["expires"] = (NOW - timedelta(seconds=1)).isoformat()
    elif change == "future_publication":
        value["ad_content"]["published"] = (NOW + timedelta(seconds=1)).isoformat()
    elif change == "future_modified":
        value["sistEndret"] = (NOW + timedelta(seconds=1)).isoformat()
    elif change == "missing_expiry":
        del value["ad_content"]["expires"]
    else:
        value["ad_content"]["title"] = "Call private@example.no"
    assert not observe(value).claims


def registry_claim(field, value, subject=ORG, scope="legal_entity"):
    return Claim(claim_id=field, organisation_number=ORG, section="leadership_workplaces", field_family="workplace",
        subject_id=subject, field=field, value=value, state=PublicState.AVAILABLE, scope=scope,
        verification_rule_id="brreg_json_pointer_v1", verification_score="1", evidence_ids=["registry-evidence"],
        source_snapshot_ids=["registry-snapshot"])


def test_workplace_match_requires_official_parent_relation_and_keeps_its_proof():
    value = payload()
    value["ad_content"]["employer"]["orgnr"] = CHILD
    assert not observe(value).claims
    relation = registry_claim("workplace.overordnetEnhet", ORG, CHILD, "workplace")
    result = observe(value, employer_bindings(ORG, [relation]))
    assert result.claims and "registry-evidence" in result.claims[0].evidence_ids
    assert "registry-snapshot" in result.claims[0].source_snapshot_ids
    wrong = relation.model_copy(update={"value": "111111111"})
    assert not observe(value, employer_bindings(ORG, [wrong])).claims


class FakeGateway:
    def __init__(self):
        self.calls = []

    def set_rate_limit(self, *args):
        pass

    async def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        purpose = kwargs["purpose"]
        if purpose == "nav_public_access":
            body = b"Public token for testing: eyJabc.def.ghi"
            assert not kwargs["api_headers"]
        elif purpose == "nav_feed":
            assert kwargs["api_headers"]["Authorization"] == "Bearer eyJabc.def.ghi"
            assert "GMT" in kwargs["api_headers"]["If-Modified-Since"]
            body = json.dumps({"items": [{"_feed_entry": {"uuid": VACANCY, "status": "ACTIVE", "businessName": "Example AS"}}],
                               "next_url": "/api/v1/feed/next-page"}).encode()
        else:
            body = json.dumps(payload()).encode()
        return 200, {}, body, url, "ok"


def test_nav_once_per_batch_pagination_dedup_and_homepage_is_only_candidate():
    gateway = FakeGateway()
    target = SimpleNamespace(claims=[registry_claim("name", "Example AS")])
    with patch("signalpost.nav.datetime") as clock:
        clock.now.return_value = NOW
        results, audit, homepages = asyncio.run(research_jobs({ORG: target}, gateway, NOW, allow_current=True, max_pages=2))
    assert len(results[ORG].claims) == 5
    assert [kwargs["purpose"] for _, kwargs in gateway.calls].count("nav_job") == 1
    assert audit["negative_coverage"] is False and audit["state"] == "partial"
    assert "pageSize=1000" in gateway.calls[-1][0]
    assert homepages[ORG] == [{"raw": "https://example.no/", "source": "nav_employer"}]
    assert not any(claim.field_family == "owned_web" for claim in results[ORG].claims)


def test_historical_cutoff_does_not_query_current_nav():
    gateway = FakeGateway()
    results, audit, _ = asyncio.run(research_jobs({}, gateway, NOW))
    assert not results and not gateway.calls and audit["state"] == "not_attempted"


def test_one_deleted_previous_vacancy_does_not_block_other_jobs():
    deleted = "00000000-1234-1234-1234-123456789abc"
    class DeletedVacancy(FakeGateway):
        async def fetch(self, url, **kwargs):
            if url.endswith(deleted):
                return 404, {}, b"", url, "http_error"
            return await super().fetch(url, **kwargs)
    prior = {ORG: [{"subject_id": "nav:" + deleted, "verification_rule_id": "nav_exact_employer_job_v1"}]}
    with patch("signalpost.nav.datetime") as clock:
        clock.now.return_value = NOW
        results, audit, _ = asyncio.run(research_jobs({ORG: SimpleNamespace(claims=[registry_claim("name", "Example AS")])},
            DeletedVacancy(), NOW, allow_current=True, previous_claims=prior, max_pages=1))
    assert len(results[ORG].claims) == 5 and audit["detail_failures"] == 1
    assert not audit["negative_coverage"]


def test_feed_outage_is_not_zero_jobs_and_tokens_stay_out_of_audit():
    class Outage(FakeGateway):
        async def fetch(self, url, **kwargs):
            raise OSError("eyJsecret.token.signature")

    results, audit, _ = asyncio.run(research_jobs({ORG: SimpleNamespace(claims=[])}, Outage(), NOW, allow_current=True))
    assert not results and audit["state"] == "blocked" and not audit["negative_coverage"]
    assert "eyJsecret" not in json.dumps(audit)


@pytest.mark.parametrize("url", ["https://example.no/api/v1/feed", ORIGIN + "/private", "http://pam-stilling-feed.nav.no/api/v1/feed"])
def test_authorization_cannot_be_sent_to_other_origins_or_paths(url):
    with pytest.raises(NetworkPolicyError):
        asyncio.run(NetworkGateway().fetch(url, purpose="nav_feed", access_profile="nav_feed_api",
            api_headers={"Authorization": "Bearer secret"}, use_robots=False))


def test_nav_retrieval_time_does_not_generate_refresh_changes():
    from signalpost.history import claim_fingerprint
    value = payload()
    first = observe(value)
    later = job_observation(ORG, value, json.dumps(value).encode(), ORIGIN + "/api/v1/feedentry/" + VACANCY,
        NOW + timedelta(minutes=1), {ORG: []}, NOW + timedelta(minutes=1))
    assert [claim_fingerprint(claim.model_dump(mode="json")) for claim in first.claims] == [
        claim_fingerprint(claim.model_dump(mode="json")) for claim in later.claims]


def test_nav_publication_graph_and_refresh_drop_stale_open_ads_without_false_closure():
    from signalpost.adapter import to_evaluator
    from signalpost.history import company_state, compare_states, merge_prior_facts
    from signalpost.models import InputRow
    from signalpost.run import _envelope, _merge_website_provenance
    def baseline():
        return _envelope(InputRow(input_ref="one", row_number=1, organisation_number=ORG),
            {ORG: {"organisation_number": ORG, "name": "Example AS"}}, "test", NOW, {})
    envelope = baseline()
    result = observe(payload())
    envelope.claims.extend(result.claims)
    _merge_website_provenance(envelope, result)
    for section in ("hiring_activity", "claims_evidence_states"):
        envelope.sections[section].claims.extend(result.claims)
        envelope.sections[section].state = PublicState.AVAILABLE
    published = to_evaluator(envelope)
    assert len([claim for claim in published["claims"] if claim["field_family"] == "jobs"]) == 5
    previous = company_state(envelope, "a" * 64)
    current = merge_prior_facts(company_state(baseline(), "a" * 64), previous)
    assert not any(claim["verification_rule_id"] == "nav_exact_employer_job_v1" for claim in current.claims)
    changes = compare_states(previous, current, cutoff=NOW, previous_ref="previous", current_ref="current")
    assert not any(change["type"] == "closed_job" for change in changes)


def test_nav_authorization_is_not_forwarded_on_redirects_or_written_to_ledger():
    class RedirectTransport:
        calls = []

        async def request(self, url, headers, timeout):
            self.calls.append((url, headers))
            return 302, {"Location": "https://example.no/"}, b"", url

    transport = RedirectTransport()
    gateway = NetworkGateway(transport=transport, retries=0)
    with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)):
        with pytest.raises(NetworkPolicyError):
            asyncio.run(gateway.fetch(ORIGIN + "/api/v1/feed", purpose="nav_feed", access_profile="nav_feed_api",
                api_headers={"Authorization": "Bearer secret-value"}, use_robots=False))
    assert len(transport.calls) == 1
    assert "secret-value" not in repr(gateway.ledger)


def test_production_runner_nav_without_website_duplicate_rows_and_idempotent_refresh(tmp_path, capsys):
    from signalpost import run
    class Transport:
        async def request(self, url, headers, timeout):
            if url.endswith("/api/publicToken"):
                return 200, {}, b"Public token: eyJabc.def.ghi", url
            if "/feedentry/" in url:
                body = payload()
            elif "/api/v1/feed" in url:
                body = {"items": [{"_feed_entry": {"uuid": VACANCY, "status": "ACTIVE", "businessName": "Example AS"}}]}
            elif "wikidata.org" in url:
                body = {"results": {"bindings": []}}
            else:
                return 404, {}, b"", url
            return 200, {"Content-Type": "application/json"}, json.dumps(body).encode(), url

    def gateway_factory(*args, **kwargs):
        return NetworkGateway(*args, **kwargs, transport=Transport())
    (tmp_path / "input").write_text(ORG + "\n" + ORG + "\nbad\n")
    (tmp_path / "registry").write_text(json.dumps({"organisation_number": ORG, "name": "Example AS"}) + "\n")
    def execute(suffix, previous=None):
        args = ["--input", str(tmp_path / "input"), "--registry-snapshot", str(tmp_path / "registry"),
            "--output", str(tmp_path / ("output" + suffix)), "--state-output", str(tmp_path / ("state" + suffix)),
            "--checkpoint", str(tmp_path / ("checkpoint" + suffix)), "--live-websites", "--no-keyless-websites"]
        if previous:
            args.extend(["--previous-state", str(tmp_path / previous)])
        with patch.object(run, "NetworkGateway", gateway_factory), patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), \
                patch.object(NetworkGateway, "robots_decision", return_value=("allowed", None)), \
                patch("signalpost.nav.datetime", wraps=datetime) as nav_clock, patch.object(run, "datetime", wraps=datetime) as run_clock:
            nav_clock.now.return_value = NOW
            run_clock.now.return_value = NOW
            assert run.main(args) == 0
        return [json.loads(line) for line in (tmp_path / ("output" + suffix)).read_text().splitlines()]
    first = execute("1")
    assert len(first) == 3 and first[2]["terminal_state"] == "failed"
    for row in first[:2]:
        assert len([claim for claim in row["claims"] if claim["verification_rule_id"] == "nav_exact_employer_job_v1"]) == 5
        assert not any(claim["field"] == "verified_website_url" for claim in row["claims"])
    second = execute("2", "state1")
    assert all(not row["refresh"]["changes"] for row in second)
    reports = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert all(report["requests_by_purpose"]["nav_public_access"] == 1 for report in reports)
