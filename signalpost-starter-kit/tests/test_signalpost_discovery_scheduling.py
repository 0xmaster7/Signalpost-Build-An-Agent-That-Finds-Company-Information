from test_signalpost_nav_window import Gateway, ORG, ad, claim, page, research, summary, targets, vacancy

import asyncio

from signalpost.websites import research_company


def test_feed_traversal_finishes_before_any_detail_lookup():
    gateway = Gateway([page([summary(1, "Official Name AS")], "/api/v1/feed/second"),
        page([summary(2)])], {vacancy(1): ad(1), vacancy(2): ad(2)})
    results, audit, _ = research(gateway, targets(claim("name", "Official Name AS")))
    purposes = [kwargs["purpose"] for _, kwargs in gateway.calls]
    assert max(index for index, purpose in enumerate(purposes) if purpose == "nav_feed") < purposes.index("nav_job")
    assert results[ORG].claims and audit["feed_complete"]
    assert audit["feed_elapsed_seconds"] >= 0 and audit["detail_elapsed_seconds"] >= 0


def test_feedentry_identifier_is_not_assumed_to_equal_ad_uuid():
    gateway = Gateway([page([{**summary(1), "id": "different-entry-id"}])], {"different-entry-id": ad(1)})
    results, audit, _ = research(gateway)
    assert results[ORG].claims and audit["details"] == 1
    assert any(url.endswith("/feedentry/different-entry-id") for url, _ in gateway.calls)


def test_name_alias_priority_still_requires_exact_employer_number():
    gateway = Gateway([page([summary(1), summary(2, "Official Name AS avd Bergen")])],
        {vacancy(1): ad(1), vacancy(2): ad(2, employer="111111111")})
    results, audit, _ = research(gateway, targets(claim("name", "Official Name AS")), max_details=1)
    assert not results and audit["details"] == 1 and not audit["complete"]
    assert next(url for url, kwargs in gateway.calls if kwargs["purpose"] == "nav_job").endswith(vacancy(2))


def test_website_logs_source_tier_and_robot_rejection_without_fetching():
    class Disallowed:
        def set_rate_limit(self, *args):
            pass

        async def robots_decision(self, *args, **kwargs):
            return "disallowed", None

        async def fetch(self, *args, **kwargs):
            raise AssertionError("company robots disallow must prevent crawling")

    output = asyncio.run(research_company({"organisation_number": ORG, "name": "Example AS",
        "website_candidates": ["https://example.no/"]}, Disallowed(), enable_keyless=False, phase="verify"))
    assert output.audit["candidates"]
    for candidate in output.audit["candidates"]:
        assert candidate["source"] and candidate["identity_gate_tier"] == "not_evaluated"
        assert candidate["decision"] == "blocked_robots"
