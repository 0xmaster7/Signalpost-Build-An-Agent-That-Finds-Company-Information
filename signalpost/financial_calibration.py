"""Company-local currency assumptions from current, independently labelled PDF rows."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from .brreg import METRICS, BrregResult, _date, financial_record_subject, supported_currency
from .models import Claim, Evidence, FinancialUnitAssumption, PublicState, SourceSnapshot, financial_dimensions_compatible

ASSUMPTION_RULE = "company_pdf_calibrated_currency_assumption_v1"
DOCUMENT_RULE = "official_pdf_json_row_reconciliation_v1"


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _identity(record: dict[str, Any]) -> dict[str, str]:
    values = {key: record.get(key) for key in ("record_id", "filing_id", "record_version")}
    values["journalnr"] = record.get("raw", {}).get("journalnr")
    return {key: str(value) for key, value in values.items() if value is not None and str(value).strip()}


def _eligible(record: dict[str, Any], org: str, cutoff: datetime) -> bool:
    start, end, filed = (_date(record.get(key)) for key in ("period_start", "period_end", "filing_timestamp"))
    raw = record.get("raw", {})
    entity = raw.get("virksomhet")
    return bool(isinstance(entity, dict) and entity.get("organisasjonsnummer") == org
        and start and end and start <= end <= cutoff
        and (not record.get("filing_timestamp") or filed is not None and filed <= cutoff)
        and supported_currency(record.get("currency"))
        and financial_dimensions_compatible(record.get("currency"), record.get("currency"))
        and record.get("scope") in {"legal_entity", "group"} and _identity(record))


def _metadata_conflict(record: dict[str, Any]) -> bool:
    metrics = record.get("metrics", {})
    return any(metrics.get(metric + "_unit_conflict")
        or metrics.get(metric + "_unit_state") not in {"absent", "supported"}
        for metric in METRICS if _number(metrics.get(metric)) is not None)


def _pdf_support(claim: Claim, evidence: dict[str, Evidence], snapshots: dict[str, SourceSnapshot]) -> bool:
    if (claim.state != PublicState.AVAILABLE or claim.field_family != "financial" or claim.field not in METRICS
            or claim.unit_assumed_currency or claim.verification_rule_id != DOCUMENT_RULE
            or claim.scope != "legal_entity" or claim.unit != claim.currency
            or _number(claim.value) in {None, Decimal(0)}):
        return False
    support = [evidence[ref] for ref in claim.evidence_ids if ref in evidence]
    if len(support) != len(claim.evidence_ids):
        return False
    if any(item.extraction_method == "brreg_company_currency_assumption_v1" for item in support):
        return False
    pdf = []
    for item in support:
        if (item.subject_organisation_number != claim.organisation_number
                or not item.source_snapshot_ids or not set(item.source_snapshot_ids) <= set(claim.source_snapshot_ids)):
            return False
        for ref in item.source_snapshot_ids:
            source = snapshots.get(ref)
            if (source is None or source.http_status != 200 or source.source_url != item.source_url
                    or source.content_sha256 != item.content_sha256):
                return False
        if item.extraction_method.startswith("official-filing-ocr-"):
            parts = urlsplit(item.source_url)
            expected = f"/regnskapsregisteret/regnskap/aarsregnskap/kopi/{claim.organisation_number}/{claim.period_end.year}" if claim.period_end else ""
            if (parts.scheme != "https" or parts.hostname != "data.brreg.no" or parts.path != expected
                    or parts.query or parts.fragment or not item.page_number or not item.excerpt):
                return False
            pdf.append(item)
    return (len({item.content_sha256 for item in pdf}) == 1
        and any(item.page_number == 1 for item in pdf) and any(item.page_number > 1 for item in pdf))


def _journal_matches(claim: Claim, record: dict[str, Any], evidence: dict[str, Evidence]) -> bool:
    journal = str(record.get("raw", {}).get("journalnr") or "")
    if not journal:
        return False
    covers = [evidence[ref] for ref in claim.evidence_ids if evidence[ref].page_number == 1
        and evidence[ref].extraction_method.startswith("official-filing-ocr-")]
    for cover in covers:
        match = re.search(r"journalnummer\s*:?\s*([\d ]+)", cover.excerpt or "", re.IGNORECASE)
        if match and re.sub(r"\s", "", match.group(1)) == journal:
            return True
    return False


def validate_company_unit_assumptions(claims: list[Claim], evidence: list[Evidence],
        snapshots: list[SourceSnapshot], cutoff: datetime) -> None:
    by_id = {claim.claim_id: claim for claim in claims}
    evidence_by_id = {item.evidence_id: item for item in evidence}
    snapshots_by_id = {item.source_id: item for item in snapshots}
    for claim in claims:
        has_assumption_evidence = any(evidence_by_id[ref].extraction_method == "brreg_company_currency_assumption_v1"
            for ref in claim.evidence_ids if ref in evidence_by_id)
        if has_assumption_evidence and not claim.unit_assumed_currency:
            raise ValueError("company currency assumption evidence requires unit_assumed_currency")
        if not claim.unit_assumed_currency:
            continue
        basis = claim.unit_assumption_basis
        if basis is None:
            raise ValueError("assumed currency claim has no calibration reference")
        if (claim.field not in METRICS or _number(claim.value) is None
                or claim.period_start is None or claim.period_end is None
                or claim.period_start > claim.period_end or claim.period_end > cutoff
                or (claim.as_of is not None and claim.as_of > cutoff)):
            raise ValueError("company calibration target requires a genuine finite metric within the cutoff")
        anchors = [by_id[ref] for ref in basis.anchor_claim_ids if ref in by_id]
        if len(anchors) != len(basis.anchor_claim_ids) or len({anchor.field for anchor in anchors}) < 2:
            raise ValueError("company calibration requires two present, distinct PDF anchor metrics")
        if set(basis.anchor_metrics) != {anchor.field for anchor in anchors}:
            raise ValueError("company calibration anchor metrics do not match the referenced claims")
        for anchor in anchors:
            pointer = basis.reference_api_pointer_prefix + "/" + METRICS.get(anchor.field, "")
            exact_api_binding = any(item.json_pointer in {pointer, pointer + "/sum"}
                and item.extraction_method == "brreg_json_pointer_v1"
                and basis.reference_api_snapshot_id in item.source_snapshot_ids
                for ref in anchor.evidence_ids if (item := evidence_by_id.get(ref)) is not None)
            if (not _pdf_support(anchor, evidence_by_id, snapshots_by_id)
                    or anchor.organisation_number != claim.organisation_number or anchor.currency != basis.currency
                    or anchor.scope != basis.reference_scope or anchor.period_start != basis.reference_period_start
                    or anchor.period_end != basis.reference_period_end or anchor.period_end > cutoff
                    or (anchor.as_of is not None and anchor.as_of > cutoff)
                    or not exact_api_binding
                    or not _journal_matches(anchor, {"raw": basis.reference_filing_identity}, evidence_by_id)
                    or not set(anchor.evidence_ids) <= set(basis.evidence_ids)
                    or not set(anchor.source_snapshot_ids) <= set(basis.source_snapshot_ids)):
                raise ValueError("company calibration reference is not supported by current nonzero PDF anchors")


def calibrate_company_financials(result: BrregResult, org: str, cutoff: datetime) -> BrregResult:
    """Call after enrich_company; mutate and return result, without fetching any sources.

    Two distinct nonzero PDF rows must equal full-currency API values in the
    unique latest eligible company filing. Missing units on other API values
    may then be published as explicit company-local assumptions. No ratio-based
    calibration, universal API contract, or group PDF reconciliation is inferred.
    """
    audit: dict[str, Any] = {"state": "not_available", "reason": "no_current_pdf_anchors", "claims_added": 0}
    result.observations["financial_calibration"] = audit
    if any(error.code == "ANNUAL_EXISTING_VALUE_CONFLICT" or (
            error.code == "ANNUAL_DOCUMENT_CLAIM_CONFLICT"
            and error.message.rsplit(":", 1)[-1].strip() != "full_time_equivalents")
            for error in result.errors):
        audit.update(state="ambiguous", reason="document_conflict")
        return result
    records = [record for record in result.account_records if _eligible(record, org, cutoff)]
    company = [record for record in records if record["scope"] == "legal_entity"]
    if not company:
        return result
    latest_end = max(_date(record["period_end"]) for record in company)
    latest = [record for record in company if _date(record["period_end"]) == latest_end]
    if len(latest) != 1:
        audit.update(state="ambiguous", reason="multiple_current_filing_versions")
        return result
    reference = latest[0]
    if not reference.get("raw", {}).get("journalnr"):
        audit.update(reason="missing_exact_document_filing_identity")
        return result
    if _metadata_conflict(reference):
        audit.update(state="ambiguous", reason="explicit_unit_metadata_conflict")
        return result
    source = result.account_source
    json_sources = [item for item in result.snapshots if item.source_url == source.get("url")
        and item.content_sha256 == source.get("content_sha256") and item.http_status == 200]
    if source.get("status") != 200 or not json_sources:
        audit.update(reason="missing_api_source_snapshot")
        return result
    json_source = json_sources[0]
    by_evidence = {item.evidence_id: item for item in result.evidence}
    by_snapshot = {item.source_id: item for item in result.snapshots}
    start, end = _date(reference["period_start"]), _date(reference["period_end"])
    anchors: list[Claim] = []
    for claim in result.claims:
        if (claim.organisation_number != org or claim.period_start != start or claim.period_end != end
                or claim.currency != reference["currency"] or not _pdf_support(claim, by_evidence, by_snapshot)):
            continue
        pointer = reference["_source_prefix"] + "/" + METRICS[claim.field]
        if not any(by_evidence[ref].json_pointer in {pointer, pointer + "/sum"}
                and by_evidence[ref].source_url == json_source.source_url
                and by_evidence[ref].content_sha256 == json_source.content_sha256
                and json_source.source_id in by_evidence[ref].source_snapshot_ids for ref in claim.evidence_ids):
            continue
        if not _journal_matches(claim, reference, by_evidence):
            audit.update(state="ambiguous", reason="document_filing_identity_mismatch")
            return result
        unit_state = reference["metrics"].get(claim.field + "_unit_state")
        explicit_unit = reference["metrics"].get(claim.field + "_unit")
        if (_number(claim.value) != _number(reference["metrics"].get(claim.field))
                or unit_state not in {"absent", "supported"}
                or (unit_state == "supported" and str(explicit_unit).strip().upper() != claim.currency)):
            audit.update(state="ambiguous", reason="pdf_api_value_or_unit_conflict")
            return result
        anchors.append(claim)
    if len({claim.field for claim in anchors}) < 2:
        audit.update(reason="fewer_than_two_nonzero_anchor_metrics")
        return result
    if any(len({_number(claim.value) for claim in anchors if claim.field == metric}) > 1 for metric in METRICS):
        audit.update(state="ambiguous", reason="conflicting_anchor_values")
        return result
    anchors.sort(key=lambda claim: claim.claim_id)
    anchor_evidence = sorted({ref for claim in anchors for ref in claim.evidence_ids})
    anchor_snapshots = sorted({ref for claim in anchors for ref in claim.source_snapshot_ids})
    reference_subject = financial_record_subject(org, reference)
    calibration_data = {"org": org, "reference_subject": reference_subject,
        "anchor_claim_ids": [claim.claim_id for claim in anchors], "evidence_ids": anchor_evidence}
    calibration_id = org + ":currency-calibration:" + hashlib.sha256(json.dumps(calibration_data,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    counts = Counter((record["scope"], _date(record["period_start"]), _date(record["period_end"])) for record in records)
    for record in records:
        record_start, record_end = _date(record["period_start"]), _date(record["period_end"])
        if (record["currency"] != reference["currency"] or _metadata_conflict(record)
                or counts[record["scope"], record_start, record_end] != 1):
            continue
        if record["scope"] == "group" and ("enhet" in record["raw"] or any(
                record["metrics"].get(metric + "_unit_state") != "absent"
                for metric in METRICS if _number(record["metrics"].get(metric)) is not None)):
            continue
        subject = financial_record_subject(org, record)
        for metric in METRICS:
            value = record["metrics"].get(metric)
            if _number(value) is None or record["metrics"].get(metric + "_unit_state") != "absent":
                continue
            existing = [claim for claim in result.claims if claim.field_family == "financial" and claim.field == metric
                and claim.scope == record["scope"] and claim.period_start == record_start and claim.period_end == record_end]
            if existing:
                continue
            pointer = record["_source_prefix"] + "/" + METRICS[metric]
            raw_metric: Any = record["raw"]
            for part in METRICS[metric].split("/"):
                raw_metric = raw_metric.get(part) if isinstance(raw_metric, dict) else None
            if isinstance(raw_metric, dict):
                pointer += "/sum"
            evidence_id = subject + ":currency-assumption:" + metric
            result.evidence.append(Evidence(evidence_id=evidence_id, source_url=json_source.source_url,
                retrieved_at=json_source.retrieved_at, content_sha256=json_source.content_sha256,
                extraction_method="brreg_company_currency_assumption_v1", json_pointer=pointer,
                excerpt="Currency unit assumed from company PDF/API anchors; target row not PDF validated; no documented API unit contract.",
                subject_organisation_number=org, source_snapshot_ids=[json_source.source_id]))
            basis = FinancialUnitAssumption(calibration_id=calibration_id, organisation_number=org,
                reference_subject_id=reference_subject, reference_period_start=start, reference_period_end=end,
                reference_filing_identity=_identity(reference), reference_api_pointer_prefix=reference["_source_prefix"],
                reference_api_snapshot_id=json_source.source_id, currency=reference["currency"],
                anchor_claim_ids=[claim.claim_id for claim in anchors], anchor_metrics=sorted({claim.field for claim in anchors}),
                evidence_ids=anchor_evidence, source_snapshot_ids=anchor_snapshots,
                same_period_as_reference=record_start == start and record_end == end,
                same_scope_as_reference=record["scope"] == "legal_entity", same_filing_as_reference=subject == reference_subject)
            result.claims.append(Claim(claim_id=evidence_id, organisation_number=org,
                section="accounts_history", field_family="financial", subject_id=subject, field=metric,
                value=value, state=PublicState.AVAILABLE, unit=record["currency"], currency=record["currency"],
                unit_assumed_currency=True, unit_assumption_basis=basis, period_start=record_start, period_end=record_end,
                as_of=_date(record.get("filing_timestamp")), scope=record["scope"], verification_rule_id=ASSUMPTION_RULE,
                verification_score="1.0", evidence_ids=[evidence_id, *anchor_evidence],
                source_snapshot_ids=sorted({json_source.source_id, *anchor_snapshots})))
            audit["claims_added"] += 1
    audit.update(state="available", reason="company_local_assumption_from_two_nonzero_metrics",
        calibration_id=calibration_id, reference_subject_id=reference_subject,
        anchor_metrics=sorted({claim.field for claim in anchors}), documented_api_unit_contract=False)
    if audit["claims_added"]:
        result.section_states["accounts_history"] = PublicState.AVAILABLE
        result.terminal_state = PublicState.AVAILABLE
    return result
