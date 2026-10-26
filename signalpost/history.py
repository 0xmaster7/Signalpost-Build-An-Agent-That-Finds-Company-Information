"""Canonical refresh state and evidence-bounded change detection.

The evaluator's state vocabulary stays in :mod:`signalpost.adapter`; this module
works only with canonical claims and source provenance.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import Claim, Envelope, Evidence, PublicState, SourceSnapshot, approved_frozen_hash_exception

STATE_SCHEMA_VERSION = 1


def _source_policy_version() -> str:
    repository = Path(__file__).resolve().parents[1]
    paths = ("docs/vendor/source-policy.md", "docs/source-rights.md", "docs/sources/brreg.md")
    contents = []
    for relative in paths:
        path = repository / relative
        contents.append((relative, hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"))
    payload = json.dumps(contents, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


SOURCE_POLICY_VERSION = _source_policy_version()


class PriorStateError(ValueError):
    """A supplied prior state is not safe to use for comparison."""


class CompanyState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organisation_number: str
    identity_fingerprint: str
    configuration_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_policy_version: str
    cutoff: datetime
    observed_at: datetime
    claims: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    snapshots: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    coverage: dict[str, dict[str, Any]] = Field(default_factory=dict)
    first_observed: dict[str, str] = Field(default_factory=dict)
    last_observed: dict[str, str] = Field(default_factory=dict)
    snapshot_content_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)


class StateArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    source_policy_version: str
    configuration_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    companies: dict[str, CompanyState]


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.replace(tzinfo=timezone.utc).isoformat()
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _semantic_value(value: Any, field: str | None = None) -> Any:
    if isinstance(value, dict):
        return {str(key): _semantic_value(value[key], str(key)) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        items = [_semantic_value(item, field) for item in value]
        if field in {"industry_codes", "social_links"}:
            return sorted(items, key=lambda item: canonical_json(item))
        return items
    if isinstance(value, str):
        normalized = " ".join(unicodedata.normalize("NFC", value).split())
        if field and any(token in field.casefold() for token in ("website", "url", "domain")):
            raw = normalized if "://" in normalized else "https://" + normalized
            parsed = urlsplit(raw)
            if parsed.hostname:
                host = parsed.hostname.casefold()
                try:
                    parsed_port = parsed.port
                except ValueError:
                    return normalized
                port = f":{parsed_port}" if parsed_port and parsed_port not in {80, 443} else ""
                path = parsed.path.rstrip("/")
                normalized = urlunsplit((parsed.scheme.casefold(), host + port, path, parsed.query, parsed.fragment))
        return normalized
    return value


def stable_snapshot_id(snapshot: dict[str, Any]) -> str:
    """Content identity deliberately excludes retrieval/observation time."""
    return "snapshot:" + sha256_json({"url": snapshot["source_url"], "content_sha256": snapshot["content_sha256"]})


def observation_id(snapshot: dict[str, Any]) -> str:
    return "observation:" + sha256_json({"snapshot_id": stable_snapshot_id(snapshot),
                                          "retrieved_at": snapshot["retrieved_at"]})


def claim_fingerprint(claim: dict[str, Any]) -> str:
    """Hash stable claim semantics; claim IDs and evidence ordering are not facts."""
    return sha256_json({
        "organisation_number": claim.get("organisation_number"),
        "section": claim.get("section"),
        "field_family": claim.get("field_family"),
        "subject_id": claim.get("subject_id"),
        "field": claim.get("field"),
        "value": _semantic_value(claim.get("value"), str(claim.get("field") or "")),
        "state": claim.get("state"),
        "unit": claim.get("unit"),
        "currency": claim.get("currency"),
        "period_start": claim.get("period_start"),
        "period_end": claim.get("period_end"),
        "as_of": claim.get("as_of"),
        "scope": claim.get("scope"),
    })


def _claim_key(claim: dict[str, Any]) -> str:
    # The value is excluded so a changed value is recognized as an update.
    key = {
        "organisation_number": claim.get("organisation_number"),
        "section": claim.get("section"), "field_family": claim.get("field_family"),
        "subject_id": claim.get("subject_id"), "field": claim.get("field"),
        "unit": claim.get("unit"), "currency": claim.get("currency"),
        "period_start": claim.get("period_start"), "period_end": claim.get("period_end"),
        "scope": claim.get("scope"),
        # Filing/version identity is included for financial records. A corrected
        # filing with the same period remains distinguishable from a new period.
        "filing_identity": claim.get("filing_identity"),
    }
    # Role claim rows currently identify their source collection through
    # evidence pointers rather than a person/role subject ID. Retaining the
    # normalized row value in the key avoids collapsing distinct holders.
    if claim.get("field_family") == "role":
        key["role_observed_value"] = _semantic_value(claim.get("value"), str(claim.get("field") or ""))
    return sha256_json(key)


def _comparison_keys(claim: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> list[str]:
    key = _claim_key(claim)
    if claim.get("field") != "website_description":
        return [key]
    support = [evidence[ref] for ref in claim.get("evidence_ids", []) if ref in evidence]
    pages = [item for item in support if item.get("extraction_method") == "website_html_extract_v1"]
    if not pages:
        pages = [item for item in support if item.get("extraction_method") not in {
            "audited_exact_site_identity_proof_v1", "brreg_website_candidate_v1"}]
    urls = {str(item["source_url"]) for item in pages if item.get("source_url")}
    # Page metadata can coexist within the same company. A newly discovered
    # article description must not replace the homepage description in history.
    return sorted({sha256_json({"claim_key": key,
        "source_resource": _semantic_value(url, "website_url")}) for url in urls}) or [key]


def _configuration_fingerprint(config: dict[str, Any]) -> str:
    return sha256_json(config)


def _coverage(envelope: Envelope) -> dict[str, dict[str, Any]]:
    coverage: dict[str, dict[str, Any]] = {}
    for name, section in envelope.sections.items():
        coverage[name] = {"state": section.state.value if section.state else None,
                          "attempt_outcome": section.attempt_outcome,
                          "diagnostics": sorted(section.diagnostics)}
    leadership_diagnostics = envelope.sections["leadership_workplaces"].diagnostics
    def diagnostic_refs(prefix: str) -> list[str]:
        return sorted(value.split(":", 1)[1] for value in leadership_diagnostics
                      if value.startswith(prefix + ":") and ":" in value)
    evidence_ids = {item.evidence_id for item in envelope.evidence}
    role_completeness = [ref for ref in diagnostic_refs("roles_completeness_evidence_id") if ref in evidence_ids]
    workplace_completeness = [ref for ref in diagnostic_refs("workplaces_completeness_evidence_id") if ref in evidence_ids]
    role_claims = [claim for claim in envelope.claims if claim.field_family == "role" and claim.state == PublicState.AVAILABLE]
    workplace_claims = [claim for claim in envelope.claims if claim.field_family == "workplace" and claim.state == PublicState.AVAILABLE]
    section_state = envelope.sections["leadership_workplaces"].state
    coverage["_roles"] = {"complete": bool(role_completeness),
                          "evidence_id": role_completeness[0] if role_completeness else None,
                          "state_evidence_ids": diagnostic_refs("roles_state_evidence_id"),
                          "state": (PublicState.AVAILABLE.value if role_claims else
                                    PublicState.NOT_AVAILABLE.value if role_completeness else
                                    section_state.value if section_state else None)}
    coverage["_workplaces"] = {"complete": bool(workplace_completeness),
                               "evidence_id": workplace_completeness[0] if workplace_completeness else None,
                               "evidence_ids": workplace_completeness,
                               "state_evidence_ids": diagnostic_refs("subunits_state_evidence_id"),
                               "state": (PublicState.AVAILABLE.value if workplace_claims else
                                         PublicState.NOT_AVAILABLE.value if workplace_completeness else
                                         section_state.value if section_state else None)}
    website = envelope.sections["website_owned_profiles"]
    coverage["_website"] = {"complete": (website.attempt_outcome == "completed"
                                           and website.state == PublicState.AVAILABLE),
                             "execution_state": website.attempt_outcome,
                             "crawl_state": website.state.value if website.state else None}
    return coverage


def company_state(envelope: Envelope, config_fingerprint: str,
                  previous: CompanyState | None = None) -> CompanyState:
    claims = [claim.model_dump(mode="json") for claim in envelope.claims]
    for claim in claims:
        claim["evidence_ids"] = sorted(claim.get("evidence_ids", []))
        claim["source_snapshot_ids"] = sorted(claim.get("source_snapshot_ids", []))
    evidence = [item.model_dump(mode="json") for item in envelope.evidence]
    for item in evidence:
        item["source_snapshot_ids"] = sorted(item.get("source_snapshot_ids", []))
    evidence = sorted(evidence, key=lambda item: item["evidence_id"])
    snapshots = sorted((item.model_dump(mode="json") for item in envelope.source_snapshots), key=lambda item: item["source_id"])
    # Retain only available claims in the factual state. Non-available outcomes
    # are represented by coverage and errors, never as absent factual values.
    claims = [claim for claim in claims if claim.get("state") == PublicState.AVAILABLE.value]
    # Collapse semantically duplicate observations while retaining all evidence
    # references, so source ordering and duplicate rows cannot create events.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        grouped.setdefault(claim_fingerprint(claim), []).append(claim)
    canonical_claims = []
    for fingerprint, copies in sorted(grouped.items()):
        merged = dict(sorted(copies, key=lambda item: str(item.get("claim_id")))[0])
        merged["evidence_ids"] = sorted({ref for item in copies for ref in item.get("evidence_ids", [])})
        merged["source_snapshot_ids"] = sorted({ref for item in copies for ref in item.get("source_snapshot_ids", [])})
        canonical_claims.append(merged)
    claims = canonical_claims
    claim_ids: dict[str, list[str]] = {}
    for claim in claims:
        claim_ids.setdefault(claim_fingerprint(claim), []).append(str(claim.get("claim_id", "")))
    observed_at = max((item["retrieved_at"] for item in evidence), default=envelope.created_at.isoformat())
    prior_first = previous.first_observed if previous else {}
    first_observed = {fingerprint: prior_first.get(fingerprint, observed_at) for fingerprint in claim_ids}
    last_observed = {fingerprint: observed_at for fingerprint in claim_ids}
    content_ids = sorted({stable_snapshot_id(item) for item in snapshots})
    observations = sorted({observation_id(item) for item in snapshots})
    return CompanyState(organisation_number=envelope.organisation_number,
        identity_fingerprint=sha256_json({"organisation_number": envelope.organisation_number}),
        configuration_fingerprint=config_fingerprint, source_policy_version=SOURCE_POLICY_VERSION,
        cutoff=envelope.evidence_cutoff,
        observed_at=max((item.retrieved_at for item in envelope.evidence), default=envelope.created_at),
        claims=claims, evidence=evidence, snapshots=snapshots,
        errors=[item.model_dump(mode="json") for item in envelope.errors],
        coverage=_coverage(envelope), first_observed=first_observed, last_observed=last_observed,
        snapshot_content_ids=content_ids, observation_ids=observations)


def validate_artifact(raw: Any) -> StateArtifact:
    try:
        artifact = StateArtifact.model_validate(raw)
    except (ValidationError, TypeError, ValueError) as exc:
        raise PriorStateError(f"prior state schema or structure is invalid ({type(exc).__name__})") from exc
    if artifact.schema_version != STATE_SCHEMA_VERSION:
        raise PriorStateError(f"unsupported prior state schema version {artifact.schema_version}")
    if artifact.source_policy_version != SOURCE_POLICY_VERSION:
        raise PriorStateError("prior state source policy version is incompatible")
    for org, company in artifact.companies.items():
        if org != company.organisation_number or company.identity_fingerprint != sha256_json({"organisation_number": org}):
            raise PriorStateError("prior state company identity fingerprint does not match its key")
        if company.source_policy_version != artifact.source_policy_version or company.configuration_fingerprint != artifact.configuration_fingerprint:
            raise PriorStateError("prior state company source/config identity is incompatible")
        if company.cutoff.tzinfo is None or company.observed_at.tzinfo is None:
            raise PriorStateError("prior state cutoff and observation timestamps must include a timezone")
        try:
            claims = [Claim.model_validate(item) for item in company.claims]
            evidence = [Evidence.model_validate(item) for item in company.evidence]
            snapshots = [SourceSnapshot.model_validate(item) for item in company.snapshots]
        except (ValidationError, TypeError, ValueError) as exc:
            raise PriorStateError(f"prior state claim or provenance structure is invalid ({type(exc).__name__})") from exc
        if any(claim.organisation_number != org for claim in claims):
            raise PriorStateError("prior state contains a claim for another organisation")
        evidence_by_id = {item.evidence_id: item for item in evidence}
        snapshots_by_id = {item.source_id: item for item in snapshots}
        if len(evidence_by_id) != len(evidence) or len(snapshots_by_id) != len(snapshots):
            raise PriorStateError("prior state has duplicate evidence or snapshot identifiers")
        if any(item.retrieved_at.tzinfo is None for item in evidence) or any(item.retrieved_at.tzinfo is None for item in snapshots):
            raise PriorStateError("prior state provenance timestamps must include a timezone")
        expected_snapshot_ids = sorted({stable_snapshot_id(item.model_dump(mode="json")) for item in snapshots})
        expected_observation_ids = sorted({observation_id(item.model_dump(mode="json")) for item in snapshots})
        if company.snapshot_content_ids != expected_snapshot_ids or company.observation_ids != expected_observation_ids:
            raise PriorStateError("prior state snapshot or observation identities do not match source provenance")
        for claim in claims:
            if claim.state != PublicState.AVAILABLE:
                raise PriorStateError("prior state factual claim is not available")
            if not set(claim.evidence_ids) <= evidence_by_id.keys() or not set(claim.source_snapshot_ids) <= snapshots_by_id.keys():
                raise PriorStateError("prior state claim references missing evidence or snapshots")
            for evidence_id in claim.evidence_ids:
                item = evidence_by_id[evidence_id]
                if item.subject_organisation_number != org or not set(item.source_snapshot_ids) <= snapshots_by_id.keys():
                    raise PriorStateError("prior state evidence is not anchored to the company or a present snapshot")
                if not set(item.source_snapshot_ids) <= set(claim.source_snapshot_ids):
                    raise PriorStateError("prior state claim does not retain its evidence snapshots")
                for snapshot_id in item.source_snapshot_ids:
                    snapshot = snapshots_by_id[snapshot_id]
                    if item.source_url != snapshot.source_url or (item.content_sha256 != snapshot.content_sha256 and not approved_frozen_hash_exception(item, snapshot)):
                        raise PriorStateError("prior state evidence does not match its source snapshot")
        for item in evidence:
            if item.subject_organisation_number != org or not item.source_snapshot_ids or not set(item.source_snapshot_ids) <= snapshots_by_id.keys():
                raise PriorStateError("prior state evidence is not anchored to its company snapshots")
            for snapshot_id in item.source_snapshot_ids:
                snapshot = snapshots_by_id[snapshot_id]
                if item.source_url != snapshot.source_url or (item.content_sha256 != snapshot.content_sha256 and not approved_frozen_hash_exception(item, snapshot)):
                    raise PriorStateError("prior state evidence does not match its source snapshot")
        coverage_evidence_ids = {ref for coverage in company.coverage.values()
                                 for ref in ([coverage.get("evidence_id")] + list(coverage.get("evidence_ids", []))
                                             + list(coverage.get("state_evidence_ids", []))) if ref}
        if not coverage_evidence_ids <= evidence_by_id.keys():
            raise PriorStateError("prior state coverage references missing source evidence")
        expected_fingerprints = {claim_fingerprint(item.model_dump(mode="json")) for item in claims}
        if not expected_fingerprints <= company.first_observed.keys() or not expected_fingerprints <= company.last_observed.keys():
            raise PriorStateError("prior state observation times do not cover its factual claims")
        for timestamp in [*company.first_observed.values(), *company.last_observed.values()]:
            try:
                parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            except ValueError as exc:
                raise PriorStateError("prior state first/last observation timestamp is malformed") from exc
            if parsed.tzinfo is None:
                raise PriorStateError("prior state first/last observation timestamps must include a timezone")
    return artifact


def artifact_payload(companies: dict[str, CompanyState], config_fingerprint: str) -> dict[str, Any]:
    return {"schema_version": STATE_SCHEMA_VERSION, "source_policy_version": SOURCE_POLICY_VERSION,
            "configuration_fingerprint": config_fingerprint,
            "companies": {org: company.model_dump(mode="json") for org, company in sorted(companies.items())}}


def artifact_ref(payload: dict[str, Any]) -> str:
    return "sha256:" + sha256_json(payload)


def merge_prior_facts(current: CompanyState, previous: CompanyState | None) -> CompanyState:
    """Retain prior facts unless the current family proves a complete removal."""
    if previous is None:
        return current
    if current.organisation_number != previous.organisation_number:
        raise PriorStateError("cannot merge history from another organisation")
    original_current = list(current.claims)
    current_by_semantics = {sha256_json({k: v for k, v in claim.items()
        if k not in {"evidence_ids", "source_snapshot_ids", "claim_id"}}): claim for claim in original_current}
    prior_by_semantics = {sha256_json({k: v for k, v in claim.items()
        if k not in {"evidence_ids", "source_snapshot_ids", "claim_id"}}): claim for claim in previous.claims}
    retained = dict(current_by_semantics)
    for semantic_id, claim in prior_by_semantics.items():
        family = claim.get("field_family")
        section = str(claim.get("section") or "")
        section_coverage = current.coverage.get(section, {})
        if claim.get("verification_rule_id") == "nav_exact_employer_job_v1":
            conclusive = True
        elif family == "role":
            conclusive = current.coverage.get("_roles", {}).get("complete", False)
        elif family == "workplace":
            conclusive = current.coverage.get("_workplaces", {}).get("complete", False)
        elif family in {"financial", "financial_record_metadata", "workforce"}:
            conclusive = False  # Keep submitted/restated periods as history.
        elif family in {"jobs", "public_activity"}:
            conclusive = False  # Missing web observations never prove closure.
        else:
            conclusive = (section_coverage.get("state") == PublicState.AVAILABLE.value
                          and section_coverage.get("attempt_outcome") in {None, "completed"})
        if semantic_id not in retained and not conclusive:
            retained[semantic_id] = claim
    current_fingerprints = {claim_fingerprint(item) for item in original_current}
    current.claims = sorted(retained.values(), key=lambda item: (str(item.get("field_family")),
        str(item.get("field")), sha256_json(item.get("value")), str(item.get("period_start")), str(item.get("period_end"))))
    all_fingerprints = {claim_fingerprint(item) for item in current.claims}
    observed = current.observed_at.isoformat()
    current.first_observed = {fingerprint: previous.first_observed.get(fingerprint,
        current.first_observed.get(fingerprint, observed)) for fingerprint in all_fingerprints}
    current.last_observed = {fingerprint: (current.last_observed.get(fingerprint, observed)
        if fingerprint in current_fingerprints else previous.last_observed.get(fingerprint, observed))
        for fingerprint in all_fingerprints}
    evidence_by_id = {item["evidence_id"]: item for item in [*previous.evidence, *current.evidence]}
    snapshots_by_id = {item["source_id"]: item for item in [*previous.snapshots, *current.snapshots]}
    evidence_ids = {ref for claim in current.claims for ref in claim.get("evidence_ids", [])}
    evidence_ids.update(ref for coverage in current.coverage.values()
        for ref in ([coverage.get("evidence_id")] + list(coverage.get("evidence_ids", []))
                    + list(coverage.get("state_evidence_ids", []))) if ref)
    snapshot_ids = {ref for claim in current.claims for ref in claim.get("source_snapshot_ids", [])}
    snapshot_ids.update(ref for evidence_id in evidence_ids if evidence_id in evidence_by_id
                        for ref in evidence_by_id[evidence_id].get("source_snapshot_ids", []))
    current.evidence = sorted((evidence_by_id[key] for key in evidence_ids if key in evidence_by_id),
                              key=lambda item: item["evidence_id"])
    current.snapshots = sorted((snapshots_by_id[key] for key in snapshot_ids if key in snapshots_by_id),
                               key=lambda item: item["source_id"])
    current.snapshot_content_ids = sorted({stable_snapshot_id(item) for item in current.snapshots})
    current.observation_ids = sorted({observation_id(item) for item in current.snapshots})
    return current


def _evidence_refs(claim: dict[str, Any] | None, evidence: list[dict[str, Any]],
                   extra_ids: list[str] | None = None) -> list[dict[str, Any]]:
    if not claim and not extra_ids:
        return []
    ids = set(extra_ids or [])
    if claim:
        ids.update(claim.get("evidence_ids", []))
    by_id = {item.get("evidence_id"): item for item in evidence}
    return sorted((by_id[item] for item in ids if item in by_id), key=lambda item: item["evidence_id"])


def _snapshot_refs(evidence: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = {ref for item in evidence for ref in item.get("source_snapshot_ids", [])}
    by_id = {item.get("source_id"): item for item in snapshots}
    return sorted((by_id[item] for item in ids if item in by_id), key=lambda item: item["source_id"])


def _event_type(old: dict[str, Any] | None, new: dict[str, Any] | None) -> str:
    claim = new or old or {}
    family = claim.get("field_family")
    field = str(claim.get("field") or "")
    if family == "financial_record_metadata" and old is None:
        return "new_filing"
    if family == "financial_record_metadata" and new is not None and old is not None:
        return "corrected_filing"
    if family == "financial" and old is None:
        return "new_filing"
    if family == "financial" and old is not None and new is not None:
        return "corrected_filing"
    if family == "role":
        if field == "role.name":
            return "new_role" if old is None else "ended_role" if new is None else "claim_changed"
        return "claim_changed"
    if family == "workplace":
        if field == "workplace.organisasjonsnummer":
            return "new_workplace" if old is None else "closed_workplace" if new is None else "claim_changed"
        return "claim_changed"
    if family == "jobs":
        if new is None:
            return "claim_changed"  # Disappearance from a crawl is not proof of closure.
        if field == "job_status":
            status = str(new.get("value", "")).casefold()
            if status == "closed":
                return "closed_job" if old is not None else "claim_changed"
            if old is None and status in {"open", "active"}:
                return "new_job"
        if old is None:
            return "claim_changed"
    if family == "public_activity" and old is None:
        return "new_activity" if field == "activity_headline" else "claim_changed"
    if field in {"website", "website_url"}:
        return "website_changed"
    if field in {"name", "legal_name", "brand_name"}:
        return "brand_changed"
    return "claim_changed"


def _effective_at(claim: dict[str, Any] | None) -> str | None:
    if not claim:
        return None
    value = claim.get("as_of") or claim.get("period_end")
    if value is None and str(claim.get("field") or "").endswith((".from_date", ".to_date", "source_published_at")):
        value = claim.get("value")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def compare_states(previous: CompanyState | None, current: CompanyState, *, cutoff: datetime,
                   previous_ref: str | None, current_ref: str) -> list[dict[str, Any]]:
    if previous is None:
        return []
    if previous.organisation_number != current.organisation_number:
        raise PriorStateError("refresh comparison requires the same exact organisation number")
    old_claims: dict[str, list[dict[str, Any]]] = {}
    new_claims: dict[str, list[dict[str, Any]]] = {}
    previous_evidence = {item["evidence_id"]: item for item in previous.evidence}
    current_evidence = {item["evidence_id"]: item for item in current.evidence}
    previous_fingerprints = {claim_fingerprint(item) for item in previous.claims}
    for item in previous.claims:
        for key in _comparison_keys(item, previous_evidence):
            old_claims.setdefault(key, []).append(item)
    for item in current.claims:
        for key in _comparison_keys(item, current_evidence):
            new_claims.setdefault(key, []).append(item)
    # Do not report a transition whose source effective/publication date is
    # after the run cutoff. Retrieval-only changes are absent from fingerprints.
    events: list[dict[str, Any]] = []
    for key in sorted(old_claims.keys() | new_claims.keys()):
        old_group, new_group = old_claims.get(key, []), new_claims.get(key, [])
        old_by_fp = {claim_fingerprint(item): item for item in old_group}
        new_by_fp = {claim_fingerprint(item): item for item in new_group}
        added = [new_by_fp[fp] for fp in sorted(new_by_fp.keys() - old_by_fp.keys())]
        removed = [old_by_fp[fp] for fp in sorted(old_by_fp.keys() - new_by_fp.keys())]
        transitions: list[tuple[dict[str, Any] | None, dict[str, Any] | None]] = []
        if not old_group:
            transitions.extend((None, item) for item in added)
        elif not new_group:
            transitions.extend((item, None) for item in removed)
        elif added:
            baseline = sorted(old_group, key=claim_fingerprint)[-1]
            transitions.extend((baseline, item) for item in added)
        elif removed:
            transitions.extend((item, None) for item in removed)
        for old, new in transitions:
            candidate = new or old or {}
            effective = _effective_at(candidate)
            if effective:
                try:
                    effective_dt = datetime.fromisoformat(str(effective).replace("Z", "+00:00"))
                    if effective_dt.tzinfo is None:
                        effective_dt = effective_dt.replace(tzinfo=timezone.utc)
                    if effective_dt.astimezone(timezone.utc) > cutoff:
                        continue
                except ValueError:
                    pass
            if old is None and new is not None:
                if new.get("field") == "website_description" and claim_fingerprint(new) in previous_fingerprints:
                    continue  # Another page corroborates an already observed description.
                kind = _event_type(None, new)
                confirmation = None
            elif new is None and old is not None:
                kind = _event_type(old, None)
                family = old.get("field_family")
                confirmation = None
                if family == "role":
                    confirmation = current.coverage.get("_roles", {})
                elif family == "workplace":
                    confirmation = current.coverage.get("_workplaces", {})
                if family in {"role", "workplace"}:
                    if (family == "role" and old.get("field") != "role.name") or (
                            family == "workplace" and old.get("field") != "workplace.organisasjonsnummer"):
                        continue
                    confirmation_ids = confirmation.get("evidence_ids") or ([confirmation.get("evidence_id")] if confirmation else [])
                    if not confirmation or not confirmation.get("complete") or not confirmation_ids:
                        continue
                    confirmation_evidence = {item.get("evidence_id") for item in current.evidence}
                    if not set(confirmation_ids) <= confirmation_evidence:
                        continue
                if family == "jobs" or family not in {"role", "workplace"}:
                    continue
            else:
                kind = _event_type(old, new)
                confirmation = None
            old_fingerprint = claim_fingerprint(old) if old else None
            new_fingerprint = claim_fingerprint(new) if new else None
            previous_evidence_refs = _evidence_refs(old, previous.evidence)
            current_extra_evidence = (confirmation.get("evidence_ids") or [confirmation.get("evidence_id")]) if confirmation else []
            current_evidence_refs = _evidence_refs(new, current.evidence, current_extra_evidence)
            events.append({
                "event_id": "change:" + sha256_json({"org": current.organisation_number, "type": kind,
                    "key": key, "old": old_fingerprint, "new": new_fingerprint, "cutoff": cutoff}),
                "type": kind, "organisation_number": current.organisation_number,
                "field": (new or old).get("field"),
                "old_value": old.get("value") if old else None,
                "new_value": new.get("value") if new else None,
                "effective_at": effective, "observed_at": current.observed_at.isoformat(),
                "previous_state_ref": previous_ref, "current_state_ref": current_ref,
                "previous_claim_fingerprint": old_fingerprint,
                "current_claim_fingerprint": new_fingerprint,
                "previous_evidence": previous_evidence_refs,
                "current_evidence": current_evidence_refs,
                "previous_source_snapshots": _snapshot_refs(previous_evidence_refs, previous.snapshots),
                "current_source_snapshots": _snapshot_refs(current_evidence_refs, current.snapshots),
                "removal_confirmation_evidence_ids": ((confirmation.get("evidence_ids") or [confirmation.get("evidence_id")])
                    if confirmation else []),
                "provenance_complete": bool((old is None or old.get("evidence_ids")) and
                    (new is None or new.get("evidence_ids")) and
                    (new is not None or (confirmation and (confirmation.get("evidence_ids") or confirmation.get("evidence_id"))))),
            })
    evidence_lookup = {item.get("evidence_id"): item for item in current.evidence}
    for section in sorted(set(previous.coverage) & set(current.coverage)):
        old_status = previous.coverage[section].get("state")
        current_coverage = current.coverage[section]
        new_status = current_coverage.get("state")
        if old_status != PublicState.AVAILABLE.value or new_status not in {PublicState.FAILED.value, PublicState.BLOCKED.value}:
            continue
        evidence_ids = list(current_coverage.get("state_evidence_ids", []))
        for diagnostic in current_coverage.get("diagnostics", []):
            _, separator, evidence_id = str(diagnostic).partition(":")
            if separator and evidence_id in evidence_lookup:
                evidence_ids.append(evidence_id)
        if not evidence_ids:
            continue
        old_claims = [item for item in previous.claims if item.get("section") == section]
        prior_evidence = sorted({ref for item in old_claims for ref in item.get("evidence_ids", [])})
        prior_evidence_refs = _evidence_refs(None, previous.evidence, prior_evidence)
        current_evidence_refs = _evidence_refs(None, current.evidence, sorted(set(evidence_ids)))
        events.append({
            "event_id": "change:" + sha256_json({"org": current.organisation_number,
                "type": "source_became_unavailable", "section": section, "state": new_status, "cutoff": cutoff}),
            "type": "source_became_unavailable", "organisation_number": current.organisation_number,
            "section": section, "field": None, "old_value": old_status, "new_value": new_status,
            "effective_at": None, "observed_at": current.observed_at.isoformat(),
            "previous_state_ref": previous_ref, "current_state_ref": current_ref,
            "previous_claim_fingerprint": None, "current_claim_fingerprint": None,
            "previous_evidence": prior_evidence_refs,
            "current_evidence": current_evidence_refs,
            "previous_source_snapshots": _snapshot_refs(prior_evidence_refs, previous.snapshots),
            "current_source_snapshots": _snapshot_refs(current_evidence_refs, current.snapshots),
            "removal_confirmation_evidence_ids": [],
            "provenance_complete": bool(prior_evidence and evidence_ids),
        })
    # Duplicate input rows receive identical events, but event IDs are stable;
    # this sorting also makes output independent of claim/evidence ordering.
    return sorted({item["event_id"]: item for item in events}.values(), key=lambda item: item["event_id"])
