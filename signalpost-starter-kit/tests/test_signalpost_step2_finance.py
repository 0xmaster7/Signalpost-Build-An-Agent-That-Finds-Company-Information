import asyncio
import copy
import json
from collections import Counter
from datetime import datetime, timezone

import pytest

from signalpost import brreg, run
from signalpost.adapter import to_evaluator
from signalpost.financial_calibration import STRUCTURED_RULE, calibrate_company_financials
from signalpost.history import artifact_payload, claim_fingerprint, company_state, validate_artifact
from signalpost.models import Claim, PublicState, validate_batch_publication_graph
from signalpost.operations import Budget, CheckpointStore, RunBudget, financial_request_scope
from test_signalpost_financial_calibration import CUTOFF, ORG, OTHER, attach_anchors, envelope_for, raw_record


class Gateway:
    def __init__(self, records, subunit=False):
        self.records = records
        self.calls = Counter()
        self.subunit = subunit

    async def fetch(self, url, *, purpose, **kwargs):
        self.calls[purpose] += 1
        entity = {"organisasjonsnummer": ORG, "navn": "API Only AS", "organisasjonsform": {"kode": "AS"}}
        if self.subunit:
            entity["overordnetEnhet"] = OTHER
        body = {"entity": entity, "accounts": self.records, "roles": {"rollegrupper": []},
            "subunits": {"_embedded": {"underenheter": []}, "page": {"number": 0, "totalPages": 1}}}[purpose]
        return 200, {}, json.dumps(body).encode(), url, "ok"


def fetched(records=None, subunit=False):
    gateway = Gateway(records if records is not None else [raw_record()], subunit)
    result = asyncio.run(brreg.fetch_company(ORG, gateway, CUTOFF))
    return result, gateway


def money(result):
    return [claim for claim in result.claims if claim.field_family == "financial"]


def test_api_only_all_years_scopes_and_noncalendar_periods_publish_once():
    records = [raw_record(year, scope=scope) for year in (2023, 2024, 2025) for scope in ("SELSKAP", "KONSERN")]
    records[0]["regnskapsperiode"]["fraDato"] = "2023-03-01"
    result, gateway = fetched(records)
    assert gateway.calls["accounts"] == 1
    assert len(money(result)) == 24
    assert len({claim.subject_id for claim in money(result)}) == 6
    assert {claim.scope for claim in money(result)} == {"legal_entity", "group"}
    assert any(claim.period_start.month == 3 for claim in money(result))
    assert all(claim.unit_assumed_currency and claim.verification_rule_id == STRUCTURED_RULE for claim in money(result))
    assert all(claim.unit_assumption_basis.calibration_state == "UNCALIBRATED" for claim in money(result))
    assert all(not claim.unit_assumption_basis.documented_api_unit_contract for claim in money(result))
    assert not any(item.page_number for item in result.evidence)
    envelope = envelope_for(result)
    validate_batch_publication_graph([envelope])
    payload = to_evaluator(envelope)
    assert sum(claim.get("unit_assumed_currency", False) for claim in payload["claims"]) == 24
    state = company_state(envelope, "d" * 64)
    restored = validate_artifact(artifact_payload({ORG: state}, "d" * 64)).companies[ORG]
    serialized = next(claim for claim in restored.claims if claim.get("unit_assumed_currency"))
    changed = copy.deepcopy(serialized)
    changed["unit_assumption_basis"]["api_snapshot_id"] += "changed"
    assert claim_fingerprint(changed) != claim_fingerprint(serialized)
    asyncio.run(brreg.fetch_financial_statements(result, ORG, gateway, CUTOFF))
    assert gateway.calls["accounts"] == 1


def test_foundation_deferred_accounts_and_typed_checkpoint_resume(tmp_path):
    gateway = Gateway([raw_record()])
    result = asyncio.run(brreg.fetch_company(ORG, gateway, CUTOFF, include_accounts=False,
        allow_current_identity_after_run_start=True))
    assert not gateway.calls["accounts"] and not result.account_records
    assert any(claim.value == "API Only AS" for claim in result.claims)
    asyncio.run(brreg.fetch_financial_statements(result, ORG, gateway, CUTOFF))
    store = CheckpointStore(tmp_path / "checkpoint")
    store.save_phase("financial_statements", ORG, result, [envelope_for(result)])
    restored = store.phase_results("financial_statements")[ORG]
    assert isinstance(restored, brreg.BrregResult)
    asyncio.run(brreg.fetch_financial_statements(restored, ORG, gateway, CUTOFF))
    assert len(money(restored)) == 4 and gateway.calls["accounts"] == 1
    store.close()


@pytest.mark.parametrize("mutation", ["org", "future_period", "future_filing", "bad_filing", "period", "scope", "currency", "identity", "version", "subunit"])
def test_invalid_records_never_publish_money(mutation):
    record = raw_record()
    records = [record]
    if mutation == "org":
        record["virksomhet"]["organisasjonsnummer"] = OTHER
    elif mutation == "future_period":
        record["regnskapsperiode"]["tilDato"] = "2027-01-01"
    elif mutation == "future_filing":
        record["innsendingsdato"] = "2027-01-01"
    elif mutation == "bad_filing":
        record["innsendingsdato"] = "invalid"
    elif mutation == "period":
        record["regnskapsperiode"]["fraDato"] = "2026-01-01"
    elif mutation == "scope":
        record["regnskapstype"] = "UNKNOWN"
    elif mutation == "currency":
        record["valuta"] = "QQQ"
    elif mutation == "identity":
        for key in ("id", "versjon", "journalnr"):
            record.pop(key)
    elif mutation == "version":
        records.append(raw_record(version=2))
    result, gateway = fetched(records, subunit=mutation == "subunit")
    assert not money(result)
    assert gateway.calls["accounts"] == 1


@pytest.mark.parametrize("unit", [None, "", "unknown", 1000])
def test_explicit_invalid_units_are_not_assumed(unit):
    record = raw_record()
    record["enhet"] = unit
    result, _ = fetched([record])
    assert not money(result)


def test_explicit_units_conflicts_and_finite_values():
    record = raw_record(values={"revenue": {"sum": 10, "enhet": "TNOK"}, "cash": 0,
        "annual_result": True, "equity": float("nan"), "total_assets": float("inf")})
    result, _ = fetched([record])
    assert {(claim.field, claim.unit, claim.unit_assumed_currency) for claim in money(result)} == {
        ("revenue", "TNOK", False), ("cash", "NOK", True)}
    record["enhet"] = "NOK"
    result, _ = fetched([record])
    assert {(claim.field, claim.unit_assumed_currency) for claim in money(result)} == {("cash", False)}
    record = raw_record()
    record.update(enhet="NOK", valuta="EUR")
    assert not money(fetched([record])[0])


@pytest.mark.parametrize("mutation", ["unflagged", "rule", "pointer", "snapshot", "metadata", "identity", "identity_omission", "filing_omission", "unit_state", "cutoff"])
def test_assumption_graph_rejects_forgery_in_publication_and_history(mutation):
    result, _ = fetched()
    state = company_state(envelope_for(result), "d" * 64)
    claim = money(result)[0]
    if mutation in {"unflagged", "rule", "unit_state"}:
        forged = claim.model_dump()
        if mutation == "unflagged":
            forged["unit_assumed_currency"] = False
        elif mutation == "rule":
            forged["verification_rule_id"] = "official_pdf_json_row_reconciliation_v1"
        else:
            forged["unit_assumption_basis"]["source_unit_state"] = "explicit_null"
        with pytest.raises(ValueError):
            Claim.model_validate(forged)
        return
    if mutation == "pointer":
        next(item for item in result.evidence if item.evidence_id in claim.evidence_ids).json_pointer = "/9/wrong"
    elif mutation == "snapshot":
        next(item for item in result.snapshots if item.source_id in claim.source_snapshot_ids).http_status = 404
    elif mutation == "metadata":
        result.claims = [item for item in result.claims if item.field != "financial_record.period_start"]
    elif mutation == "identity":
        claim.unit_assumption_basis.filing_identity["record_version"] = "999"
    elif mutation == "identity_omission":
        claim.unit_assumption_basis.filing_identity.pop("record_version")
    elif mutation == "filing_omission":
        claim.as_of = None
    elif mutation == "cutoff":
        claim.as_of = datetime(2027, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        envelope_for(result)
    state.claims = [item.model_dump(mode="json") for item in result.claims]
    state.evidence = [item.model_dump(mode="json") for item in result.evidence]
    state.snapshots = [item.model_dump(mode="json") for item in result.snapshots]
    with pytest.raises(ValueError):
        validate_artifact(artifact_payload({ORG: state}, "d" * 64))


def test_legacy_pdf_calibration_can_upgrade_api_assumptions():
    result, _ = fetched()
    attach_anchors(result)
    calibrate_company_financials(result, ORG, CUTOFF)
    calibrated = [claim for claim in money(result) if claim.verification_rule_id == "company_pdf_calibrated_currency_assumption_v1"]
    assert {claim.field for claim in calibrated} == {"total_assets", "equity"}
    envelope_for(result)


def test_existing_document_agreement_records_inferred_units_without_anchors():
    result, _ = fetched()
    result.observations["annual_accounts_document"] = {"financial_cross_checks": [{"metric": "revenue",
        "value": 10000, "page": 2, "span": "Revenue 10000", "unit_span": "Belop i NOK", "currency": "NOK"}]}
    calibrate_company_financials(result, ORG, CUTOFF)
    assert result.financial_cross_checks[0]["inferred_api_unit"] == "NOK"
    assert all(claim.unit_assumption_basis.calibration_state == "UNCALIBRATED" for claim in money(result))


def test_financial_request_reserve_cannot_be_spent_by_foundation():
    async def check():
        budget = Budget(RunBudget(physical_request_limit=2, logical_request_limit=2,
            per_company_physical_limit=2, per_host_physical_limit=2))
        budget.financial_request_reserve = budget.financial_logical_reserve = 1
        request = {"required": True, "company": ORG, "host": "data.brreg.no"}
        assert await budget.reserve_request(**request)
        assert await budget.reserve_logical_request()
        assert not await budget.reserve_request(**request)
        assert not await budget.reserve_logical_request()
        with financial_request_scope():
            assert await budget.reserve_request(**request)
            assert await budget.reserve_logical_request()
        assert budget.financial_request_reserve == budget.financial_logical_reserve == 0
    asyncio.run(check())


@pytest.mark.parametrize("ocr", ["disabled", "fails", "graph", "phase_fails", "finance_fails", "finance_graph"])
def test_production_finance_precedes_ocr_and_resumes_once(tmp_path, monkeypatch, ocr):
    calls = Counter()
    gateway = Gateway([raw_record()])

    async def official(org, unused, cutoff, **kwargs):
        calls["foundation"] += 1
        assert unused.retries == 1
        return await brreg.fetch_company(org, gateway, cutoff, **kwargs)

    async def financial(result, org, unused, cutoff):
        calls["finance"] += 1
        assert unused.retries == 0
        if ocr == "finance_fails":
            result.claims.clear()
            raise RuntimeError("synthetic finance exception")
        value = await brreg.fetch_financial_statements(result, org, gateway, cutoff)
        if ocr == "finance_graph":
            money(value)[0].evidence_ids[:] = ["missing"]
        return value

    async def document(result, *args):
        calls["ocr"] += 1
        assert gateway.calls["accounts"] == 1 and len(money(result)) == 4
        if ocr == "graph":
            result.claims[0].evidence_ids[:] = ["missing"]
            return result
        raise RuntimeError("synthetic OCR failure")

    async def no_network(*args, **kwargs):
        raise AssertionError("synthetic test attempted a network request")

    monkeypatch.setattr(run, "fetch_company", official)
    monkeypatch.setattr(run, "fetch_financial_statements", financial)
    monkeypatch.setattr("signalpost.annual_accounts.enrich_company", document)
    if ocr == "phase_fails":
        def broken_processor(*args, **kwargs):
            raise RuntimeError("synthetic phase setup failure")
        monkeypatch.setattr("signalpost.annual_accounts.DocumentProcessor", broken_processor)
    monkeypatch.setattr("signalpost.network.NetworkGateway.fetch", no_network)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"budget": {"ocr_seconds": 0 if ocr == "disabled" else 60}}))
    source = tmp_path / "input"
    source.write_text(ORG + "\n" + ORG + "\n")
    argv = ["--input", str(source), "--output", str(tmp_path / "output"), "--checkpoint", str(tmp_path / "checkpoint"),
        "--config", str(config), "--live-brreg"]
    assert run.main(argv) == 0
    store = CheckpointStore(tmp_path / "checkpoint")
    envelopes = store.rows()
    assert len(envelopes) == 2
    validate_batch_publication_graph(envelopes)
    assert all(any(claim.value == "API Only AS" for claim in envelope.claims) for envelope in envelopes)
    if ocr not in {"finance_fails", "finance_graph"}:
        assert all(sum(claim.field_family == "financial" for claim in envelope.claims) == 4 for envelope in envelopes)
        assert isinstance(store.phase_results("financial_statements")[ORG], brreg.BrregResult)
    store.connection.execute("UPDATE shells SET execution_state='baseline_done'")
    store.connection.commit()
    store.close()
    assert run.main([*argv, "--resume"]) == 0
    assert calls["foundation"] == calls["finance"] == 1
    assert gateway.calls["accounts"] == (0 if ocr == "finance_fails" else 1)
    assert calls["ocr"] == (0 if ocr in {"disabled", "phase_fails", "finance_fails", "finance_graph"} else 1)
