from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from signalpost.models import Envelope
from signalpost.site_export import BUNDLE_LIMIT_BYTES, SiteExportError, export_site_data, resolve_source, safe_link
from signalpost.synthesis import synthesize

ROOT = Path(__file__).resolve().parents[2]
STAMP = "2026-11-01T00:00:00Z"
SECTION_NAMES = ("identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
                 "hiring_activity", "claims_evidence_states", "refresh_changes")


def synthetic_row(organisation_number: str = "000000001", *, snippet: str = "Synthetic public legal record") -> dict:
    sections = {name: {"state": "available", "attempt_outcome": None, "claims": []} for name in SECTION_NAMES}
    row = {"input_ref": "synthetic:" + organisation_number, "organisation_number": organisation_number,
           "terminal_state": "available", "sections": sections, "claims": [], "evidence": [], "source_snapshots": [],
           "refresh": {"changes": []}, "synthesis": {}, "errors": [], "operations": [],
           "batch": {"batch_id": "synthetic-site-test", "evidence_cutoff": STAMP}, "run": {"created_at": STAMP}}
    add_fact(row, "name", "SYNTHETIC Fjord Example AS", snippet=snippet)
    add_fact(row, "municipality", "SYNTHETIC Municipality")
    add_fact(row, "industry_codes.0", {"kode": "00.000", "beskrivelse": "SYNTHETIC industry"})
    return row


def add_fact(row: dict, field: str, value, *, section: str = "identity_brand", state: str = "available",
             snippet: str = "Synthetic evidence", **dimensions) -> dict:
    organisation_number = row["organisation_number"]
    sequence = len(row["claims"])
    evidence_id = f"{organisation_number}:evidence:{sequence}"
    snapshot_id = f"{organisation_number}:snapshot:{sequence}"
    source_url = f"https://synthetic.example.test/{organisation_number}/{sequence}"
    digest = hashlib.sha256(f"synthetic:{organisation_number}:{sequence}".encode()).hexdigest()
    claim = {"claim_id": f"{organisation_number}:claim:{sequence}", "organisation_number": organisation_number,
             "section": section, "field_family": "financial" if section == "accounts_history" else "identity",
             "subject_id": organisation_number, "field": field, "value": value, "state": state,
             "scope": "legal_entity", "verification_rule_id": "synthetic_site_test_v1", "verification_score": "1",
             "evidence_ids": [evidence_id], "source_snapshot_ids": [snapshot_id], **dimensions}
    row["claims"].append(claim)
    row["sections"][section]["claims"].append(copy.deepcopy(claim))
    row["sections"]["claims_evidence_states"]["claims"].append(copy.deepcopy(claim))
    row["evidence"].append({"evidence_id": evidence_id, "source_url": source_url,
                            "retrieved_at": STAMP, "content_sha256": digest,
                            "extraction_method": "synthetic_json_v1", "json_pointer": "/synthetic/value",
                            "excerpt": snippet, "page_number": 2, "subject_organisation_number": organisation_number,
                            "source_snapshot_ids": [snapshot_id]})
    row["source_snapshots"].append({"source_id": snapshot_id, "source_url": source_url, "retrieved_at": STAMP,
                                    "content_sha256": digest, "http_status": 200, "rights_status": "synthetic"})
    return claim


def attach_summary(row: dict) -> dict:
    envelope = Envelope.model_validate({"input_ref": row["input_ref"], "row_number": 1,
        "organisation_number": row["organisation_number"], "terminal_state": row["terminal_state"],
        "sections": row["sections"], "claims": row["claims"], "evidence": row["evidence"],
        "source_snapshots": row["source_snapshots"], "refresh": row["refresh"],
        "batch_id": row["batch"]["batch_id"], "evidence_cutoff": STAMP})
    row["synthesis"] = {"schema_version": 1, "summary": synthesize(envelope)}
    return row


def attach_change(row: dict) -> None:
    row["refresh"]["changes"] = [{"event_id": "synthetic:change:1", "type": "claim_changed",
        "organisation_number": row["organisation_number"], "section": "identity_brand", "field": "name",
        "old_value": "SYNTHETIC Old Name AS", "new_value": row["claims"][0]["value"],
        "observed_at": STAMP, "provenance_complete": True,
        "previous_evidence": [], "current_evidence": copy.deepcopy(row["evidence"][:1]),
        "previous_source_snapshots": [], "current_source_snapshots": copy.deepcopy(row["source_snapshots"][:1])}]


class SiteExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.input_path = self.directory / "evaluator.jsonl"
        self.output = self.directory / "site-data"

    def export(self, rows: list[dict], **options):
        self.input_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        return export_site_data(self.input_path, self.output, **options)

    def company(self, organisation_number="000000001"):
        return json.loads((self.output / "companies" / f"{organisation_number}.json").read_bytes())

    def test_full_evidence_dimensions_and_summary_are_preserved(self):
        row = synthetic_row()
        add_fact(row, "revenue", 12345678, section="accounts_history", currency="NOK", unit="TNOK",
                 period_start="2025-01-01T00:00:00Z", period_end="2025-12-31T00:00:00Z", scope="group")
        attach_change(row)
        attach_summary(row)
        report = self.export([row])
        company = self.company()
        self.assertEqual(company["supported_summary"], row["synthesis"]["summary"])
        claim = company["sections"]["accounts_history"]["claims"][0]
        self.assertEqual((claim["value"], claim["currency"], claim["unit"], claim["scope"]), (12345678, "NOK", "TNOK", "group"))
        self.assertEqual(claim["period_end"], "2025-12-31T00:00:00Z")
        source = resolve_source(company, claim["evidence_ids"][0])
        self.assertEqual(source["content_sha256"], row["evidence"][-1]["content_sha256"])
        self.assertEqual((source["retrieved_at"], source["page_number"], source["json_pointer"]), (STAMP, 2, "/synthetic/value"))
        self.assertEqual(company["change_history"][0]["observed_at"], STAMP)
        index = json.loads((self.output / "index.json").read_bytes())
        self.assertEqual(index["companies"][0]["orgnr"], "000000001")
        self.assertEqual(index["companies"][0]["company_sha256"], hashlib.sha256((self.output / "companies/000000001.json").read_bytes()).hexdigest())
        self.assertLessEqual(report["bundle_bytes"], BUNDLE_LIMIT_BYTES)

    def test_missing_summary_does_not_invent_narrative(self):
        self.export([synthetic_row()])
        self.assertIsNone(self.company()["supported_summary"])
        self.assertEqual(self.company()["summary_state"], "not_provided")

    def test_every_public_state_and_unattempted_state_remains_distinct(self):
        row = synthetic_row()
        states = ["available", "not_available", "blocked", "ambiguous", "failed", "not_applicable", None]
        for section_name, state in zip(SECTION_NAMES, states):
            row["sections"][section_name]["state"] = state
        row["sections"]["refresh_changes"]["attempt_outcome"] = "budget_skipped"
        for state in states[:-1]:
            add_fact(row, "synthetic_state_" + state, 0 if state == "available" else None, state=state)
        self.export([row])
        company = self.company()
        self.assertEqual([company["sections"][name]["state"] for name in SECTION_NAMES], states)
        self.assertEqual(company["sections"]["refresh_changes"]["attempt_outcome"], "budget_skipped")
        self.assertEqual({claim["state"] for claim in company["sections"]["identity_brand"]["claims"]}, set(states[:-1]))
        index = json.loads((self.output / "index.json").read_bytes())
        self.assertEqual(index["companies"][0]["availability"]["sections"]["accounts_history"]["state"], "not_available")

    def test_exact_duplicate_rows_deduplicate_deterministically(self):
        row = attach_summary(synthetic_row())
        duplicate = copy.deepcopy(row)
        duplicate["input_ref"] = "synthetic:duplicate-input"
        report = self.export([row, duplicate])
        self.assertEqual((report["company_count"], report["duplicate_rows"]), (1, 1))
        repeat = self.directory / "repeat"
        export_site_data(self.input_path, repeat)
        self.assertEqual((repeat / "bundle.json").read_bytes(), (self.output / "bundle.json").read_bytes())
        self.assertEqual(len(self.company()["sections"]["identity_brand"]["claims"]), 3)

    def test_conflicting_duplicate_company_is_rejected_without_files(self):
        row = synthetic_row()
        conflict = copy.deepcopy(row)
        conflict["sections"]["accounts_history"]["state"] = "failed"
        with self.assertRaisesRegex(SiteExportError, "conflicting rows"):
            self.export([row, conflict])
        self.assertFalse(self.output.exists())

    def test_rejects_forged_evidence_and_dimensions(self):
        mutations = {
            "wrong_company": lambda row: row["evidence"][0].update(subject_organisation_number="000000002"),
            "wrong_hash": lambda row: row["evidence"][0].update(content_sha256="f" * 64),
            "wrong_url": lambda row: row["evidence"][0].update(source_url="https://foreign.example.test/"),
            "missing_evidence": lambda row: row.update(evidence=[]),
            "missing_snapshot": lambda row: row.update(source_snapshots=[]),
            "section_forgery": lambda row: row["sections"]["identity_brand"]["claims"][0].update(value="forged"),
            "unsupported_summary": lambda row: row["synthesis"]["summary"]["sentences"][0].update(text="Uncited invention"),
            "foreign_change": lambda row: row["refresh"]["changes"][0].update(organisation_number="000000002"),
            "historical_hash": lambda row: row["refresh"]["changes"][0]["current_evidence"][0].update(content_sha256="f" * 64),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                row = synthetic_row()
                attach_change(row)
                attach_summary(row)
                mutate(row)
                with self.assertRaises(SiteExportError):
                    self.export([row])
                self.assertFalse(self.output.exists())
        for dimensions in ({"unit": "unsupported"}, {"scope": "unknown"}, {"period_start": None},
                           {"period_end": "2024-01-01T00:00:00Z"}, {"value": True}, {"value": "NaN"}):
            with self.subTest(dimensions=dimensions):
                row = synthetic_row()
                financial = {"unit": "NOK", "currency": "NOK", "scope": "legal_entity",
                             "period_start": "2025-01-01T00:00:00Z", "period_end": "2025-12-31T00:00:00Z", "value": 0,
                             **dimensions}
                value = financial.pop("value")
                add_fact(row, "revenue", value, section="accounts_history", **financial)
                with self.assertRaises(SiteExportError):
                    self.export([row])

    def test_ambiguous_identity_keeps_alternatives_instead_of_picking_name(self):
        row = synthetic_row()
        add_fact(row, "legal_name", "SYNTHETIC Conflicting Name AS")
        self.export([row])
        identity = self.company()["identity"]["name"]
        self.assertIsNone(identity["value"])
        self.assertEqual(identity["state"], "ambiguous")
        self.assertEqual(len(identity["values"]), 2)

    def test_unavailable_identity_and_mixed_state_remain_explicit(self):
        row = synthetic_row()
        row["claims"][0]["state"] = "not_available"
        for section_name in ("identity_brand", "claims_evidence_states"):
            for claim in row["sections"][section_name]["claims"]:
                if claim["claim_id"] == row["claims"][0]["claim_id"]:
                    claim["state"] = "not_available"
        self.export([row])
        company = self.company()
        self.assertEqual(company["identity"]["name"]["state"], "not_available")
        self.assertEqual(company["identity"]["name"]["values"], [])
        index = json.loads((self.output / "index.json").read_bytes())
        self.assertIsNone(index["companies"][0]["name"])

    def test_contacts_omitted_but_public_legal_text_remains(self):
        row = synthetic_row(snippet="Public legal purpose. Person: secret@example.test; +47 12345678")
        add_fact(row, "contact_email", "secret@example.test")
        add_fact(row, "registered_purpose", ["SYNTHETIC legal purpose retained verbatim"])
        add_fact(row, "role.name", "SYNTHETIC Legal Director", section="leadership_workplaces")
        attach_summary(row)
        self.export([row])
        payload = (self.output / "bundle.json").read_text()
        self.assertNotIn("secret@example.test", payload)
        self.assertNotIn("+47 12345678", payload)
        self.assertIn("SYNTHETIC legal purpose retained verbatim", payload)
        self.assertIn("SYNTHETIC Legal Director", payload)
        self.assertEqual(self.company()["privacy"]["omitted_claims"], 1)
        self.assertTrue(resolve_source(self.company(), row["evidence"][0]["evidence_id"])["snippet_redacted"])

    def test_script_payload_is_data_and_unsafe_urls_are_not_links(self):
        row = synthetic_row(snippet="</script><img src=x onerror=alert(1)>")
        row["evidence"][0]["source_url"] = "javascript:alert(1)"
        row["source_snapshots"][0]["source_url"] = "javascript:alert(1)"
        self.export([row])
        payload = (self.output / "bundle.json").read_bytes()
        self.assertNotIn(b"</script>", payload)
        source = resolve_source(self.company(), row["evidence"][0]["evidence_id"])
        self.assertIsNone(source["link_url"])
        self.assertEqual(source["source_url"], "javascript:alert(1)")
        for source_url in ("data:text/html,test", "//example.test/path", "https://user:pass@example.test/", "https://example.test/\n", "https://example.test:bad/", "https://example.test\\@evil.test/"):
            self.assertIsNone(safe_link(source_url))
        self.assertEqual(safe_link("https://synthetic.example.test/record"), "https://synthetic.example.test/record")

    def test_100_company_bundle_cap_and_full_provenance_after_compaction(self):
        rows = [synthetic_row(f"{sequence:09}", snippet="SYNTHETIC å evidence " * 1800) for sequence in range(1, 101)]
        report = self.export(rows)
        self.assertEqual(report["company_count"], 100)
        self.assertLessEqual(report["bundle_bytes"], 3_000_000)
        bundle = json.loads((self.output / "bundle.json").read_bytes())
        self.assertTrue(bundle["compact"])
        compact = bundle["companies"]["000000001"]
        source_id = rows[0]["evidence"][0]["evidence_id"]
        self.assertTrue(compact["sources"][source_id]["snippet_truncated"])
        self.assertEqual(compact["sources"][source_id]["content_sha256"], rows[0]["evidence"][0]["content_sha256"])
        self.assertEqual(resolve_source(self.company(), source_id)["snippet"], rows[0]["evidence"][0]["excerpt"])

    def test_oversized_facts_omitted_explicitly_and_resolve_in_full_file(self):
        row = synthetic_row()
        for sequence in range(16):
            add_fact(row, "synthetic_large_fact_" + str(sequence), "SYNTHETIC public value " * 4000)
        report = self.export([row], bundle_limit_bytes=32_000)
        bundle = json.loads((self.output / "bundle.json").read_bytes())
        compact = bundle["companies"]["000000001"]
        self.assertLessEqual(report["bundle_bytes"], 32_000)
        self.assertGreater(compact["compaction"]["omitted_facts"], 0)
        self.assertTrue(compact["compaction"]["omitted_source_ids"])
        self.assertEqual(compact["compaction"]["omitted_facts"], 19)
        source_id = compact["compaction"]["omitted_source_ids"][0]
        self.assertEqual(resolve_source(self.company(), source_id)["evidence_id"], source_id)
        self.assertEqual(sum(len(section["claims"]) for section in self.company()["sections"].values()), 19)

    def test_impossible_cap_and_nonempty_destination_leave_no_partial_export(self):
        with self.assertRaisesRegex(SiteExportError, "cannot fit"):
            self.export([synthetic_row()], bundle_limit_bytes=20)
        self.assertFalse(self.output.exists())
        self.output.mkdir()
        sentinel = self.output / "existing.json"
        sentinel.write_text("keep")
        with self.assertRaisesRegex(SiteExportError, "must be empty"):
            self.export([synthetic_row()])
        self.assertEqual(sentinel.read_text(), "keep")

    def test_invalid_inputs_are_counted_without_exporting_diagnostics_or_raw_data(self):
        invalid = {"organisation_number": "not-an-org", "terminal_state": "failed", "claims": [], "evidence": [],
                   "errors": [{"code": "INPUT_INVALID", "message": "secret@example.test"}]}
        report = self.export([invalid, synthetic_row()])
        self.assertEqual(report["rejected_input_rows"], 1)
        self.assertNotIn("secret@example.test", (self.output / "index.json").read_text())

    def test_cli_works_from_an_unrelated_directory(self):
        self.input_path.write_text(json.dumps(synthetic_row()) + "\n")
        completed = subprocess.run([sys.executable, str(ROOT / "signalpost-starter-kit/scripts/export_site_data.py"),
            "--input", str(self.input_path), "--output-dir", str(self.output)], cwd=self.directory,
            capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["company_count"], 1)


if __name__ == "__main__":
    unittest.main()
