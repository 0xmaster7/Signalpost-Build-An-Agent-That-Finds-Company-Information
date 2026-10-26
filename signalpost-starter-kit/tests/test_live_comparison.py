import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_live_envelopes.py"
SPEC = importlib.util.spec_from_file_location("live_comparison", SCRIPT)
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


class LiveComparisonTests(unittest.TestCase):
    def evidence(self, provider):
        return [{"evidence_id" if provider == "ours" else "id": "one", "source_url": "https://data.brreg.no/example",
            "content_sha256": "a" * 64, "retrieved_at": "2026-10-26T00:00:00Z", "extraction_method": "fixture",
            "json_pointer": "/amount"}]

    def test_available_top_level_claims_only_not_repeated_sections(self):
        claim = {"state": "available", "field": "revenue", "value": 0, "unit": "NOK", "currency": "NOK",
            "period_start": "2025-01-01T00:00:00Z", "period_end": "2025-12-31T00:00:00Z", "scope": "legal_entity", "evidence_ids": ["one"]}
        value = {"claims": [claim], "sections": {"accounts": {"claims": [claim]}}, "evidence": self.evidence("ours")}
        result = comparison.normalize(value, "ours")
        self.assertEqual(result["financial_claims"], 1)
        self.assertEqual(result["financial"][0]["value"], "0")
        self.assertEqual(result["evidence_complete_financial_claims"], 1)

    def test_registry_only_and_group_site_are_not_verified_websites(self):
        fields = [{"field": "official_website", "value": "https://example.no/", "availability": "available", "identity_level": "registry_declared"},
            {"field": "official_website", "value": "https://group.no/", "availability": "available", "identity_level": "exact", "site_relation": "parent_or_group_site"}]
        result = comparison.normalize({"claims": fields}, "arnav")
        self.assertEqual(result["verified_websites"], 0)
        self.assertEqual(result["registry_or_shared_url_references"], 2)

    def test_pipeline_diagnostics_do_not_count_unit_state_strings_as_amounts(self):
        envelope = {"synthesis": {"brreg_observations": {"financial_records": 3}}, "errors": [
            {"code": "BRREG_FINANCIAL_UNIT_UNSUPPORTED", "message": "Financial metric revenue was withheld because unit is missing"},
            {"code": "BRREG_FINANCIAL_UNIT_UNSUPPORTED", "message": "Financial metric revenue_unit_state was withheld because unit is missing"}]}
        result = comparison.pipeline(envelope)
        self.assertEqual(result["structured_api_records"], 3)
        self.assertEqual(result["structured_api_unit_withheld_metric_attempts"], 1)

    def test_registered_headcount_and_employee_statements_are_not_fte(self):
        fields = [{"field": "workforce", "availability": "available", "value": {"measure": "employees", "value": 6}},
            {"field": "registered_employees", "availability": "available", "value": 6},
            {"field": "workforce", "availability": "available", "value": {"measure": "full_time_equivalents", "value": 0},
             "reporting_period": {"start": "2025-01-01", "end": "2025-12-31"}}]
        result = comparison.normalize({"claims": fields}, "arnav")
        self.assertEqual(result["fte_claims"], 1)
        self.assertEqual(result["fte"][0]["value"], "0")

    def test_skipped_website_phase_is_not_reported_as_completed_crawl(self):
        result = comparison.pipeline({"synthesis": {"website_research": {
            "execution_state": "deadline_skipped", "reason": "soft_deadline_or_completion_reserve"}}})
        self.assertEqual(result["website_execution_state"], "deadline_skipped")
        self.assertEqual(result["website_execution_reason"], "soft_deadline_or_completion_reserve")
        self.assertIsNone(result["website_crawl_state"])

    def test_many_job_atoms_and_cross_source_uuid_are_one_posting(self):
        vacancy = "12345678-1234-1234-1234-123456789abc"
        fields = [{"field_family": "jobs", "scope": "job", "state": "available", "field": field,
                   "subject_id": subject, "value": value} for subject in ("nav:" + vacancy, "site:" + vacancy)
            for field, value in (("job_title", "Engineer"), ("canonical_job_url", "https://arbeidsplassen.nav.no/stillinger/stilling/" + vacancy))]
        result = comparison.normalize({"claims": fields}, "ours")
        self.assertEqual(result["verified_jobs"], 1)
        self.assertEqual(result["new_source_contributions"]["nav_jobs"], 1)

    def test_declared_unit_conversion_does_not_mix_company_and_group(self):
        base = {"metric": "revenue", "value": "1000", "declared_currency_value": "1000", "currency": "NOK",
                "period_start": "2025-01-01", "period_end": "2025-12-31", "scope": "legal_entity"}
        other = {**base, "value": "1", "declared_currency_value": "1000.0"}
        rows = comparison.pair_observations({"financial": [base]}, {"financial": [other]}, "financial")
        self.assertEqual(rows[0]["status"], "equal_declared_dimensions")
        self.assertTrue(rows[0]["unit_contract_caveat"])
        rows = comparison.pair_observations({"financial": [base]}, {"financial": [{**other, "scope": "group"}]}, "financial")
        self.assertEqual({row["status"] for row in rows}, {"only_ours", "only_arnav"})

    def test_missing_dimensions_and_real_conflicts_are_not_matches(self):
        base = {"metric": "revenue", "value": "1", "declared_currency_value": None, "currency": "NOK", "scope": "unknown"}
        rows = comparison.pair_observations({"financial": [base]}, {"financial": [base]}, "financial")
        self.assertEqual(rows[0]["status"], "not_comparable_dimensions")
        base.update(scope="legal_entity", period_start="2025-01-01", period_end="2025-12-31", declared_currency_value="1")
        rows = comparison.pair_observations({"financial": [base]}, {"financial": [{**base, "declared_currency_value": "2"}]}, "financial")
        self.assertEqual(rows[0]["status"], "value_mismatch")


if __name__ == "__main__":
    unittest.main()
