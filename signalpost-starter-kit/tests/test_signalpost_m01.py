from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from signalpost.adapter import to_evaluator, validate_vendor_payload
from signalpost.inputs import normalize_org_number, parse_records
from signalpost.models import Claim, Envelope, Evidence, PublicState, RefreshState, Section, SourceSnapshot, empty_section
from signalpost.network import NetworkGateway, NetworkPolicyError, StructuredLogger, UrlLibTransport, canonical_url, classify_response, registered_domain, robots_directives, validate_public_host
from signalpost.operations import Budget, OrderedAtomicWriter, RunBudget
from signalpost.run import main
import signalpost.run as run_module


SECTIONS = {name: empty_section() for name in (
    "identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
    "hiring_activity", "claims_evidence_states", "refresh_changes")}


def valid_envelope(row: int = 1) -> Envelope:
    now = datetime.now(timezone.utc)
    evidence = Evidence(evidence_id="e1", source_url="https://data.brreg.no/x", retrieved_at=now,
                        content_sha256="a" * 64, extraction_method="json_pointer")
    claim = Claim(claim_id="c1", organisation_number="923609016", section="identity_brand", field_family="identity",
                  subject_id="923609016", field="legal_name", value="Example AS", state=PublicState.AVAILABLE,
                  scope="legal_entity", verification_rule_id="fixture_exact_org_v1", verification_score="1",
                  evidence_ids=["e1"], source_snapshot_ids=["registry_fixture"])
    snapshot = SourceSnapshot(source_id="registry_fixture", source_url="https://data.brreg.no/x", retrieved_at=now,
                              content_sha256="a" * 64)
    return Envelope(input_ref=f"row:{row}", row_number=row, organisation_number="923609016",
                    terminal_state=PublicState.AVAILABLE, sections=SECTIONS,
                    refresh=RefreshState(), claims=[claim], evidence=[evidence], source_snapshots=[snapshot], batch_id="b1", evidence_cutoff=now)


class InputContractTests(unittest.TestCase):
    def test_mod11_and_leading_zero_are_textual(self):
        self.assertEqual(normalize_org_number(" 923 609 010 "), ("923609010", True))
        normalized, valid = normalize_org_number("012345676")
        self.assertEqual(normalized, "012345676")
        self.assertIsInstance(normalized, str)
        self.assertFalse(valid)
        self.assertEqual(normalize_org_number(923609010), ("923609010", True))
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
                                content_sha256="a" * 64, extraction_method="test")
            Envelope(input_ref="r", row_number=1, organisation_number="923609016", terminal_state=PublicState.AVAILABLE,
                     sections=SECTIONS, refresh=RefreshState(), claims=[claim], evidence=[evidence],
                     source_snapshots=[SourceSnapshot(source_id="snapshot", source_url="https://example.com", retrieved_at=now,
                                                      content_sha256="b" * 64)], batch_id="b", evidence_cutoff=now)

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
            self.assertEqual([json.loads(line)["row_number"] for line in path.read_text().splitlines()], [1, 2])

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

    async def test_robots_rules_crawl_delay_and_200_waf_soft_404(self):
        fake = FakeTransport([(200, {}, b"User-agent: *\nDisallow: /private\nCrawl-delay: 0.1\n", "https://8.8.8.8/robots.txt")])
        gateway = NetworkGateway(fake, retries=0)
        self.assertEqual(await gateway.robots_allowed("https://8.8.8.8/private/x", "SignalpostBot"), (False, 0.1))
        self.assertEqual(classify_response(200, {}, b"Just a moment..."), "waf_challenge")
        self.assertEqual(classify_response(200, {}, b"<title>404 Not Found</title>"), "soft_404")

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
            self.assertEqual([item["row_number"] for item in envelopes], [1, 2])
            self.assertTrue(all(item["terminal_state"] == "available" for item in envelopes))
            self.assertTrue(all(len(item["sections"]) == 7 for item in envelopes))
            self.assertTrue(all(item["evidence_cutoff"] == "2026-10-17T23:59:00+05:30" for item in envelopes))
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


if __name__ == "__main__":
    unittest.main()
