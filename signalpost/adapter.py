from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .brreg import SUPPORTED_CURRENCY_CODES
from .models import (Envelope, PublicState, SUPPORTED_FINANCIAL_UNITS,
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


def to_evaluator(envelope: Envelope) -> dict[str, Any]:
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
    payload = {
        "input_ref": envelope.input_ref,
        "organisation_number": envelope.organisation_number,
        "terminal_state": envelope.terminal_state.value,
        "sections": {name: section.model_dump(mode="json") for name, section in envelope.sections.items()},
        "claims": [claim.model_dump(mode="json") for claim in envelope.claims],
        "evidence": [item.model_dump(mode="json") for item in envelope.evidence],
        "source_snapshots": [item.model_dump(mode="json") for item in envelope.source_snapshots],
        "refresh": {**envelope.refresh.model_dump(mode="json"),
                    "changes": [_evaluator_change(item.model_dump(mode="json")) for item in envelope.refresh.changes]},
        "synthesis": {"schema_version": 1, "summary": expected_summary},
        "errors": [item.model_dump(mode="json") for item in envelope.errors],
        "operations": [item.model_dump(mode="json") for item in envelope.operations],
        "run": {"created_at": envelope.created_at.isoformat()},
        "batch": {"batch_id": envelope.batch_id, "evidence_cutoff": envelope.evidence_cutoff.isoformat()},
    }
    validate_vendor_payload(payload)
    return payload
