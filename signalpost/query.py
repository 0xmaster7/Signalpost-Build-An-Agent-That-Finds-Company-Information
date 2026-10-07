"""Deterministic FIND, COMPARE and VERIFY over canonical evaluator envelopes."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .models import ChangeEvent, Claim, Evidence, PublicState, SourceSnapshot, approved_frozen_hash_exception


class QueryError(ValueError):
    pass


def _decimal_equal(value: Any, proposed: Decimal) -> bool:
    try:
        candidate = Decimal(str(value))
        return candidate.is_finite() and candidate == proposed
    except (InvalidOperation, ValueError, TypeError):
        return False


@dataclass
class CompanyProfile:
    organisation_number: str
    sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    claims: list[Claim] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    snapshots: dict[str, SourceSnapshot] = field(default_factory=dict)
    changes: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def section_state(self, family: str) -> str | None:
        section_name = {
            "identity": "identity_brand", "financial": "accounts_history", "role": "leadership_workplaces",
            "workplace": "leadership_workplaces", "website": "website_owned_profiles",
            "jobs": "hiring_activity", "public_activity": "hiring_activity",
        }.get(family, family)
        section = self.sections.get(section_name) or {}
        return section.get("state")

    def claim_citations(self, claim: Claim) -> list[dict[str, Any]]:
        result = []
        for evidence_id in sorted(set(claim.evidence_ids)):
            item = self.evidence.get(evidence_id)
            if item is None or item.subject_organisation_number != self.organisation_number:
                continue
            result.append({"claim_id": claim.claim_id, "evidence_id": item.evidence_id,
                "source_url": item.source_url, "source_class": item.source_class,
                "retrieved_at": item.retrieved_at.isoformat(), "content_sha256": item.content_sha256,
                "extraction_method": item.extraction_method, "json_pointer": item.json_pointer,
                "source_snapshot_ids": list(item.source_snapshot_ids),
                "snapshots": [self.snapshots[ref].model_dump(mode="json") for ref in item.source_snapshot_ids
                              if ref in self.snapshots]})
        return result


@dataclass
class CanonicalIndex:
    """Reusable exact-entity and canonical-field indexes for interactive queries."""
    profiles: dict[str, CompanyProfile]
    by_field: dict[str, list[tuple[str, Claim]]]
    names_by_org: dict[str, list[str]]


def build_index(profiles: dict[str, CompanyProfile] | Iterable[CompanyProfile]) -> CanonicalIndex:
    keyed = profiles if isinstance(profiles, dict) else {profile.organisation_number: profile for profile in profiles}
    by_field: dict[str, list[tuple[str, Claim]]] = {}
    names: dict[str, list[str]] = {}
    for org, profile in sorted(keyed.items()):
        for claim in profile.claims:
            if claim.state != PublicState.AVAILABLE or claim.organisation_number != org:
                continue
            index_field = "name" if claim.field == "legal_name" else claim.field
            by_field.setdefault(index_field, []).append((org, claim))
            if claim.field in {"name", "legal_name", "public_brand"} and isinstance(claim.value, str):
                names.setdefault(org, []).append(claim.value)
    for entries in by_field.values():
        entries.sort(key=lambda pair: (pair[0], pair[1].claim_id))
    for values in names.values():
        values.sort(key=str.casefold)
    return CanonicalIndex(dict(keyed), by_field, names)


def load_profiles(path: str | Path) -> dict[str, CompanyProfile]:
    """Load evaluator JSONL as a keyed canonical view and verify its bindings."""
    profiles: dict[str, CompanyProfile] = {}
    with Path(path).open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            if len(line) > 2_000_000:
                raise QueryError(f"data row {line_number} exceeds the 2 MB safety limit")
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise QueryError(f"invalid JSON at data row {line_number}") from exc
            org = raw.get("organisation_number")
            if not isinstance(org, str) or not re.fullmatch(r"\d{9}", org):
                raise QueryError(f"data row {line_number} has no exact nine-digit organisation_number")
            profile = profiles.setdefault(org, CompanyProfile(org))
            profile.sections.update(raw.get("sections") or {})
            profile.errors.extend(raw.get("errors") or [])
            for item in raw.get("source_snapshots") or []:
                snapshot = SourceSnapshot.model_validate(item)
                existing = profile.snapshots.get(snapshot.source_id)
                if existing and (existing.source_url != snapshot.source_url
                                 or existing.content_sha256 != snapshot.content_sha256):
                    raise QueryError(f"conflicting source snapshot {snapshot.source_id} in row {line_number}")
                # Duplicate input rows can observe the same stable content snapshot
                # at separate times. Keep a deterministic earliest observation.
                if existing is None or snapshot.retrieved_at < existing.retrieved_at:
                    profile.snapshots[snapshot.source_id] = snapshot
            for item in raw.get("evidence") or []:
                evidence = Evidence.model_validate(item)
                if evidence.subject_organisation_number != org:
                    raise QueryError(f"evidence {evidence.evidence_id} crosses company identity at row {line_number}")
                if (not evidence.source_snapshot_ids
                        or any(ref not in profile.snapshots for ref in evidence.source_snapshot_ids)):
                    raise QueryError(f"evidence {evidence.evidence_id} lacks a bound source snapshot at row {line_number}")
                if any(profile.snapshots[ref].source_url != evidence.source_url
                       or (profile.snapshots[ref].content_sha256 != evidence.content_sha256
                           and not approved_frozen_hash_exception(evidence, profile.snapshots[ref]))
                       for ref in evidence.source_snapshot_ids):
                    raise QueryError(f"evidence {evidence.evidence_id} does not match its source snapshot")
                if evidence.evidence_id in profile.evidence and profile.evidence[evidence.evidence_id] != evidence:
                    raise QueryError(f"conflicting evidence {evidence.evidence_id} at row {line_number}")
                profile.evidence[evidence.evidence_id] = evidence
            for item in raw.get("claims") or []:
                claim = Claim.model_validate(item)
                if claim.state == PublicState.AVAILABLE:
                    if claim.organisation_number != org:
                        raise QueryError(f"available claim {claim.claim_id} crosses company identity at row {line_number}")
                    if not claim.evidence_ids or any(ref not in profile.evidence for ref in claim.evidence_ids):
                        raise QueryError(f"available claim {claim.claim_id} lacks profile evidence at row {line_number}")
                    if not claim.source_snapshot_ids or any(ref not in profile.snapshots for ref in claim.source_snapshot_ids):
                        raise QueryError(f"available claim {claim.claim_id} lacks source snapshots at row {line_number}")
                    for ref in claim.evidence_ids:
                        item_evidence = profile.evidence[ref]
                        if (item_evidence.subject_organisation_number != org
                                or not set(item_evidence.source_snapshot_ids) <= set(claim.source_snapshot_ids)
                                or any(sid not in profile.snapshots for sid in item_evidence.source_snapshot_ids)):
                            raise QueryError(f"claim {claim.claim_id} has an unbound evidence reference")
                if not any(old.claim_id == claim.claim_id for old in profile.claims):
                    profile.claims.append(claim)
            refresh = raw.get("refresh") or {}
            for item in refresh.get("changes") or []:
                event = ChangeEvent.model_validate(item)
                if event.organisation_number != org:
                    raise QueryError(f"change event {event.event_id} crosses company identity at row {line_number}")
                event_snapshots = {snapshot.source_id: snapshot for snapshot in
                    [*event.previous_source_snapshots, *event.current_source_snapshots]}
                for evidence in [*event.previous_evidence, *event.current_evidence]:
                    if evidence.subject_organisation_number != org:
                        raise QueryError(f"change event {event.event_id} has evidence from another company")
                    if event.provenance_complete and (
                            not evidence.source_snapshot_ids
                            or any(ref not in event_snapshots for ref in evidence.source_snapshot_ids)
                            or any(event_snapshots[ref].source_url != evidence.source_url
                                   or event_snapshots[ref].content_sha256 != evidence.content_sha256
                                   for ref in evidence.source_snapshot_ids)):
                        raise QueryError(f"change event {event.event_id} has unbound provenance")
                profile.changes.append(event.model_dump(mode="json"))
    for profile in profiles.values():
        profile.claims.sort(key=lambda item: (item.section or "", item.field_family or "", item.field,
            item.period_end.isoformat() if item.period_end else "", item.claim_id))
        unique = {event.get("event_id"): event for event in profile.changes}
        profile.changes = [unique[key] for key in sorted(unique)]
    return profiles


FIELD_ALIASES = {
    "org": "organisation_number", "organisation_number": "organisation_number",
    "name": "name", "legal_name": "name", "brand": "public_brand",
    "legal_form": "legal_form", "municipality": "municipality",
    "industry": "industry_codes.0", "employees": "employees",
    "revenue": "revenue", "operating_result": "operating_result",
    "profit_before_tax": "profit_before_tax", "annual_result": "annual_result",
    "total_assets": "total_assets", "equity": "equity", "total_debt": "total_debt",
    "website": "verified_website_url", "role": "role.name", "job": "job_title",
}
NUMERIC_FIELDS = {"employees", "revenue", "operating_result", "profit_before_tax", "annual_result",
                  "total_assets", "equity", "total_debt"}
FINANCIAL_FIELDS = NUMERIC_FIELDS - {"employees"}
SINGLE_VALUE_FIELDS = {"name", "public_brand", "legal_form", "municipality", "verified_website_url", "employees"}
SUPPORTED_OPERATORS = {"eq", "contains", "gt", "gte", "lt", "lte", "range"}


@dataclass(frozen=True)
class FindFilter:
    field: str
    operator: str
    value: str | Decimal | tuple[Decimal, Decimal]
    currency: str | None = None
    period_end: str | None = None
    scope: str | None = None
    unit: str | None = None


def validate_filter(item: FindFilter) -> FindFilter:
    if item.field not in FIELD_ALIASES:
        raise QueryError(f"unsupported field: {item.field[:80]}")
    if item.operator not in SUPPORTED_OPERATORS:
        raise QueryError("unsupported filter operator")
    if item.field in NUMERIC_FIELDS:
        if item.operator not in {"eq", "gt", "gte", "lt", "lte", "range"}:
            raise QueryError("numeric fields require a numeric operator")
        if item.field in FINANCIAL_FIELDS and not (item.currency and item.period_end and item.scope and item.unit):
            raise QueryError("financial filters require exact currency, period_end, scope, and unit dimensions")
        if item.scope not in {None, "legal_entity", "group", "unknown", "workplace"}:
            raise QueryError("unsupported numeric fact scope")
        if item.operator == "range":
            if (not isinstance(item.value, tuple) or len(item.value) != 2
                    or any(not isinstance(value, Decimal) or not value.is_finite() for value in item.value)
                    or item.value[0] > item.value[1]):
                raise QueryError("range requires ordered lower and upper numeric bounds")
            numeric_values = item.value
        elif not isinstance(item.value, Decimal) or not item.value.is_finite():
            raise QueryError("numeric filter values must be Decimal")
        else:
            numeric_values = (item.value,)
        if any(len(value.as_tuple().digits) > 30 or abs(value.adjusted()) > 18 for value in numeric_values):
            raise QueryError("numeric filter is outside the supported range")
    elif item.operator in {"gt", "gte", "lt", "lte", "range"}:
        raise QueryError("ordered comparisons require a supported numeric field")
    elif len(str(item.value)) > 300:
        raise QueryError("text filter value exceeds 300 characters")
    if item.field == "organisation_number" and item.operator != "eq":
        raise QueryError("organisation_number supports exact equality only")
    if item.field == "organisation_number" and not re.fullmatch(r"\d{9}", str(item.value)):
        raise QueryError("organisation_number filters require an exact nine-digit string")
    if item.period_end:
        try:
            date.fromisoformat(item.period_end)
        except ValueError as exc:
            raise QueryError("period_end must be an ISO date") from exc
    return item


def _field_claims(profile: CompanyProfile, field: str) -> list[Claim]:
    if field == "organisation_number":
        return []
    canonical = FIELD_ALIASES[field]
    return [claim for claim in profile.claims if claim.state == PublicState.AVAILABLE and _claim_matches_field(claim, canonical)
            and claim.organisation_number == profile.organisation_number]


def _claim_matches_field(claim: Claim, canonical_field: str) -> bool:
    return claim.field == canonical_field or (canonical_field == "name" and claim.field == "legal_name")


def _truth(profile: CompanyProfile, item: FindFilter) -> tuple[bool | None, list[Claim], str | None]:
    item = validate_filter(item)
    if item.field == "organisation_number":
        return (profile.organisation_number == str(item.value), [], None)
    candidates = _field_claims(profile, item.field)
    if item.field in FINANCIAL_FIELDS:
        candidates = [claim for claim in candidates if claim.currency == item.currency
                     and (claim.period_end.date().isoformat() if claim.period_end else None) == item.period_end
                     and claim.scope == item.scope and claim.unit == item.unit]
        if not candidates:
            return None, [], "no fact with the requested currency, reporting period, scope, and unit"
    matched = []
    for claim in candidates:
        value = claim.value
        if item.field in NUMERIC_FIELDS:
            try:
                actual = Decimal(str(value))
            except (InvalidOperation, ValueError):
                continue
            if item.operator == "range":
                ok = item.value[0] <= actual <= item.value[1]
            else:
                expected = item.value
                ok = {"eq": actual == expected, "gt": actual > expected, "gte": actual >= expected,
                      "lt": actual < expected, "lte": actual <= expected}[item.operator]
        elif item.operator == "contains":
            ok = isinstance(value, str) and str(item.value).casefold() in value.casefold()
        else:
            ok = str(value).casefold() == str(item.value).casefold()
        if ok:
            matched.append(claim)
    if matched:
        return True, matched, None
    if candidates and FIELD_ALIASES[item.field] in SINGLE_VALUE_FIELDS:
        return False, candidates, "canonical single-valued fact contradicts the requested value"
    return None, [], "canonical data does not establish whether the predicate is false"


def find_companies(profiles: Iterable[CompanyProfile] | dict[str, CompanyProfile], *, text: str = "",
                   filters: list[FindFilter] | None = None, index: CanonicalIndex | None = None) -> dict[str, Any]:
    if len(text) > 300:
        raise QueryError("text query exceeds 300 characters")
    if len(filters or []) > 12:
        raise QueryError("at most 12 AND filters are supported")
    checked = [validate_filter(item) for item in (filters or [])]
    if len({(item.field, item.operator, str(item.value), item.currency, item.period_end, item.scope, item.unit) for item in checked}) != len(checked):
        raise QueryError("duplicate filters are not supported")
    index = index or build_index(profiles)
    query = text.strip().casefold()
    candidates = set(index.profiles)
    if query:
        candidates &= {org for org, values in index.names_by_org.items()
                       if any(query in value.casefold() for value in values)}
    matched_citations: dict[str, dict[str, dict[str, Any]]] = {org: {} for org in candidates}
    unknown_reasons: dict[str, list[str]] = {org: [] for org in candidates}
    for item in checked:
        true_by_org: dict[str, list[Claim]] = {}
        field_rows: dict[str, list[Claim]] = {}
        if item.field != "organisation_number":
            for org, claim in index.by_field.get(FIELD_ALIASES[item.field], []):
                if org in candidates:
                    field_rows.setdefault(org, []).append(claim)
        false_orgs: set[str] = set()
        for org in tuple(candidates):
            if item.field == "organisation_number":
                if org == str(item.value):
                    true_by_org[org] = []
                else:
                    false_orgs.add(org)
                continue
            rows = field_rows.get(org, [])
            if not rows:
                unknown_reasons[org].append(f"{item.field}: no available canonical fact")
                continue
            dimension_rows = rows
            if item.field in FINANCIAL_FIELDS:
                dimension_rows = [claim for claim in rows if claim.currency == item.currency
                    and (claim.period_end.date().isoformat() if claim.period_end else None) == item.period_end
                    and claim.scope == item.scope and claim.unit == item.unit]
                if not dimension_rows:
                    unknown_reasons[org].append(f"{item.field}: no fact with the requested currency, reporting period, scope, and unit")
                    continue
            matched = []
            for claim in dimension_rows:
                try:
                    if item.field in NUMERIC_FIELDS:
                        actual = Decimal(str(claim.value))
                        if not actual.is_finite():
                            continue
                        if item.operator == "range":
                            ok = item.value[0] <= actual <= item.value[1]
                        else:
                            ok = {"eq": actual == item.value, "gt": actual > item.value,
                                  "gte": actual >= item.value, "lt": actual < item.value,
                                  "lte": actual <= item.value}[item.operator]
                    elif item.operator == "contains":
                        ok = isinstance(claim.value, str) and str(item.value).casefold() in claim.value.casefold()
                    else:
                        ok = str(claim.value).casefold() == str(item.value).casefold()
                except (InvalidOperation, KeyError, TypeError):
                    ok = False
                if ok:
                    matched.append(claim)
            if matched:
                true_by_org[org] = matched
            elif ((FIELD_ALIASES[item.field] in SINGLE_VALUE_FIELDS
                    and len({json.dumps(claim.value, ensure_ascii=False, sort_keys=True, default=str)
                             for claim in dimension_rows}) == 1)
                  or (item.field in FINANCIAL_FIELDS and len(dimension_rows) == 1)):
                false_orgs.add(org)
            else:
                unknown_reasons[org].append(f"{item.field}: available data does not establish the predicate")
        for org, claims in true_by_org.items():
            for claim in claims:
                matched_citations[org].update({ref["evidence_id"]: ref for ref in index.profiles[org].claim_citations(claim)})
        candidates -= false_orgs
    matches, unknown = [], []
    for org in sorted(candidates, key=lambda key: (key, _profile_name(index.profiles[key]).casefold())):
        profile = index.profiles[org]
        name_count = sum(claim.field in {"name", "legal_name", "public_brand"} for claim in profile.claims)
        item = {"organisation_number": org, "name": _profile_name(profile),
                "citations": [matched_citations[org][key] for key in sorted(matched_citations[org])]}
        if unknown_reasons[org]:
            unknown.append({**item, "reasons": unknown_reasons[org]})
        else:
            matches.append({**item, "claim_count": name_count})
    return {"status": "complete", "mode": "and", "matches": matches, "unknown": unknown,
            "result_count": len(matches), "unknown_count": len(unknown)}


def _profile_name(profile: CompanyProfile) -> str:
    claim = next((item for item in profile.claims if item.field in {"name", "legal_name"}
                  and item.organisation_number == profile.organisation_number
                  and item.state == PublicState.AVAILABLE and isinstance(item.value, str)), None)
    return claim.value if claim else profile.organisation_number


def compare_companies(profiles: dict[str, CompanyProfile], organisation_numbers: list[str], fields: list[str] | None = None) -> dict[str, Any]:
    if not 2 <= len(organisation_numbers) <= 4:
        raise QueryError("compare requires two to four organisation numbers")
    if len(set(organisation_numbers)) != len(organisation_numbers):
        raise QueryError("duplicate companies are not supported in comparison")
    if any(not re.fullmatch(r"\d{9}", org) for org in organisation_numbers):
        raise QueryError("organisation numbers must be exact nine-character strings")
    if len(fields or []) > 12:
        raise QueryError("at most 12 comparison fields are supported")
    requested = fields or ["legal_name", "legal_form", "municipality", "revenue", "annual_result", "website"]
    requested = [FIELD_ALIASES.get(item, item) for item in requested]
    allowed_fields = {FIELD_ALIASES[key] for key in FIELD_ALIASES if key != "org"}
    if any(item not in allowed_fields for item in requested):
        raise QueryError("unsupported comparison field")
    columns = []
    selected_profiles = []
    for org in organisation_numbers:
        profile = profiles.get(org)
        if profile is None:
            raise QueryError(f"company {org} is not present in the canonical dataset")
        selected_profiles.append(profile)
    for canonical_field in requested:
        values = []
        dimensions = set()
        single_fact_per_company = True
        financial_field = canonical_field in {FIELD_ALIASES[name] for name in FINANCIAL_FIELDS}
        for profile in selected_profiles:
            claims = [claim for claim in profile.claims if _claim_matches_field(claim, canonical_field) and claim.state == PublicState.AVAILABLE
                      and claim.organisation_number == profile.organisation_number]
            if not claims:
                values.append({"organisation_number": profile.organisation_number, "status": _missing_status(profile, canonical_field),
                               "value": None, "citations": []})
                continue
            if len(claims) != 1:
                single_fact_per_company = False
            for claim in claims:
                dim = (claim.currency, claim.period_start.isoformat() if claim.period_start else None,
                       claim.period_end.isoformat() if claim.period_end else None, claim.scope, claim.unit)
                dimensions.add(dim)
                values.append({"organisation_number": profile.organisation_number, "status": "available",
                    "value": claim.value, "currency": claim.currency,
                    "period_start": claim.period_start.isoformat() if claim.period_start else None,
                    "period_end": claim.period_end.isoformat() if claim.period_end else None,
                    "scope": claim.scope, "unit": claim.unit,
                    "citations": profile.claim_citations(claim)})
        dimensions_complete = all(all(part is not None for part in dim) for dim in dimensions) if financial_field else True
        comparable = (len(dimensions) == 1 and dimensions_complete and single_fact_per_company
                      and all(item["status"] == "available" for item in values))
        columns.append({"field": canonical_field, "status": "comparable" if comparable else "not_comparable",
                        "values": values, "reason": None if comparable else "missing facts or financial dimensions are missing or differ"})
    return {"status": "complete", "organisation_numbers": list(organisation_numbers), "columns": columns,
            "ranking": None, "derived_deltas": None}


def _missing_status(profile: CompanyProfile, field: str) -> str:
    family = next((claim.field_family for claim in profile.claims if claim.field == field), None)
    family = family or ("financial" if field in {FIELD_ALIASES[item] for item in FINANCIAL_FIELDS}
        else "role" if field.startswith("role.") else "jobs" if field.startswith("job.")
        else "website" if field.startswith("website") else "identity")
    state = profile.section_state(family)
    return "unavailable" if state in {"blocked", "failed", "not_available"} else "unknown"


def verify_proposition(profiles: dict[str, CompanyProfile], *, organisation_number: str, field: str,
                       value: str, currency: str | None = None, period_end: str | None = None,
                       scope: str | None = None, unit: str | None = None) -> dict[str, Any]:
    if len(value) > 500 or len(field) > 80:
        raise QueryError("proposition exceeds the allowed input size")
    if not re.fullmatch(r"\d{9}", organisation_number):
        raise QueryError("verification requires an exact nine-digit organisation number")
    if organisation_number not in profiles:
        return {"status": "unavailable", "organisation_number": organisation_number,
                "field": field, "reason": "company is absent from the canonical dataset", "citations": []}
    profile = profiles[organisation_number]
    field = FIELD_ALIASES.get(field, field)
    if field not in set(FIELD_ALIASES.values()):
        raise QueryError("field is not represented by a canonical claim in the dataset")
    proposed_numeric: Decimal | None = None
    if field in {FIELD_ALIASES[item] for item in FINANCIAL_FIELDS}:
        try:
            proposed_numeric = Decimal(value)
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise QueryError("financial proposition must be a finite numeric value") from exc
        if not proposed_numeric.is_finite() or len(proposed_numeric.as_tuple().digits) > 30 or abs(proposed_numeric.adjusted()) > 18:
            raise QueryError("financial proposition must be a finite numeric value in the supported range")
    candidates = [claim for claim in profile.claims if claim.organisation_number == organisation_number
                  and _claim_matches_field(claim, field) and claim.state == PublicState.AVAILABLE]
    if field in {FIELD_ALIASES[item] for item in FINANCIAL_FIELDS} and not (currency and period_end and scope and unit):
        return {"status": "insufficient_evidence", "organisation_number": organisation_number,
                "field": field, "reason": "financial verification requires exact currency, period_end, scope, and unit dimensions",
                "citations": []}
    if currency is not None or period_end is not None or scope is not None or unit is not None:
        candidates = [claim for claim in candidates if claim.currency == currency
            and (claim.period_end.date().isoformat() if claim.period_end else None) == period_end
            and claim.scope == scope and claim.unit == unit]
    if not candidates:
        state = _missing_status(profile, field)
        return {"status": "unavailable" if state == "unavailable" else "insufficient_evidence",
                "organisation_number": organisation_number, "field": field,
                "reason": f"no comparable available claim; canonical source state is {state}", "citations": []}
    if field in {FIELD_ALIASES[item] for item in FINANCIAL_FIELDS}:
        dims = {(claim.currency, claim.period_start.isoformat() if claim.period_start else None,
                 claim.period_end.isoformat() if claim.period_end else None, claim.scope, claim.unit) for claim in candidates}
        if len(dims) != 1 or any(part is None for part in next(iter(dims))):
            return {"status": "insufficient_evidence", "organisation_number": organisation_number,
                    "field": field, "reason": "multiple or incomplete financial dimensions prevent verification",
                    "citations": []}
    if proposed_numeric is not None:
        exact = [claim for claim in candidates if _decimal_equal(claim.value, proposed_numeric)]
    else:
        exact = [claim for claim in candidates if str(claim.value).casefold() == value.casefold()]
    if exact:
        selected = exact
        status, reason = "supported", "an exact canonical claim supports the proposition"
    elif ((field in SINGLE_VALUE_FIELDS or field in FINANCIAL_FIELDS)
          and len({json.dumps(claim.value, ensure_ascii=False, sort_keys=True, default=str)
                   for claim in candidates}) == 1):
        selected = candidates
        status, reason = "contradicted", "a comparable canonical fact records a different value"
    else:
        selected = []
        status, reason = "insufficient_evidence", "the canonical field may contain multiple valid values"
    citations = {item["evidence_id"]: item for claim in selected for item in profile.claim_citations(claim)}
    return {"status": status, "organisation_number": organisation_number, "field": field,
            "proposed_value": value, "reason": reason, "claim_ids": [claim.claim_id for claim in selected],
            "citations": [citations[key] for key in sorted(citations)]}
