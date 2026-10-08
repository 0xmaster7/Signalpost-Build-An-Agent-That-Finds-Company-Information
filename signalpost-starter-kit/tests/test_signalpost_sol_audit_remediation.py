from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "signalpost-starter-kit" / "scripts"))

from signalpost.adapter import to_evaluator
from signalpost.brreg import _role_collection_shape, financial_records
from signalpost.inputs import parse_records
from signalpost.models import (Claim, Evidence, PublicState, SourceSnapshot,
    validate_batch_publication_graph, validate_publication_graph)
from signalpost.operations import OrderedAtomicWriter, publish_paired_artifacts, validate_paired_publication
from signalpost.websites import PageRecord, _parse_page, _public_evidence, verify_site_pages
from signalpost.websites import _page_footprints, research_company
from signalpost.query import CompanyProfile, verify_proposition
from test_signalpost_m01 import valid_envelope


NOW = datetime.now(timezone.utc)


def valid_financial_envelope():
    envelope = valid_envelope()
    claim = Claim(claim_id="financial-revenue", organisation_number=envelope.organisation_number,
        section="accounts_history", field_family="financial", subject_id=envelope.organisation_number,
        field="revenue", value=123, state=PublicState.AVAILABLE, unit="TNOK", currency="NOK",
        period_start=NOW.replace(year=2024, month=1, day=1), period_end=NOW.replace(year=2024, month=12, day=31),
        scope="legal_entity", verification_rule_id="brreg-test", verification_score="1",
        evidence_ids=["e1"], source_snapshot_ids=["registry_fixture"])
    envelope.claims.append(claim)
    envelope.sections["accounts_history"].claims.append(claim)
    envelope.sections["claims_evidence_states"].claims.append(claim)
    return envelope


class SolAuditRemediationTests(unittest.TestCase):
    def test_research_company_rejects_customer_reference_as_target_website_but_keeps_owned_shared_site(self):
        import asyncio
        from test_signalpost_m05 import FakeGateway, CUTOFF
        org, name = "923609016", "Acme AS"
        rival_html = ("<html><head><title>Acme AS</title></head><body>"
            "<main><h1>Customer story</h1><p>Acme AS is our customer.</p></main>"
            "<address>Acme AS 923609016, Main Street 1, 0123 Oslo</address>"
            "<footer>Customer references</footer></body></html>").encode()
        profile = {"organisation_number": org, "name": name,
            "registered_address": {"adresse": ["Main Street 1"], "postnummer": "0123", "poststed": "Oslo"},
            "website_candidates": [{"raw": "https://rival.no/customer-stories/acme", "source": "registry_live"}]}
        result = asyncio.run(research_company(profile, FakeGateway({
            "https://rival.no/customer-stories/acme": (200, {"Content-Type": "text/html"}, rival_html)}),
            enable_keyless=False, evidence_cutoff=CUTOFF))
        self.assertFalse(result.claims)
        self.assertNotEqual(result.audit["candidates"][0]["decision"], "accepted")

        owned_html = (f'<html><head><title>{name}</title><script type="application/ld+json">'
            + json.dumps({"@type": "Organization", "name": name, "legalName": name, "identifier": org})
            + '</script></head><body><h1>Acme AS</h1><p>Acme products and services for customers.</p></body></html>').encode()
        owned = asyncio.run(research_company({"organisation_number": org, "name": name,
            "website_candidates": [{"raw": "https://group.no/acme", "source": "registry_live"}]},
            FakeGateway({"https://group.no/acme": (200, {"Content-Type": "text/html"}, owned_html)}),
            enable_keyless=False, evidence_cutoff=CUTOFF, shared_domains={"group.no"}))
        self.assertTrue(any(claim.field == "verified_website_domain" for claim in owned.claims))

    def test_production_job_status_reconciles_explicit_status_and_dates(self):
        import asyncio
        from test_signalpost_m05 import FakeGateway, CUTOFF, LEGAL, ORG
        cases = [
            ({"jobStatus": "closed", "validThrough": "2027-01-01"}, "closed", 0),
            ({"jobStatus": "open", "validThrough": "2026-01-01"}, "closed", 0),
            ({"jobStatus": "pending_review", "validThrough": "2027-01-01"}, None, 0),
            ({"validThrough": "not-a-date"}, None, 0),
            ({"validThrough": "2027-01-01"}, "open", 1),
        ]
        for status_fields, expected, current_count in cases:
            with self.subTest(status_fields=status_fields):
                posting = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Engineer",
                    "url": "/jobs/1", "datePosted": "2026-09-01",
                    "hiringOrganization": {"@type": "Organization", "name": LEGAL, "identifier": ORG},
                    **status_fields}
                home = (f'<html><head><title>{LEGAL}</title><script type="application/ld+json">'
                    + json.dumps({"@type": "Organization", "legalName": LEGAL, "identifier": ORG})
                    + '</script></head><body><h1>Company</h1><a href="/careers">Careers</a></body></html>').encode()
                careers = (f'<html><head><title>Careers</title><script type="application/ld+json">'
                    + json.dumps(posting) + '</script></head><body><h1>Careers</h1></body></html>').encode()
                result = asyncio.run(research_company({"organisation_number": ORG, "name": LEGAL,
                    "website_candidates": [{"raw": "https://company.no/", "source": "registry_live"}]},
                    FakeGateway({"https://company.no/": (200, {"Content-Type": "text/html"}, home),
                                "https://company.no/careers": (200, {"Content-Type": "text/html"}, careers)}),
                    enable_keyless=False, evidence_cutoff=CUTOFF))
                statuses = [claim.value for claim in result.claims if claim.field == "job_status"]
                self.assertEqual(statuses, [expected] if expected else [])
                self.assertEqual(result.audit["jobs"]["current_subjects"], current_count)

    def test_rival_main_identity_and_target_footer_is_ambiguous(self):
        page = PageRecord(requested_url="https://rival.no/", final_url="https://rival.no/", status=200,
            content_type="text/html", body=b"fixture", digest="a" * 64, retrieved_at=NOW,
            title="Rival Group AS", visible_text="Rival Group AS services",
            identity_text="Rival Group AS 923609010 Acme AS 923609016",
            identity_blocks=[], footer_blocks=["Rival Group AS 923609010", "Acme AS 923609016"],
            headings=["Rival Group AS"])
        result = verify_site_pages({"organisation_number": "923609016", "name": "Acme AS"}, [page])
        self.assertNotEqual(result["decision"], "accepted")
        parsed = _parse_page("https://rival.no/", 200, {"Content-Type": "text/html"},
            b"<html><head><title>Rival Group AS</title></head><body><main><h1>Rival Group AS</h1></main>"
            b"<footer>Acme AS 923609016</footer></body></html>", "https://rival.no/")
        self.assertIsNotNone(parsed)
        self.assertFalse(any("923609016" in block for block in parsed.identity_blocks))
        parsed_result = verify_site_pages({"organisation_number": "923609016", "name": "Acme AS"}, [parsed])
        self.assertNotEqual(parsed_result["decision"], "accepted")

    def test_nonfooter_rival_legal_identity_overrides_incidental_target_footer(self):
        page = PageRecord(requested_url="https://rival.no/about", final_url="https://rival.no/about", status=200,
            content_type="text/html", body=b"fixture", digest="f" * 64, retrieved_at=NOW,
            title="About", identity_blocks=["Rival Group AS 923609010"],
            footer_blocks=["Acme AS 923609016"])
        result = verify_site_pages({"organisation_number": "923609016", "name": "Acme AS"}, [page])
        self.assertNotEqual(result["decision"], "accepted")

    def test_multi_company_group_homepage_is_not_owned_by_footer_targets(self):
        page = PageRecord(requested_url="https://group.no/", final_url="https://group.no/", status=200,
            content_type="text/html", body=b"fixture", digest="b" * 64, retrieved_at=NOW,
            title="Group home", identity_text="Acme AS 923609016 Beta AS 917065101",
            footer_blocks=["Acme AS 923609016 Beta AS 917065101"])
        for org, name in (("923609016", "Acme AS"), ("917065101", "Beta AS")):
            result = verify_site_pages({"organisation_number": org, "name": name}, [page], shared_domain=True)
            self.assertNotEqual(result["decision"], "accepted")
        parent_page = PageRecord(requested_url="https://group.no/", final_url="https://group.no/", status=200,
            content_type="text/html", body=b"fixture", digest="b" * 64, retrieved_at=NOW,
            title="Group home", identity_text="Acme AS 923609016 Holding AS 917065101",
            identity_blocks=["Acme AS 923609016"], footer_blocks=["Holding AS 917065101"])
        result = verify_site_pages({"organisation_number": "923609016", "name": "Acme AS",
            "related_organisation_numbers": ["917065101"]}, [parent_page], shared_domain=True)
        self.assertNotEqual(result["decision"], "accepted")

    def test_target_specific_identity_proof_is_required_and_shared_subpage_can_pass(self):
        page = PageRecord(requested_url="https://group.no/acme", final_url="https://group.no/acme", status=200,
            content_type="text/html", body=b"fixture", digest="e" * 64, retrieved_at=NOW,
            title="Acme AS", identity_text="Acme AS 923609016", identity_blocks=["Acme AS 923609016"],
            headings=["Acme AS"])
        profile = {"organisation_number": "923609016", "name": "Acme AS", "related_organisation_numbers": ["917065101"]}
        self.assertEqual(verify_site_pages(profile, [page], shared_domain=True)["decision"], "accepted")
        page.identity_blocks = ["Acme AS"]
        page.identity_text = "Acme AS"
        self.assertNotEqual(verify_site_pages(profile, [page], shared_domain=True)["decision"], "accepted")

    def test_website_evidence_identity_is_subject_bound_content_snapshot_is_shareable(self):
        page = PageRecord(requested_url="https://group.no/", final_url="https://group.no/", status=200,
            content_type="text/html", body=b"same", digest="c" * 64, retrieved_at=NOW)
        snapshots, evidence = [], []
        a = _public_evidence(page, snapshots, evidence, org="923609016", excerpt="Same", locator="/p")
        b = _public_evidence(page, snapshots, evidence, org="917065101", excerpt="Same", locator="/p")
        self.assertNotEqual(a, b)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual({item.subject_organisation_number for item in evidence}, {"923609016", "917065101"})

    def test_batch_validator_rejects_conflicting_cross_envelope_evidence_id(self):
        first = valid_envelope()
        second_raw = valid_envelope(2).model_dump(mode="json")
        second_raw["organisation_number"] = "917065101"
        second_raw["claims"][0].update({"organisation_number": "917065101", "claim_id": "c2", "subject_id": "917065101"})
        second_raw["evidence"][0]["subject_organisation_number"] = "917065101"
        from signalpost.models import Envelope
        second = Envelope.model_validate(second_raw)
        with self.assertRaisesRegex(ValueError, "conflicting evidence"):
            validate_batch_publication_graph([first, second])

    def test_batch_validator_rejects_conflicting_cross_envelope_snapshot_id(self):
        first = valid_envelope()
        second_raw = valid_envelope(2).model_dump(mode="json")
        second_raw["source_snapshots"][0]["content_sha256"] = "b" * 64
        second_raw["evidence"][0]["content_sha256"] = "b" * 64
        second_raw["evidence"][0]["evidence_id"] = "e2"
        second_raw["claims"][0]["evidence_ids"] = ["e2"]
        from signalpost.models import Envelope
        second = Envelope.model_validate(second_raw)
        with self.assertRaisesRegex(ValueError, "conflicting snapshot"):
            validate_batch_publication_graph([first, second])

    def test_record_financial_unit_is_inherited_without_currency_guess(self):
        record = {"regnskapstype": "SELSKAP", "valuta": "NOK", "enhet": "TNOK",
            "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"},
            "resultatregnskapResultat": {"driftsresultat": {
                "driftsinntekter": {"sumDriftsinntekter": {"sum": 123}}}}}
        parsed = financial_records([record])[0]
        self.assertEqual(parsed["metrics"]["revenue"], 123)
        self.assertEqual(parsed["metrics"]["revenue_unit"], "TNOK")
        record["resultatregnskapResultat"]["driftsresultat"]["driftsinntekter"]["sumDriftsinntekter"] = {"sum": 123, "enhet": "NOK"}
        conflict = financial_records([record])[0]["metrics"]
        self.assertEqual(conflict["revenue_unit"], "__conflict__")
        self.assertTrue(conflict["revenue_unit_conflict"])
        record["enhet"] = None
        record["resultatregnskapResultat"]["driftsresultat"]["driftsinntekter"]["sumDriftsinntekter"] = {"sum": 123}
        record["valuta"] = "NOK"
        self.assertIsNone(financial_records([record])[0]["metrics"].get("revenue_unit"))

    def test_financial_unit_classification_preserves_absent_null_malformed_unsupported_and_conflict(self):
        def record(metric_unit=... , record_unit=...):
            metric = {"sum": 0}
            if metric_unit is not ...:
                metric["enhet"] = metric_unit
            row = {"regnskapstype": "SELSKAP", "valuta": "NOK",
                "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"},
                "resultatregnskapResultat": {"driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": metric}}}}
            if record_unit is not ...:
                row["enhet"] = record_unit
            return financial_records([row])[0]["metrics"]
        self.assertEqual((record(record_unit="TNOK")["revenue_unit"], record(record_unit="TNOK")["revenue_unit_state"]), ("TNOK", "supported"))
        self.assertEqual(record(metric_unit="NOK", record_unit="TNOK")["revenue_unit_state"], "conflict")
        self.assertEqual(record(record_unit="TNOK", metric_unit=None)["revenue_unit_state"], "explicit_null")
        self.assertEqual(record(record_unit="TNOK", metric_unit=0)["revenue_unit_state"], "malformed")
        self.assertEqual(record(record_unit="TNOK", metric_unit="")["revenue_unit_state"], "malformed")
        self.assertEqual(record(metric_unit="UNKNOWN")["revenue_unit_state"], "unsupported")
        self.assertEqual(record()["revenue_unit_state"], "absent")
        self.assertEqual(record(record_unit=None)["revenue_unit_state"], "explicit_null")
        self.assertEqual(record(record_unit=0)["revenue_unit_state"], "malformed")
        self.assertEqual(record(record_unit="")["revenue_unit_state"], "malformed")
        self.assertEqual(record(record_unit="UNKNOWN")["revenue_unit_state"], "unsupported")
        self.assertEqual(record(record_unit="TNOK", metric_unit="EUR")["revenue_unit_state"], "conflict")

    def test_financial_currency_unit_pair_is_rejected_at_canonical_and_final_boundaries(self):
        envelope = valid_financial_envelope()
        envelope.claims[1].currency = "EUR"
        with self.assertRaisesRegex(ValueError, "supported unit, currency"):
            validate_publication_graph(envelope)
        envelope = valid_financial_envelope()
        envelope.claims[1].currency = "EUR"
        with self.assertRaisesRegex(ValueError, "supported unit, currency"):
            to_evaluator(envelope)
        for value in (0, -1):
            valid = valid_financial_envelope()
            valid.claims[1].value = value
            validate_publication_graph(valid)
            to_evaluator(valid)

    def test_incomplete_roles_group_is_not_complete_empty(self):
        self.assertFalse(_role_collection_shape({"rollegrupper": [{"type": {"kode": "LEDE"}}]}))
        self.assertFalse(_role_collection_shape({"rollegrupper": [{"type": {"kode": "LEDE"}, "roller": None}]}))
        self.assertTrue(_role_collection_shape({"rollegrupper": []}))

    def test_adapter_rejects_mutated_synthesis_and_section_claim(self):
        envelope = valid_envelope()
        from signalpost.synthesis import synthesize
        envelope.synthesis["summary"] = synthesize(envelope)
        envelope.synthesis["summary"]["sentences"][0]["text"] = "Company has revenue of NOK 999999999."
        with self.assertRaisesRegex(ValueError, "wording"):
            to_evaluator(envelope)
        envelope = valid_envelope()
        claim = envelope.claims[0].model_copy(deep=True)
        claim.value = "Rival AS"
        envelope.sections["identity_brand"].claims = [claim]
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            to_evaluator(envelope)

    def test_adapter_rejects_unknown_top_level_and_nested_synthesis_fields(self):
        from signalpost.synthesis import synthesize
        for location in ("top", "summary", "website_research", "nested_audit"):
            with self.subTest(location=location):
                envelope = valid_envelope()
                envelope.synthesis["summary"] = synthesize(envelope)
                if location == "top":
                    envelope.synthesis["unsupported_financial_prose"] = "Revenue is one billion NOK."
                elif location == "summary":
                    envelope.synthesis["summary"]["unsupported_financial_prose"] = "Revenue is one billion NOK."
                elif location == "website_research":
                    envelope.synthesis["website_research"] = {"unsupported_financial_prose": "Revenue is one billion NOK."}
                else:
                    envelope.synthesis["website_research"] = {"jobs": {"nested": {"unsupported_financial_prose": "Revenue is one billion NOK."}}}
                with self.assertRaisesRegex(ValueError, "unknown .*synthesis fields"):
                    to_evaluator(envelope)

    def test_adapter_rejects_missing_synthesis_citation_and_missing_section_claim(self):
        from signalpost.synthesis import synthesize
        envelope = valid_envelope()
        envelope.synthesis["summary"] = synthesize(envelope)
        envelope.synthesis["summary"]["sentences"][0]["evidence_ids"] = []
        with self.assertRaisesRegex(ValueError, "claim and evidence references"):
            to_evaluator(envelope)
        envelope = valid_envelope()
        envelope.sections["identity_brand"].claims = []
        with self.assertRaisesRegex(ValueError, "missing from its publication section"):
            to_evaluator(envelope)

    def test_adapter_rejects_financial_mutations_at_final_boundary(self):
        for field, value in (("value", float("nan")), ("currency", "QQQ"),
                             ("unit", "UNKNOWN"), ("period_end", NOW.replace(year=2023))):
            with self.subTest(field=field):
                envelope = valid_financial_envelope()
                setattr(envelope.claims[1], field, value)
                with self.assertRaises(ValueError):
                    to_evaluator(envelope)

    def test_strict_csv_rejects_unterminated_quote_instead_of_dropping_neighbor(self):
        with self.assertRaises(Exception):
            parse_records('organisation_number,comment\n917065101,"bad\n923609016,ok\n', "csv")
        rows = parse_records('organisation_number,comment\r\n923609016,"first\r\nsecond"\r\n', "csv")
        self.assertEqual(len(rows), 1)
        self.assertIn("second", rows[0].raw["comment"])
        rich = parse_records('\ufefforganisation_number,name,comment\r\n012345676,"Acme, AS","say ""yes"""\r\n012345676,Acme,duplicate\r\n', "csv")
        self.assertEqual(len(rich), 2)
        self.assertEqual(rich[0].organisation_number, "012345676")
        self.assertEqual(rich[0].raw["comment"], 'say "yes"')
        with self.assertRaises(Exception):
            parse_records('organisation_number\tcomment\n923609016\t"bad\n917065101\tok\n', "tsv")

    def test_output_equal_to_input_fails_before_run(self):
        from signalpost.run import main
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.jsonl"
            source.write_text('{"organisation_number":"923609016"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "read-only input"):
                main(["--input", str(source), "--output", str(source)])

    def test_output_symlink_alias_to_input_fails_preflight(self):
        from signalpost.run import main
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.jsonl"
            alias = Path(directory) / "output.jsonl"
            source.write_text('{"organisation_number":"923609016"}\n', encoding="utf-8")
            alias.symlink_to(source)
            with self.assertRaisesRegex(ValueError, "read-only input"):
                main(["--input", str(source), "--output", str(alias)])

    def test_frozen_hash_exception_rejects_public_web_method_spoof(self):
        from signalpost.models import approved_frozen_hash_exception
        evidence = Evidence(evidence_id="x", source_url="https://site.example/page", retrieved_at=NOW,
            content_sha256="a" * 64, extraction_method="frozen_registry_jsonl_v1", source_class="public_web",
            subject_organisation_number="923609016", source_snapshot_ids=["registry_snapshot:x"])
        snapshot = SourceSnapshot(source_id="registry_snapshot:x", source_url=evidence.source_url,
            retrieved_at=NOW, content_sha256="b" * 64, rights_status="NLOD-2.0")
        self.assertFalse(approved_frozen_hash_exception(evidence, snapshot))
        envelope = valid_envelope()
        envelope.evidence[0].extraction_method = "frozen_registry_jsonl_v1"
        envelope.evidence[0].source_class = "public_web"
        envelope.evidence[0].json_pointer = "/"
        envelope.evidence[0].content_sha256 = "b" * 64
        from signalpost.models import validate_publication_graph
        with self.assertRaisesRegex(ValueError, "hash must match"):
            validate_publication_graph(envelope)

    def test_frozen_hash_exception_requires_internal_exact_hash_bound_snapshot(self):
        from signalpost.models import approved_frozen_hash_exception
        full_hash = "c" * 64
        urn = f"urn:signalpost:frozen-registry:{full_hash}"
        evidence = Evidence(evidence_id="x", source_url=urn, retrieved_at=NOW, content_sha256="a" * 64,
            extraction_method="frozen_registry_jsonl_v1", source_class="official", json_pointer="/navn",
            subject_organisation_number="923609016", source_snapshot_ids=[f"registry_snapshot:{full_hash}"])
        snapshot = SourceSnapshot(source_id=f"registry_snapshot:{full_hash}", source_url=urn,
            retrieved_at=NOW, content_sha256=full_hash, rights_status="NLOD-2.0")
        self.assertTrue(approved_frozen_hash_exception(evidence, snapshot))
        mutations = [
            {"source_url": "https://forged.example/registry.jsonl"},
            {"source_id": "registry_snapshot:" + "d" * 64},
            {"rights_status": "MIT"},
            {"content_sha256": "d" * 64},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed = snapshot.model_copy(update=mutation)
                self.assertFalse(approved_frozen_hash_exception(evidence, changed))
        for mutation in ({"source_url": "https://forged.example/registry.jsonl"},
                         {"extraction_method": "website_html_extract_v1"},
                         {"source_class": "public_web"}, {"json_pointer": "/forged"}):
            changed_evidence = evidence.model_copy(update=mutation)
            self.assertFalse(approved_frozen_hash_exception(changed_evidence, snapshot))

    def test_verify_compares_integral_financial_decimals_with_dimensions(self):
        from signalpost.models import Claim, PublicState
        claim = Claim(claim_id="revenue", organisation_number="923609016", section="accounts_history",
            field_family="financial", subject_id="923609016", field="revenue", value=185783.0,
            state=PublicState.AVAILABLE, unit="NOK", currency="NOK",
            period_start=NOW.replace(year=2024, month=1, day=1), period_end=NOW.replace(year=2024, month=12, day=31),
            scope="legal_entity", verification_rule_id="fixture", verification_score="1",
            evidence_ids=["e1"], source_snapshot_ids=["registry_fixture"])
        profile = CompanyProfile("923609016", claims=[claim])
        result = verify_proposition({"923609016": profile}, organisation_number="923609016", field="revenue",
            value="185783", currency="NOK", period_end=claim.period_end.date().isoformat(), scope="legal_entity", unit="NOK")
        self.assertEqual(result["status"], "supported")
        mismatch = verify_proposition({"923609016": profile}, organisation_number="923609016", field="revenue",
            value="185783", currency="NOK", period_end=claim.period_end.date().isoformat(), scope="legal_entity", unit="TNOK")
        self.assertNotEqual(mismatch["status"], "supported")
        for malformed in ("not-a-number", "NaN", "Infinity"):
            with self.subTest(value=malformed), self.assertRaisesRegex(ValueError, "finite numeric"):
                verify_proposition({"923609016": profile}, organisation_number="923609016", field="revenue",
                    value=malformed, currency="NOK", period_end=claim.period_end.date().isoformat(),
                    scope="legal_entity", unit="NOK")

    def test_old_undated_job_posting_does_not_become_current(self):
        page = PageRecord(requested_url="https://acme.no/jobs", final_url="https://acme.no/jobs", status=200,
            content_type="text/html", body=b"", digest="d" * 64, retrieved_at=NOW,
            structured={"json-ld": [{"@type": "JobPosting", "title": "Engineer", "datePosted": "2020-01-01",
                "url": "https://acme.no/jobs/1", "hiringOrganization": {"@type": "Organization",
                "name": "Acme AS", "identifier": "923609016"}}]})
        jobs, _, _ = _page_footprints(page, org="923609016", legal_name="Acme AS", verified_names={"Acme AS"}, cutoff=NOW)
        self.assertEqual(len(jobs), 1)
        self.assertIsNone(jobs[0]["status"])

    def test_explicitly_blocked_source_rights_skip_before_network(self):
        class NoNetwork:
            def set_rate_limit(self, *args, **kwargs):
                raise AssertionError("blocked source reached network setup")
        import asyncio
        async def run():
            result = await research_company({"organisation_number": "923609016", "name": "Acme AS",
                "website_candidates": [{"raw": "https://www.acme.no", "source": "registry_live", "rights_status": "NLOD-2.0"}]},
                NoNetwork(), rights_decisions={"acme.no": "blocked"}, phase="verify")
            self.assertEqual(result.audit["candidates"][0]["decision"], "blocked_source_rights")
        asyncio.run(run())

    def test_paired_publication_leaves_explicit_incomplete_marker_on_second_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = OrderedAtomicWriter(Path(directory) / "out.jsonl")
            state = OrderedAtomicWriter(Path(directory) / "state.json")
            with patch.object(state, "write_bytes", side_effect=OSError("injected state failure")):
                with self.assertRaisesRegex(OSError, "injected"):
                    publish_paired_artifacts(output, state, [], b"{}\n")
            marker_path = Path(directory) / "out.jsonl.publication.json"
            marker = json.loads(marker_path.read_text())
            self.assertEqual(marker["status"], "publishing")
            with self.assertRaisesRegex(ValueError, "incomplete"):
                validate_paired_publication(marker_path)

    def test_paired_publication_commit_marker_binds_both_artifact_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = OrderedAtomicWriter(Path(directory) / "out.jsonl")
            state = OrderedAtomicWriter(Path(directory) / "state.json")
            marker = publish_paired_artifacts(output, state, [], b"{\"state\":1}\n")
            self.assertEqual(validate_paired_publication(marker)["status"], "committed")
            output.output_path.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "output artifact"):
                validate_paired_publication(marker)


if __name__ == "__main__":
    unittest.main()
