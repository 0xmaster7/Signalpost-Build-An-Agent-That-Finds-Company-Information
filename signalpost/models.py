from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PublicState(StrEnum):
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class InputRow(StrictModel):
    input_ref: str
    row_number: int = Field(ge=1)
    organisation_number: str
    raw: dict[str, Any] = Field(default_factory=dict)


class Evidence(StrictModel):
    evidence_id: str
    source_url: str
    retrieved_at: datetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    extraction_method: str = Field(min_length=1)
    json_pointer: str | None = None
    excerpt: str | None = None
    source_class: str = "official"


class Claim(StrictModel):
    claim_id: str
    organisation_number: str | None = None
    section: str | None = None
    field_family: str | None = None
    subject_id: str | None = None
    field: str
    value: Any
    state: PublicState
    unit: str | None = None
    currency: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    as_of: datetime | None = None
    scope: str | None = None
    verification_rule_id: str | None = None
    verification_score: Decimal | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    source_snapshot_ids: list[str] = Field(default_factory=list)
    confidence: Decimal | None = None

    @model_validator(mode="after")
    def available_claim_needs_evidence(self) -> "Claim":
        if self.state == PublicState.AVAILABLE and not self.evidence_ids:
            raise ValueError("available claims require evidence")
        if self.state == PublicState.AVAILABLE:
            required = (self.organisation_number, self.section, self.field_family, self.subject_id,
                        self.scope, self.verification_rule_id, self.verification_score)
            if any(value is None for value in required) or not self.source_snapshot_ids:
                raise ValueError("available claims require entity, section, family, subject, verification, and snapshot provenance")
        if self.scope is not None and self.scope not in {"legal_entity", "group", "workplace", "person_role", "job", "event"}:
            raise ValueError("unsupported claim scope")
        return self


class SourceSnapshot(StrictModel):
    source_id: str
    source_url: str
    retrieved_at: datetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    http_status: int | None = Field(default=None, ge=100, le=599)
    cache_mode: str = "transient"
    rights_status: str = "unknown"


class RefreshState(StrictModel):
    previous_state_ref: str | None = None
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    next_refresh_at: datetime | None = None
    retained_claim_ids: list[str] = Field(default_factory=list)


class RunError(StrictModel):
    code: str
    message: str
    retryable: bool = False
    source_id: str | None = None


class Operation(StrictModel):
    operation_id: str
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    physical_requests: int = Field(default=0, ge=0)
    logical_requests: int = Field(default=0, ge=0)


class Section(StrictModel):
    state: PublicState
    claims: list[Claim] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class Envelope(StrictModel):
    """Canonical seven-section row. Vendor serialization belongs in adapter.py."""

    input_ref: str
    row_number: int = Field(ge=1)
    organisation_number: str
    terminal_state: PublicState
    sections: dict[str, Section]
    refresh: RefreshState
    operations: list[Operation] = Field(default_factory=list)
    synthesis: dict[str, Any] = Field(default_factory=dict)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    source_snapshots: list[SourceSnapshot] = Field(default_factory=list)
    errors: list[RunError] = Field(default_factory=list)
    batch_id: str
    evidence_cutoff: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def canonical_sections_and_evidence(self) -> "Envelope":
        required = {
            "identity_brand", "accounts_history", "leadership_workplaces",
            "website_owned_profiles", "hiring_activity", "claims_evidence_states", "refresh_changes",
        }
        if set(self.sections) != required:
            raise ValueError("envelope must contain the seven canonical sections")
        evidence_ids = {item.evidence_id for item in self.evidence}
        snapshot_ids = {item.source_id for item in self.source_snapshots}
        for claim in self.claims:
            if claim.state == PublicState.AVAILABLE:
                if claim.organisation_number != self.organisation_number:
                    raise ValueError("available claims must match the envelope organisation number")
                if not claim.evidence_ids or not set(claim.evidence_ids) <= evidence_ids:
                    raise ValueError("available claims must reference present evidence with hashes and extraction methods")
                if not set(claim.source_snapshot_ids) <= snapshot_ids:
                    raise ValueError("available claims must reference present source snapshots")
        return self

    @field_validator("organisation_number")
    @classmethod
    def string_identifier(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("organisation_number must remain a string")
        return value


class RightsRecord(StrictModel):
    source_id: str
    status: str = "unknown"
    attribution: str | None = None
    retention: str = "transient"
    reviewed_at: datetime | None = None


class CacheManifestEntry(StrictModel):
    cache_key: str
    source_id: str
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    fetched_at: datetime
    expires_at: datetime | None = None
    rights_status: str
    storage_path: str | None = None


def empty_section(state: PublicState = PublicState.NOT_AVAILABLE) -> Section:
    return Section(state=state)
