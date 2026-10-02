from __future__ import annotations

from typing import Any

from .models import Envelope


VENDOR_REQUIRED_FIELDS = ("input_ref", "organisation_number", "terminal_state", "sections", "claims", "evidence",
                          "source_snapshots", "refresh", "synthesis", "errors", "operations", "run", "batch")


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
        "refresh": envelope.refresh.model_dump(mode="json"),
        "synthesis": envelope.synthesis,
        "errors": [item.model_dump(mode="json") for item in envelope.errors],
        "operations": [item.model_dump(mode="json") for item in envelope.operations],
        "run": {"created_at": envelope.created_at.isoformat()},
        "batch": {"batch_id": envelope.batch_id, "evidence_cutoff": envelope.evidence_cutoff.isoformat()},
    }
    validate_vendor_payload(payload)
    return payload
