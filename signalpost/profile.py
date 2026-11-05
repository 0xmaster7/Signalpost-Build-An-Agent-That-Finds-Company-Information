"""Deterministic human profiles over the canonical publication graph."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import Claim, Envelope, PublicState, validate_publication_graph

PROFILE_SCHEMA_VERSION = 1
PROFILE_MODE = "deterministic_supported_profile"
_DOMAINS = {
    "identity": ("Identity", ("identity_brand",)),
    "industry_activity": ("Registry industry and activity", ("identity_brand",)),
    "size_fte": ("Employee count and FTE", ("identity_brand", "hiring_activity")),
    "location": ("Registered location", ("identity_brand",)),
    "leadership": ("Leadership", ("leadership_workplaces",)),
    "financials": ("Legal-entity financials", ("accounts_history",)),
    "presence": ("Verified website presence", ("website_owned_profiles",)),
    "hiring": ("Hiring", ("hiring_activity",)),
    "dated_activity": ("Dated public activity", ("hiring_activity",)),
    "refresh_changes": ("Refresh changes", ("refresh_changes",)),
}
_LABELS = {
    "name": "Registered legal name", "legal_name": "Registered legal name",
    "legal_form": "Registered legal form", "registered_business_activity": "Registered business activity",
    "registered_purpose": "Registered purpose", "employees": "Registry employee count",
    "full_time_equivalents": "Reported full-time equivalents",
    "business_address": "Registered business address", "postal_address": "Registered postal address",
    "registered_workplace_address": "Registered workplace address", "municipality": "Registered municipality",
    "revenue": "Revenue", "operating_result": "Operating result", "annual_result": "Annual result",
    "total_assets": "Total assets", "equity": "Equity", "total_liabilities": "Total liabilities",
    "website_url": "Verified website", "public_brand": "Verified public brand",
    "company_owned_profile": "Verified company-owned profile",
}
_PROFILE_KEYS = {"schema_version", "mode", "organisation_number", "evidence_cutoff", "sentences", "unknowns", "blocked", "refresh_context"}
_SENTENCE_KEYS = {"sentence_id", "domain", "text", "fact_ids", "evidence_ids", "change_ids"}
_UNKNOWN_KEYS = {"domain", "text", "reasons", "candidate_claim_ids", "evidence_ids", "state_context", "change_ids"}
_CONTEXT_KEYS = {"section", "state", "attempt_outcome", "json_pointer"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and all(isinstance(part, str) for part in value):
        return " ".join(part.strip() for part in value if part.strip())
    return _canonical(value)


def _instant(value: Any) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _number(value: Any, *, signed: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return False
    try:
        return Decimal(str(value)).is_finite() and (signed or Decimal(str(value)) >= 0)
    except InvalidOperation:
        return False


def _envelope(source: Envelope | Mapping[str, Any]) -> Envelope:
    if isinstance(source, Envelope):
        return validate_publication_graph(source)
    if not isinstance(source, Mapping):
        raise TypeError("profile source must be a canonical Envelope or evaluator object")
    if "batch_id" in source and "evidence_cutoff" in source:
        return Envelope.model_validate(dict(source))
    batch = source.get("batch") or {}
    run = source.get("run") or {}
    canonical = {key: source[key] for key in (
        "input_ref", "organisation_number", "terminal_state", "sections", "claims", "evidence",
        "source_snapshots", "refresh", "operations", "errors") if key in source}
    canonical.update(row_number=source.get("row_number", 1), batch_id=batch.get("batch_id"),
                     evidence_cutoff=batch.get("evidence_cutoff"))
    if run.get("created_at") is not None:
        canonical["created_at"] = run["created_at"]
    return Envelope.model_validate(canonical)


def _domain(claim: Claim) -> str | None:
    if claim.section == "identity_brand":
        if claim.field in {"name", "legal_name", "legal_form"}:
            return "identity"
        if claim.field.startswith("industry_codes.") or claim.field in {"registered_business_activity", "registered_purpose"}:
            return "industry_activity"
        if claim.field == "employees":
            return "size_fte"
        if claim.field in {"business_address", "postal_address", "registered_workplace_address", "municipality"}:
            return "location"
    if claim.section == "accounts_history" and claim.field_family in {"financial", "financial_record_metadata"}:
        return "financials"
    if claim.section == "leadership_workplaces" and claim.field_family == "role":
        return "leadership"
    if claim.section == "hiring_activity":
        return {"workforce": "size_fte", "jobs": "hiring", "public_activity": "dated_activity"}.get(claim.field_family)
    if claim.section == "website_owned_profiles" and claim.field in {"website_url", "public_brand", "company_owned_profile"}:
        return "presence"
    return None


def _row_key(claim: Claim, envelope: Envelope) -> tuple[str, ...] | None:
    evidence = {item.evidence_id: item for item in envelope.evidence}
    rows = set()
    for reference in claim.evidence_ids:
        item = evidence[reference]
        match = re.match(r"(.*/roller/\d+)(?:/|$)", item.json_pointer or "")
        if match:
            rows.add((item.source_url, item.content_sha256, match.group(1)))
    return next(iter(rows)) if len(rows) == 1 else None


def _period(claim: Claim, cutoff: datetime) -> tuple[datetime, datetime] | None:
    start, end = _instant(claim.period_start), _instant(claim.period_end)
    return (start, end) if start is not None and end is not None and start <= end <= cutoff else None


def _publication_date(claim: Claim, cutoff: datetime) -> str | None:
    value = claim.value
    if not isinstance(value, dict) or not isinstance(value.get("source_value"), str) or not value["source_value"].strip():
        return None
    published = _instant(value.get("normalized_utc"))
    if published is None or published > cutoff:
        return None
    raw = value["source_value"].strip()
    try:
        source_date = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        source_date = source_date.replace(tzinfo=timezone.utc) if source_date.tzinfo is None else source_date
    except ValueError:
        from email.utils import parsedate_to_datetime
        try:
            source_date = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
    if source_date.tzinfo is None or source_date.astimezone(timezone.utc) != published:
        return None
    return raw


def _sentence(domain: str, text: str, claims: list[Claim], *, change_ids: list[str] | None = None) -> dict[str, Any]:
    record = {"domain": domain, "text": text, "fact_ids": sorted({claim.claim_id for claim in claims}),
              "evidence_ids": sorted({reference for claim in claims for reference in claim.evidence_ids}),
              "change_ids": sorted(change_ids or [])}
    record["sentence_id"] = "profile:" + hashlib.sha256(_canonical(record).encode()).hexdigest()[:24]
    return record


def build_profile(source: Envelope | Mapping[str, Any]) -> dict[str, Any]:
    """Build an offline profile from an Envelope, its JSON object, or evaluator JSON.

    Factual sentences contain canonical ``fact_ids`` and ``evidence_ids``.
    State-only unknowns describe this profile's verification limits, with JSON
    pointers into canonical sections. No missing observation becomes a zero.
    Exporters may call this helper without depending on orchestration or an LLM.
    """
    envelope = _envelope(source)
    cutoff = _instant(envelope.evidence_cutoff)
    if cutoff is None:
        raise ValueError("profile requires a timezone-aware evidence cutoff")
    candidates: dict[str, list[Claim]] = defaultdict(list)
    eligible: dict[str, list[Claim]] = defaultdict(list)
    reasons: dict[str, set[str]] = defaultdict(set)
    for claim in sorted(envelope.claims, key=lambda item: item.claim_id):
        domain = _domain(claim)
        if domain is None:
            continue
        candidates[domain].append(claim)
        section = envelope.sections[claim.section]
        expected_scope = {"leadership": "person_role", "hiring": "job", "dated_activity": "event"}.get(domain, "legal_entity")
        if claim.state != PublicState.AVAILABLE:
            reasons[domain].add("unavailable_claims")
        elif section.state != PublicState.AVAILABLE or section.attempt_outcome in {"not_attempted", "budget_skipped", "policy_skipped"}:
            reasons[domain].add("section_not_available")
        elif claim.scope != expected_scope:
            reasons[domain].add("unsupported_scope")
        elif domain in {"identity", "industry_activity", "location", "presence"} and claim.subject_id != envelope.organisation_number:
            reasons[domain].add("unsupported_subject")
        elif claim.field == "employees" and claim.subject_id != envelope.organisation_number:
            reasons[domain].add("unsupported_subject")
        elif claim.as_of is not None and (_instant(claim.as_of) is None or _instant(claim.as_of) > cutoff):
            reasons[domain].add("after_cutoff_or_invalid_date")
        elif claim.value is None or claim.value == "" or claim.value == [] or claim.value == {}:
            reasons[domain].add("empty_value")
        else:
            eligible[domain].append(claim)
    sentences = []

    def unique(domain: str, claims: list[Claim], *, by_subject: bool = False) -> list[list[Claim]]:
        grouped: dict[tuple[Any, ...], list[Claim]] = defaultdict(list)
        for claim in claims:
            field = "name" if claim.field == "legal_name" else claim.field
            grouped[(field, claim.period_start, claim.period_end, claim.subject_id if by_subject else None)].append(claim)
        result = []
        for group in grouped.values():
            signatures = {_canonical([claim.value, claim.unit, claim.currency, claim.unit_assumed_currency]) for claim in group}
            claim = group[0]
            ambiguous = any(item.state == PublicState.AMBIGUOUS and item.field == claim.field
                            and item.scope == claim.scope and item.period_start == claim.period_start
                            and item.period_end == claim.period_end
                            and (not by_subject or item.subject_id == claim.subject_id)
                            for item in candidates[domain])
            if len(signatures) != 1 or ambiguous:
                reasons[domain].add("conflicting_claims")
            else:
                result.append(group)
        return result

    for domain in ("identity", "industry_activity", "size_fte", "location", "presence"):
        for group in unique(domain, eligible[domain]):
            claim = group[0]
            label = "Registered industry classification" if claim.field.startswith("industry_codes.") else _LABELS.get(claim.field)
            if label is None:
                continue
            dimensions = ""
            if domain == "size_fte":
                if not _number(claim.value):
                    reasons[domain].add("invalid_size_value")
                    continue
                if claim.field == "full_time_equivalents":
                    period = _period(claim, cutoff)
                    if period is None or claim.unit != "FTE":
                        reasons[domain].add("invalid_period_or_unit")
                        continue
                    dimensions = f" (period {period[0].date().isoformat()} to {period[1].date().isoformat()}; unit FTE; scope legal_entity)"
            sentences.append(_sentence(domain, f"{label}: {_text(claim.value)}{dimensions}.", group))

    periods = {period for claim in eligible["financials"] if (period := _period(claim, cutoff)) is not None}
    latest = max((period[1] for period in periods), default=None)
    latest_periods = {period for period in periods if period[1] == latest}
    if len(latest_periods) == 1:
        latest_period = next(iter(latest_periods))
        metrics = [claim for claim in eligible["financials"] if claim.field_family == "financial"
                   and _period(claim, cutoff) == latest_period]
        for group in unique("financials", metrics):
            claim = group[0]
            if not _number(claim.value, signed=True):
                reasons["financials"].add("invalid_financial_value")
                continue
            qualifier = "; currency unit assumed; target value not independently PDF validated" if claim.unit_assumed_currency else ""
            text = (f"Latest supported accounts in this profile, period {latest_period[0].date().isoformat()} to "
                    f"{latest_period[1].date().isoformat()}: {_LABELS.get(claim.field, claim.field.replace('_', ' '))}: "
                    f"{_text(claim.value)} (unit {claim.unit}; currency {claim.currency}; scope legal_entity{qualifier}).")
            sentences.append(_sentence("financials", text, group))
    elif latest_periods:
        reasons["financials"].add("ambiguous_latest_period")
    if any(_period(claim, cutoff) is None for claim in eligible["financials"]):
        reasons["financials"].add("invalid_period")

    role_rows: dict[tuple[str, ...], list[Claim]] = defaultdict(list)
    for claim in eligible["leadership"]:
        row = _row_key(claim, envelope)
        if row is not None:
            role_rows[row].append(claim)
    for row in sorted(role_rows):
        groups = unique("leadership", role_rows[row])
        if len(groups) != len({claim.field for claim in role_rows[row]}):
            reasons["leadership"].add("conflicting_claims")
            continue
        fields = {group[0].field: group for group in groups}
        names = fields.get("role.name")
        roles = fields.get("role.role_description") or fields.get("role.role_code")
        if names and roles:
            selected = names + roles
            qualifiers = []
            for field, label in (("role.inactive", "inactive"), ("role.from_date", "from"), ("role.to_date", "to")):
                if field in fields:
                    selected += fields[field]
                    qualifiers.append(f"{label} {_text(fields[field][0].value)}")
            detail = "; " + "; ".join(qualifiers) if qualifiers else ""
            sentences.append(_sentence("leadership", f"Registry role record: {_text(names[0].value)}; role {_text(roles[0].value)}{detail}.", selected))

    for domain, primary_field, date_field in (("hiring", "job_title", "posting_date"),
                                               ("dated_activity", "activity_headline", "source_published_at")):
        subjects: dict[str, list[Claim]] = defaultdict(list)
        for claim in eligible[domain]:
            subjects[claim.subject_id].append(claim)
        for subject in sorted(subjects):
            fields = {group[0].field: group for group in unique(domain, subjects[subject], by_subject=True)}
            primary = fields.get(primary_field)
            dates = fields.get(date_field)
            published = _publication_date(dates[0], cutoff) if dates else None
            if not primary or not published:
                reasons[domain].add("missing_title_or_source_publication_date")
                continue
            selected = primary + dates
            if domain == "hiring":
                status = fields.get("job_status")
                if not status:
                    reasons[domain].add("missing_job_status")
                    continue
                selected += status
                text = f"Recorded job posting: {_text(primary[0].value)}; source publication {published}; recorded status {_text(status[0].value)}."
            else:
                text = f"Dated public activity: {_text(primary[0].value)}; source publication {published}."
            sentences.append(_sentence(domain, text, selected))

    selected_ids = {reference for sentence in sentences for reference in sentence["fact_ids"]}
    changes = sorted(envelope.refresh.changes, key=lambda item: item.event_id)
    unresolved_changes = []
    for event in changes:
        current_evidence_ids = {item.evidence_id for item in event.current_evidence}
        matches = [claim for claim in envelope.claims if claim.claim_id in selected_ids and claim.field == event.field
                   and claim.section == event.section and _canonical(claim.value) == _canonical(event.new_value)
                   and current_evidence_ids.intersection(claim.evidence_ids)]
        event_evidence = [*event.previous_evidence, *event.current_evidence]
        event_snapshots = {item.source_id: item for item in [*event.previous_source_snapshots, *event.current_source_snapshots]}
        supported = (event.organisation_number == envelope.organisation_number and event.provenance_complete
                     and _instant(event.observed_at) is not None and _instant(event.observed_at) <= cutoff and event_evidence)
        for item in event_evidence:
            supported = supported and item.subject_organisation_number == envelope.organisation_number and bool(item.source_snapshot_ids)
            supported = supported and all(reference in event_snapshots and event_snapshots[reference].source_url == item.source_url
                and event_snapshots[reference].content_sha256 == item.content_sha256 for reference in item.source_snapshot_ids)
        if matches and supported:
            text = (f"Refresh observed {event.type.value} for {event.field} at {event.observed_at.isoformat()}; "
                    f"supported current value {_text(event.new_value)}.")
            sentences.append(_sentence("refresh_changes", text, matches, change_ids=[event.event_id]))
        else:
            unresolved_changes.append(event.event_id)
    if unresolved_changes:
        reasons["refresh_changes"].add("changes_without_supported_current_claims")

    unknowns, blocked = [], []
    present = {sentence["domain"] for sentence in sentences}
    for domain, (label, section_names) in _DOMAINS.items():
        if domain in present and not reasons[domain]:
            continue
        context = [{"section": name, "state": envelope.sections[name].state.value if envelope.sections[name].state else None,
                    "attempt_outcome": envelope.sections[name].attempt_outcome, "json_pointer": f"/sections/{name}"}
                   for name in section_names]
        record = {"domain": domain, "text": f"{label}: verification incomplete in this profile.",
                  "reasons": sorted(reasons[domain] or {"no_supported_claims"}),
                  "candidate_claim_ids": sorted(claim.claim_id for claim in candidates[domain]),
                  "evidence_ids": sorted({reference for claim in candidates[domain] for reference in claim.evidence_ids
                                          if reference in {item.evidence_id for item in envelope.evidence}}),
                  "state_context": context, "change_ids": unresolved_changes if domain == "refresh_changes" else []}
        unknowns.append(record)
        if any(item["state"] == "blocked" or item["attempt_outcome"] == "policy_skipped" for item in context):
            blocked.append(record)
    result = {"schema_version": PROFILE_SCHEMA_VERSION, "mode": PROFILE_MODE,
              "organisation_number": envelope.organisation_number, "evidence_cutoff": cutoff.isoformat(),
              "sentences": sorted(sentences, key=lambda item: (list(_DOMAINS).index(item["domain"]), item["text"], item["sentence_id"])),
              "unknowns": unknowns, "blocked": blocked,
              "refresh_context": {"mode": envelope.refresh.mode, "previous_state_ref": envelope.refresh.previous_state_ref,
                                  "current_state_ref": envelope.refresh.current_state_ref}}
    validate_profile_schema(result)
    return result


def validate_profile_schema(profile: dict[str, Any]) -> None:
    """Validate this additive schema without opening other synthesis paths."""
    if not isinstance(profile, dict) or set(profile) != _PROFILE_KEYS:
        raise ValueError("profile does not match schema v1")
    if profile["schema_version"] != PROFILE_SCHEMA_VERSION or profile["mode"] != PROFILE_MODE:
        raise ValueError("unsupported profile schema or mode")
    if not isinstance(profile["sentences"], list):
        raise ValueError("profile sentences must be an array")
    for sentence in profile["sentences"]:
        if (not isinstance(sentence, dict) or set(sentence) != _SENTENCE_KEYS
                or sentence["domain"] not in _DOMAINS or not isinstance(sentence["text"], str)
                or any(not isinstance(sentence[key], list) or not all(isinstance(item, str) for item in sentence[key])
                       for key in ("fact_ids", "evidence_ids", "change_ids"))
                or not sentence["fact_ids"] or not sentence["evidence_ids"]):
            raise ValueError("invalid claim-backed profile sentence")
    for key in ("unknowns", "blocked"):
        if not isinstance(profile[key], list):
            raise ValueError("profile unknowns and blocked must be arrays")
        for record in profile[key]:
            if (not isinstance(record, dict) or set(record) != _UNKNOWN_KEYS or record["domain"] not in _DOMAINS
                    or not isinstance(record["state_context"], list) or not record["state_context"]
                    or any(not isinstance(context, dict) or set(context) != _CONTEXT_KEYS for context in record["state_context"])):
                raise ValueError("invalid profile state context")
    context = profile["refresh_context"]
    if not isinstance(context, dict) or set(context) != {"mode", "previous_state_ref", "current_state_ref"}:
        raise ValueError("invalid profile refresh context")


def validate_profile(source: Envelope | Mapping[str, Any], profile: dict[str, Any]) -> None:
    """Reject edited prose, references, state assertions, or selection semantics."""
    validate_profile_schema(profile)
    if profile != build_profile(source):
        raise ValueError("profile differs from deterministic canonical support")
