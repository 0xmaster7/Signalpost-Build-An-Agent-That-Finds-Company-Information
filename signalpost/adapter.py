from __future__ import annotations

from typing import Any

from .models import Envelope


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
        "synthesis": envelope.synthesis,
        "errors": [item.model_dump(mode="json") for item in envelope.errors],
        "operations": [item.model_dump(mode="json") for item in envelope.operations],
        "run": {"created_at": envelope.created_at.isoformat()},
        "batch": {"batch_id": envelope.batch_id, "evidence_cutoff": envelope.evidence_cutoff.isoformat()},
    }
    validate_vendor_payload(payload)
    return payload
