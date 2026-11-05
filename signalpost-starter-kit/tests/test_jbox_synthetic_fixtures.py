import json
import re
import unittest
from pathlib import Path


PROMPT_PATH = Path(__file__).resolve().parents[2] / "JBOX_PROMPT.md"


class JboxSyntheticFixtureTests(unittest.TestCase):
    def test_inline_company_fixtures_have_resolvable_provenance(self):
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        fixture_match = re.search(r"```json\s*(\[.*?\])\s*```", prompt, re.DOTALL)
        self.assertIsNotNone(fixture_match)
        companies = json.loads(fixture_match.group(1))

        self.assertEqual([company["terminal_state"] for company in companies], ["available", "blocked", "available"])
        self.assertEqual(companies[1]["identity"]["name"]["state"], "blocked")
        self.assertEqual(companies[2]["identity"]["name"]["state"], "ambiguous")

        for company in companies:
            sources = company["sources"]
            snapshots = company["source_snapshots"]
            claims_by_id = {
                claim["claim_id"]: claim
                for section in company["sections"].values()
                for claim in section["claims"]
            }

            for identity_facet in company["identity"].values():
                if isinstance(identity_facet, dict):
                    for claim_id in identity_facet.get("claim_ids", []):
                        self.assertIn(claim_id, claims_by_id)

            for claim in claims_by_id.values():
                for evidence_id in claim["evidence_ids"]:
                    self.assertIn(evidence_id, sources)
                    evidence = sources[evidence_id]
                    self.assertEqual(evidence["evidence_id"], evidence_id)
                    self.assertTrue(evidence["snippet"])
                    self.assertIn(".example.test/", evidence["source_url"])
                    self.assertTrue(evidence["source_url"].endswith(evidence_id.rsplit(":", 1)[-1]))
                    for snapshot_id in evidence["source_snapshot_ids"]:
                        self.assertIn(snapshot_id, snapshots)

                for snapshot_id in claim["source_snapshot_ids"]:
                    self.assertIn(snapshot_id, snapshots)

    def test_prompt_requires_local_bundle_and_source_buttons(self):
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        self.assertIn("Do not show the synthetic examples in this prompt as real companies or use them as production fallback data.", prompt)
        self.assertIn("Put a **Sources** button on every displayed claim.", prompt)
        self.assertIn("If it is absent or malformed, show a clear empty/error state", prompt)


if __name__ == "__main__":
    unittest.main()
