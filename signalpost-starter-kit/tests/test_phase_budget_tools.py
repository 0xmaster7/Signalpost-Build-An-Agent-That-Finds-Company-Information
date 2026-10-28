import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_holdout_sampling_is_disjoint_and_refuses_rerandomization(tmp_path):
    registry = tmp_path / "registry.csv"
    with registry.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["organisasjonsnummer", "navn", "organisasjonsform.kode",
            "antallAnsatte", "konkurs", "underAvvikling"])
        writer.writeheader()
        for index in range(200):
            writer.writerow({"organisasjonsnummer": str(800000000 + index), "navn": f"Employer {index} AS",
                "organisasjonsform.kode": "AS", "antallAnsatte": "1", "konkurs": "nei", "underAvvikling": "nei"})
    excluded = {str(800000000 + index) for index in range(100)}
    source = tmp_path / "excluded.jsonl"
    source.write_text("".join(json.dumps({"organisation_number": org}) + "\n" for org in sorted(excluded)))
    destination = tmp_path / "selection"
    command = [sys.executable, str(SCRIPTS / "select_live_comparison.py"), "--registry", str(registry),
        "--output-dir", str(destination), "--no-fixed-cohort", "--exclude-input", str(source)]
    subprocess.run(command, check=True, capture_output=True)
    selection = json.loads((destination / "selection.json").read_text())
    assert selection["fixed_companies"] == [] and selection["random_additions"] == 100
    assert not excluded & {row["organisation_number"] for row in selection["rows"]}
    frozen = (destination / "companies.jsonl").read_bytes()
    assert hashlib.sha256(frozen).hexdigest() == selection["input_sha256"]
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert (destination / "companies.jsonl").read_bytes() == frozen


@pytest.mark.parametrize("method", [None, "structured_api_currency_assumption",
    "company_pdf_calibrated_currency_assumption"])
def test_normalization_preserves_assumption_and_does_not_claim_direct_units(method):
    comparison = module("compare_live_envelopes")
    basis = {"target_pdf_validated": False}
    if method is not None:
        basis["method"] = method
    result = comparison.normalize({"claims": [{"state": "available", "field": "revenue", "value": 10,
        "unit": "NOK", "currency": "NOK", "scope": "group", "unit_assumed_currency": True,
        "unit_assumption_basis": basis,
        "period_start": "2025-01-01", "period_end": "2025-12-31"}]}, "ours")
    item = result["financial"][0]
    assert item["unit_assumed_currency"] and item["scope"] == "group"
    assert item["unit_basis"] == (method or "unspecified_currency_assumption")
    assert item["unit_assumption_basis"]["target_pdf_validated"] is False


def test_experiment_input_validation_rejects_duplicate_rows(tmp_path):
    experiment = module("run_phase_budget_experiment")
    source = tmp_path / "input.jsonl"
    source.write_text((json.dumps({"organisation_number": "987974249"}) + "\n") * 100)
    try:
        experiment.inputs(source)
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("Duplicate input cohort was accepted")
