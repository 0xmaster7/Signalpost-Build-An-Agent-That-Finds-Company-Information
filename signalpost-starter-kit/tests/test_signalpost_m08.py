from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import httpx

from signalpost.adapter import to_evaluator
from signalpost.models import (ChangeEvent, ChangeEvidenceRef, ChangeSnapshotRef, ChangeType, Claim, Envelope,
                               Evidence, PublicState, RefreshState, Section, SourceSnapshot)
from signalpost.query import (CompanyProfile, FindFilter, QueryError, compare_companies, find_companies,
                              load_profiles, verify_proposition)
from signalpost.synthesis import synthesize, validate_synthesis
from signalpost.web import _link, create_app
from signalpost.identifiers import website_claim_value_digest


AS_OF = datetime(2024, 12, 31, tzinfo=timezone.utc)


def make_envelope(org: str, name: str, facts: list[dict], *, states: dict | None = None) -> Envelope:
    sections = {key: Section(state=(states or {}).get(key, PublicState.AVAILABLE)) for key in (
        "identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
        "hiring_activity", "claims_evidence_states", "refresh_changes")}
    claims, evidence, snapshots = [], [], []
    for index, fact in enumerate([{"field": "name", "value": name, "section": "identity_brand", "family": "identity"}, *facts]):
        url = fact.get("source_url", f"https://registry.example.test/{org}/{index}")
        digest = hashlib.sha256(json.dumps(fact, sort_keys=True, default=str).encode()).hexdigest()
        evid = f"{org}:e{index}"
        snap = f"{org}:s{index}"
        evidence.append(Evidence(evidence_id=evid, source_url=url, retrieved_at=AS_OF,
            content_sha256=digest, extraction_method="json_pointer_m08_fixture", json_pointer="/value",
            source_class="official", subject_organisation_number=org, source_snapshot_ids=[snap]))
        snapshots.append(SourceSnapshot(source_id=snap, source_url=url, retrieved_at=AS_OF,
            content_sha256=digest, http_status=200, rights_status="fixture"))
        claim_id = (f"{org}:web:{fact['field']}:page-{index}:{website_claim_value_digest(fact['field'], fact['value'])}"
                    if fact.get("family") == "owned_web" else f"{org}:c{index}")
        claim = Claim(claim_id=claim_id, organisation_number=org,
            section=fact.get("section", "identity_brand"), field_family=fact.get("family", "identity"),
            subject_id=org, field=fact["field"], value=fact["value"], state=PublicState.AVAILABLE,
            unit=fact.get("unit"), currency=fact.get("currency"), period_start=fact.get("period_start"),
            period_end=fact.get("period_end"), scope=fact.get("scope", "legal_entity"),
            verification_rule_id="independent_m08_fixture_v1", verification_score="1.0",
            evidence_ids=[evid], source_snapshot_ids=[snap])
        claims.append(claim)
        sections[claim.section].claims.append(claim)
    return Envelope(input_ref="m08:" + org, row_number=1, organisation_number=org,
        terminal_state=PublicState.AVAILABLE, sections=sections, refresh=RefreshState(),
        claims=claims, evidence=evidence, source_snapshots=snapshots, batch_id="m08-gold-fixture", evidence_cutoff=AS_OF)


def finance(value, *, field="revenue", currency="NOK", end="2024-12-31", start="2024-01-01", scope="legal_entity"):
    return {"section": "accounts_history", "family": "financial", "field": field, "value": value,
            "currency": currency, "period_start": datetime.fromisoformat(start).replace(tzinfo=timezone.utc) if start else None,
            "period_end": datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else None, "scope": scope}


def profiles_fixture() -> dict[str, CompanyProfile]:
    rows = [
        make_envelope("001234567", "Acme AS", [
            {"section": "identity_brand", "family": "identity", "field": "legal_form", "value": "AS"},
            {"section": "identity_brand", "family": "identity", "field": "municipality", "value": "Oslo"},
            finance(Decimal("0")), finance(Decimal("-5"), field="annual_result"),
            {"section": "leadership_workplaces", "family": "role", "field": "role.name", "value": "Director A"},
            {"section": "website_owned_profiles", "family": "website", "field": "website_url", "value": "https://acme.example"},
        ]),
        make_envelope("123456789", "Acme Services AS", [
            {"section": "identity_brand", "family": "identity", "field": "legal_form", "value": "AS"},
            {"section": "identity_brand", "family": "identity", "field": "municipality", "value": "Bergen"},
            finance(Decimal("100")),
        ]),
        make_envelope("923609016", "Sparse AS", [], states={"accounts_history": PublicState.BLOCKED,
            "website_owned_profiles": PublicState.AMBIGUOUS, "hiring_activity": PublicState.NOT_AVAILABLE}),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "canonical.jsonl"
        path.write_text("".join(json.dumps(to_evaluator(row), ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        return load_profiles(path)


class FindContractTests(unittest.TestCase):
    def setUp(self):
        self.profiles = profiles_fixture()

    def test_exact_org_leading_zero_and_name_similarity_stays_separate(self):
        exact = find_companies(self.profiles.values(), filters=[FindFilter("organisation_number", "eq", "001234567")])
        self.assertEqual([row["organisation_number"] for row in exact["matches"]], ["001234567"])
        name = find_companies(self.profiles.values(), text="Acme AS")
        self.assertEqual([row["organisation_number"] for row in name["matches"]], ["001234567"])

    def test_frozen_registry_legal_name_spelling_is_searchable_and_verifiable(self):
        envelope = make_envelope("001234567", "Acme AS", [])
        envelope.claims[0].field = "legal_name"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legal-name.jsonl"
            path.write_text(json.dumps(to_evaluator(envelope)) + "\n", encoding="utf-8")
            profiles = load_profiles(path)
        found = find_companies(profiles, filters=[FindFilter("legal_name", "eq", "Acme AS")])
        self.assertEqual([item["organisation_number"] for item in found["matches"]], ["001234567"])
        verified = verify_proposition(profiles, organisation_number="001234567", field="legal_name", value="Acme AS")
        self.assertEqual(verified["status"], "supported")

    def test_multiple_filters_are_and_and_unknown_does_not_match(self):
        result = find_companies(self.profiles.values(), filters=[FindFilter("municipality", "eq", "Oslo"), FindFilter("legal_form", "eq", "AS")])
        self.assertEqual([row["organisation_number"] for row in result["matches"]], ["001234567"])
        blocked = find_companies(self.profiles.values(), filters=[FindFilter("revenue", "gt", Decimal("-1"), "NOK", "2024-12-31", "legal_entity")])
        self.assertEqual([row["organisation_number"] for row in blocked["matches"]], ["001234567", "123456789"])
        self.assertEqual([row["organisation_number"] for row in blocked["unknown"]], ["923609016"])

    def test_numeric_zero_negative_boundaries_and_range(self):
        def run(op, value):
            return find_companies(self.profiles.values(), filters=[FindFilter("annual_result", op, value, "NOK", "2024-12-31", "legal_entity")])
        self.assertEqual([r["organisation_number"] for r in run("eq", Decimal("-5"))["matches"]], ["001234567"])
        self.assertEqual([r["organisation_number"] for r in run("gte", Decimal("0"))["matches"]], [])
        self.assertEqual([r["organisation_number"] for r in run("range", (Decimal("-5"), Decimal("-5")))["matches"]], ["001234567"])

    def test_filter_rejects_currency_or_period_guessing(self):
        with self.assertRaises(QueryError):
            find_companies(self.profiles.values(), filters=[FindFilter("revenue", "gt", Decimal("10"))])
        wrong_currency = find_companies(self.profiles.values(), filters=[FindFilter("revenue", "gt", Decimal("10"), "EUR", "2024-12-31", "legal_entity")])
        self.assertEqual(wrong_currency["matches"], [])
        self.assertEqual(wrong_currency["unknown_count"], 3)
        with self.assertRaises(QueryError):
            find_companies(self.profiles.values(), filters=[FindFilter("revenue", "eval", "x")])

    def test_unknown_field_duplicate_conflict_and_size_are_rejected(self):
        for filters, text in [([FindFilter("sql;drop", "eq", "x")], ""),
            ([FindFilter("legal_form", "eq", "AS")] * 2, ""), ([], "x" * 301)]:
            with self.assertRaises(QueryError):
                find_companies(self.profiles.values(), text=text, filters=filters)
        with self.assertRaises(QueryError):
            find_companies(self.profiles.values(), filters=[FindFilter("organisation_number", "eq", "123")])

    def test_nonfinite_and_extreme_numeric_predicates_are_rejected(self):
        for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("1e100")):
            with self.subTest(value=value), self.assertRaises(QueryError):
                find_companies(self.profiles.values(), filters=[FindFilter(
                    "revenue", "eq", value, "NOK", "2024-12-31", "legal_entity")])

    def test_numeric_dimensions_are_exact_period_currency_and_scope(self):
        for kwargs in ({"currency": "EUR"}, {"period_end": "2023-12-31"}, {"scope": "group"}):
            filters = FindFilter("revenue", "eq", Decimal("0"), "NOK", "2024-12-31", "legal_entity")
            from dataclasses import replace
            result = find_companies(self.profiles.values(), filters=[replace(filters, **kwargs)])
            self.assertEqual(result["matches"], [])
            self.assertGreater(result["unknown_count"], 0)

    def test_conflicting_scalar_values_remain_unknown_instead_of_being_excluded(self):
        one = make_envelope("001234567", "Acme AS", [{"field": "legal_form", "value": "AS"},
            {"field": "legal_form", "value": "ENK"}])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conflicting.jsonl"
            path.write_text(json.dumps(to_evaluator(one)) + "\n", encoding="utf-8")
            records = load_profiles(path)
        result = find_companies(records, filters=[FindFilter("legal_form", "eq", "ASA")])
        self.assertEqual(result["matches"], [])
        self.assertEqual([item["organisation_number"] for item in result["unknown"]], ["001234567"])
        verification = verify_proposition(records, organisation_number="001234567", field="legal_form", value="ASA")
        self.assertEqual(verification["status"], "insufficient_evidence")


class CompareContractTests(unittest.TestCase):
    def setUp(self):
        self.profiles = profiles_fixture()

    def test_comparable_and_missing_both_values_are_not_ranked(self):
        result = compare_companies(self.profiles, ["001234567", "123456789"], ["revenue", "legal_form"])
        revenue, legal_form = result["columns"]
        self.assertEqual(revenue["status"], "comparable")
        self.assertEqual([Decimal(row["value"]) for row in revenue["values"]], [Decimal("0"), Decimal("100")])
        self.assertIsNone(result["ranking"])
        self.assertEqual(legal_form["status"], "comparable")

    def test_different_currency_period_or_scope_is_not_comparable(self):
        base = make_envelope("001234567", "Acme AS", [finance(5, currency="NOK")])
        euro = make_envelope("123456789", "Acme Services AS", [finance(5, currency="EUR")])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "two.jsonl"
            path.write_text(json.dumps(to_evaluator(base)) + "\n" + json.dumps(to_evaluator(euro)) + "\n")
            records = load_profiles(path)
        self.assertEqual(compare_companies(records, ["001234567", "123456789"], ["revenue"])["columns"][0]["status"], "not_comparable")

    def test_period_and_scope_mismatches_are_visible(self):
        base = make_envelope("001234567", "Acme AS", [finance(5, end="2024-12-31")])
        other = make_envelope("123456789", "Acme Services AS", [finance(5, end="2023-12-31", scope="group")])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "two.jsonl"
            path.write_text(json.dumps(to_evaluator(base)) + "\n" + json.dumps(to_evaluator(other)) + "\n")
            records = load_profiles(path)
        column = compare_companies(records, ["001234567", "123456789"], ["revenue"])["columns"][0]
        self.assertEqual(column["status"], "not_comparable")
        self.assertIn("2024-12-31", str(column["values"]))
        self.assertIn("group", str(column["values"]))

    def test_both_missing_and_corrected_financial_values_remain_non_comparable(self):
        both_missing = compare_companies(self.profiles, ["001234567", "123456789"], ["job_title"])
        self.assertEqual([row["status"] for row in both_missing["columns"][0]["values"]], ["unknown", "unknown"])
        corrected = make_envelope("001234567", "Acme AS", [finance(10), finance(12)])
        counterpart = make_envelope("123456789", "Acme Services AS", [finance(10)])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "restated.jsonl"
            path.write_text(json.dumps(to_evaluator(corrected)) + "\n" + json.dumps(to_evaluator(counterpart)) + "\n")
            records = load_profiles(path)
        column = compare_companies(records, ["001234567", "123456789"], ["revenue"])["columns"][0]
        self.assertEqual(column["status"], "not_comparable")
        self.assertEqual(len(column["values"]), 3)

    def test_financial_missing_dimensions_are_not_comparable(self):
        one = make_envelope("001234567", "Acme AS", [finance(1, currency=None, start=None)])
        two = make_envelope("123456789", "Acme Services AS", [finance(2, currency=None, start=None)])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "two.jsonl"
            path.write_text(json.dumps(to_evaluator(one)) + "\n" + json.dumps(to_evaluator(two)) + "\n")
            records = load_profiles(path)
        self.assertEqual(compare_companies(records, ["001234567", "123456789"], ["revenue"])["columns"][0]["status"], "not_comparable")

    def test_identity_isolation_and_exact_company_count(self):
        with self.assertRaises(QueryError):
            compare_companies(self.profiles, ["001234567", "001234567"], ["legal_name"])
        with self.assertRaises(QueryError):
            compare_companies(self.profiles, ["001234567", "123456789", "923609016", "001234567"], ["legal_name"])
        column = compare_companies(self.profiles, ["001234567", "123456789"], ["role.name"])["columns"][0]
        self.assertEqual(column["values"][1]["status"], "unknown")
        self.assertNotIn("001234567", str(column["values"][1]["citations"]))


class VerifyContractTests(unittest.TestCase):
    def setUp(self):
        self.profiles = profiles_fixture()

    def test_supported_proposition_has_traceable_same_company_evidence(self):
        result = verify_proposition(self.profiles, organisation_number="001234567", field="revenue", value="0",
            currency="NOK", period_end="2024-12-31", scope="legal_entity")
        self.assertEqual(result["status"], "supported")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0]["evidence_id"], "001234567:e3")

    def test_genuinely_contradicted_scalar_and_unknown_multi_value(self):
        mismatch = verify_proposition(self.profiles, organisation_number="001234567", field="legal_form", value="ENK")
        self.assertEqual(mismatch["status"], "contradicted")
        multi = verify_proposition(self.profiles, organisation_number="001234567", field="role.name", value="Director B")
        self.assertEqual(multi["status"], "insufficient_evidence")

    def test_unknown_unavailable_incomplete_and_dimensions(self):
        self.assertEqual(verify_proposition(self.profiles, organisation_number="923609016", field="legal_name", value="Other")["status"], "contradicted")
        unavailable = verify_proposition(self.profiles, organisation_number="923609016", field="revenue", value="1",
            currency="NOK", period_end="2024-12-31", scope="legal_entity")
        self.assertEqual(unavailable["status"], "unavailable")
        no_dimensions = verify_proposition(self.profiles, organisation_number="001234567", field="revenue", value="0")
        self.assertEqual(no_dimensions["status"], "insufficient_evidence")
        absent = verify_proposition(self.profiles, organisation_number="999999999", field="revenue", value="1")
        self.assertEqual(absent["status"], "unavailable")
        with self.assertRaises(QueryError):
            verify_proposition(self.profiles, organisation_number="123", field="revenue", value="1")

    def test_contradiction_from_same_company_exact_period_only(self):
        result = verify_proposition(self.profiles, organisation_number="001234567", field="revenue", value="10",
            currency="NOK", period_end="2023-12-31", scope="legal_entity")
        self.assertEqual(result["status"], "insufficient_evidence")

    def test_loader_rejects_wrong_company_evidence_binding(self):
        envelope = make_envelope("001234567", "Acme AS", [])
        payload = to_evaluator(envelope)
        payload["claims"][0]["organisation_number"] = "123456789"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wrong-company.jsonl"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaises(QueryError):
                load_profiles(path)

    def test_loader_rejects_evidence_hash_that_disagrees_with_its_source_snapshot(self):
        payload = to_evaluator(make_envelope("001234567", "Acme AS", []))
        payload["evidence"][0]["content_sha256"] = "f" * 64
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mismatched-snapshot.jsonl"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaises(QueryError):
                load_profiles(path)

    def test_frozen_registry_row_hash_is_bound_to_aggregate_snapshot_by_id(self):
        payload = to_evaluator(make_envelope("001234567", "Acme AS", []))
        snapshot, evidence = payload["source_snapshots"][0], payload["evidence"][0]
        aggregate_id = "registry_snapshot:aggregate"
        snapshot["source_id"] = aggregate_id
        snapshot["content_sha256"] = hashlib.sha256(b"aggregate frozen registry").hexdigest()
        evidence["source_snapshot_ids"] = [aggregate_id]
        evidence["extraction_method"] = "frozen_registry_jsonl_v1"
        for claim in payload["claims"]:
            claim["source_snapshot_ids"] = [aggregate_id]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frozen-row.jsonl"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            self.assertIn("001234567", load_profiles(path))

    def test_loader_rejects_m07_event_for_another_company(self):
        payload = to_evaluator(make_envelope("001234567", "Acme AS", []))
        payload["refresh"]["changes"] = [{"event_id": "foreign-event", "type": "brand_changed",
            "organisation_number": "123456789", "observed_at": AS_OF.isoformat(), "provenance_complete": False}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "foreign-event.jsonl"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaises(QueryError):
                load_profiles(path)


class SynthesisContractTests(unittest.TestCase):
    def test_all_synthesis_sentences_are_claim_and_evidence_backed(self):
        envelope = make_envelope("001234567", "Acme AS", [finance(Decimal("0"))])
        output = synthesize(envelope)
        validate_synthesis(envelope, output)
        self.assertTrue(output["sentences"])
        self.assertTrue(all(sentence["fact_ids"] and sentence["evidence_ids"] for sentence in output["sentences"]))
        self.assertTrue(any("0" in sentence["text"] for sentence in output["sentences"]))

    def test_equal_facts_from_distinct_pages_publish_once_with_all_provenance(self):
        heading = {"section": "website_owned_profiles", "family": "owned_web",
                   "field": "product_or_service_heading", "value": "Tjenester"}
        envelope = make_envelope("001234567", "Acme AS", [heading, {**heading, "source_url":
            "https://acme.example/services"}])
        output = synthesize(envelope)
        matching = [item for item in output["sentences"] if item["text"].startswith("product_or_service_heading:")]
        self.assertEqual(len(matching), 1)
        self.assertEqual(len(matching[0]["fact_ids"]), 2)
        self.assertEqual(len(matching[0]["evidence_ids"]), 2)
        validate_synthesis(envelope, output)

        duplicate = copy.deepcopy(output)
        duplicate["sentences"].append(copy.deepcopy(matching[0]))
        with self.assertRaisesRegex(ValueError, "duplicate factual synthesis sentence"):
            validate_synthesis(envelope, duplicate)

    def test_deduplicated_fact_sentence_requires_a_citation_for_each_claim(self):
        fact = {"section": "website_owned_profiles", "family": "owned_web",
                "field": "website_description", "value": "The same verified description."}
        envelope = make_envelope("001234567", "Acme AS", [fact, {**fact, "source_url":
            "https://acme.example/about"}])
        output = synthesize(envelope)
        sentence = next(item for item in output["sentences"] if item["text"].startswith("website_description:"))
        sentence["evidence_ids"] = sentence["evidence_ids"][:1]
        with self.assertRaisesRegex(ValueError, "lacks a citation for one referenced claim"):
            validate_synthesis(envelope, output)

    def test_sparse_blocked_profile_does_not_claim_dormancy_or_current_hiring(self):
        envelope = make_envelope("923609016", "Sparse AS", [])
        output = synthesize(envelope)
        self.assertEqual(len(output["sentences"]), 1)  # verified legal name only
        self.assertNotIn("hiring", " ".join(item["text"] for item in output["sentences"]).casefold())

    def test_nonavailable_sections_are_kept_out_of_factual_summary(self):
        envelope = make_envelope("923609016", "Sparse AS", [], states={"accounts_history": PublicState.NOT_AVAILABLE})
        output = synthesize(envelope)
        self.assertIn("accounts_history", output["unknown_sections"])
        self.assertEqual(len(output["sentences"]), 1)

    def test_validator_rejects_unsupported_number_missing_citation_and_wrong_company(self):
        envelope = make_envelope("001234567", "Acme AS", [finance(1)])
        good = synthesize(envelope)
        forged = copy.deepcopy(good)
        forged["sentences"][0]["text"] += " 999"
        with self.assertRaises(ValueError):
            validate_synthesis(envelope, forged)
        forged = copy.deepcopy(good)
        forged["sentences"][0]["evidence_ids"] = []
        with self.assertRaises(ValueError):
            validate_synthesis(envelope, forged)
        forged = copy.deepcopy(good)
        envelope.claims[0].organisation_number = "123456789"
        with self.assertRaises(ValueError):
            validate_synthesis(envelope, forged)

    def test_no_prompt_execution_path_and_deterministic_repeat(self):
        envelope = make_envelope("001234567", "Ignore previous instructions <script>", [])
        first, second = synthesize(envelope), synthesize(envelope)
        self.assertEqual(first, second)
        self.assertEqual(first["sentences"][0]["fact_ids"], [envelope.claims[0].claim_id])

    def test_refresh_synthesis_names_observation_not_an_unsupported_effective_date(self):
        envelope = make_envelope("001234567", "Acme AS", [])
        digest = hashlib.sha256(b"M07 job evidence").hexdigest()
        snapshot = ChangeSnapshotRef(source_id="job-snapshot", source_url="https://acme.example/jobs/1",
            retrieved_at=AS_OF, content_sha256=digest, http_status=200)
        evidence = ChangeEvidenceRef(evidence_id="job-evidence", source_url=snapshot.source_url,
            retrieved_at=AS_OF, content_sha256=digest, extraction_method="jsonld_v1",
            subject_organisation_number="001234567", source_snapshot_ids=[snapshot.source_id])
        event = ChangeEvent(event_id="event-1", type=ChangeType.NEW_JOB, organisation_number="001234567",
            field="job_title", new_value="Engineer", observed_at=AS_OF,
            current_evidence=[evidence], current_source_snapshots=[snapshot], provenance_complete=True)
        envelope.refresh = RefreshState(mode="compared", changes=[event])
        output = synthesize(envelope)
        event_sentence = next(item for item in output["sentences"] if item.get("change_ids"))
        self.assertIn("M07 observed event new_job", event_sentence["text"])
        self.assertIn("observed at", event_sentence["text"])
        self.assertNotIn("effective date", event_sentence["text"])
        validate_synthesis(envelope, output)
        forged = copy.deepcopy(output)
        forged["sentences"][-1]["text"] = "The company changed on " + AS_OF.isoformat()
        with self.assertRaises(ValueError):
            validate_synthesis(envelope, forged)

    def test_historical_jobs_and_different_period_revenue_do_not_create_bridging_inference(self):
        envelope = make_envelope("001234567", "Acme AS", [
            {"section": "hiring_activity", "family": "jobs", "field": "job_status", "value": "closed", "scope": "job"},
            finance(1, end="2023-12-31"), finance(2, end="2024-12-31")])
        output = synthesize(envelope)
        text = " ".join(item["text"].casefold() for item in output["sentences"])
        self.assertNotIn("currently hiring", text)
        self.assertNotIn("rapidly expanding", text)
        self.assertNotIn("growth", text)


class ServerRenderedUXTests(unittest.TestCase):
    def setUp(self):
        self.rows = [make_envelope("001234567", "Acme <script> AS", [finance(0),
            {"section": "identity_brand", "family": "identity", "field": "legal_form", "value": "AS"},
            {"section": "identity_brand", "family": "identity", "field": "municipality", "value": "Oslo"},
            {"section": "website_owned_profiles", "family": "website", "field": "website_url", "value": "https://acme.example"}]),
            make_envelope("123456789", "Acme Services AS", [finance(2, currency="EUR"),
                {"section": "identity_brand", "family": "identity", "field": "legal_form", "value": "AS"},
                {"section": "identity_brand", "family": "identity", "field": "municipality", "value": "Bergen"}])]
        self.history_digest = hashlib.sha256(b"M08 history fixture").hexdigest()
        history_snapshot = ChangeSnapshotRef(source_id="m08-history-snapshot", source_url="https://acme.example/jobs/1",
            retrieved_at=AS_OF, content_sha256=self.history_digest, http_status=200)
        history_evidence = ChangeEvidenceRef(evidence_id="m08-history-evidence", source_url=history_snapshot.source_url,
            retrieved_at=AS_OF, content_sha256=self.history_digest, extraction_method="jsonld_v1",
            subject_organisation_number="001234567", source_snapshot_ids=[history_snapshot.source_id])
        self.rows[0].refresh.changes = [ChangeEvent(event_id="m08-history-event", type=ChangeType.NEW_JOB,
            organisation_number="001234567", field="job_title", new_value="Engineer", observed_at=AS_OF,
            current_evidence=[history_evidence], current_source_snapshots=[history_snapshot], provenance_complete=True)]
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "canonical.jsonl"
        self.path.write_text("".join(json.dumps(to_evaluator(row), ensure_ascii=False) + "\n" for row in self.rows), encoding="utf-8")
        self.app = create_app(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def get(self, path, params=None):
        async def request():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver") as client:
                return await client.get(path, params=params)
        return asyncio.run(request())

    def test_find_profile_evidence_compare_verify_and_changes_routes(self):
        found = self.get("/", params={"q": "Acme"})
        self.assertEqual(found.status_code, 200)
        self.assertIn("Find companies", found.text)
        and_find = self.get("/", params=[("q", "Acme"), ("filter_field", "legal_form"),
            ("filter_op", "eq"), ("filter_value", "AS"), ("filter_field", "municipality"),
            ("filter_op", "eq"), ("filter_value", "Oslo")])
        self.assertIn("1 match", and_find.text)
        profile = self.get("/companies/001234567")
        for section in ("Identity and public brand", "Accounts and history", "Leadership and workplaces",
                        "Website and owned profiles", "Hiring and activity", "Evidence and availability", "Refresh and changes"):
            self.assertIn(section, profile.text)
        evidence_id = next(iter(load_profiles(self.path)["001234567"].evidence))
        detail = self.get(f"/evidence/001234567/{evidence_id}")
        self.assertIn("Content SHA-256", detail.text)
        compare = self.get("/compare", params=[("org", "001234567"), ("org", "123456789"), ("field", "revenue")])
        self.assertIn("not_comparable", compare.text)
        verify = self.get("/verify", params={"org": "001234567", "field": "revenue", "value": "0",
            "currency": "NOK", "period_end": "2024-12-31", "scope": "legal_entity"})
        self.assertIn("supported", verify.text)
        self.assertEqual(self.get("/changes").status_code, 200)
        history = self.get("/changes", params={"org": "001234567"})
        self.assertIn("m08-history-evidence", history.text)
        self.assertIn("effective date not established", history.text)
        history_detail = self.get("/evidence/001234567/m08-history-evidence")
        self.assertIn(self.history_digest, history_detail.text)

    def test_xss_escaping_responsive_keyboard_and_safe_external_links(self):
        response = self.get("/", params={"q": "<script>alert(1)</script>"})
        self.assertIn("&lt;script&gt;", response.text)
        self.assertNotIn("<script>alert(1)</script>", response.text)
        profile = self.get("/companies/001234567").text
        self.assertIn('name="viewport"', profile)
        self.assertIn("@media(max-width:650px)", profile)
        self.assertIn(":focus", profile)
        self.assertIn('rel="noopener noreferrer"', profile)
        self.assertNotIn('href="javascript:', profile)
        self.assertNotIn('href="javascript:', _link("javascript:alert(1)"))

    def test_unknown_or_malicious_route_inputs_are_rejected(self):
        self.assertEqual(self.get("/companies/attacker-name").status_code, 404)
        self.assertEqual(self.get("/compare", params={"org": "1,2,3,4,5"}).status_code, 400)
        self.assertEqual(self.get("/", params={"field": "revenue", "op": "exec", "value": "1"}).status_code, 400)
        self.assertEqual(self.get("/changes", params={"org": "x" * 5000}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
