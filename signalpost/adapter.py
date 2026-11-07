from __future__ import annotations

import copy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .brreg import SUPPORTED_CURRENCY_CODES
from .models import (Claim, Envelope, Evidence, PublicState, SUPPORTED_FINANCIAL_UNITS,
                     financial_dimensions_compatible, validate_publication_graph)


VENDOR_REQUIRED_FIELDS = ("input_ref", "organisation_number", "terminal_state", "sections", "claims", "evidence",
                          "source_snapshots", "refresh", "synthesis", "errors", "operations", "run", "batch")

# Provisional evaluator enum mapping remains isolated at the serialization edge.
CHANGE_TYPE_MAP = {
    "new_role": "new_role", "ended_role": "ended_role",
    "new_workplace": "new_workplace", "closed_workplace": "closed_workplace",
    "new_job": "new_job", "closed_job": "closed_job",
    "new_filing": "new_filing", "corrected_filing": "corrected_filing",
    "new_activity": "new_activity", "brand_changed": "brand_changed",
    "website_changed": "website_changed", "claim_changed": "claim_changed",
    "source_became_unavailable": "source_became_unavailable",
}


def _evaluator_change(event: dict[str, Any]) -> dict[str, Any]:
    kind = event.get("type")
    if kind not in CHANGE_TYPE_MAP:
        raise ValueError(f"unsupported canonical change type: {kind}")
    return {**event, "type": CHANGE_TYPE_MAP[kind]}


def validate_vendor_payload(payload: dict[str, Any]) -> None:
    missing = [key for key in VENDOR_REQUIRED_FIELDS if key not in payload]
    if missing:
        raise ValueError(f"evaluator payload missing required fields: {', '.join(missing)}")


def _legacy_state(state: Any, reason: str | None = None) -> str:
    value = getattr(state, "value", state)
    return {"available": "complete", "not_available": "not_found", "not_applicable": "not_applicable",
            "blocked": "blocked_robots" if reason and "robot" in reason.casefold() else "blocked_policy",
            "failed": "source_error" if reason and "source" in reason.casefold() else "submission_error",
            "ambiguous": "submission_error"}.get(str(value), "submission_error")


def to_evaluator(envelope: Envelope, publication_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Provisional current-known evaluator shape; all vendor keys live in this module."""
    # Runtime assembly mutates envelope collections after initial construction;
    # revalidate at the deterministic publication boundary before serialization.
    envelope = validate_publication_graph(envelope)
    canonical_claims = {claim.claim_id: claim.model_dump(mode="json") for claim in envelope.claims}
    for section_name, section in envelope.sections.items():
        for claim in section.claims:
            canonical = canonical_claims.get(claim.claim_id)
            if canonical is None or canonical != claim.model_dump(mode="json"):
                raise ValueError(f"section {section_name} contains a claim inconsistent with canonical top-level claims")
    for claim in envelope.claims:
        section_name = claim.section
        if not section_name or section_name not in envelope.sections:
            raise ValueError("canonical claim has no matching publication section")
        if not any(item.claim_id == claim.claim_id for item in envelope.sections[section_name].claims):
            raise ValueError(f"canonical claim is missing from its publication section: {claim.claim_id}")
        if not any(item.claim_id == claim.claim_id for item in envelope.sections["claims_evidence_states"].claims):
            raise ValueError(f"canonical claim is missing from the claims/evidence section: {claim.claim_id}")
    for claim in envelope.claims:
        if claim.state == PublicState.AVAILABLE and claim.field_family == "financial":
            if (not financial_dimensions_compatible(claim.unit, claim.currency)
                    or claim.currency not in SUPPORTED_CURRENCY_CODES
                    or claim.period_start is None or claim.period_end is None
                    or claim.period_start > claim.period_end or claim.scope not in {"legal_entity", "group"}
                    or isinstance(claim.value, bool) or not isinstance(claim.value, (int, float, Decimal))):
                raise ValueError("financial publication has missing or unsupported unit, value, currency, period, or scope semantics")
            try:
                numeric = Decimal(str(claim.value))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError("financial publication value must be finite numeric data") from exc
            if not numeric.is_finite():
                raise ValueError("financial publication value must be finite numeric data")
    from .synthesis import synthesize, validate_synthesis, validate_synthesis_schema
    validate_synthesis_schema(envelope.synthesis)
    # Nested operational observations in Envelope.synthesis are useful during
    # orchestration, but they are not publication facts unless represented in
    # the canonical claim/evidence graph. Rebuild the published summary from
    # that graph and reject a stale or edited supplied summary.
    expected_summary = synthesize(envelope)
    supplied_summary = envelope.synthesis.get("summary")
    if supplied_summary is not None and supplied_summary != expected_summary:
        validate_synthesis(envelope, supplied_summary)
        raise ValueError("synthesis summary differs from deterministic canonical output")
    validate_synthesis(envelope, expected_summary)
    sections = {name: section.model_dump(mode="json") for name, section in envelope.sections.items()}
    for section in sections.values():
        section["canonical_state"] = section["state"]
        section["canonical_attempt_outcome"] = section["attempt_outcome"]
        if section["state"] is None:
            section["state"] = "not_available"
            section["attempt_outcome"] = section["attempt_outcome"] or "not_checked"
        section["availability"] = section["state"]
        section["claim_ids"] = [c["claim_id"] for c in section["claims"]]
        for claim in section["claims"]:
            claim["availability"] = claim["state"]
    claims = []
    for claim in canonical_claims.values():
        published_claim = dict(claim)
        published_claim["id"] = published_claim["claim_id"]
        published_claim["availability"] = published_claim["state"]
        claims.append(published_claim)
    evidence = []
    for item in envelope.evidence:
        published_evidence = item.model_dump(mode="json")
        published_evidence["id"] = published_evidence["evidence_id"]
        published_evidence["claim_span"] = published_evidence.get("excerpt")
        evidence.append(published_evidence)
    context = publication_context or {}
    legacy_state = _legacy_state(envelope.terminal_state, " ".join(error.message for error in envelope.errors))
    ops = [item.model_dump(mode="json") for item in envelope.operations]
    timestamps = [operation["started_at"] for operation in ops if operation.get("started_at")]
    finishes = [operation["finished_at"] for operation in ops if operation.get("finished_at")]
    requests = context.get("requests", sum(operation["physical_requests"] for operation in ops) if ops else None)
    runtime = context.get("runtime_ms")
    if runtime is None and timestamps and finishes:
        runtime = max(0, int((datetime.fromisoformat(max(finishes)) - datetime.fromisoformat(min(timestamps))).total_seconds() * 1000))
    context_run = {"run_id": context.get("run_id", envelope.batch_id), "started_at": context.get("started_at", min(timestamps) if timestamps else None),
                   "completed_at": context.get("completed_at", max(finishes) if finishes else None), "runtime_ms": runtime,
                   "terminal_status": legacy_state}
    modules = {}
    for name, status in sorted(context.get("phase_statuses", {}).items()):
        outcome = status.get("outcome")
        if outcome in {"completed", "failed"}:
            modules[name] = {**dict(sorted(status.items())), "state": "complete" if outcome == "completed" else "source_error"}
    payload = {
        "input_ref": envelope.input_ref,
        "organisation_number": envelope.organisation_number,
        "terminal_state": envelope.terminal_state.value,
        "sections": sections,
        "claims": claims,
        "evidence": evidence,
        "source_snapshots": [item.model_dump(mode="json") for item in envelope.source_snapshots],
        "refresh": {**envelope.refresh.model_dump(mode="json"),
                    "changes": [_evaluator_change(item.model_dump(mode="json")) for item in envelope.refresh.changes]},
        "synthesis": {"schema_version": 1, "summary": expected_summary},
        "errors": [item.model_dump(mode="json") for item in envelope.errors],
        "operations": {"requests": requests, "runtime_ms": runtime, "third_party_cost_usd": 0},
        "operation_log": ops,
        "run": {"created_at": envelope.created_at.isoformat(), **context_run, "modules": modules},
        "batch": {"batch_id": envelope.batch_id, "evidence_cutoff": envelope.evidence_cutoff.isoformat()},
        "state": legacy_state,
        "availability": envelope.terminal_state.value,
        "changes": [_evaluator_change(item.model_dump(mode="json")) for item in envelope.refresh.changes],
    }
    payload["profile"] = {"organisation_number": envelope.organisation_number,
                          "summary": expected_summary}
    for key in ("run_id", "started_at", "completed_at"):
        payload[key] = context_run[key]
    payload["modules"] = modules
    validate_vendor_payload(payload)
    return payload


def _decode_claim_aliases(claim: dict[str, Any]) -> None:
    if "id" in claim and claim["id"] != claim.get("claim_id"):
        raise ValueError("conflicting claim id aliases")
    if "availability" in claim and claim["availability"] != claim.get("state"):
        raise ValueError("conflicting claim availability")
    claim.pop("id", None)
    claim.pop("availability", None)


def _decode_evidence_aliases(evidence: dict[str, Any]) -> None:
    if "id" in evidence and evidence["id"] != evidence.get("evidence_id"):
        raise ValueError("conflicting evidence id aliases")
    if "claim_span" in evidence and evidence["claim_span"] != evidence.get("excerpt"):
        raise ValueError("conflicting claim span")
    evidence.pop("id", None)
    evidence.pop("claim_span", None)


def claim_from_evaluator(raw: dict[str, Any]) -> Claim:
    claim = copy.deepcopy(raw)
    _decode_claim_aliases(claim)
    return Claim.model_validate(claim)


def evidence_from_evaluator(raw: dict[str, Any]) -> Evidence:
    evidence = copy.deepcopy(raw)
    _decode_evidence_aliases(evidence)
    return Evidence.model_validate(evidence)


def from_evaluator(raw: dict[str, Any], row_number: int = 1) -> Envelope:
    """Restore the canonical strict envelope from this adapter's evaluator shape."""
    value = copy.deepcopy(raw)
    if "availability" in value and value["terminal_state"] != value["availability"]:
        raise ValueError("conflicting terminal availability aliases")
    if "state" in value and value["state"] != _legacy_state(value["terminal_state"], " ".join(error["message"] for error in value.get("errors", []))):
        raise ValueError("conflicting terminal state aliases")
    if "terminal_status" in value.get("run", {}) and value["run"]["terminal_status"] != value.get("state"):
        raise ValueError("conflicting run terminal status alias")
    if "changes" in value and value.get("refresh", {}).get("changes") != value["changes"]:
        raise ValueError("conflicting changes and refresh aliases")
    if "operations" in value and isinstance(value["operations"], dict):
        if "operation_log" not in value:
            raise ValueError("operations summary requires operation_log")
        value["operations"] = value.pop("operation_log")
    else:
        value.pop("operation_log", None)
    for claim in value.get("claims", []):
        _decode_claim_aliases(claim)
    for evidence in value.get("evidence", []):
        _decode_evidence_aliases(evidence)
    for section in value.get("sections", {}).values():
        if section.get("availability") is not None and section.get("availability") != section.get("state"):
            raise ValueError("conflicting section availability")
        if "canonical_state" in section:
            expected_state = section["canonical_state"] or "not_available"
            if section.get("state") != expected_state:
                raise ValueError("conflicting section state aliases")
        if "canonical_attempt_outcome" in section:
            section["attempt_outcome"] = section.pop("canonical_attempt_outcome")
        section["state"] = section.pop("canonical_state", section.get("state"))
        if "claim_ids" in section and section["claim_ids"] != [claim["claim_id"] for claim in section.get("claims", [])]:
            raise ValueError("conflicting section claim id aliases")
        section.pop("availability", None)
        section.pop("claim_ids", None)
        for claim in section.get("claims", []):
            _decode_claim_aliases(claim)
    for key in ("state", "availability", "changes", "modules", "profile"):
        value.pop(key, None)
    for key in ("run_id", "started_at", "completed_at"):
        if key in value and value[key] != value.get("run", {}).get(key):
            raise ValueError("conflicting run aliases")
        value.pop(key, None)
    value["row_number"] = row_number
    value["batch_id"] = value.get("batch", {}).get("batch_id")
    value["evidence_cutoff"] = value.get("batch", {}).get("evidence_cutoff")
    value["created_at"] = value.get("run", {}).get("created_at")
    value.pop("batch", None)
    value.pop("run", None)
    envelope = Envelope.model_validate(value)
    canonical_claims = {claim.claim_id: claim for claim in envelope.claims}
    for section in envelope.sections.values():
        if any(canonical_claims.get(claim.claim_id) != claim for claim in section.claims):
            raise ValueError("section claim copy differs from canonical claims")
    return envelope
