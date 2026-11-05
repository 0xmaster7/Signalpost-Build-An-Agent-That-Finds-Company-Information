import asyncio

import pytest

from signalpost.network import NetworkGateway
from signalpost.websites import (_identifier_spans, _negative_subject_context,
    _resolve_same_document_relationship, research_company)


ORG = "123456789"


@pytest.mark.parametrize("value", ["123456789", "123 456 789", "NO 123456789 MVA", "123.456.789"])
def test_org_identifier_formats_normalize(value):
    assert [item[0] for item in _identifier_spans(value)] == [ORG]


@pytest.mark.parametrize("value", ["0123456789", "123/456/789", "123 456 780"])
def test_org_identifier_formats_keep_boundaries(value):
    assert not _identifier_spans(value) or all(item[0] != ORG for item in _identifier_spans(value))


def test_formatted_foreign_identifier_remains_a_negative_subject_mention():
    assert _negative_subject_context("Customer: Example AS, org. no. 123 456 789", ORG, ["Example AS"])


def test_same_document_reference_requires_unique_id():
    doc = [{"@graph": [
        {"@id": "#site", "@type": "WebSite", "publisher": {"@id": "#org"}},
        {"@id": "#org", "@type": "Organization", "name": "Example AS"},
    ]}]
    assert _resolve_same_document_relationship(doc[0]["@graph"][0]["publisher"], doc) == [doc[0]["@graph"][1]]
    doc[0]["@graph"].append({"@id": "#org", "@type": "Organization", "name": "Unrelated AS"})
    assert _resolve_same_document_relationship(doc[0]["@graph"][0]["publisher"], doc) == []


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.timeouts = []

    async def request(self, url, headers, timeout):
        self.timeouts.append(timeout)
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def gateway_for(responses, monkeypatch, timeout=4):
    transport = FakeTransport(responses)
    gateway = NetworkGateway(transport=transport, timeout=timeout)
    monkeypatch.setattr(gateway, "_validate_host", lambda _url: None)
    return gateway, transport


@pytest.mark.parametrize("status,expected", [(404, "allowed"), (403, "unusable"), (503, "unreachable")])
def test_robots_http_causes_are_not_collapsed(status, expected, monkeypatch):
    response = (status, {}, b"", "https://example.no/robots.txt")
    gateway, _transport = gateway_for([response, response] if status == 503 else [response], monkeypatch)
    assert asyncio.run(gateway.robots_decision("https://example.no/", "Bot"))[0] == expected


def test_real_robots_disallow_stays_blocked(monkeypatch):
    body = b"User-agent: *\nDisallow: /"
    gateway, _transport = gateway_for([(200, {}, body, "https://example.no/robots.txt")], monkeypatch)
    assert asyncio.run(gateway.robots_decision("https://example.no/", "Bot"))[0] == "disallowed"


def test_transient_robots_failure_retries_once_with_longer_timeout(monkeypatch):
    gateway, transport = gateway_for([asyncio.TimeoutError(),
        (200, {}, b"User-agent: *\n", "https://example.no/robots.txt")], monkeypatch)
    assert asyncio.run(gateway.robots_decision("https://example.no/", "Bot"))[0] == "allowed"
    assert transport.timeouts == [4, 8]
    assert gateway.ledger.physical_requests == 2


def test_candidate_audit_records_source_robots_fetch_and_rejection():
    class CandidateGateway:
        class Ledger:
            entries = []

        ledger = Ledger()

        def set_rate_limit(self, *args):
            pass

        async def robots_decision(self, *args, **kwargs):
            return "allowed", None

        async def fetch(self, url, **kwargs):
            return 404, {}, b"", url, "http_error"

    profile = {"organisation_number": ORG, "name": "Example AS",
        "website_candidates": [{"raw": "example.no", "source": "registry_email",
            "source_url": "https://registry.example/entity", "content_sha256": "a" * 64}]}
    result = asyncio.run(research_company(profile, CandidateGateway(), enable_keyless=False, phase="verify"))
    candidate = result.audit["candidates"][0]
    assert candidate["candidate_source"] == {"kind": "registry_email",
        "evidence_url": "https://registry.example/entity", "evidence_sha256": "a" * 64}
    assert candidate["robots_cause"] == "allowed"
    assert candidate["fetch_result"] == {"status": 404, "outcome": "http_error"}
    assert candidate["identity_gate_tier"] == "ambiguous"
    assert candidate["rejection_reason"] == "rejected_http"
    assert candidate["identity_rejection_reason"] == "insufficient_direct_ownership_proof"
