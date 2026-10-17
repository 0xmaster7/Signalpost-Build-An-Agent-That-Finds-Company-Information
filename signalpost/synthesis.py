"""Deterministic, evidence-bounded presentation over canonical claims."""
from __future__ import annotations

import json
from typing import Any

from .identifiers import canonical_product_heading
from .models import Envelope, PublicState

SYNTHESIS_SCHEMA_VERSION = 1
SYNTHESIS_ROOT_KEYS = frozenset({"summary", "brreg_observations", "baseline_identity",
    "live_identity_observation", "cutoff_identity_source", "evidence_cutoff",
    "evidence_cutoff_source", "website_research"})
_SYNTHESIS_KEYS = frozenset("""
summary brreg_observations baseline_identity live_identity_observation cutoff_identity_source
evidence_cutoff evidence_cutoff_source website_research schema_version mode sentences unknown_sections
text fact_ids change_ids evidence_ids json_pointer organisation_number name legal_form as_of source_url content_sha256
state reason fields retrieved_at accounts_state_evidence_id ceo_state entity_http_status
group_checked rule_id
entity_removed_from_disclosure financial_records identity_profile identity_state_evidence_id
business_address registered_workplace_address land landkode employees historical_names industry_codes latest_submitted_accounts
legal_form_description municipality_number parent_organisation_number postal_address status status_dates website
registrertIForetaksregisteret registrertIMvaregisteret konkurs underAvvikling
underTvangsavviklingEllerTvangsopplosning registreringsdatoEnhetsregisteret stiftelsesdato
adresse kommune kommunenummer postnummer poststed from to kode beskrivelse evidence_id raw source_snapshot_id
role_family_state roles_completeness_evidence_id roles_count roles_state_evidence_id
subunits_state_evidence_id target_is_subunit website_candidates workplace_count workplace_rows_returned
workplaces_complete workplaces_completeness_evidence_id workplaces_completeness_evidence_ids workplaces_state
accepted_domains activity ats_origins bytes_received candidates crawl_state duplicate_accepted_proofs_deduplicated
bytes sha256
elapsed_ms high_risk_review hiring_activity_state jobs max_absolute_pages max_default_pages max_depth
page_count page_requests pages request_count_scope request_outcomes source_policy state_counts
website_claim_families url source kind registered_domain robots_state crawl_delay_seconds rights_status
decision final_url http_status proof target_url proof_record_id proof_evidence_id source_candidate_evidence_id
discovery error redirect_target review_reason claim_count provider_id provider_version query_id result_id rank
response_sha256 json_ld_subject_match compatible_legal_name page_url page_sha256 registered_address_match
shared_domain conflicting_subject_ids domain proof_method organisation_number candidate_source
subject_ids method address municipality postcode street registered_role additional_signal
execution_state claims request_count jobs_candidates published explicit_zero identity_rejected
candidate_count
annual_accounts_document pages_processed ocr_seconds processing_seconds financial_claims workforce_claims cache_hit
robots_error
future_dated_skipped published_subjects current_subjects state activity_candidates undated future outside_window
deduplicated subject_rejected lookback_days page_discovery_target max_from_already_fetched_feed_responses
source_class external_sources_enabled terms_policy accepted ambiguous blocked failed
""".split())


def validate_synthesis_schema(synthesis: dict[str, Any]) -> None:
    """Validate the closed v1 synthesis object before it crosses serialization."""
    if not isinstance(synthesis, dict):
        raise ValueError("synthesis must be an object")
    unknown_root = set(synthesis) - (SYNTHESIS_ROOT_KEYS | {"schema_version"})
    if unknown_root:
        raise ValueError(f"unknown synthesis fields: {', '.join(sorted(unknown_root))}")
    if synthesis.get("schema_version", SYNTHESIS_SCHEMA_VERSION) != SYNTHESIS_SCHEMA_VERSION:
        raise ValueError("unsupported synthesis schema version")
    def visit(value: Any, path: tuple[str, ...] = ()) -> None:
        if path == ("website_research", "ats_origins", "*"):
            # This is an operational refusal record, never a published fact.
            # Accept it only at its exact path and only when no request was made.
            if (not isinstance(value, dict) or set(value) != {"host", "status", "requested"}
                    or not isinstance(value["host"], str) or not value["host"]
                    or value["requested"] is not False
                    or value["status"] not in {"unlisted_origin_skipped", "approved_host_but_mode_disabled"}):
                raise ValueError("invalid unrequested ATS origin diagnostic")
            return
        if isinstance(value, dict):
            unknown = set(value) - _SYNTHESIS_KEYS
            if unknown:
                raise ValueError(f"unknown nested synthesis fields: {', '.join(sorted(unknown))}")
            for key, child in value.items():
                visit(child, path + (key,))
        elif isinstance(value, list):
            for child in value:
                visit(child, path + ("*",))
    visit(synthesis)
    summary = synthesis.get("summary")
    if summary is not None:
        if not isinstance(summary, dict) or set(summary) != {"schema_version", "mode", "sentences", "unknown_sections"}:
            raise ValueError("synthesis summary does not match schema v1")
        if summary.get("schema_version") != SYNTHESIS_SCHEMA_VERSION or summary.get("mode") != "deterministic_verified_facts":
            raise ValueError("unsupported synthesis summary schema or mode")
        if not isinstance(summary.get("sentences"), list) or not isinstance(summary.get("unknown_sections"), list):
            raise ValueError("synthesis summary sentences and unknown sections must be arrays")
        for sentence in summary["sentences"]:
            if not isinstance(sentence, dict):
                raise ValueError("synthesis sentence must be an object")
            keys = set(sentence)
            factual = {"text", "fact_ids", "evidence_ids"}
            changed = {"text", "fact_ids", "change_ids", "evidence_ids"}
            if keys not in (factual, changed):
                raise ValueError("synthesis sentence does not match schema v1")


def _value_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if hasattr(value, "as_tuple"):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sentence(claim: Any) -> str:
    registered_labels = {"registered_business_activity": "Registered business activity",
                         "registered_purpose": "Registered purpose"}
    if claim.field in registered_labels and isinstance(claim.value, list) and all(isinstance(line, str) for line in claim.value):
        text = registered_labels[claim.field] + ": " + " ".join(line.strip() for line in claim.value if line.strip())
    elif claim.field in {"business_address", "postal_address", "registered_workplace_address", "workplace.beliggenhetsadresse", "workplace.postadresse"}:
        label = {"business_address": "Registered business address", "postal_address": "Registered postal address",
            "registered_workplace_address": "Registered workplace address",
            "workplace.beliggenhetsadresse": "Registered workplace location", "workplace.postadresse": "Workplace postal address"}[claim.field]
        text = label + ": " + _value_text(claim.value) + " (registry record)"
    else:
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


def _fact_key(claim: Any) -> tuple[str, str]:
    """Key facts using the same canonical equivalence rule as website headings."""
    value = (_value_text(claim.value))
    if claim.field == "product_or_service_heading" and isinstance(claim.value, str):
        value = canonical_product_heading(claim.value)
    dimensions = json.dumps({"organisation_number": claim.organisation_number,
        "subject_id": claim.subject_id, "field_family": claim.field_family, "field": claim.field,
        "value": value, "period_start": claim.period_start.isoformat() if claim.period_start else None,
        "period_end": claim.period_end.isoformat() if claim.period_end else None,
        "currency": claim.currency, "unit": claim.unit, "scope": claim.scope},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return claim.section or "", dimensions


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
    # Distinct canonical observations can express the same exact fact when
    # repeated across pages. Publish one sentence, retaining every claim and
    # citation so the deduplication does not discard provenance.
    factual_sentences: dict[tuple[str, str], dict[str, Any]] = {}
    for claim in claims:
        text = _sentence(claim)
        sentence = factual_sentences.setdefault(_fact_key(claim),
            {"text": text, "fact_ids": [], "evidence_ids": []})
        sentence["fact_ids"].append(claim.claim_id)
        sentence["evidence_ids"].extend(claim.evidence_ids)
    sentences = []
    for sentence in factual_sentences.values():
        sentence["fact_ids"] = sorted(set(sentence["fact_ids"]))
        sentence["evidence_ids"] = sorted(set(sentence["evidence_ids"]))
        sentences.append(sentence)
    for event in sorted(envelope.refresh.changes, key=lambda item: item.event_id):
        event_evidence = sorted({item.evidence_id for item in [*event.previous_evidence, *event.current_evidence]})
        if event.provenance_complete and event_evidence:
            sentences.append({"text": _change_sentence(event), "fact_ids": [], "change_ids": [event.event_id],
                              "evidence_ids": event_evidence})
    result = {"schema_version": SYNTHESIS_SCHEMA_VERSION, "mode": "deterministic_verified_facts", "sentences": sentences,
              "unknown_sections": sorted(name for name, section in envelope.sections.items()
                  if section.state in {None, PublicState.NOT_AVAILABLE, PublicState.AMBIGUOUS,
                                       PublicState.BLOCKED, PublicState.FAILED}
                  or section.attempt_outcome in {"not_attempted", "budget_skipped", "policy_skipped"})}
    validate_synthesis(envelope, result)
    return result


def validate_synthesis(envelope: Envelope, synthesis: dict[str, Any]) -> None:
    """Reject any sentence without exact, same-company canonical support."""
    # The same closed sentence schema applies whether this is the canonical
    # summary object or a direct caller's synthesized result.
    if set(synthesis) != {"schema_version", "mode", "sentences", "unknown_sections"}:
        raise ValueError("synthesis summary does not match schema v1")
    if synthesis.get("schema_version") != SYNTHESIS_SCHEMA_VERSION:
        raise ValueError("unsupported synthesis summary schema")
    claims = {claim.claim_id: claim for claim in envelope.claims}
    evidence = {item.evidence_id: item for item in envelope.evidence}
    changes = {item.event_id: item for item in envelope.refresh.changes}
    seen_factual_facts: set[tuple[str, str]] = set()
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
        text = sentence.get("text")
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("synthesis sentence repeats a claim reference")
        sentence_claims = []
        for fact_id in fact_ids:
            claim = claims.get(fact_id)
            if (claim is None or claim.state != PublicState.AVAILABLE
                    or claim.organisation_number != envelope.organisation_number):
                raise ValueError("synthesis fact is unavailable or belongs to another company")
            sentence_claims.append(claim)
        fact_keys = {_fact_key(claim) for claim in sentence_claims}
        if len(fact_keys) != 1:
            raise ValueError("synthesis sentence combines distinct canonical facts")
        fact_key = next(iter(fact_keys))
        if fact_key in seen_factual_facts:
            raise ValueError("duplicate factual synthesis sentence")
        seen_factual_facts.add(fact_key)
        if text not in {_sentence(claim) for claim in sentence_claims}:
            raise ValueError("synthesis sentence contains unsupported or altered factual wording")
        supported_evidence = set().union(*(set(claim.evidence_ids) for claim in sentence_claims))
        if set(evidence_ids) != supported_evidence:
            raise ValueError("synthesis citations are incomplete or unsupported for referenced claims")
        for evidence_id in evidence_ids:
            item = evidence.get(evidence_id)
            if item is None or item.subject_organisation_number != envelope.organisation_number:
                raise ValueError("synthesis evidence is missing or belongs to another company")
            if not item.source_snapshot_ids or any(ref not in {s.source_id for s in envelope.source_snapshots}
                                                    for ref in item.source_snapshot_ids):
                raise ValueError("synthesis evidence lacks a bound source snapshot")
