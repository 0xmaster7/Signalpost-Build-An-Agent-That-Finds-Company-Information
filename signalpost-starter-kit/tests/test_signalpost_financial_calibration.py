from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from signalpost.adapter import to_evaluator
from signalpost.brreg import METRICS, fetch_company, financial_record_subject, financial_records
from signalpost.financial_calibration import ASSUMPTION_RULE, calibrate_company_financials
from signalpost.history import (
    artifact_payload, claim_fingerprint, company_state, merge_prior_facts, validate_artifact,
)
from signalpost.models import (
    Claim, Envelope, Evidence, PublicState, RefreshState, RunError, Section, SourceSnapshot,
)

ORG = "987974249"
OTHER = "923609016"
CUTOFF = datetime(2026, 10, 27, tzinfo=timezone.utc)
OBSERVED = datetime(2026, 10, 26, tzinfo=timezone.utc)
SECTIONS = ("identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
    "hiring_activity", "claims_evidence_states", "refresh_changes")


def raw_record(year=2025, scope="SELSKAP", org=ORG, values=None, version=1):
    result = {"id": f"{org}-{year}-{scope}", "versjon": version, "journalnr": f"{year}123456",
        "virksomhet": {"organisasjonsnummer": org}, "regnskapstype": scope,
        "regnskapsperiode": {"fraDato": f"{year}-01-01", "tilDato": f"{year}-12-31"},
        "valuta": "NOK", "innsendingsdato": f"{year + 1}-06-01"}
    for metric, value in (values if values is not None else {"revenue": 10000, "annual_result": -100,
            "total_assets": 50000, "equity": 0}).items():
        node = result
        parts = METRICS[metric].split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return result


class Gateway:
    def __init__(self, records, org=ORG):
        self.records = records
        self.org = org

    async def fetch(self, url, *, purpose, **kwargs):
        bodies = {"entity": {"organisasjonsnummer": self.org, "navn": "Example AS",
            "organisasjonsform": {"kode": "AS"}}, "accounts": self.records,
            "roles": {"rollegrupper": []}, "subunits": {"_embedded": {"underenheter": []},
                "page": {"totalPages": 0, "totalElements": 0, "number": 0}}}
        return 200, {}, json.dumps(bodies[purpose]).encode(), url, "ok"


def result_for(records=None, org=ORG):
    return asyncio.run(fetch_company(org, Gateway(records or [raw_record(org=org)], org), CUTOFF))


def attach_anchors(result, record_index=0, metrics=("revenue", "annual_result"), overrides=None):
    record = result.account_records[record_index]
    org = record["raw"]["virksomhet"]["organisasjonsnummer"]
    year = record["period_end"][:4]
    pdf_url = f"https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/{year}"
    pdf_id = f"{org}:pdf:{record_index}"
    pdf_hash = "b" * 64
    result.snapshots.append(SourceSnapshot(source_id=pdf_id, source_url=pdf_url,
        retrieved_at=OBSERVED, content_sha256=pdf_hash, http_status=200))
    cover_id = pdf_id + ":cover"
    result.evidence.append(Evidence(evidence_id=cover_id, source_url=pdf_url, retrieved_at=OBSERVED,
        content_sha256=pdf_hash, page_number=1, extraction_method="official-filing-ocr-v3",
        excerpt=f"Organisasjonsnummer: {org} | Journalnummer: {record['raw']['journalnr']} | {record['period_start']} - {record['period_end']}",
        subject_organisation_number=org, source_snapshot_ids=[pdf_id]))
    source = result.account_source
    json_id = next(item.source_id for item in result.snapshots if item.source_url == source["url"]
        and item.content_sha256 == source["content_sha256"])
    for metric in metrics:
        row_id, api_id = pdf_id + ":" + metric, pdf_id + ":" + metric + ":api"
        result.evidence.append(Evidence(evidence_id=row_id, source_url=pdf_url, retrieved_at=OBSERVED,
            content_sha256=pdf_hash, page_number=2, extraction_method="official-filing-ocr-v3",
            excerpt=f"Belop i: NOK | {metric}: {record['metrics'][metric]}",
            subject_organisation_number=org, source_snapshot_ids=[pdf_id]))
        result.evidence.append(Evidence(evidence_id=api_id, source_url=source["url"],
            retrieved_at=source["retrieved_at"], content_sha256=source["content_sha256"],
            extraction_method="brreg_json_pointer_v1", json_pointer=record["_source_prefix"] + "/" + METRICS[metric],
            subject_organisation_number=org, source_snapshot_ids=[json_id]))
        result.claims.append(Claim(claim_id=pdf_id + ":claim:" + metric, organisation_number=org,
            section="accounts_history", field_family="financial", subject_id=pdf_id + ":filing",
            field=metric, value=(overrides or {}).get(metric, record["metrics"][metric]), state=PublicState.AVAILABLE,
            unit="NOK", currency="NOK", period_start=datetime.fromisoformat(record["period_start"]).replace(tzinfo=timezone.utc),
            period_end=datetime.fromisoformat(record["period_end"]).replace(tzinfo=timezone.utc),
            scope="legal_entity", verification_rule_id="official_pdf_json_row_reconciliation_v1",
            verification_score="1.0", evidence_ids=[cover_id, row_id, api_id], source_snapshot_ids=[pdf_id, json_id]))


def assumed(result):
    return [claim for claim in result.claims if claim.unit_assumed_currency]


def envelope_for(result):
    sections = {name: Section(state=PublicState.AVAILABLE if any(claim.section == name for claim in result.claims)
        else PublicState.NOT_AVAILABLE, claims=[claim for claim in result.claims if claim.section == name])
        for name in SECTIONS}
    sections["claims_evidence_states"] = Section(state=PublicState.AVAILABLE, claims=result.claims)
    return Envelope(input_ref="fixture", row_number=1, organisation_number=ORG,
        terminal_state=PublicState.AVAILABLE, sections=sections, refresh=RefreshState(), claims=result.claims,
        evidence=result.evidence, source_snapshots=result.snapshots, batch_id="fixture", evidence_cutoff=CUTOFF)


def test_company_local_assumptions_require_two_nonzero_normalized_anchors_and_preserve_zero():
    result = result_for()
    attach_anchors(result)
    calibrate_company_financials(result, ORG, CUTOFF)
    assert {claim.field: claim.value for claim in assumed(result)} == {"total_assets": 50000, "equity": 0}
    for claim in assumed(result):
        assert claim.verification_rule_id == ASSUMPTION_RULE
        basis = claim.unit_assumption_basis
        assert basis.same_period_as_reference and basis.same_scope_as_reference and basis.same_filing_as_reference
        assert not basis.target_pdf_validated and not basis.documented_api_unit_contract
        assert basis.api_value_multiplier == 1
        assert len(basis.anchor_claim_ids) == 2
    count = len(result.claims)
    calibrate_company_financials(result, ORG, CUTOFF)
    assert len(result.claims) == count
    other = result_for(org=OTHER)
    calibrate_company_financials(other, OTHER, CUTOFF)
    assert assumed(other) == []
    assert not any(claim.field_family == "financial" for claim in other.claims)


@pytest.mark.parametrize("values", [dict(revenue=0, annual_result=0, total_assets=300),
    dict(revenue=100, annual_result=0, total_assets=300)])
def test_zero_only_and_single_nonzero_anchor_cannot_establish_scale(values):
    result = result_for([raw_record(values=values)])
    attach_anchors(result)
    calibrate_company_financials(result, ORG, CUTOFF)
    assert assumed(result) == []


@pytest.mark.parametrize("mutation", ["ratio", "conflict", "wrong_org", "wrong_currency", "wrong_period",
    "wrong_journal", "wrong_json_record", "wrong_snapshot", "explicit_conflict", "explicit_null", "missing_filing"])
def test_conflicts_and_inexact_binding_abstain(mutation):
    result = result_for()
    attach_anchors(result)
    anchors = [claim for claim in result.claims if claim.field_family == "financial"]
    if mutation == "ratio":
        anchors[0].value /= 1000
    elif mutation == "conflict":
        result.errors.append(RunError(code="ANNUAL_DOCUMENT_CLAIM_CONFLICT", message="equity"))
    elif mutation == "wrong_org":
        result.account_records[0]["raw"]["virksomhet"]["organisasjonsnummer"] = OTHER
    elif mutation == "wrong_currency":
        anchors[0].currency = "EUR"
    elif mutation == "wrong_period":
        anchors[0].period_start = datetime(2025, 2, 1, tzinfo=timezone.utc)
    elif mutation == "wrong_journal":
        next(item for item in result.evidence if item.evidence_id.endswith(":cover")).excerpt = "Journalnummer: 9999999"
    elif mutation == "wrong_json_record":
        next(item for item in result.evidence if item.evidence_id.endswith(":revenue:api")).json_pointer = "/9/" + METRICS["revenue"]
    elif mutation == "wrong_snapshot":
        next(item for item in result.evidence if item.evidence_id.endswith(":revenue")).content_sha256 = "c" * 64
    elif mutation == "explicit_conflict":
        result.account_records[0]["metrics"]["revenue_unit_conflict"] = True
    elif mutation == "explicit_null":
        result.account_records[0]["metrics"]["revenue_unit_state"] = "explicit_null"
    elif mutation == "missing_filing":
        result.account_records[0]["raw"].pop("journalnr")
    calibrate_company_financials(result, ORG, CUTOFF)
    assert assumed(result) == []


def test_multiple_periods_and_groups_remain_separate_and_explicitly_assumed():
    raw = [raw_record(), raw_record(2024), raw_record(scope="KONSERN"), raw_record(2024, scope="KONSERN")]
    result = result_for(raw)
    attach_anchors(result)
    calibrate_company_financials(result, ORG, CUTOFF)
    claims = assumed(result)
    assert len(claims) == 14
    assert len({claim.subject_id for claim in claims}) == 4
    for claim in claims:
        basis = claim.unit_assumption_basis
        assert basis.same_scope_as_reference == (claim.scope == "legal_entity")
        assert basis.same_period_as_reference == (claim.period_end.year == 2025)
        assert not basis.target_pdf_validated
        if claim.scope == "group":
            assert not basis.same_filing_as_reference
            assert "group" in claim.subject_id
    envelope_for(result)


@pytest.mark.parametrize("unit", ["NOK", "TNOK", None, "unknown"])
def test_group_explicit_units_are_not_inferred_or_discarded(unit):
    group = raw_record(scope="KONSERN")
    group["enhet"] = unit
    result = result_for([raw_record(), group])
    original_group = [claim.model_dump() for claim in result.claims if claim.field_family == "financial" and claim.scope == "group"]
    attach_anchors(result)
    calibrate_company_financials(result, ORG, CUTOFF)
    assert not any(claim.scope == "group" for claim in assumed(result))
    assert [claim.model_dump() for claim in result.claims if claim.field_family == "financial" and claim.scope == "group"] == original_group
    assert len(original_group) == (4 if unit in {"NOK", "TNOK"} else 0)


def test_only_genuine_finite_metrics_are_published_with_explicit_units():
    record = raw_record(values={"revenue": {"sum": 10, "enhet": "NOK"}, "annual_result": True,
        "equity": float("nan"), "total_assets": float("inf"), "cash": 0})
    record["enhet"] = "NOK"
    result = result_for([record, raw_record(scope="KONSERN", values={"revenue": 42})])
    financial = [claim for claim in result.claims if claim.field_family == "financial"]
    assert {claim.field for claim in financial} == {"revenue", "cash"}
    assert all(isinstance(claim.value, (int, float)) and not isinstance(claim.value, bool) for claim in financial)
    assert all(not claim.unit_assumed_currency for claim in financial)
    assert all(claim.field in METRICS for claim in financial)


def test_latest_version_ambiguity_stale_anchors_and_future_target_abstain():
    records = [raw_record(), raw_record(version=2)]
    result = result_for(records)
    attach_anchors(result)
    calibrate_company_financials(result, ORG, CUTOFF)
    assert assumed(result) == []
    result = result_for([raw_record(), raw_record(2024), raw_record(2026)])
    attach_anchors(result, record_index=1)
    calibrate_company_financials(result, ORG, CUTOFF)
    assert assumed(result) == []
    result = result_for([raw_record(), raw_record(2026)])
    attach_anchors(result)
    calibrate_company_financials(result, ORG, CUTOFF)
    assert all(claim.period_end <= CUTOFF for claim in assumed(result))


def test_adapter_json_and_refresh_retain_assumption_basis_and_detect_changed_basis():
    result = result_for()
    attach_anchors(result)
    calibrate_company_financials(result, ORG, CUTOFF)
    envelope = envelope_for(result)
    payload = json.loads(json.dumps(to_evaluator(envelope)))
    serialized = next(claim for claim in payload["claims"] if claim["unit_assumed_currency"])
    assert serialized["unit_assumption_basis"]["documented_api_unit_contract"] is False
    assert serialized["unit_assumption_basis"]["target_pdf_validated"] is False
    assert any(claim["unit_assumed_currency"] for claim in payload["sections"]["accounts_history"]["claims"])
    fingerprint = claim_fingerprint(serialized)
    changed = deepcopy(serialized)
    changed["unit_assumption_basis"]["calibration_id"] += "-new"
    assert claim_fingerprint(changed) != fingerprint
    unflagged = deepcopy(serialized)
    unflagged["unit_assumed_currency"] = False
    unflagged["unit_assumption_basis"] = None
    assert claim_fingerprint(unflagged) != fingerprint
    state = company_state(envelope, "d" * 64)
    restored = validate_artifact(artifact_payload({ORG: state}, "d" * 64)).companies[ORG]
    assert any(claim["unit_assumed_currency"] for claim in restored.claims)
    empty = result_for()
    current = company_state(envelope_for(empty), "d" * 64)
    merged = merge_prior_facts(current, restored)
    validate_artifact(artifact_payload({ORG: merged}, "d" * 64))
    assert any(claim["unit_assumed_currency"] for claim in merged.claims)


def test_assumed_claim_cannot_be_relabelled_as_reconciled_or_used_without_anchors():
    result = result_for()
    attach_anchors(result)
    calibrate_company_financials(result, ORG, CUTOFF)
    claim = assumed(result)[0]
    forged = claim.model_dump()
    forged["verification_rule_id"] = "official_pdf_json_row_reconciliation_v1"
    with pytest.raises(ValueError, match="assumption verification rule"):
        Claim.model_validate(forged)
    forged = claim.model_dump()
    forged["unit_assumed_currency"] = False
    forged["unit_assumption_basis"] = None
    with pytest.raises(ValueError, match="requires unit_assumed_currency"):
        Claim.model_validate(forged)
    forged["verification_rule_id"] = "official_pdf_json_row_reconciliation_v1"
    relabelled = Claim.model_validate(forged)
    replaced = deepcopy(result)
    replaced.claims = [relabelled if item.claim_id == claim.claim_id else item for item in replaced.claims]
    with pytest.raises(ValueError, match="assumption evidence requires unit_assumed_currency"):
        envelope_for(replaced)
    result.claims = [item for item in result.claims if item.claim_id not in claim.unit_assumption_basis.anchor_claim_ids]
    with pytest.raises(ValueError, match="two present"):
        envelope_for(result)


def test_unknown_metadata_and_nested_explicit_conflicts_remain_withheld_without_calibration():
    for value in (None, "", "unknown", 1000):
        record = raw_record()
        record["enhet"] = value
        result = result_for([record])
        calibrate_company_financials(result, ORG, CUTOFF)
        assert not any(claim.field_family == "financial" for claim in result.claims)
    record = raw_record(values={"revenue": {"sum": 10, "enhet": "TNOK"}})
    record["enhet"] = "NOK"
    normalized = financial_records([record])[0]
    assert normalized["metrics"]["revenue_unit_conflict"] is True
    assert not any(claim.field_family == "financial" for claim in result_for([record]).claims)


def test_subject_identity_includes_scope_exact_period_and_version():
    records = financial_records([raw_record(), raw_record(scope="KONSERN"), raw_record(2024), raw_record(version=2)])
    assert len({financial_record_subject(ORG, record) for record in records}) == 4


def test_explicit_currency_unit_conflict_is_not_relabelled_or_calibrated():
    record = raw_record(values={"total_assets": 42})
    record.update(valuta="EUR", enhet="NOK")
    result = result_for([record])
    calibrate_company_financials(result, ORG, CUTOFF)
    assert not any(claim.field_family == "financial" for claim in result.claims)
    assert any(error.code == "BRREG_FINANCIAL_UNIT_UNSUPPORTED" for error in result.errors)


def test_fte_only_conflict_does_not_invalidate_independent_monetary_anchors():
    result = result_for()
    attach_anchors(result)
    result.errors.append(RunError(code="ANNUAL_DOCUMENT_CLAIM_CONFLICT",
        message="Conflicting document candidates withheld: full_time_equivalents"))
    calibrate_company_financials(result, ORG, CUTOFF)
    assert assumed(result)
