from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import sys
import tempfile
import time
import tracemalloc
import unittest
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from signalpost.adapter import to_evaluator, validate_vendor_payload
from signalpost.inputs import load_input, normalize_org_number, parse_records
from signalpost.models import Claim, Envelope, Evidence, PublicState, RefreshState, Section, SourceSnapshot, empty_section
from signalpost.network import NetworkGateway, NetworkPolicyError, StructuredLogger, UrlLibTransport, canonical_url, classify_response, registered_domain, robots_directives, validate_public_host
from signalpost.operations import Budget, OrderedAtomicWriter, RunBudget
from signalpost.run import main
from signalpost.brreg import (SUPPORTED_CURRENCY_CODES, cutoff_identity, financial_records, group_relationships,
    normalize_entity, role_records, subunit_page, fetch_company, supported_currency)
from signalpost.inputs import stream_registry_matches
import signalpost.run as run_module


SECTIONS = {name: empty_section() for name in (
    "identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
    "hiring_activity", "claims_evidence_states", "refresh_changes")}


def valid_envelope(row: int = 1) -> Envelope:
    now = datetime.now(timezone.utc)
    evidence = Evidence(evidence_id="e1", source_url="https://data.brreg.no/x", retrieved_at=now,
                        content_sha256="a" * 64, extraction_method="json_pointer",
                        subject_organisation_number="923609016", source_snapshot_ids=["registry_fixture"])
    claim = Claim(claim_id="c1", organisation_number="923609016", section="identity_brand", field_family="identity",
                  subject_id="923609016", field="legal_name", value="Example AS", state=PublicState.AVAILABLE,
                  scope="legal_entity", verification_rule_id="fixture_exact_org_v1", verification_score="1",
                  evidence_ids=["e1"], source_snapshot_ids=["registry_fixture"])
    snapshot = SourceSnapshot(source_id="registry_fixture", source_url="https://data.brreg.no/x", retrieved_at=now,
                              content_sha256="a" * 64)
    sections = {name: section.model_copy(deep=True) for name, section in SECTIONS.items()}
    sections["identity_brand"].claims = [claim]
    sections["claims_evidence_states"].claims = [claim]
    return Envelope(input_ref=f"row:{row}", row_number=row, organisation_number="923609016",
                    terminal_state=PublicState.AVAILABLE, sections=sections,
                    refresh=RefreshState(), claims=[claim], evidence=[evidence], source_snapshots=[snapshot], batch_id="b1", evidence_cutoff=now)


class InputContractTests(unittest.TestCase):
    def test_mod11_and_leading_zero_are_textual(self):
        self.assertEqual(normalize_org_number(" 923 609 016 "), ("923609016", True))
        self.assertEqual(normalize_org_number("923609010"), ("923609010", False))
        normalized, valid = normalize_org_number("012345676")
        self.assertEqual(normalized, "012345676")
        self.assertIsInstance(normalized, str)
        self.assertFalse(valid)
        self.assertEqual(normalize_org_number(923609010), ("923609010", False))
        self.assertEqual(normalize_org_number(123456789.0), ("", False))

    def test_duplicates_preserve_input_rows_and_malformed_row_isolated(self):
        rows = parse_records('923609016\nnot-json\n923609016\n', "plain")
        self.assertEqual(len(rows), 3)
        self.assertEqual([row.organisation_number for row in rows], ["923609016", "notjson", "923609016"])
        self.assertEqual([row.input_ref for row in rows], ["row:1", "row:2", "row:3"])

    def test_jsonl_bad_line_does_not_drop_neighbor_rows(self):
        rows = parse_records('{"orgnr":"923609016"}\n{broken}\n', "jsonl")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].organisation_number, "923609016")
        self.assertEqual(rows[1].organisation_number, "")

    def test_auto_detects_tsv_and_invalid_utf8_row_isolated(self):
        rows = parse_records("organisation_number\tname\n923609016\tValid AS\n", "auto")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].organisation_number, "923609016")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad.jsonl"
            source.write_bytes(b'{"organisation_number":"923609016"}\n{\xff}\n{"organisation_number":"923609016"}\n')
            parsed = load_input(source, "jsonl")
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0].organisation_number, "923609016")
        self.assertEqual(parsed[1].organisation_number, "")
        self.assertEqual(parsed[2].organisation_number, "923609016")


class EnvelopeContractTests(unittest.TestCase):
    def test_seven_sections_states_and_adapter_fixture(self):
        env = valid_envelope()
        payload = to_evaluator(env)
        self.assertEqual(len(payload["sections"]), 7)
        self.assertEqual(payload["terminal_state"], "available")
        self.assertEqual(set(item.value for item in PublicState), {
            "available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"})
        self.assertEqual(payload["evidence"][0]["content_sha256"], "a" * 64)

    def test_available_claim_requires_present_hashed_evidence(self):
        now = datetime.now(timezone.utc)
        with self.assertRaisesRegex(ValueError, "present evidence"):
            claim = Claim(claim_id="c", organisation_number="923609016", section="identity_brand", field_family="identity",
                          subject_id="923609016", field="name", value="x", state=PublicState.AVAILABLE,
                          scope="legal_entity", verification_rule_id="test", verification_score="1", evidence_ids=["missing"],
                          source_snapshot_ids=["snapshot"])
            evidence = Evidence(evidence_id="present", source_url="https://example.com", retrieved_at=now,
                                content_sha256="a" * 64, extraction_method="test",
                                subject_organisation_number="923609016", source_snapshot_ids=["snapshot"])
            Envelope(input_ref="r", row_number=1, organisation_number="923609016", terminal_state=PublicState.AVAILABLE,
                     sections=SECTIONS, refresh=RefreshState(), claims=[claim], evidence=[evidence],
                     source_snapshots=[SourceSnapshot(source_id="snapshot", source_url="https://example.com", retrieved_at=now,
                                                      content_sha256="b" * 64)], batch_id="b", evidence_cutoff=now)

    def test_evidence_must_bind_to_the_claim_subject_snapshot_url_and_hash(self):
        mutations = (
            lambda env: setattr(env.evidence[0], "source_snapshot_ids", ["missing"]),
            lambda env: setattr(env.evidence[0], "source_url", "https://other.example/x"),
            lambda env: setattr(env.evidence[0], "content_sha256", "b" * 64),
            lambda env: setattr(env.evidence[0], "subject_organisation_number", "923609028"),
        )
        for mutate in mutations:
            env = valid_envelope().model_copy(deep=True)
            mutate(env)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                Envelope.model_validate(env.model_dump())

    def test_duplicate_evidence_and_snapshot_identifiers_are_rejected(self):
        env = valid_envelope().model_copy(deep=True)
        env.evidence.append(env.evidence[0].model_copy(deep=True))
        with self.assertRaisesRegex(ValueError, "evidence identifiers must be unique"):
            Envelope.model_validate(env.model_dump())
        env = valid_envelope().model_copy(deep=True)
        env.source_snapshots.append(env.source_snapshots[0].model_copy(deep=True))
        with self.assertRaisesRegex(ValueError, "snapshot identifiers must be unique"):
            Envelope.model_validate(env.model_dump())

    def test_seven_sections_are_required(self):
        with self.assertRaisesRegex(ValueError, "seven canonical sections"):
            Envelope(input_ref="r", row_number=1, organisation_number="923609016", terminal_state=PublicState.FAILED,
                     sections={"identity_brand": empty_section()}, refresh=RefreshState(), batch_id="b",
                     evidence_cutoff=datetime.now(timezone.utc))

    def test_adapter_rejects_missing_required_vendor_fields(self):
        with self.assertRaisesRegex(ValueError, "missing required fields"):
            validate_vendor_payload({"input_ref": "x"})

    def test_adapter_matches_provisional_golden_fixture(self):
        golden = json.loads((ROOT / "signalpost-starter-kit/tests/fixtures/contracts/evaluator-provisional.json").read_text())
        payload = to_evaluator(valid_envelope())
        self.assertEqual(set(payload), set(golden["top_level_fields"]))
        self.assertEqual(set(payload["sections"]), set(golden["section_names"]))


class OutputAndBudgetTests(unittest.IsolatedAsyncioTestCase):
    def test_output_is_sorted_and_atomic_replacement_failure_preserves_old(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.jsonl"
            path.write_text("old\n")
            with patch("signalpost.operations.os.replace", side_effect=OSError("simulated crash")):
                with self.assertRaises(OSError):
                    OrderedAtomicWriter(path).write([valid_envelope(2), valid_envelope(1)])
            self.assertEqual(path.read_text(), "old\n")
            OrderedAtomicWriter(path).write([valid_envelope(2), valid_envelope(1)])
            self.assertEqual([json.loads(line)["input_ref"] for line in path.read_text().splitlines()], ["row:1", "row:2"])

    async def test_budget_request_reservation_is_atomic(self):
        budget = Budget(RunBudget(hard_seconds=10, soft_seconds=1, completion_reserve_seconds=1, physical_request_limit=7))
        results = await asyncio.gather(*(budget.reserve_request() for _ in range(40)))
        self.assertEqual(sum(results), 7)
        self.assertEqual(budget.physical_requests, 7)

    async def test_decimal_cost_reservation_does_not_use_float_rounding(self):
        budget = Budget(RunBudget(hard_seconds=10, soft_seconds=1, completion_reserve_seconds=1,
                                  physical_request_limit=10, paid_cost_limit=Decimal("0.3")))
        self.assertTrue(await budget.reserve_request(cost=Decimal("0.1")))
        self.assertTrue(await budget.reserve_request(cost=Decimal("0.1")))
        self.assertTrue(await budget.reserve_request(cost=Decimal("0.1")))
        self.assertFalse(await budget.reserve_request(cost=Decimal("0.0001")))
        self.assertEqual(str(budget.cost), "0.3")

    async def test_negative_or_non_finite_paid_cost_is_rejected(self):
        for value in (Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RunBudget(paid_cost_limit=value)
        budget = Budget(RunBudget(hard_seconds=10, soft_seconds=1, completion_reserve_seconds=1))
        for value in (Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(request_cost=value), self.assertRaises(ValueError):
                await budget.reserve_request(cost=value)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    async def request(self, url, headers, timeout):
        self.urls.append(url)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class NetworkSecurityTests(unittest.IsolatedAsyncioTestCase):
    def test_url_canonicalization_and_ssrf_address_classes(self):
        self.assertEqual(canonical_url("HTTPS://Example.COM:443/a b?q=x#frag"), "https://example.com/a%20b?q=x")
        with self.assertRaises(NetworkPolicyError):
            canonical_url("file:///etc/passwd")
        with self.assertRaises(NetworkPolicyError):
            canonical_url("https://user:pass@example.com")
        for address in ("127.0.0.1", "10.0.0.2", "169.254.1.1", "[::1]", "192.168.1.2"):
            with self.assertRaises(NetworkPolicyError, msg=address):
                validate_public_host(f"http://{address}/")
        validate_public_host("https://8.8.8.8/")

    async def test_retry_and_each_physical_attempt_is_ledgered(self):
        fake = FakeTransport([OSError("temporary"), (200, {}, b"hello", "https://8.8.8.8/a")])
        gateway = NetworkGateway(fake, retries=1)
        status, _, body, _, outcome = await gateway.fetch("https://8.8.8.8/a", use_robots=False)
        self.assertEqual((status, body, outcome), (200, b"hello", "ok"))
        self.assertEqual(gateway.ledger.physical_requests, 2)
        self.assertEqual(gateway.ledger.logical_requests, 1)
        self.assertEqual([entry.outcome for entry in gateway.ledger.entries], ["transport_error", "received"])

    async def test_concurrent_requests_respect_per_host_start_rate(self):
        starts = []
        class TimedTransport:
            async def request(self, url, headers, timeout):
                starts.append(time.monotonic())
                return 200, {}, b"ok", url
        gateway = NetworkGateway(TimedTransport(), retries=0)
        gateway.set_rate_limit("8.8.8.8", 30)
        await asyncio.gather(*(gateway.fetch(f"https://8.8.8.8/{i}", use_robots=False) for i in range(4)))
        self.assertEqual(len(starts), 4)
        self.assertTrue(all(right - left >= 0.025 for left, right in zip(starts, starts[1:])))

    async def test_trusted_proxy_mode_uses_configured_proxy_path(self):
        with patch.dict(os.environ, {"http_proxy": "http://proxy.fixture:8080", "https_proxy": "http://proxy.fixture:8080"}):
            transport = UrlLibTransport(trust_env=True)
            proxy_handler = next(handler for handler in transport._opener.handlers if hasattr(handler, "proxies"))
            self.assertEqual(proxy_handler.proxies.get("https"), "http://proxy.fixture:8080")
        fake = FakeTransport([(200, {}, b"proxied", "https://example.com/fixture")])
        gateway = NetworkGateway(fake, trusted_proxy=True, proxy_url="http://proxy.fixture:8080", retries=0)
        status, _, body, _, outcome = await gateway.fetch("https://example.com/fixture", use_robots=False)
        self.assertEqual((status, body, outcome), (200, b"proxied", "ok"))
        self.assertEqual(gateway.ledger.physical_requests, 1)

    async def test_redirect_to_private_destination_rejected_and_counted(self):
        fake = FakeTransport([(302, {"Location": "http://127.0.0.1/admin"}, b"", "https://8.8.8.8/")])
        gateway = NetworkGateway(fake, retries=0)
        with self.assertRaises(NetworkPolicyError):
            await gateway.fetch("https://8.8.8.8/", use_robots=False)
        self.assertEqual(gateway.ledger.physical_requests, 1)

    async def test_source_allowlist_rejects_cross_host_redirect(self):
        fake = FakeTransport([(302, {"Location": "https://1.1.1.1/out"}, b"", "https://8.8.8.8/start")])
        gateway = NetworkGateway(fake, retries=0)
        with self.assertRaises(NetworkPolicyError):
            await gateway.fetch("https://8.8.8.8/start", use_robots=False, allowed_hosts={"8.8.8.8"})
        self.assertEqual(gateway.ledger.physical_requests, 1)

    async def test_safe_redirect_hop_is_counted(self):
        fake = FakeTransport([
            (302, {"Location": "https://1.1.1.1/next"}, b"", "https://8.8.8.8/start"),
            (200, {}, b"done", "https://1.1.1.1/next"),
        ])
        gateway = NetworkGateway(fake, retries=0)
        result = await gateway.fetch("https://8.8.8.8/start", use_robots=False)
        self.assertEqual(result[-1], "ok")
        self.assertEqual(gateway.ledger.physical_requests, 2)
        self.assertEqual(gateway.ledger.logical_requests, 1)

    async def test_robots_404_allows_and_5xx_conservatively_skips(self):
        allowed_gateway = NetworkGateway(FakeTransport([(404, {}, b"", "https://8.8.8.8/robots.txt"), (200, {}, b"ok", "https://8.8.8.8/a")]), retries=0)
        _, _, _, _, outcome = await allowed_gateway.fetch("https://8.8.8.8/a")
        self.assertEqual(outcome, "ok")
        skip_gateway = NetworkGateway(FakeTransport([(503, {}, b"", "https://8.8.8.8/robots.txt")]), retries=0)
        self.assertEqual(await skip_gateway.robots_allowed("https://8.8.8.8/a", "SignalpostBot"), (False, None))
        oversized = NetworkGateway(FakeTransport([(200, {}, b"x" * (256 * 1024 + 1), "https://8.8.8.8/robots.txt")]), retries=0)
        self.assertEqual(await oversized.robots_allowed("https://8.8.8.8/a", "SignalpostBot"), (False, None))

    async def test_explicit_robots_disallow_remains_blocked_for_website_and_brreg_api(self):
        robots = (200, {}, b"User-agent: *\nDisallow: /", "https://data.brreg.no/robots.txt")
        site_gateway = NetworkGateway(FakeTransport([robots]), retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("195.43.63.68",)):
            site_result = await site_gateway.fetch("https://data.brreg.no/company", purpose="page")
        self.assertEqual(site_result[-1], "robots_disallowed")
        api_gateway = NetworkGateway(FakeTransport([robots]), retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("195.43.63.68",)):
            api_result = await api_gateway.fetch("https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                purpose="entity", allowed_hosts={"data.brreg.no"}, access_profile="brreg_structured_api")
        self.assertEqual(api_result[-1], "robots_disallowed")
        self.assertEqual(api_gateway.ledger.physical_requests, 1)

    async def test_robots_transport_failure_is_distinct_and_ordinary_crawl_stays_fail_closed(self):
        fake = FakeTransport([OSError("connection reset after request")])
        gateway = NetworkGateway(fake, retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("93.184.216.34",)):
            result = await gateway.fetch("https://example.com/about", purpose="page")
        self.assertEqual(result[-1], "robots_unreachable")
        self.assertNotEqual(result[-1], "robots_disallowed")
        self.assertEqual(fake.urls, ["https://example.com/robots.txt"])

    async def test_brreg_structured_api_only_continues_after_robots_transport_failure(self):
        fake = FakeTransport([
            OSError("connection reset after request"),
            (200, {}, b'{"organisasjonsnummer":"923609016"}',
             "https://data.brreg.no/enhetsregisteret/api/enheter/923609016"),
        ])
        gateway = NetworkGateway(fake, retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("195.43.63.68",)):
            result = await gateway.fetch("https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                purpose="entity", allowed_hosts={"data.brreg.no"}, access_profile="brreg_structured_api")
        self.assertEqual(result[-1], "ok")
        self.assertEqual(len(fake.urls), 2)
        self.assertEqual(fake.urls[0], "https://data.brreg.no/robots.txt")
        self.assertIn("/enhetsregisteret/api/enheter/923609016", fake.urls[1])

    async def test_brreg_api_does_not_continue_after_unusable_robots_response(self):
        fake = FakeTransport([
            (200, {}, b"Just a moment... verify you are human", "https://data.brreg.no/robots.txt"),
            (200, {}, b'{"organisasjonsnummer":"923609016"}',
             "https://data.brreg.no/enhetsregisteret/api/enheter/923609016"),
        ])
        gateway = NetworkGateway(fake, retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("195.43.63.68",)):
            result = await gateway.fetch("https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                purpose="entity", allowed_hosts={"data.brreg.no"}, access_profile="brreg_structured_api")
        self.assertEqual(result[-1], "robots_unusable")
        self.assertEqual(fake.urls, ["https://data.brreg.no/robots.txt"])

    async def test_brreg_api_profile_cannot_be_reused_for_arbitrary_websites(self):
        fake = FakeTransport([])
        gateway = NetworkGateway(fake, retries=0)
        for url, purpose in (
            ("https://example.com/enhetsregisteret/api/enheter/923609016", "entity"),
            ("https://data.brreg.no/company/923609016", "entity"),
            ("https://data.brreg.no/enhetsregisteret/api/enheter/923609016", "page"),
        ):
            with self.assertRaises(NetworkPolicyError):
                await gateway.fetch(url, purpose=purpose, access_profile="brreg_structured_api")
        self.assertEqual(fake.urls, [])

    async def test_brreg_api_profile_rejects_port_credentials_queries_and_unapproved_redirects(self):
        gateway = NetworkGateway(FakeTransport([]), retries=0)
        invalid = (
            "https://data.brreg.no:8443/enhetsregisteret/api/enheter/923609016",
            "https://user@data.brreg.no/enhetsregisteret/api/enheter/923609016",
            "https://data.brreg.no/enhetsregisteret/api/enheter/923609016?unrelated=1",
            "https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet=923609016&evil=1",
        )
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(NetworkPolicyError):
                await gateway.fetch(url, purpose="subunits" if "underenheter" in url else "entity",
                    access_profile="brreg_structured_api")
        redirect = FakeTransport([
            (302, {"Location": "https://example.com/attacker"}, b"", "https://data.brreg.no/enhetsregisteret/api/enheter/923609016"),
        ])
        gateway = NetworkGateway(redirect, retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("195.43.63.68",)):
            with self.assertRaises(NetworkPolicyError):
                await gateway.fetch("https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                    purpose="entity", allowed_hosts={"data.brreg.no"}, access_profile="brreg_structured_api", use_robots=False)
        self.assertEqual(len(gateway.ledger.entries), 1)

    async def test_parallel_same_origin_requests_share_one_robots_fetch(self):
        responses = [(200, {}, b"", "https://8.8.8.8/robots.txt")] + [
            (200, {}, b"ok", f"https://8.8.8.8/{i}") for i in range(10)]
        gateway = NetworkGateway(FakeTransport(responses), retries=0)
        results = await asyncio.gather(*(gateway.fetch(f"https://8.8.8.8/{i}") for i in range(10)))
        self.assertTrue(all(result[-1] == "ok" for result in results))
        self.assertEqual(sum(entry.purpose == "robots" for entry in gateway.ledger.entries), 1)
        self.assertEqual(gateway.ledger.physical_requests, 11)

    async def test_robots_rules_crawl_delay_and_200_waf_soft_404(self):
        fake = FakeTransport([(200, {}, b"User-agent: *\nDisallow: /private\nCrawl-delay: 0.1\n", "https://8.8.8.8/robots.txt")])
        gateway = NetworkGateway(fake, retries=0)
        self.assertEqual(await gateway.robots_allowed("https://8.8.8.8/private/x", "SignalpostBot"), (False, 0.1))
        self.assertEqual(classify_response(200, {}, b"Just a moment..."), "waf_challenge")
        self.assertEqual(classify_response(200, {}, b"<title>404 Not Found</title>"), "soft_404")

    async def test_real_gateway_robots_wildcards_end_anchor_user_agent_and_allow_precedence(self):
        async def outcome(rules: bytes, url: str, agent: str = "SignalpostBot"):
            host = "https://8.8.8.8"
            fake = FakeTransport([(200, {}, rules, host + "/robots.txt"), (200, {}, b"ok", url)])
            gateway = NetworkGateway(fake, retries=0)
            result = await gateway.fetch(url, user_agent=agent)
            return result[-1], fake.urls

        blocked, requested = await outcome(b"User-agent: *\nDisallow: /private$\n", "https://8.8.8.8/private")
        self.assertEqual(blocked, "robots_disallowed")
        self.assertEqual(requested, ["https://8.8.8.8/robots.txt"])
        allowed, _ = await outcome(b"User-agent: *\nDisallow: /private$\n", "https://8.8.8.8/private/more")
        self.assertEqual(allowed, "ok")
        wildcard, _ = await outcome(b"User-agent: *\nDisallow: /private/*/secret\n", "https://8.8.8.8/private/a/secret")
        self.assertEqual(wildcard, "robots_disallowed")
        tie_allow, _ = await outcome(b"User-agent: *\nDisallow: /private\nAllow: /private\n", "https://8.8.8.8/private")
        self.assertEqual(tie_allow, "ok")
        specificity, _ = await outcome(b"User-agent: *\nDisallow: /\nUser-agent: SignalpostBot\nDisallow: /private\n", "https://8.8.8.8/public")
        self.assertEqual(specificity, "ok")
        encoded, _ = await outcome(b"User-agent: *\nDisallow: /private/%2Fsecret\n", "https://8.8.8.8/private/%2fsecret")
        self.assertEqual(encoded, "robots_disallowed")
        root, _ = await outcome(b"User-agent: *\nDisallow: /\n", "https://8.8.8.8/")
        self.assertEqual(root, "robots_disallowed")

    def test_meta_header_directives_and_public_suffix(self):
        directives = robots_directives({"X-Robots-Tag": "SignalpostBot: noarchive"},
                                       b'<meta name="robots" content="noindex,nofollow">')
        self.assertEqual(directives, {"noindex", "nofollow", "noarchive"})
        self.assertEqual(registered_domain("www.example.co.uk"), "example.co.uk")
        self.assertIsNone(registered_domain("8.8.8.8"))

    async def test_gateway_stops_at_budget_limit(self):
        budget = Budget(RunBudget(hard_seconds=10, soft_seconds=1, completion_reserve_seconds=1, physical_request_limit=1))
        fake = FakeTransport([(200, {}, b"ok", "https://8.8.8.8/")])
        gateway = NetworkGateway(fake, retries=0, budget=budget)
        await gateway.fetch("https://8.8.8.8/", use_robots=False)
        result = await gateway.fetch("https://8.8.8.8/next", use_robots=False)
        self.assertEqual(result[-1], "budget_exhausted")
        self.assertEqual(len(fake.urls), 1)

    async def test_stalled_response_times_out_and_is_ledgered(self):
        class SlowTransport:
            async def request(self, url, headers, timeout):
                await asyncio.sleep(0.1)
                return 200, {}, b"late", url
        gateway = NetworkGateway(SlowTransport(), timeout=0.01, retries=0)
        result = await gateway.fetch("https://8.8.8.8/", use_robots=False)
        self.assertEqual(result[-1], "timeout")
        self.assertEqual(gateway.ledger.physical_requests, 1)

    async def test_expansion_bomb_is_capped(self):
        packed = gzip.compress(b"z" * 50000)
        fake = FakeTransport([(200, {"Content-Encoding": "gzip", "Content-Length": str(len(packed))}, packed, "https://8.8.8.8/")])
        gateway = NetworkGateway(fake, retries=0, response_cap=1000)
        result = await gateway.fetch("https://8.8.8.8/", use_robots=False)
        self.assertEqual(result[-1], "decompression_limit")

    def test_secret_redaction(self):
        event = StructuredLogger.emit("request", api_key="abcdef123", authorization="Bearer secret")
        self.assertNotIn("abcdef123", event)
        self.assertNotIn("Bearer", event)
        self.assertNotIn("secret", event)


class OfflineCliTests(unittest.TestCase):
    def test_cli_generates_n_envelopes_from_offline_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.jsonl").write_text('{"organisation_number":"923609016"}\n{"organisation_number":"923609016"}\n')
            (root / "registry.jsonl").write_text('{"organisation_number":"923609016","name":"Example AS"}\n')
            (root / "config.json").write_text('{"budget":{"hard_seconds":10,"soft_seconds":0,"completion_reserve_seconds":0,"physical_request_limit":0,"paid_cost_limit":"0"}}')
            original = run_module._envelope
            def assert_shells_exist(*args, **kwargs):
                pending = root / "out.jsonl.pending.jsonl"
                self.assertEqual(len(pending.read_text().splitlines()), 2)
                return original(*args, **kwargs)
            with patch("signalpost.run._envelope", side_effect=assert_shells_exist):
                code = main(["--input", str(root / "input.jsonl"), "--registry-snapshot", str(root / "registry.jsonl"),
                             "--output", str(root / "out.jsonl"), "--state-output", str(root / "state.sqlite"),
                             "--config", str(root / "config.json"), "--batch-id", "fixture"])
            self.assertEqual(code, 0)
            envelopes = [json.loads(line) for line in (root / "out.jsonl").read_text().splitlines()]
            self.assertEqual(len(envelopes), 2)
            self.assertEqual([item["input_ref"] for item in envelopes], ["row:1", "row:2"])
            self.assertTrue(all(item["terminal_state"] == "available" for item in envelopes))
            self.assertTrue(all(len(item["sections"]) == 7 for item in envelopes))
            self.assertTrue(all(item["batch"]["evidence_cutoff"] for item in envelopes))
            self.assertTrue(all(set(item["synthesis"]) == {"schema_version", "summary"} for item in envelopes))
            self.assertFalse((root / "out.jsonl.pending.jsonl").exists())


class GatewayArchitectureTests(unittest.TestCase):
    def test_production_http_implementation_is_confined_to_gateway(self):
        patterns = ("urllib.request", "requests.get(", "requests.post(", "httpx.AsyncClient(", "socket.create_connection(")
        for path in (ROOT / "signalpost").glob("*.py"):
            if path.name == "network.py":
                continue
            content = path.read_text(encoding="utf-8")
            for pattern in patterns:
                self.assertNotIn(pattern, content, f"unledgered HTTP path in {path.name}")


class BrregFoundationTests(unittest.IsolatedAsyncioTestCase):
    def test_runner_distinguishes_malformed_empty_failed_and_available_accounts(self):
        target = "923609016"
        period = {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}
        valid_record = {"id": "valid", "regnskapstype": "SELSKAP", "regnskapsperiode": period,
            "virksomhet": {"organisasjonsnummer": target},
            "valuta": "NOK", "enhet": "NOK", "resultatregnskapResultat": {"driftsresultat": {
                "driftsinntekter": {"sumDriftsinntekter": 10}}}}
        cases = (
            ("malformed", {"unexpected": "shape"}, 200, "failed", "BRREG_ACCOUNTS_MALFORMED"),
            ("empty", [], 200, "not_available", None),
            ("transport_failure", [], 503, "failed", "BRREG_ACCOUNTS_503"),
            ("available", [valid_record], 200, "available", None),
        )
        for label, accounts_body, accounts_status, expected_state, expected_error in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, output, state = root / "input.jsonl", root / "output.jsonl", root / "state.sqlite"
                source.write_text(json.dumps({"organisation_number": target}) + "\n", encoding="utf-8")

                class RoutingTransport:
                    async def request(self, url, headers, timeout):
                        if "/regnskap/" in url:
                            body, status = accounts_body, accounts_status
                        elif url.endswith("/roller"):
                            body, status = {"rollegrupper": []}, 200
                        elif "/underenheter?" in url:
                            body, status = {"_embedded": {"underenheter": []}, "page": {"number": 0, "totalPages": 1}}, 200
                        else:
                            body, status = {"organisasjonsnummer": target, "navn": "Target AS", "organisasjonsform": {"kode": "AS"}}, 200
                        return status, {"Content-Type": "application/json"}, json.dumps(body).encode(), url

                gateway = NetworkGateway(RoutingTransport(), retries=0)
                with patch("signalpost.run.NetworkGateway", return_value=gateway), \
                     patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), \
                     patch.object(gateway, "robots_decision", return_value=("allowed", None)):
                    self.assertEqual(main(["--input", str(source), "--output", str(output),
                        "--state-output", str(state), "--batch-id", label, "--live-brreg"]), 0)
                envelope = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
                self.assertEqual(envelope["sections"]["accounts_history"]["state"], expected_state)
                self.assertEqual(any(error["code"] == expected_error for error in envelope["errors"])
                    if expected_error else False, bool(expected_error))
                financial = [claim for claim in envelope["claims"] if claim["field_family"] == "financial"]
                self.assertEqual(bool(financial), label == "available")
                self.assertEqual(envelope["terminal_state"], "available")

    async def test_run_start_fallback_allows_current_live_identity_but_not_without_explicit_policy(self):
        entity = {"organisasjonsnummer": "923609003", "navn": "Target AS", "organisasjonsform": {"kode": "AS"}}
        accounts = [{"id": "x", "regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"},
                     "valuta": "NOK", "eiendeler": {"sumEiendeler": 12}}]
        class RoutingTransport:
            async def request(self, url, headers, timeout):
                if "/regnskap/" in url: value = accounts
                elif url.endswith("/roller"): value = {"rollegrupper": []}
                elif "/underenheter?" in url: value = {"_embedded": {"underenheter": []}, "page": {"number": 0, "totalPages": 1}}
                else: value = entity
                return 200, {"Content-Type": "application/json"}, json.dumps(value).encode(), url
        cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc)
        def gateway(): return NetworkGateway(RoutingTransport(), retries=0)
        async def fetch(allow):
            item = gateway()
            with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), patch.object(item, "robots_decision", return_value=("allowed", None)):
                return await fetch_company("923609003", item, cutoff, allow_current_identity_after_run_start=allow)
        excluded = await fetch(False)
        included = await fetch(True)
        self.assertFalse(any(c.section == "identity_brand" for c in excluded.claims))
        self.assertTrue(any(c.field == "organisation_number" and c.value == "923609003" for c in included.claims))
        self.assertTrue(any(c.field == "name" and c.value == "Target AS" for c in included.claims))
        self.assertTrue(all(c.period_end is None or c.period_end <= cutoff for c in included.claims if c.section != "identity_brand"))

    def test_all_financial_history_periods_and_corrections_are_retained(self):
        rows = []
        for year in range(2018, 2024):
            rows.append({"id": f"filing-{year}", "versjon": 1, "regnskapstype": "SELSKAP",
                         "regnskapsperiode": {"fraDato": f"{year}-04-01", "tilDato": f"{year + 1}-03-31"},
                         "valuta": "NOK", "resultatregnskapResultat": {"driftsresultat": {
                             "driftsinntekter": {"sumDriftsinntekter": year * 100}, "driftsresultat": year * 10}}})
        rows.append({**rows[-1], "versjon": 2, "resultatregnskapResultat": {"driftsresultat": {
            "driftsinntekter": {"sumDriftsinntekter": 999}, "driftsresultat": 91}}})
        normalized = financial_records(rows)
        self.assertEqual(len(normalized), 7)
        self.assertEqual([item["period_start"] for item in normalized[:2]], ["2018-04-01", "2019-04-01"])
        self.assertEqual([item["metrics"]["revenue"] for item in normalized[-2:]], [202300, 999])
        self.assertEqual(normalized[0]["scope"], "legal_entity")

    def test_metric_label_mismatch_does_not_get_promoted(self):
        records = financial_records([{"regnskapstype": "SELSKAP", "regnskapsperiode": {},
                                      "resultatregnskapResultat": {"driftsresultat": {
                                          "driftsinntekter": {"sumAnnenInntekt": 123456}}}}])
        self.assertIsNone(records[0]["metrics"]["revenue"])

    def test_group_scope_is_explicit_and_separate(self):
        records = financial_records([
            {"regnskapstype": "SELSKAP", "regnskapsperiode": {}, "eiendeler": {"sumEiendeler": 10}},
            {"regnskapstype": "KONSERN", "regnskapsperiode": {}, "eiendeler": {"sumEiendeler": 20}},
        ])
        self.assertEqual([row["scope"] for row in records], ["legal_entity", "group"])

    def test_unknown_financial_scope_stays_unknown(self):
        records = financial_records([{"regnskapstype": "SPECIAL", "regnskapsperiode": {}, "eiendeler": {"sumEiendeler": 20}}])
        self.assertEqual(records[0]["scope"], "unknown")

    def test_non_finite_and_malformed_financial_metrics_are_not_parsed_as_numbers(self):
        records = financial_records([{"id": "bad", "regnskapstype": "SELSKAP",
            "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}, "valuta": "NOK",
            "eiendeler": {"sumEiendeler": float("nan")},
            "resultatregnskapResultat": {"driftsresultat": {"driftsresultat": "12.0"}}}])
        self.assertIsNone(records[0]["metrics"]["total_assets"])
        self.assertIsNone(records[0]["metrics"]["operating_result"])

    def test_group_tree_keeps_target_and_parent_relationships_separate(self):
        tree = {"organisasjonsnummer": "923609003", "navn": "Target AS", "children": [{
            "organisasjonsnummer": "923609016", "navn": "Subsidiary AS", "nivaa": 1, "knytningsform": "SUBSIDIARY",
            "children": [{"organisasjonsnummer": "923609028", "navn": "Workplace", "nivaa": 2}]}]}
        relationships = group_relationships(tree, "923609003")
        self.assertEqual([r["organisation_number"] for r in relationships], ["923609016", "923609028"])
        self.assertEqual(relationships[0]["parent_organisation_number"], "923609003")
        self.assertEqual(relationships[1]["parent_organisation_number"], "923609016")

    def test_cutoff_keeps_frozen_identity_when_live_rename_is_after_cutoff(self):
        cutoff = datetime(2026, 10, 10, tzinfo=timezone.utc)
        frozen = {"name": "Old Name AS", "as_of": "2026-10-01"}
        live = {"name": "New Name AS", "retrieved_at": "2026-10-12T00:00:00Z"}
        selected = cutoff_identity(frozen, live, cutoff)
        self.assertEqual((selected["name"], selected["source"]), ("Old Name AS", "frozen"))
        self.assertIsNone(cutoff_identity(frozen, live, datetime(2026, 9, 1, tzinfo=timezone.utc)))

    def test_frozen_snapshot_is_published_if_live_identity_is_post_cutoff(self):
        env = valid_envelope()
        env.claims = []
        env.sections["identity_brand"] = empty_section()
        env.sections["claims_evidence_states"] = empty_section()
        env.terminal_state = PublicState.NOT_AVAILABLE
        cutoff = datetime(2026, 10, 10, tzinfo=timezone.utc)
        baseline = {"organisation_number": "923609016", "name": "Frozen Name AS", "snapshot_as_of": "2026-10-01",
                    "source_url": "https://data.brreg.no/snapshot/entity", "__signalpost_snapshot_row_sha256": "b" * 64}
        env = run_module._attach_frozen_baseline(env, baseline, "a" * 64, cutoff)
        claim = next(item for item in env.claims if item.field == "legal_name")
        self.assertEqual(claim.value, "Frozen Name AS")
        self.assertEqual(claim.as_of, datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertEqual(env.terminal_state, PublicState.AVAILABLE)
        self.assertEqual(env.source_snapshots[-1].rights_status, "NLOD-2.0")

    def test_roles_keep_holder_subject_and_discard_birth_date(self):
        result = role_records({"rollegrupper": [{"type": {"kode": "STYR", "beskrivelse": "Board"}, "roller": [{
            "type": {"kode": "LEDA", "beskrivelse": "Chair"}, "person": {"navn": {"fornavn": "Ada"}, "foedselsdato": "1970-01-01"},
            "enhet": {"organisasjonsnummer": "923609016", "navn": "Holder AS"}}]}]})
        self.assertEqual(result[0]["holder_organisation_number"], "923609016")
        self.assertEqual(result[0]["holder_kind"], "organisation")
        self.assertNotIn("foedselsdato", json.dumps(result))
        self.assertEqual(role_records({"rollegrupper": [None, {"roller": [None]}]}), [])

    def test_entity_normalizer_preserves_historical_names_and_multiple_industries(self):
        normalized = normalize_entity({"organisasjonsnummer": "923609016", "historiskeNavn": [
            {"navn": "Old AS", "fraDato": "2020-01-01", "tilDato": "2022-01-01"}],
            "naeringskode1": {"kode": "01.110"}, "naeringskode2": {"kode": "02.100"}})
        self.assertEqual(normalized["historical_names"][0]["name"], "Old AS")
        self.assertEqual(len(normalized["industry_codes"]), 2)

    def test_enk_entity_drops_registration_addresses(self):
        normalized = normalize_entity({"organisasjonsform": {"kode": "ENK"},
                                       "forretningsadresse": {"adresse": ["Private street 1"], "poststed": "Oslo"},
                                       "postadresse": {"adresse": ["Private box"]}})
        self.assertIsNone(normalized["business_address"])
        self.assertIsNone(normalized["postal_address"])

    def test_subunit_pagination_marks_partial_until_last_page(self):
        first = {"_embedded": {"underenheter": [{"organisasjonsnummer": "123456785"}]},
                 "_links": {"next": {"href": "?page=1"}}, "page": {"number": 0, "totalPages": 2}}
        rows, next_url, complete = subunit_page(first)
        self.assertEqual(len(rows), 1)
        self.assertFalse(complete)
        self.assertEqual(next_url, "?page=1")
        self.assertTrue(subunit_page({"_embedded": {"underenheter": []}, "page": {"number": 1, "totalPages": 2}})[2])

    async def test_live_entity_404_and_410_have_distinct_states(self):
        class StatusTransport:
            def __init__(self, entity_status): self.entity_status = entity_status
            async def request(self, url, headers, timeout):
                status = self.entity_status if "/enheter/923609003" in url and not url.endswith("/roller") else 404
                return status, {}, b"{}", url
        for status, expected in ((404, PublicState.NOT_AVAILABLE), (410, PublicState.BLOCKED)):
            gateway = NetworkGateway(StatusTransport(status), retries=0)
            with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), patch.object(gateway, "robots_decision", return_value=("allowed", None)):
                result = await fetch_company("923609003", gateway, datetime.now(timezone.utc) + timedelta(days=1))
            self.assertEqual(result.section_states["identity_brand"], expected)
            self.assertFalse(any(c.section == "identity_brand" and c.state == PublicState.AVAILABLE for c in result.claims))
            self.assertEqual(result.section_states["accounts_history"], PublicState.NOT_AVAILABLE)
            self.assertFalse(any(c.field_family == "financial" for c in result.claims))
            state_evidence_id = result.observations["identity_state_evidence_id"]
            state_evidence = next(item for item in result.evidence if item.evidence_id == state_evidence_id)
            self.assertEqual(state_evidence.extraction_method, "brreg_entity_status_v1")
            self.assertEqual(next(s.http_status for s in result.snapshots if s.source_url.endswith("/923609003")), status)

    async def test_default_cli_uses_live_brreg_without_frozen_snapshot_and_preserves_duplicate_rows(self):
        class FakeGateway:
            def __init__(self, *args, **kwargs):
                self.ledger = type("Ledger", (), {"physical_requests": 0, "logical_requests": 0, "entries": []})()
            def set_rate_limit(self, *args): pass
            async def fetch(self, url, **kwargs):
                self.ledger.logical_requests += 1
                self.ledger.physical_requests += 1
                if "/roller" in url: body = {"rollegrupper": []}
                elif "/underenheter?" in url: body = {"_embedded": {"underenheter": []}, "page": {"number": 0, "totalPages": 1}}
                elif "/regnskap/" in url: body = [{"id": "F1", "virksomhet": {"organisasjonsnummer": "923609016"}, "regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}, "valuta": "NOK", "eiendeler": {"sumEiendeler": 5}}]
                else: body = {"organisasjonsnummer": "923609016", "navn": "Target AS"}
                self.ledger.entries.append(type("Entry", (), {"purpose": kwargs["purpose"], "url": url, "status": 200, "outcome": "received"})())
                return 200, {}, json.dumps(body).encode(), url, "ok"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.jsonl").write_text('{"organisation_number":"923609016"}\n{"organisation_number":"923609016"}\n')
            with patch("signalpost.run.NetworkGateway", FakeGateway):
                code = await asyncio.to_thread(main, ["--input", str(root / "input.jsonl"), "--output", str(root / "out.jsonl"),
                                                       "--state-output", str(root / "state.sqlite"), "--batch-id", "m02-fixture"])
            output = [json.loads(line) for line in (root / "out.jsonl").read_text().splitlines()]
            self.assertEqual(code, 0)
            self.assertEqual(len(output), 2)
            self.assertEqual([env["organisation_number"] for env in output], ["923609016", "923609016"])
            self.assertTrue(all(env["sections"]["accounts_history"]["state"] == "available" for env in output))
            self.assertTrue(all(all(e["json_pointer"] and e["extraction_method"] for e in env["evidence"]) for env in output))

    def test_stream_snapshot_filters_large_jsonl_and_hashes_exact_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.jsonl"
            with path.open("w") as stream:
                for i in range(1, 411_161):
                    stream.write(json.dumps({"organisation_number": f"{i % 1_000_000_000:09d}", "name": str(i)}) + "\n")
            # Select one unique key appearing in source; output memory is bounded by request count.
            tracemalloc.start()
            matches, digest = stream_registry_matches(path, {"000000001", "000000002"})
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            self.assertLessEqual(len(matches), 2)
            self.assertEqual(len(digest), 64)
            self.assertLess(peak, 16 * 1024 * 1024)

    async def test_company_fetch_uses_exact_target_and_keeps_role_holder_distinct(self):
        entity = {"organisasjonsnummer": "923609003", "navn": "Target AS", "organisasjonsform": {"kode": "AS"}}
        accounts = [{"id": "x", "regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2024-04-01", "tilDato": "2025-03-31"},
                     "valuta": "NOK", "eiendeler": {"sumEiendeler": 12}}]
        roles = {"rollegrupper": [{"type": {"kode": "STYR", "beskrivelse": "Board"}, "roller": [{
            "type": {"kode": "LEDA", "beskrivelse": "Chair"}, "person": {"navn": {"fornavn": "A"}},
            "enhet": {"organisasjonsnummer": "923609016"}}]}]}
        subunits = {"_embedded": {"underenheter": []}, "page": {"number": 0, "totalPages": 1}}
        class RoutingTransport:
            async def request(self, url, headers, timeout):
                if "/regnskap/" in url: value = accounts
                elif url.endswith("/roller"): value = roles
                elif "/underenheter?" in url: value = subunits
                else: value = entity
                return 200, {"Content-Type": "application/json"}, json.dumps(value).encode(), url
        gateway = NetworkGateway(RoutingTransport(), retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), patch.object(gateway, "robots_decision", return_value=("allowed", None)):
            result = await fetch_company("923609003", gateway, datetime.now(timezone.utc) + timedelta(days=1))
        self.assertEqual(gateway.ledger.logical_requests, 4)
        self.assertTrue(all(claim.organisation_number == "923609003" for claim in result.claims))
        holder = next(claim for claim in result.claims if claim.field == "role.holder_organisation_number")
        self.assertEqual(holder.subject_id, "923609003")
        self.assertEqual(holder.value, "923609016")
        self.assertEqual(result.observations["financial_records"], 1)
        self.assertEqual(result.observations["ceo_state"], "not_available")
        self.assertIn(result.observations["roles_completeness_evidence_id"], {item.evidence_id for item in result.evidence})
        payload_hashes = {hashlib.sha256(json.dumps(value).encode()).hexdigest()
                          for value in (entity, accounts, roles, subunits)}
        self.assertTrue(all(item.json_pointer and len(item.content_sha256) == 64 for item in result.evidence))
        self.assertTrue(all(item.content_sha256 in payload_hashes for item in result.evidence))

    async def test_subunit_children_are_individually_parent_and_identifier_validated(self):
        target = "923609016"
        valid_child = {"organisasjonsnummer": "923609024", "overordnetEnhet": target, "navn": "Valid subunit"}
        wrong_parent = {"organisasjonsnummer": "923609008", "overordnetEnhet": "923609024", "navn": "Wrong parent"}
        malformed_child = {"organisasjonsnummer": "12", "overordnetEnhet": target, "navn": "Malformed"}

        async def fetch_with(rows):
            class RoutingTransport:
                async def request(self, url, headers, timeout):
                    if "/regnskap/" in url: body = []
                    elif url.endswith("/roller"): body = {"rollegrupper": []}
                    elif "/underenheter?" in url:
                        body = {"_embedded": {"underenheter": rows}, "page": {"number": 0, "totalPages": 1}}
                    else: body = {"organisasjonsnummer": target, "navn": "Target AS", "organisasjonsform": {"kode": "AS"}}
                    return 200, {"Content-Type": "application/json"}, json.dumps(body).encode(), url
            gateway = NetworkGateway(RoutingTransport(), retries=0)
            with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), patch.object(gateway, "robots_decision", return_value=("allowed", None)):
                return await fetch_company(target, gateway, datetime.now(timezone.utc) + timedelta(days=1))

        wrong_only = await fetch_with([wrong_parent])
        self.assertFalse(any(claim.field_family == "workplace" for claim in wrong_only.claims))
        self.assertFalse(wrong_only.observations["workplaces_complete"])
        self.assertIn("BRREG_SUBUNIT_RELATION_INVALID", {error.code for error in wrong_only.errors})

        mixed = await fetch_with([valid_child, wrong_parent, malformed_child])
        workplace_orgs = {claim.value for claim in mixed.claims if claim.field == "workplace.organisasjonsnummer"}
        self.assertEqual(workplace_orgs, {"923609024"})
        self.assertFalse(mixed.observations["workplaces_complete"])

    async def test_subunits_reject_self_child_dedupe_identical_and_abstain_conflicting_duplicates(self):
        target = "923609016"
        valid_child = {"organisasjonsnummer": "923609024", "overordnetEnhet": target, "navn": "Valid subunit"}
        self_child = {"organisasjonsnummer": target, "overordnetEnhet": target, "navn": "Target AS"}
        wrong_parent = {"organisasjonsnummer": "923609008", "overordnetEnhet": "923609024", "navn": "Wrong parent"}
        malformed = {"organisasjonsnummer": "12", "overordnetEnhet": target, "navn": "Malformed"}

        async def fetch_with(rows):
            class RoutingTransport:
                async def request(self, url, headers, timeout):
                    if "/regnskap/" in url: body = []
                    elif url.endswith("/roller"): body = {"rollegrupper": []}
                    elif "/underenheter?" in url:
                        body = {"_embedded": {"underenheter": rows}, "page": {"number": 0, "totalPages": 1}}
                    else: body = {"organisasjonsnummer": target, "navn": "Target AS", "organisasjonsform": {"kode": "AS"}}
                    return 200, {"Content-Type": "application/json"}, json.dumps(body).encode(), url
            gateway = NetworkGateway(RoutingTransport(), retries=0)
            with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), patch.object(gateway, "robots_decision", return_value=("allowed", None)):
                return await fetch_company(target, gateway, datetime.now(timezone.utc) + timedelta(days=1))

        self_result = await fetch_with([self_child])
        self.assertFalse(any(claim.field_family == "workplace" for claim in self_result.claims))
        self.assertFalse(self_result.observations["workplaces_complete"])

        duplicate = await fetch_with([valid_child, dict(valid_child)])
        duplicate_claims = [claim for claim in duplicate.claims if claim.field_family == "workplace"]
        self.assertEqual(len([claim for claim in duplicate_claims if claim.field == "workplace.organisasjonsnummer"]), 1)
        self.assertEqual(duplicate.observations["workplace_count"], 1)
        self.assertTrue(duplicate.observations["workplaces_complete"])

        conflicting = await fetch_with([valid_child, {**valid_child, "navn": "Conflicting name AS"}])
        self.assertFalse(any(claim.field_family == "workplace" for claim in conflicting.claims))
        self.assertFalse(conflicting.observations["workplaces_complete"])
        self.assertIn("BRREG_SUBUNIT_DUPLICATE_CONFLICT", {error.code for error in conflicting.errors})

        mixed = await fetch_with([valid_child, wrong_parent, malformed])
        self.assertEqual({claim.value for claim in mixed.claims if claim.field == "workplace.organisasjonsnummer"}, {"923609024"})
        self.assertFalse(mixed.observations["workplaces_complete"])

    async def test_brreg_hal_empty_workplaces_have_source_bound_completeness(self):
        # Real BRREG zero-result shape observed in the bounded October live run:
        # HAL omits _embedded and explicitly reports a zero-length first page.
        target = "923609016"
        url = f"https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={target}&size=1000"
        empty = {"_links": {"self": {"href": url}},
                 "page": {"number": 0, "size": 1000, "totalElements": 0, "totalPages": 0}}

        async def fetch_with(subunits):
            class RoutingTransport:
                async def request(self, request_url, headers, timeout):
                    if "/regnskap/" in request_url: body = []
                    elif request_url.endswith("/roller"): body = {"rollegrupper": []}
                    elif "/underenheter?" in request_url: body = subunits
                    else: body = {"organisasjonsnummer": target, "navn": "Target AS"}
                    return 200, {"Content-Type": "application/json"}, json.dumps(body).encode(), request_url
            gateway = NetworkGateway(RoutingTransport(), retries=0)
            with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), patch.object(gateway, "robots_decision", return_value=("allowed", None)):
                return await fetch_company(target, gateway, datetime.now(timezone.utc) + timedelta(days=1))

        result = await fetch_with(empty)
        self.assertTrue(result.observations["workplaces_complete"])
        self.assertEqual(result.observations["workplace_count"], 0)
        self.assertFalse(any(c.field_family == "workplace" for c in result.claims))
        self.assertNotIn("BRREG_SUBUNITS_MALFORMED", {e.code for e in result.errors})
        evidence = {e.evidence_id: e for e in result.evidence}
        for ref in result.observations["workplaces_completeness_evidence_ids"]:
            item = evidence[ref]
            self.assertEqual(item.json_pointer, "/page/totalElements")
            self.assertEqual(item.content_sha256, hashlib.sha256(json.dumps(empty).encode()).hexdigest())
            self.assertEqual(item.source_url, url)
        self.assertNotIn("_embedded", empty)  # Do not invent bytes beneath the source hash.

        invalid = [{}, {"page": {}},
                   {**empty, "page": {**empty["page"], "totalElements": 1}},
                   {**empty, "page": {**empty["page"], "totalElements": False}},
                   {**empty, "page": {**empty["page"], "number": 1}},
                   {**empty, "page": {**empty["page"], "totalPages": 1}},
                   {**empty, "_links": {**empty["_links"], "next": {"href": url}}},
                   {**empty, "_embedded": {"underenheter": "bad"}}]
        for body in invalid:
            with self.subTest(body=body):
                rejected = await fetch_with(body)
                self.assertFalse(rejected.observations["workplaces_complete"])
                self.assertIn("BRREG_SUBUNITS_MALFORMED", {e.code for e in rejected.errors})

    async def test_http_200_malformed_collection_is_failure_not_absence(self):
        class MalformedTransport:
            async def request(self, url, headers, timeout):
                if "/regnskap/" in url: body = {"unexpected": "shape"}
                elif url.endswith("/roller"): body = {"rollegrupper": "bad"}
                elif "/underenheter?" in url: body = {"_embedded": {"underenheter": "bad"}}
                else: body = {"organisasjonsnummer": "923609003", "navn": "Target AS"}
                return 200, {"Content-Type": "application/json"}, json.dumps(body).encode(), url
        gateway = NetworkGateway(MalformedTransport(), retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), patch.object(gateway, "robots_decision", return_value=("allowed", None)):
            result = await fetch_company("923609003", gateway, datetime.now(timezone.utc) + timedelta(days=1))
        codes = {error.code for error in result.errors}
        self.assertTrue({"BRREG_ACCOUNTS_MALFORMED", "BRREG_ROLES_MALFORMED", "BRREG_SUBUNITS_MALFORMED"} <= codes)
        self.assertEqual(result.section_states["accounts_history"], PublicState.FAILED)
        self.assertEqual(result.observations["role_family_state"], PublicState.FAILED.value)
        self.assertIsNone(result.observations.get("roles_completeness_evidence_id"))
        self.assertFalse(result.observations["workplaces_complete"])
        self.assertFalse(any(claim.state == PublicState.AVAILABLE and claim.field_family == "financial" for claim in result.claims))

    async def test_financial_metadata_is_mandatory_and_valid_zero_is_retained(self):
        target = "923609003"
        accounts = [
            {"id": "missing-period", "regnskapstype": "SELSKAP", "valuta": "NOK", "eiendeler": {"sumEiendeler": 11}},
            {"id": "missing-currency", "regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}, "eiendeler": {"sumEiendeler": 12}},
            {"id": "unknown-scope", "regnskapstype": "SPECIAL", "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}, "valuta": "NOK", "eiendeler": {"sumEiendeler": 13}},
            {"id": "malformed", "regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}, "valuta": "NOK", "eiendeler": {"sumEiendeler": "zero-ish"}},
            {"id": "valid-zero-v2", "versjon": 2, "regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2023-01-01", "tilDato": "2023-12-31"}, "valuta": "NOK", "enhet": "NOK", "eiendeler": {"sumEiendeler": 0}},
            {"id": "valid-eur", "regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2022-01-01", "tilDato": "2022-12-31"}, "valuta": "EUR", "enhet": "EUR", "eiendeler": {"sumEiendeler": 42}},
            {"id": "unknown-currency", "regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}, "valuta": "QQQ", "eiendeler": {"sumEiendeler": 14}},
            {"id": "lowercase-currency", "regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}, "valuta": "nok", "eiendeler": {"sumEiendeler": 15}},
            {"id": "malformed-currency", "regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}, "valuta": "NO-K", "eiendeler": {"sumEiendeler": 16}},
        ]
        class AccountsTransport:
            async def request(self, url, headers, timeout):
                if "/regnskap/" in url: body = [{**record, "virksomhet": {"organisasjonsnummer": target}} for record in accounts]
                elif url.endswith("/roller"): body = {"rollegrupper": []}
                elif "/underenheter?" in url: body = {"_embedded": {"underenheter": []}, "page": {"number": 0, "totalPages": 1}}
                else: body = {"organisasjonsnummer": target, "navn": "Target AS"}
                return 200, {"Content-Type": "application/json"}, json.dumps(body).encode(), url
        gateway = NetworkGateway(AccountsTransport(), retries=0)
        with patch("signalpost.network.validate_public_host", return_value=("8.8.8.8",)), patch.object(gateway, "robots_decision", return_value=("allowed", None)):
            result = await fetch_company(target, gateway, datetime.now(timezone.utc) + timedelta(days=1))
        metrics = [claim for claim in result.claims if claim.field_family == "financial"]
        self.assertEqual([(item.field, item.value, item.currency) for item in metrics],
            [("total_assets", 0, "NOK"), ("total_assets", 42, "EUR")])
        self.assertTrue(all(item.period_start is not None and item.period_end is not None for item in metrics))
        self.assertEqual(len([item for item in result.errors if item.code == "BRREG_FINANCIAL_METADATA_INCOMPLETE"]), 6)

    def test_currency_allowlist_accepts_active_codes_not_unknown_triplets(self):
        self.assertTrue(supported_currency("NOK"))
        self.assertTrue(supported_currency("EUR"))
        self.assertFalse(supported_currency("QQQ"))
        self.assertFalse(supported_currency("nok"))
        self.assertFalse(supported_currency("NO-K"))
        self.assertIn("NOK", SUPPORTED_CURRENCY_CODES)


if __name__ == "__main__":
    unittest.main()
