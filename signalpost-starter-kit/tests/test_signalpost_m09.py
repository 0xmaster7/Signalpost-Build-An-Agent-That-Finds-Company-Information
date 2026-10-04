from __future__ import annotations

import sys
import unittest
import hashlib
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "signalpost-starter-kit" / "scripts"))

from run_m06_scale_gate import synthetic_org_number
from signalpost.inputs import parse_records
from signalpost.network import _EXTRACT, registered_domain
from signalpost.models import Envelope, Evidence, SourceSnapshot
from signalpost.adapter import to_evaluator
from signalpost.synthesis import synthesize
from signalpost import run as run_module
from test_signalpost_m01 import valid_envelope
from signalpost.websites import PageRecord, _additional_evidence_snapshot_ids, _make_claim, _page_key
from run_m02_foundation_smoke import (_atomic_json, _preserve_run_bundle,
    _run_preserving_failure, _validate_evaluator_rows)


class M09ReleaseInputMatrixTests(unittest.TestCase):
    def test_allowed_formats_preserve_order_duplicates_strings_and_unicode(self):
        cases = {
            "jsonl": ('\ufeff{"organisation_number":"001234567","name":"Ålesund AS"}\r\n'
                      '{"orgnr":"923609016","name":"Quoted Name AS"}\r\n'
                      '{"organisation_number":"001234567"}\r\n'),
            "json": '[{"organisation_number":"001234567","name":"Ålesund AS"},'
                    '{"orgnr":"923609016","name":"Quoted, \\"Name\\" AS"}]',
            "csv": 'organisation_number,name\r\n001234567,"Ålesund, AS"\r\n923609016,"Quoted ""Name"" AS"\r\n',
            "tsv": 'organisation_number\tname\r\n001234567\tÅlesund AS\r\n923609016\t"Quoted\tName AS"\r\n',
            "plain": '001234567\r\n923609016\r\n001234567\r\n',
        }
        expected_counts = {"jsonl": 3, "json": 2, "csv": 2, "tsv": 2, "plain": 3}
        for fmt, data in cases.items():
            with self.subTest(format=fmt):
                rows = parse_records(data, fmt)
                self.assertEqual(len(rows), expected_counts[fmt])
                self.assertEqual([row.input_ref for row in rows], [f"row:{i}" for i in range(1, len(rows) + 1)])
                self.assertEqual(rows[0].organisation_number, "001234567")
                self.assertIsInstance(rows[0].organisation_number, str)
        self.assertEqual([row.organisation_number for row in parse_records(cases["jsonl"], "jsonl")],
                         ["001234567", "923609016", "001234567"])

    def test_malformed_jsonl_row_isolated_between_valid_duplicate_rows(self):
        rows = parse_records('{"orgnr":"923609016"}\r\n{broken}\r\n{"orgnr":"923609016"}\r\n', "jsonl")
        self.assertEqual([row.organisation_number for row in rows], ["923609016", "", "923609016"])
        self.assertEqual(len(rows), 3)

    def test_distinct_offline_scale_identifiers_are_valid_and_not_repeated(self):
        organisations = [synthetic_org_number(index) for index in range(10_000)]
        self.assertEqual(len(set(organisations)), 10_000)
        self.assertTrue(all(len(value) == 9 and value.isdigit() for value in organisations))
        self.assertEqual(organisations[0], synthetic_org_number(0))

    def test_registered_domain_uses_bundled_suffix_snapshot_without_home_cache(self):
        self.assertFalse(_EXTRACT._cache.enabled)
        self.assertEqual(_EXTRACT.suffix_list_urls, ())
        self.assertEqual(registered_domain("www.example.co.uk"), "example.co.uk")

    def test_website_merge_reuses_matching_official_candidate_provenance_and_rejects_conflicts(self):
        envelope = valid_envelope()
        original_retrieved = envelope.evidence[0].retrieved_at
        envelope.source_snapshots[0].http_status = 200
        reused_evidence = envelope.evidence[0].model_copy(deep=True)
        reused_evidence.retrieved_at = original_retrieved + timedelta(seconds=1)
        reused_snapshot = envelope.source_snapshots[0].model_copy(deep=True)
        reused_snapshot.http_status = None  # Candidate reconstruction has less transport detail.
        run_module._merge_website_provenance(envelope, SimpleNamespace(
            evidence=[reused_evidence], snapshots=[reused_snapshot]))
        self.assertEqual(len(envelope.evidence), 1)
        self.assertEqual(envelope.evidence[0].retrieved_at, original_retrieved)
        self.assertEqual(len(envelope.source_snapshots), 1)
        self.assertEqual(envelope.source_snapshots[0].http_status, 200)

        conflicting = envelope.evidence[0].model_copy(deep=True)
        conflicting.content_sha256 = "f" * 64
        with self.assertRaisesRegex(ValueError, "evidence identifier collision with conflicting provenance"):
            run_module._merge_website_provenance(envelope, SimpleNamespace(evidence=[conflicting], snapshots=[]))
        conflicting_snapshot = envelope.source_snapshots[0].model_copy(deep=True)
        conflicting_snapshot.content_sha256 = "e" * 64
        with self.assertRaisesRegex(ValueError, "source snapshot identifier collision with conflicting provenance"):
            run_module._merge_website_provenance(envelope, SimpleNamespace(evidence=[], snapshots=[conflicting_snapshot]))

    def test_verified_site_candidate_claim_includes_snapshot_for_every_evidence_source(self):
        envelope = valid_envelope()
        org = envelope.organisation_number
        now = datetime.now(timezone.utc)
        page = PageRecord(requested_url="https://company.example/", final_url="https://company.example/",
            status=200, content_type="text/html", body=b"page", digest=hashlib.sha256(b"page").hexdigest(),
            retrieved_at=now)
        page_key = _page_key(page)
        page_snapshot = f"website:{page_key}"
        page_evidence = f"website-page:{page_key}"
        proof_snapshot, proof_evidence = "website-proof:test", "website-proof-evidence:test"
        candidate_snapshot, candidate_evidence = "brreg:entity:test", "registry-site-candidate:test"
        records = [
            (page_snapshot, page_evidence, page.final_url, page.digest, "website_html_extract_v1", "/identity"),
            (proof_snapshot, proof_evidence, page.final_url, hashlib.sha256(b"proof").hexdigest(),
                "audited_exact_site_identity_proof_v1", "/identity_proof"),
            (candidate_snapshot, candidate_evidence, f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}",
                hashlib.sha256(b"candidate").hexdigest(), "brreg_website_candidate_v1", "/hjemmeside"),
        ]
        for snapshot_id, evidence_id, url, digest, method, pointer in records:
            envelope.source_snapshots.append(SourceSnapshot(source_id=snapshot_id, source_url=url,
                retrieved_at=now, content_sha256=digest, rights_status="test"))
            envelope.evidence.append(Evidence(evidence_id=evidence_id, source_url=url, retrieved_at=now,
                content_sha256=digest, extraction_method=method, json_pointer=pointer,
                subject_organisation_number=org, source_snapshot_ids=[snapshot_id]))

        extra_snapshot_ids = _additional_evidence_snapshot_ids(envelope.evidence, [candidate_evidence])
        evidence_ids = [page_evidence, proof_evidence, candidate_evidence]
        stale_claim = _make_claim(org, "verified_website_url", page.final_url, page, page_evidence,
            evidence_ids=evidence_ids, proof_source=proof_snapshot, proof_evidence=proof_evidence)
        envelope.claims.append(stale_claim)
        with self.assertRaisesRegex(ValueError, "claim source snapshots must include every evidence snapshot"):
            envelope.__class__.model_validate(envelope.model_dump())
        envelope.claims.pop()

        claim = _make_claim(org, "verified_website_url", page.final_url, page, page_evidence,
            evidence_ids=evidence_ids, proof_source=proof_snapshot,
            proof_evidence=proof_evidence, evidence_source_snapshot_ids=extra_snapshot_ids)
        envelope.claims.append(claim)

        self.assertEqual(extra_snapshot_ids, [candidate_snapshot])
        self.assertIn(candidate_snapshot, claim.source_snapshot_ids)
        envelope.__class__.model_validate(envelope.model_dump())

    def test_distinct_website_facts_on_one_page_have_unique_claim_ids_and_synthesize(self):
        envelope = valid_envelope()
        org = envelope.organisation_number
        now = datetime.now(timezone.utc)
        page = PageRecord(requested_url="https://company.example/products", final_url="https://company.example/products",
            status=200, content_type="text/html", body=b"products", digest=hashlib.sha256(b"products").hexdigest(),
            retrieved_at=now)
        page_key = _page_key(page)
        snapshot_id, evidence_id = f"website:{page_key}", f"website-page:{page_key}"
        envelope.source_snapshots.append(SourceSnapshot(source_id=snapshot_id, source_url=page.final_url,
            retrieved_at=now, content_sha256=page.digest, rights_status="test"))
        envelope.evidence.append(Evidence(evidence_id=evidence_id, source_url=page.final_url, retrieved_at=now,
            content_sha256=page.digest, extraction_method="website_html_extract_v1", json_pointer="/html/body//h1",
            subject_organisation_number=org, source_snapshot_ids=[snapshot_id]))
        first = _make_claim(org, "product_or_service_heading", "Tjenester", page, evidence_id)
        second = _make_claim(org, "product_or_service_heading", "BioBank AS", page, evidence_id)
        self.assertNotEqual(first.claim_id, second.claim_id)
        envelope.claims.extend([first, second])
        canonical = Envelope.model_validate(envelope.model_dump())
        sentences = [item["text"] for item in synthesize(canonical)["sentences"]]
        self.assertTrue(any("Tjenester" in item for item in sentences))
        self.assertTrue(any("BioBank AS" in item for item in sentences))
        duplicate = canonical.model_copy(deep=True)
        duplicate.claims.append(duplicate.claims[-1].model_copy(update={"claim_id": duplicate.claims[0].claim_id}))
        with self.assertRaisesRegex(ValueError, "claim identifiers must be unique"):
            Envelope.model_validate(duplicate.model_dump())
        with self.assertRaisesRegex(ValueError, "claim identifiers must be unique"):
            to_evaluator(duplicate)

    def test_failed_smoke_preserves_partial_files_ledger_and_original_exception(self):
        with tempfile.TemporaryDirectory(prefix="signalpost-m09-preserve-test-") as temporary:
            root = Path(temporary)
            working = root / "working"
            working.mkdir()
            report_path = root / "failure.json"
            gateway = SimpleNamespace(
                ledger=SimpleNamespace(physical_requests=1, logical_requests=2, entries=[SimpleNamespace(
                    request_id="request-1", url="https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                    purpose="entity", status=200, bytes_received=42, elapsed_ms=18.5,
                    outcome="received", redirect_location=None)]),
                coalesced_requests=0,
                budget=SimpleNamespace(config=SimpleNamespace(hard_seconds=1800, soft_seconds=1350,
                    completion_reserve_seconds=300, physical_request_limit=2200, logical_request_limit=None,
                    paid_cost_limit="0", global_http_concurrency=8, per_host_concurrency=2,
                    per_company_physical_limit=None, per_host_physical_limit=None),
                    physical_requests=1, logical_requests=2, physical_requests_remaining=2199,
                    logical_requests_remaining=None, requests_by_company={"923609016": 1},
                    elapsed=2.0, soft_expired=False, hard_expired=False, reserve_active=False))

            def persist(failure, trace):
                _artifact_dir, bundle = _preserve_run_bundle(report_path, working, label="failure",
                    captured_stdout='{"event":"partial"}\n', gateway=gateway, traceback_text=trace)
                _atomic_json(report_path, {"failure_type": type(failure).__name__, "failure_message": str(failure),
                    "traceback": "traceback.txt", "preserved_artifacts": bundle})

            def fail_after_partial_writes():
                (working / "output.partial.jsonl").write_text('{"input_ref":"row:1"}\n', encoding="utf-8")
                (working / "state.partial.json").write_text('{"companies":{}}\n', encoding="utf-8")
                raise ValueError("claim source snapshots must include every evidence snapshot")

            with self.assertRaisesRegex(ValueError, "claim source snapshots must include every evidence snapshot"):
                _run_preserving_failure(fail_after_partial_writes, persist)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            artifact_dir = root / report["preserved_artifacts"]["artifact_directory"]
            self.assertEqual(report["failure_type"], "ValueError")
            self.assertEqual(report["preserved_artifacts"]["request_ledger"]["physical_requests"], 1)
            self.assertEqual(report["preserved_artifacts"]["request_ledger"]["logical_requests"], 2)
            self.assertTrue((artifact_dir / "run/output.partial.jsonl").exists())
            self.assertTrue((artifact_dir / "run/state.partial.json").exists())
            self.assertTrue((artifact_dir / "request-ledger.json").exists())
            self.assertIn("claim source snapshots", (artifact_dir / "traceback.txt").read_text(encoding="utf-8"))

    def test_smoke_gate_revalidates_evaluator_rows_as_canonical_envelopes(self):
        envelope = valid_envelope()
        payload = to_evaluator(envelope)
        rows, adapter_roundtrips, failures = _validate_evaluator_rows(
            [payload], [{"organisation_number": envelope.organisation_number}])
        self.assertEqual(len(rows), 1)
        self.assertEqual(adapter_roundtrips, 1)
        self.assertEqual(failures, [])

        broken = to_evaluator(envelope)
        broken["claims"][0]["source_snapshot_ids"] = []
        rows, adapter_roundtrips, failures = _validate_evaluator_rows(
            [broken], [{"organisation_number": envelope.organisation_number}])
        self.assertEqual(rows, [])
        self.assertEqual(adapter_roundtrips, 0)
        self.assertEqual(failures[0]["row"], "1")
        self.assertIn("snapshot provenance", failures[0]["reason"])


if __name__ == "__main__":
    unittest.main()
