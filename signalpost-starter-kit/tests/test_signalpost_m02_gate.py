from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "signalpost-starter-kit" / "scripts"))

from run_m02_foundation_smoke import unsupported_financial_claim


class M02SmokeGateTests(unittest.TestCase):
    def claim(self, **updates):
        row = {"field": "revenue", "currency": "NOK", "scope": "legal_entity", "value": 0,
            "period_start": "2024-01-01T00:00:00Z", "period_end": "2024-12-31T00:00:00Z"}
        row.update(updates)
        return row

    def test_zero_supported_financial_record_passes_full_metadata_gate(self):
        self.assertFalse(unsupported_financial_claim(self.claim()))

    def test_unknown_currency_period_scope_value_and_metric_are_counted_unsupported(self):
        cases = [
            self.claim(currency="QQQ"),
            self.claim(currency="nok"),
            self.claim(period_start=None),
            self.claim(period_start="bad-date"),
            self.claim(period_start="2025-01-01", period_end="2024-12-31"),
            self.claim(scope="unknown"),
            self.claim(value="10"),
            self.claim(field="invented_metric"),
        ]
        for row in cases:
            with self.subTest(row=row):
                self.assertTrue(unsupported_financial_claim(row))


if __name__ == "__main__":
    unittest.main()
