from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "signalpost-starter-kit" / "scripts"))

import verify_rc1_evidence


class RC1EvidencePackagingTests(unittest.TestCase):
    def test_historical_and_post_sol_receipts_pass_packaging_gate(self):
        self.assertEqual(verify_rc1_evidence.main(), 0)

    def test_post_sol_wrong_source_sha_fails_packaging_gate(self):
        receipt = json.loads(verify_rc1_evidence.POST_SOL_RECEIPT.read_text(encoding="utf-8"))
        receipt["source_sha"] = "0" * 40
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with patch.object(verify_rc1_evidence, "POST_SOL_RECEIPT", path):
                with self.assertRaisesRegex(SystemExit, "clean authorized remediation SHA"):
                    verify_rc1_evidence.main()

    def test_post_sol_artifact_hash_mismatch_fails_packaging_gate(self):
        receipt = json.loads(verify_rc1_evidence.POST_SOL_RECEIPT.read_text(encoding="utf-8"))
        receipt["artifact_hashes"]["output"] = "0" * 64
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with patch.object(verify_rc1_evidence, "POST_SOL_RECEIPT", path):
                with self.assertRaisesRegex(SystemExit, "run manifest"):
                    verify_rc1_evidence.main()


if __name__ == "__main__":
    unittest.main()
