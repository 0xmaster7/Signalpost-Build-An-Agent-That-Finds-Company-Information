from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "signalpost-starter-kit" / "scripts"))

from run_m06_scale_gate import synthetic_org_number
from signalpost.inputs import parse_records
from signalpost.network import _EXTRACT, registered_domain


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


if __name__ == "__main__":
    unittest.main()
