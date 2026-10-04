"""Deterministic, evidence-bounded presentation over canonical claims."""
from __future__ import annotations

import json
from typing import Any

from .models import Envelope, PublicState


def _value_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if hasattr(value, "as_tuple"):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sentence(claim: Any) -> str:
    text = f"{claim.field}: {_value_text(claim.value)}"
    dimensions = []
    if claim.period_start or claim.period_end:
        dimensions.append("period " + " – ".join(
            part for part in (claim.period_start.date().isoformat() if claim.period_start else "",
                              claim.period_end.date().isoformat() if claim.period_end else "") if part))
    if claim.currency:
        dimensions.append("currency " + claim.currency)
    if claim.unit:
        dimensions.append("unit " + claim.unit)
    if claim.scope:
        dimensions.append("scope " + claim.scope)
    if dimensions:
        text += " (" + "; ".join(dimensions) + ")"
    return text


def _change_sentence(event: Any) -> str:
    before, after = _value_text(event.old_value), _value_text(event.new_value)
    text = f"M07 observed event {event.type.value}"
    if event.field:
        text += f" for {event.field}"
    text += f": before {before}; after {after}; observed at {event.observed_at.isoformat()}"
    if event.effective_at:
        text += f"; source effective date {event.effective_at}"
    return text


def synthesize(envelope: Envelope) -> dict[str, Any]:
    """Build concise factual sentences; each sentence names its claim and evidence."""
    evidence = {item.evidence_id: item for item in envelope.evidence}
    claims = sorted(
        (item for item in envelope.claims if item.state == PublicState.AVAILABLE
         and item.organisation_number == envelope.organisation_number
         and item.evidence_ids and all(ref in evidence for ref in item.evidence_ids)),
        key=lambda item: (item.section or "", item.field_family or "", item.field,
                          item.period_end.isoformat() if item.period_end else "", item.claim_id),
    )
    sentences = []
    for claim in claims:
        sentences.append({"text": _sentence(claim), "fact_ids": [claim.claim_id],
                          "evidence_ids": sorted(set(claim.evidence_ids))})
    for event in sorted(envelope.refresh.changes, key=lambda item: item.event_id):
        event_evidence = sorted({item.evidence_id for item in [*event.previous_evidence, *event.current_evidence]})
        if event.provenance_complete and event_evidence:
            sentences.append({"text": _change_sentence(event), "fact_ids": [], "change_ids": [event.event_id],
                              "evidence_ids": event_evidence})
    result = {"mode": "deterministic_verified_facts", "sentences": sentences,
              "unknown_sections": sorted(name for name, section in envelope.sections.items()
                  if section.state in {None, PublicState.NOT_AVAILABLE, PublicState.AMBIGUOUS,
                                       PublicState.BLOCKED, PublicState.FAILED}
                  or section.attempt_outcome in {"not_attempted", "budget_skipped", "policy_skipped"})}
    validate_synthesis(envelope, result)
    return result


def validate_synthesis(envelope: Envelope, synthesis: dict[str, Any]) -> None:
    """Reject any sentence without exact, same-company canonical support."""
    claims = {claim.claim_id: claim for claim in envelope.claims}
    evidence = {item.evidence_id: item for item in envelope.evidence}
    changes = {item.event_id: item for item in envelope.refresh.changes}
    for sentence in synthesis.get("sentences", []):
        fact_ids = sentence.get("fact_ids") or []
        change_ids = sentence.get("change_ids") or []
        evidence_ids = sentence.get("evidence_ids") or []
        if bool(fact_ids) == bool(change_ids) or not evidence_ids:
            raise ValueError("factual synthesis sentences require claim and evidence references")
        if change_ids:
            if len(change_ids) != 1:
                raise ValueError("each M07 synthesis sentence must identify one change event")
            event = changes.get(change_ids[0])
            if (event is None or event.organisation_number != envelope.organisation_number
                    or not event.provenance_complete):
                raise ValueError("M07 synthesis event is missing complete canonical provenance")
            event_evidence = {item.evidence_id: item for item in [*event.previous_evidence, *event.current_evidence]}
            if not set(evidence_ids) <= set(event_evidence):
                raise ValueError("M07 synthesis citation is not attached to its event")
            event_snapshots = {item.source_id: item for item in
                [*event.previous_source_snapshots, *event.current_source_snapshots]}
            for item in (event_evidence[ref] for ref in evidence_ids):
                if item.subject_organisation_number != envelope.organisation_number:
                    raise ValueError("M07 synthesis evidence belongs to another company")
                if not item.source_snapshot_ids or not set(item.source_snapshot_ids) <= set(event_snapshots):
                    raise ValueError("M07 synthesis evidence lacks source snapshots")
                if any(event_snapshots[ref].source_url != item.source_url
                       or event_snapshots[ref].content_sha256 != item.content_sha256 for ref in item.source_snapshot_ids):
                    raise ValueError("M07 synthesis evidence does not match its source snapshot")
            if sentence.get("text") != _change_sentence(event):
                raise ValueError("M07 synthesis wording changed its event or temporal meaning")
            continue
        for fact_id in fact_ids:
            claim = claims.get(fact_id)
            if (claim is None or claim.state != PublicState.AVAILABLE
                    or claim.organisation_number != envelope.organisation_number):
                raise ValueError("synthesis fact is unavailable or belongs to another company")
            if not set(evidence_ids) <= set(claim.evidence_ids):
                raise ValueError("synthesis citation does not support its referenced claim")
            if sentence.get("text") != _sentence(claim):
                raise ValueError("synthesis sentence contains unsupported or altered factual wording")
        for evidence_id in evidence_ids:
            item = evidence.get(evidence_id)
            if item is None or item.subject_organisation_number != envelope.organisation_number:
                raise ValueError("synthesis evidence is missing or belongs to another company")
            if not item.source_snapshot_ids or any(ref not in {s.source_id for s in envelope.source_snapshots}
                                                    for ref in item.source_snapshot_ids):
                raise ValueError("synthesis evidence lacks a bound source snapshot")
