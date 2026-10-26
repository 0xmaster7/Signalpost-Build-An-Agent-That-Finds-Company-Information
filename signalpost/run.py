from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import fields
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .adapter import to_evaluator
from .inputs import load_input, normalize_org_number, stream_registry_matches
from .models import (Claim, Envelope, Evidence, PublicState, RefreshState, RunError, Section, SourceSnapshot,
                     empty_section, validate_batch_publication_graph)
from .operations import (Budget, CheckpointStore, Opportunity, OpportunityFailed, OpportunityScheduler,
                         OrderedAtomicWriter, RunBudget, publish_paired_artifacts)
from .network import NetworkGateway, StructuredLogger, registered_domain, request_company_scope
from .brreg import BrregResult, RIGHTS, cutoff_identity, fetch_company
from .history import (SOURCE_POLICY_VERSION, CompanyState, PriorStateError, artifact_payload, artifact_ref, canonical_json,
                      compare_states, company_state, merge_prior_facts, validate_artifact, sha256_json)
from .synthesis import synthesize


def _website_profile(org: str, *, live_result: Any | None = None, frozen: dict[str, Any] | None = None,
                     frozen_sha: str | None = None, frozen_source_url: str | None = None) -> dict[str, Any]:
    """Build exact-org website inputs without promoting the registry URL itself."""
    profile: dict[str, Any] = {"organisation_number": org}
    if live_result:
        identity = live_result.observations.get("identity_profile") or {}
        profile.update(identity)
        profile["website_candidates"] = list(live_result.observations.get("website_candidates", []))
        person_evidence = {e.evidence_id for e in live_result.evidence if e.extraction_method == "brreg_role_name_join_v1"}
        profile["registered_roles"] = [str(claim.value) for claim in live_result.claims
            if claim.section == "leadership_workplaces" and claim.field == "role.name" and claim.scope == "person_role" and isinstance(claim.value, str)
            and person_evidence.intersection(claim.evidence_ids)]
        parent = identity.get("parent_organisation_number") or live_result.observations.get("parent_organisation_number")
        if parent:
            profile["related_organisation_numbers"] = [str(parent)]
    if frozen and normalize_org_number(frozen.get("organisation_number", frozen.get("orgnr")))[0] == org:
        name = frozen.get("name") or frozen.get("legal_name") or frozen.get("navn") or frozen.get("Navn")
        if not profile.get("name") and name:
            profile["name"] = name
        if not profile.get("legal_form"):
            form = (frozen.get("legal_form") or frozen.get("organisasjonsform") or frozen.get("organisationsform")
                    or frozen.get("organisasjonsform.kode") or frozen.get("Organisasjonsform.kode"))
            profile["legal_form"] = form.get("kode") if isinstance(form, dict) else form
        profile.setdefault("historical_names", frozen.get("historical_names") or [])
        if str(profile.get("legal_form") or "").upper() == "ENK":
            profile["business_address"] = None
            profile["postal_address"] = None
        else:
            profile.setdefault("business_address", frozen.get("business_address") or frozen.get("forretningsadresse") or frozen.get("registered_address") or {})
            profile.setdefault("postal_address", frozen.get("postal_address") or frozen.get("postadresse") or {})
        row_hash = frozen.get("__signalpost_snapshot_row_sha256")
        if not row_hash:
            row_hash = hashlib.sha256(json.dumps({k:v for k,v in frozen.items() if not k.startswith("__signalpost_")},
                ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        source_url = frozen.get("source_url") or frozen_source_url
        raw_website = frozen.get("website") or frozen.get("website_url") or frozen.get("hjemmeside") or frozen.get("Hjemmeside")
        if raw_website and source_url and frozen_sha:
            profile.setdefault("website_candidates", []).append({"raw": raw_website, "source": "registry_frozen",
                "source_url": source_url, "content_sha256": row_hash,
                "evidence_id": f"{org}:frozen-website-candidate:{row_hash[:12]}",
                "source_snapshot_id": f"registry_snapshot:{frozen_sha[:16]}",
                "source_snapshot_sha256": frozen_sha})
        elif raw_website:
            profile.setdefault("website_candidate_without_source_url", True)
    return profile


def _find_default_input() -> Path | None:
    for candidate in ("signalpost_input.jsonl", "input.jsonl", "batch.jsonl"):
        path = Path(candidate)
        if path.exists():
            return path
    return None


def _envelope(row: Any, fixture: dict[str, dict[str, Any]], batch_id: str, cutoff: datetime, previous: dict[str, Any],
              *, registry_as_of: str | None = None, registry_source_url: str | None = None) -> Envelope:
    sections = {name: empty_section() for name in (
        "identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
        "hiring_activity", "claims_evidence_states", "refresh_changes")}
    sections["website_owned_profiles"] = Section(state=None, attempt_outcome="not_attempted")
    sections["hiring_activity"] = Section(state=None, attempt_outcome="not_attempted")
    claims: list[Claim] = []
    evidence: list[Evidence] = []
    snapshots: list[SourceSnapshot] = []
    errors: list[RunError] = []
    state = PublicState.FAILED
    normalized, checksum_ok = normalize_org_number(row.organisation_number)
    if not row.organisation_number or len(normalized) != 9 or not normalized.isdigit() or (not checksum_ok and row.organisation_number not in fixture):
        errors.append(RunError(code="INPUT_INVALID", message="A nine-digit organisation number with a valid mod-11 checksum is required."))
    elif row.organisation_number not in fixture:
        errors.append(RunError(code="REGISTRY_SNAPSHOT_MISS", message="No matching frozen registry row. Use an authoritative snapshot containing this company or enable the approved live BRREG fallback."))
    else:
        record = fixture[row.organisation_number]
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        fetched = datetime.now(timezone.utc)
        source_url = str(record.get("source_url") or registry_source_url or "urn:signalpost:registry-fixture")
        snapshot_id = f"registry_fixture:{row.organisation_number}:{digest[:16]}"
        evidence.append(Evidence(evidence_id=f"{row.input_ref}:registry", source_url=source_url,
                                 retrieved_at=fetched, content_sha256=digest,
                                 extraction_method="frozen_registry_fixture", json_pointer="/",
                                 subject_organisation_number=row.organisation_number,
                                 source_snapshot_ids=[snapshot_id]))
        snapshots.append(SourceSnapshot(source_id=snapshot_id, source_url=source_url,
                                        retrieved_at=fetched, content_sha256=digest, rights_status="fixture"))
        name = str(record.get("name") or record.get("legal_name") or record.get("navn") or record.get("Navn") or "")
        snapshot_date_raw = record.get("as_of") or record.get("snapshot_as_of") or registry_as_of
        snapshot_date = _cutoff_datetime(snapshot_date_raw) if snapshot_date_raw else None
        if snapshot_date_raw and (snapshot_date is None or snapshot_date > cutoff):
            state = PublicState.NOT_AVAILABLE
            errors.append(RunError(code="REGISTRY_SNAPSHOT_DATE_EXCLUDED",
                message="Frozen identity was withheld because the supplied snapshot date is invalid or after the evidence cutoff."))
        elif name:
            claim = Claim(claim_id=f"{row.input_ref}:legal_name", organisation_number=row.organisation_number,
                          section="identity_brand", field_family="identity", subject_id=row.organisation_number,
                          field="legal_name", value=name, state=PublicState.AVAILABLE, scope="legal_entity", as_of=snapshot_date,
                          verification_rule_id="frozen_registry_row_exact_org_v1", verification_score="1.0",
                          evidence_ids=[evidence[0].evidence_id], source_snapshot_ids=[snapshot_id])
            claims.append(claim)
            sections["identity_brand"] = Section(state=PublicState.AVAILABLE, claims=[claim])
            sections["claims_evidence_states"] = Section(state=PublicState.AVAILABLE, claims=[claim])
            state = PublicState.AVAILABLE
        else:
            errors.append(RunError(code="REGISTRY_FIXTURE_INCOMPLETE", message="Registry fixture row has no legal name."))
    return Envelope(input_ref=row.input_ref, row_number=row.row_number,
                    organisation_number=row.organisation_number, terminal_state=state,
                    sections=sections, refresh=RefreshState(
                        previous_state_ref=previous.get(row.organisation_number, {}).get("state_ref"),
                        last_attempt_at=datetime.now(timezone.utc)), claims=claims, evidence=evidence,
                    source_snapshots=snapshots, errors=errors, batch_id=batch_id, evidence_cutoff=cutoff)


def _live_envelope(row: Any, result: Any, batch_id: str, cutoff: datetime, previous: dict[str, Any],
                   frozen_match: bool = False) -> Envelope:
    sections = {name: empty_section() for name in (
        "identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
        "hiring_activity", "claims_evidence_states", "refresh_changes")}
    sections["website_owned_profiles"] = Section(state=None, attempt_outcome="not_attempted")
    sections["hiring_activity"] = Section(state=None, attempt_outcome="not_attempted")
    normalized, checksum_ok = normalize_org_number(row.organisation_number)
    claims, evidence, snapshots = list(result.claims), list(result.evidence), list(result.snapshots)
    errors = list(result.errors)
    if len(normalized) != 9 or not normalized.isdigit() or (not checksum_ok and not frozen_match):
        errors.append(RunError(code="INPUT_INVALID", message="A nine-digit organisation number with a valid mod-11 checksum is required."))
        terminal = PublicState.FAILED
    else:
        for name in ("identity_brand", "accounts_history", "leadership_workplaces", *(
                ["hiring_activity"] if "hiring_activity" in result.section_states else [])):
            diagnostics = []
            observation = result.observations
            if name == "identity_brand" and observation.get("identity_state_evidence_id"):
                diagnostics.append(f"identity_state_evidence:{observation['identity_state_evidence_id']}")
            if name == "accounts_history" and observation.get("accounts_state_evidence_id"):
                diagnostics.append(f"accounts_state_evidence:{observation['accounts_state_evidence_id']}")
            if name == "leadership_workplaces":
                for key in ("roles_state_evidence_id", "subunits_state_evidence_id"):
                    if observation.get(key): diagnostics.append(f"{key}:{observation[key]}")
                if observation.get("roles_completeness_evidence_id"):
                    diagnostics.append(f"roles_completeness_evidence_id:{observation['roles_completeness_evidence_id']}")
                completeness_ids = observation.get("workplaces_completeness_evidence_ids") or (
                    [observation["workplaces_completeness_evidence_id"]]
                    if observation.get("workplaces_completeness_evidence_id") else [])
                diagnostics.extend(f"workplaces_completeness_evidence_id:{item}" for item in completeness_ids)
                diagnostics.append(f"ceo_state:{observation.get('ceo_state', 'unknown')}")
                if not observation.get("workplaces_complete"):
                    diagnostics.append("workplace_coverage:partial_or_unavailable")
            sections[name] = Section(state=result.section_states[name], claims=[c for c in claims if c.section == name], diagnostics=diagnostics)
        sections["claims_evidence_states"] = Section(state=PublicState.AVAILABLE if claims else result.terminal_state,
                                                       claims=list(claims))
        terminal = result.terminal_state
    return Envelope(input_ref=row.input_ref, row_number=row.row_number,
                    organisation_number=row.organisation_number, terminal_state=terminal,
                    sections=sections, refresh=RefreshState(
                        previous_state_ref=previous.get(row.organisation_number, {}).get("state_ref"),
                        last_attempt_at=datetime.now(timezone.utc)), synthesis={"brreg_observations": result.observations},
                    claims=claims, evidence=evidence, source_snapshots=snapshots, errors=errors,
                    batch_id=batch_id, evidence_cutoff=cutoff)


def _attach_frozen_baseline(envelope: Envelope, record: dict[str, Any] | None, snapshot_sha: str | None,
                            cutoff: datetime, snapshot_as_of: str | None = None,
                            source_url: str | None = None) -> Envelope:
    """Retain exact frozen identity separately and use it if live data is post-cutoff/unavailable."""
    if not record or normalize_org_number(record.get("organisation_number", record.get("orgnr")))[0] != envelope.organisation_number:
        envelope.synthesis["baseline_identity"] = {"state": "not_available", "reason": "snapshot_miss"}
        return envelope
    as_of = record.get("as_of") or record.get("snapshot_as_of") or snapshot_as_of
    name = record.get("name") or record.get("legal_name") or record.get("navn")
    legal_form = record.get("legal_form") or record.get("organisationsform")
    if isinstance(legal_form, dict):
        legal_form = legal_form.get("kode")
    source_url = record.get("source_url") or source_url or (f"urn:signalpost:frozen-registry:{snapshot_sha}" if snapshot_sha else "urn:signalpost:frozen-registry")
    safe_baseline = {key: value for key, value in {"organisation_number": envelope.organisation_number, "name": name,
                    "legal_form": legal_form, "as_of": as_of, "source_url": source_url,
                    "content_sha256": snapshot_sha}.items() if value is not None}
    envelope.synthesis["baseline_identity"] = safe_baseline
    envelope.synthesis["live_identity_observation"] = {
        "fields": {claim.field: claim.value for claim in envelope.claims if claim.section == "identity_brand"},
        "retrieved_at": max((e.retrieved_at.isoformat() for e in envelope.evidence if e.source_url.startswith("https://data.brreg.no/enhetsregisteret/")), default=None),
    }
    if not as_of or not snapshot_sha:
        return envelope
    live_time = envelope.synthesis["live_identity_observation"].get("retrieved_at")
    selected = cutoff_identity({"name": name, "as_of": as_of, "source_url": source_url},
                               {"name": next((c.value for c in envelope.claims if c.section == "identity_brand" and c.field == "name"), None),
                                "retrieved_at": live_time, "source_url": "https://data.brreg.no/enhetsregisteret/api"} if live_time else None,
                               cutoff)
    envelope.synthesis["cutoff_identity_source"] = selected.get("source") if selected else None
    if selected and selected.get("source") == "frozen" and not any(c.section == "identity_brand" for c in envelope.claims):
        raw_bytes = json.dumps({k: v for k, v in record.items() if not k.startswith("__signalpost_")}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        row_hash = record.get("__signalpost_snapshot_row_sha256") or hashlib.sha256(raw_bytes).hexdigest()
        # Evidence points at a deterministic internal representation of the
        # frozen snapshot. The external source URL remains in baseline_identity;
        # the internal URI binds the aggregate snapshot identity to its hash.
        frozen_source_id = f"registry_snapshot:{snapshot_sha}"
        frozen_source_url = f"urn:signalpost:frozen-registry:{snapshot_sha}"
        source_id = frozen_source_id
        existing_snapshot = next((s for s in envelope.source_snapshots if s.source_id == source_id), None)
        if not existing_snapshot:
            envelope.source_snapshots.append(SourceSnapshot(source_id=source_id, source_url=frozen_source_url,
                retrieved_at=datetime.now(timezone.utc), content_sha256=snapshot_sha, cache_mode="transient",
                rights_status=RIGHTS))
        for key, value, pointer in (("legal_name", name, "/navn" if "navn" in record else "/legal_name" if "legal_name" in record else "/name"),
                                    ("legal_form", legal_form, "/organisasjonsform/kode" if isinstance(record.get("organisasjonsform"), dict) else "/legal_form")):
            if value is None: continue
            evidence_id = f"{envelope.organisation_number}:frozen:{key}"
            envelope.evidence.append(Evidence(evidence_id=evidence_id, source_url=frozen_source_url,
                retrieved_at=datetime.now(timezone.utc), content_sha256=row_hash, extraction_method="frozen_registry_jsonl_v1",
                json_pointer=pointer, source_class="official", subject_organisation_number=envelope.organisation_number,
                source_snapshot_ids=[source_id]))
            claim = Claim(claim_id=f"{envelope.organisation_number}:frozen:{key}", organisation_number=envelope.organisation_number,
                section="identity_brand", field_family="identity", subject_id=envelope.organisation_number, field=key,
                value=value, state=PublicState.AVAILABLE, scope="legal_entity", verification_rule_id="frozen_exact_org_snapshot_v1",
                verification_score="1.0", evidence_ids=[evidence_id], source_snapshot_ids=[source_id], as_of=_cutoff_datetime(as_of))
            envelope.claims.append(claim)
            envelope.sections["identity_brand"].claims.append(claim)
            envelope.sections["identity_brand"].state = PublicState.AVAILABLE
            envelope.sections["claims_evidence_states"].claims.append(claim)
            envelope.sections["claims_evidence_states"].state = PublicState.AVAILABLE
        envelope.terminal_state = PublicState.AVAILABLE
    return envelope


def _merge_website_provenance(envelope: Envelope, result: Any) -> None:
    """Merge website provenance, reusing identical BRREG candidate records safely."""
    evidence_fields = ("source_url", "content_sha256", "extraction_method", "json_pointer", "excerpt", "page_number",
        "source_class", "subject_organisation_number", "source_snapshot_ids")
    existing_evidence = {item.evidence_id: item for item in envelope.evidence}
    for item in result.evidence:
        existing = existing_evidence.get(item.evidence_id)
        if existing is not None:
            if any(getattr(existing, field) != getattr(item, field) for field in evidence_fields):
                raise ValueError(f"evidence identifier collision with conflicting provenance: {item.evidence_id}")
            # Keep the source's original retrieval time and record; the website
            # adapter may have reconstructed the same frozen/live candidate.
            continue
        envelope.evidence.append(item)
        existing_evidence[item.evidence_id] = item

    snapshot_fields = ("source_url", "content_sha256", "cache_mode", "rights_status")
    existing_snapshots = {item.source_id: item for item in envelope.source_snapshots}
    for item in result.snapshots:
        existing = existing_snapshots.get(item.source_id)
        if existing is not None:
            if any(getattr(existing, field) != getattr(item, field) for field in snapshot_fields):
                raise ValueError(f"source snapshot identifier collision with conflicting provenance: {item.source_id}")
            # An official response's HTTP status is more complete than the
            # website adapter's candidate-only reconstruction; preserve it.
            continue
        envelope.source_snapshots.append(item)
        existing_snapshots[item.source_id] = item


def _cutoff_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


async def _run_before_completion_reserve(awaitable: Any, budget: Budget) -> tuple[Any, bool]:
    """Cancel active source work before the hard deadline's atomic-output reserve."""
    remaining = max(0.0, budget.config.hard_seconds - budget.elapsed - budget.config.completion_reserve_seconds)
    if remaining <= 0:
        if hasattr(awaitable, "close"):
            awaitable.close()
        return {}, True
    try:
        return await asyncio.wait_for(awaitable, timeout=remaining), False
    except asyncio.TimeoutError:
        return {}, True


def run(args: argparse.Namespace) -> int:
    run_started = time.monotonic()
    run_start_utc = datetime.now(timezone.utc)
    input_path = Path(args.input) if args.input else _find_default_input()
    if not input_path or not input_path.exists():
        print("No input file found; provide --input or create signalpost_input.jsonl", file=sys.stderr)
        return 2
    rows = load_input(input_path, args.format)
    # The row set is fully parsed before any network-capable component is constructed.
    if not rows:
        print("Input contains no rows", file=sys.stderr)
        return 2
    rows_by_org: dict[str, list[Any]] = {}
    for row in rows:
        rows_by_org.setdefault(row.organisation_number, []).append(row)
    output_path = Path(args.output or os.environ.get("SIGNALPOST_OUTPUT", "signalpost_output.jsonl"))
    state_output_path = Path(args.state_output or os.environ.get("SIGNALPOST_STATE_OUTPUT") or
                             os.environ.get("SIGNALPOST_CANONICAL_STATE_OUTPUT", "signalpost_state.json"))
    checkpoint_default = str(state_output_path) + ".checkpoint.sqlite"
    checkpoint_path = Path(args.checkpoint or os.environ.get("SIGNALPOST_CHECKPOINT", checkpoint_default))
    marker_path = output_path.with_name(output_path.name + ".publication.json")
    read_only_paths = [Path(input_path), *[Path(value) for value in
        (args.registry_snapshot, args.config, args.previous_state) if value]]
    resolved_outputs = [path.resolve() for path in (output_path, state_output_path, checkpoint_path, marker_path)]
    resolved_reads = [path.resolve() for path in read_only_paths]
    if len(set(resolved_outputs)) != len(resolved_outputs) or set(resolved_outputs) & set(resolved_reads):
        raise ValueError("output, state, checkpoint, and publication marker must not alias each other or read-only input/config/state artifacts")
    config_values: dict[str, Any] = {}
    config_bytes = b""
    if args.config:
        config_bytes = Path(args.config).read_bytes()
        config_values = json.loads(config_bytes.decode("utf-8"))
        if not isinstance(config_values, dict):
            raise ValueError("runtime config must be a JSON object")
    website_rights_decisions = config_values.get("website_rights_decisions", {})
    if (not isinstance(website_rights_decisions, dict)
            or any(not isinstance(host, str) or not isinstance(status, str)
                   or status not in {"allowed", "blocked", "unknown_not_reviewed"}
                   for host, status in website_rights_decisions.items())):
        raise ValueError("website_rights_decisions must map hostnames to allowed, blocked, or unknown_not_reviewed")
    previous: dict[str, dict[str, Any]] = {}
    previous_artifact = None
    previous_state_bytes = b""
    previous_state_error: str | None = None
    if args.previous_state:
        try:
            previous_state_bytes = Path(args.previous_state).read_bytes()
            previous_artifact = validate_artifact(json.loads(previous_state_bytes.decode("utf-8")))
        except OSError:
            previous_state_error = "prior state could not be read"
        except UnicodeDecodeError:
            previous_state_error = "prior state is not valid UTF-8 JSON"
        except json.JSONDecodeError:
            previous_state_error = "prior state is not valid JSON"
        except PriorStateError as exc:
            previous_state_error = str(exc)
    live_brreg = bool(args.live_brreg or not args.registry_snapshot)
    live_websites = bool(args.live_websites)
    fixture = {}
    registry_hash = None
    if args.registry_snapshot:
        fixture, registry_hash = stream_registry_matches(args.registry_snapshot, {r.organisation_number for r in rows})
    budget = RunBudget.from_mapping(config_values.get("budget", config_values), batch_rows=len(rows))
    run_budget = Budget(budget, started_at=run_started)
    cutoff_value = args.evidence_cutoff or config_values.get("evidence_cutoff")
    cutoff_source = "evaluator" if args.evidence_cutoff else "config" if cutoff_value else "run_start"
    if args.resume and not cutoff_value and checkpoint_path.exists():
        resume_store = CheckpointStore(checkpoint_path)
        saved_cutoff = resume_store.get_meta("effective_cutoff")
        resume_store.close()
        if saved_cutoff:
            cutoff_value = saved_cutoff
            cutoff_source = "run_start"
    cutoff = (datetime.fromisoformat(str(cutoff_value).replace("Z", "+00:00")) if cutoff_value
              else run_start_utc)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    cutoff = cutoff.astimezone(timezone.utc)
    effective_config_identity = {
        "source_policy_version": SOURCE_POLICY_VERSION,
        "runtime_config": config_values,
        "registry_source_url": args.registry_source_url,
        "registry_snapshot_as_of": args.registry_snapshot_as_of,
        "network_policy": args.network_policy,
        "live_brreg": live_brreg,
        "live_websites": live_websites,
        "no_keyless_websites": args.no_keyless_websites,
        "budget": {"hard_seconds": budget.hard_seconds, "soft_seconds": budget.soft_seconds,
            "completion_reserve_seconds": budget.completion_reserve_seconds,
            "physical_request_limit": budget.physical_request_limit,
            "logical_request_limit": budget.logical_request_limit,
            "paid_cost_limit": str(budget.paid_cost_limit),
            "global_http_concurrency": budget.global_http_concurrency,
            "per_host_concurrency": budget.per_host_concurrency,
            "per_company_physical_limit": budget.per_company_physical_limit,
            "per_host_physical_limit": budget.per_host_physical_limit},
    }
    # History compatibility describes evidence semantics, not the amount of work
    # this run can attempt. The full operational identity remains in the separate
    # checkpoint fingerprint below, so a changed batch/budget cannot resume it.
    legacy_config_fingerprint = sha256_json(effective_config_identity)
    history_identity = dict(effective_config_identity)
    history_identity.pop("budget")
    runtime_identity = dict(config_values)
    budget_keys = {field.name for field in fields(RunBudget)}
    for key in budget_keys:
        runtime_identity.pop(key, None)
    if isinstance(runtime_identity.get("budget"), dict):
        remaining = {key: value for key, value in runtime_identity["budget"].items() if key not in budget_keys}
        if remaining:
            runtime_identity["budget"] = remaining
        else:
            runtime_identity.pop("budget")
    history_identity["runtime_config"] = runtime_identity
    history_identity["history_compatibility_version"] = 2
    config_fingerprint = sha256_json(history_identity)
    previous_ref = ("sha256:" + hashlib.sha256(canonical_json(previous_artifact.model_dump(mode="json"))).hexdigest()
                    if previous_artifact else None)
    if previous_artifact and previous_artifact.configuration_fingerprint != config_fingerprint:
        if previous_artifact.configuration_fingerprint == legacy_config_fingerprint:
            # Migrate only an exactly matching legacy identity; an opaque old hash
            # cannot prove compatibility after a budget change. Keep the original
            # artifact reference and all provenance/observation bytes intact.
            previous_artifact = previous_artifact.model_copy(update={
                "configuration_fingerprint": config_fingerprint,
                "companies": {org: company.model_copy(update={"configuration_fingerprint": config_fingerprint})
                              for org, company in previous_artifact.companies.items()},
            })
        else:
            previous_artifact = None
            previous_ref = None
            previous_state_error = "prior state source/config identity is incompatible with this run"
    if previous_artifact:
        previous = {org: {"state_ref": previous_ref} for org in previous_artifact.companies}
    run_fingerprint = hashlib.sha256(input_path.read_bytes() + config_bytes + json.dumps({
        "format": args.format, "live_brreg": live_brreg, "live_websites": live_websites,
        "registry_snapshot_sha256": registry_hash, "config": config_values,
        "registry_snapshot_as_of": args.registry_snapshot_as_of,
        "registry_source_url": args.registry_source_url,
        "budget": {"hard_seconds": budget.hard_seconds, "soft_seconds": budget.soft_seconds,
                   "completion_reserve_seconds": budget.completion_reserve_seconds,
                   "physical_request_limit": budget.physical_request_limit,
                   "logical_request_limit": budget.logical_request_limit,
                   "paid_cost_limit": str(budget.paid_cost_limit),
                   "global_http_concurrency": budget.global_http_concurrency,
                   "per_host_concurrency": budget.per_host_concurrency},
        "per_company_physical_limit": budget.per_company_physical_limit,
        "per_host_physical_limit": budget.per_host_physical_limit,
        "previous_state_sha256": hashlib.sha256(previous_state_bytes).hexdigest() if previous_state_bytes else None,
        "previous_state_error": previous_state_error,
        "evidence_cutoff": cutoff.isoformat(), "evidence_cutoff_source": cutoff_source,
        "network_policy": args.network_policy,
        "no_keyless": args.no_keyless_websites,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    batch_id = args.batch_id or str(uuid.uuid4())
    # Persist one internal shell per row before running any enrichment. Shells are not
    # evaluator envelopes and therefore do not invent a public terminal result.
    writer = OrderedAtomicWriter(output_path, estimated_bytes=len(rows) * 64 * 1024)  # preflight before enrichment
    state_writer = OrderedAtomicWriter(state_output_path,
        estimated_bytes=len(previous_state_bytes) + len(rows) * 64 * 1024)
    if args.resume and not checkpoint_path.exists():
        raise ValueError("--resume requested but the checkpoint does not exist")
    checkpoint = CheckpointStore(checkpoint_path)
    if args.resume:
        if checkpoint.get_meta("input_fingerprint") != run_fingerprint:
            checkpoint.close()
            raise ValueError("checkpoint input/configuration fingerprint does not match this run")
        batch_id = checkpoint.get_meta("batch_id") or batch_id
    else:
        checkpoint.connection.execute("DELETE FROM shells")
        checkpoint.connection.execute("DELETE FROM envelopes")
        checkpoint.connection.execute("DELETE FROM run_meta")
        checkpoint.connection.executemany("INSERT INTO shells VALUES (?,?,?,?)",
            [(row.row_number, row.input_ref, row.organisation_number, "pending") for row in rows])
        checkpoint.set_meta("input_fingerprint", run_fingerprint)
        checkpoint.set_meta("batch_id", batch_id)
        checkpoint.set_meta("effective_cutoff", cutoff.isoformat())
        checkpoint.set_meta("evidence_cutoff_source", cutoff_source)
    pending_path = writer.write_shells(rows, checkpoint.shell_states())
    prior_terminalized = checkpoint.terminalized() if args.resume else {}
    baseline_saved = checkpoint.envelopes_for_state("baseline_done") if args.resume else {}
    gateway = None
    scheduler_report: dict[str, Any] = {}
    live_by_org: dict[str, Any] = {}
    if live_brreg or live_websites:
        gateway = NetworkGateway(timeout=20, retries=1, budget=run_budget,
                                 trusted_proxy=args.network_policy == "trusted-proxy",
                                 global_concurrency=budget.global_http_concurrency)
        if live_brreg:
            gateway.set_rate_limit("data.brreg.no", 3.0)
        async def enrich():
            unique = list(dict.fromkeys(r.organisation_number for r in rows
                                        if r.row_number not in prior_terminalized and len(r.organisation_number) == 9 and r.organisation_number.isdigit()))
            by_org = {}
            nav_results_by_org = {}
            nav_homepages = {}

            async def nav_phase(targets):
                from .nav import research_jobs
                if run_budget.soft_expired or run_budget.reserve_active:
                    scheduler_report["nav_jobs"] = {"state": "deadline_skipped", "negative_coverage": False}
                    return {}, {}
                if run_budget.physical_requests_remaining < max(12, len(unique) * 4) + 32:
                    scheduler_report["nav_jobs"] = {"state": "budget_skipped", "negative_coverage": False,
                        "reason": "preserve_existing_research_request_reserve"}
                    return {}, {}
                previous_claims = {org: state.claims for org, state in previous_artifact.companies.items()} if previous_artifact else {}
                result, cancelled = await _run_before_completion_reserve(research_jobs(targets, gateway, cutoff,
                    allow_current=cutoff_source == "run_start", previous_claims=previous_claims), run_budget)
                if cancelled:
                    scheduler_report["nav_jobs"] = {"state": "deadline_skipped", "negative_coverage": False}
                    return {}, {}
                observations, audit, homepages = result
                scheduler_report["nav_jobs"] = audit
                return observations, homepages

            if live_brreg:
                scheduler = OpportunityScheduler(concurrency=min(4, budget.global_http_concurrency))
                baseline_orgs = {org for org in unique if all(
                    row.row_number in baseline_saved or row.row_number in prior_terminalized
                    for row in rows if row.organisation_number == org)}
                works = [Opportunity(key=org, company=org, pass_name="official_foundation",
                                     expected_company_family_gain=3, expected_atomic_claim_gain=4,
                                     expected_requests=4.02, expected_seconds=2.888, sequence=index)
                         for index, org in enumerate(unique) if org not in baseline_orgs]
                completed_queue: asyncio.Queue[Any] = asyncio.Queue()
                async def checkpoint_writer():
                    while True:
                        payload = await completed_queue.get()
                        if payload is None:
                            return
                        item, result, future = payload
                        try:
                            baseline = fixture.get(item.company)
                            for row in rows_by_org.get(item.company, ()):
                                if row.row_number in prior_terminalized:
                                    continue
                                envelope = _live_envelope(row, result, batch_id, cutoff, previous,
                                                          frozen_match=baseline is not None)
                                if args.registry_snapshot:
                                    envelope = _attach_frozen_baseline(envelope, baseline, registry_hash, cutoff,
                                        args.registry_snapshot_as_of, args.registry_source_url)
                                checkpoint.put(envelope)
                                checkpoint.set_shell_state(row.row_number, "baseline_done")
                            future.set_result(None)
                        except BaseException as exc:
                            future.set_exception(exc)
                checkpoint_task = asyncio.create_task(checkpoint_writer())
                async def official(item: Opportunity):
                    try:
                        return await fetch_company(item.company, gateway, cutoff,
                            allow_current_identity_after_run_start=cutoff_source == "run_start")
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        raise OpportunityFailed(BrregResult(
                            claims=[], evidence=[], snapshots=[],
                            errors=[RunError(code="BRREG_ACTION_UNEXPECTED_FAILURE",
                                message=f"Official work item failed: {type(exc).__name__}.", retryable=True)],
                            section_states={name: PublicState.FAILED for name in
                                ("identity_brand", "accounts_history", "leadership_workplaces")},
                            terminal_state=PublicState.FAILED,
                            observations={"execution_state": "failed", "organisation_number": item.company}))
                async def checkpoint_completed(item: Opportunity, result: Any) -> None:
                    future = asyncio.get_running_loop().create_future()
                    await completed_queue.put((item, result, future))
                    await future
                try:
                    by_org, official_deadline_cancelled = await _run_before_completion_reserve(
                        scheduler.run(works, official, on_complete=checkpoint_completed), run_budget)
                finally:
                    await completed_queue.put(None)
                    await checkpoint_task
                scheduler_report["official_foundation"] = {"passes": scheduler.metrics,
                    "companies": scheduler.company_metrics,
                    "hard_deadline_cancelled": official_deadline_cancelled}
                if live_websites:
                    nav_targets = {envelope.organisation_number: envelope for envelope in baseline_saved.values()}
                    nav_targets.update(by_org)
                    nav_results_by_org, nav_homepages = await nav_phase(nav_targets)
                # Foundation envelopes are checkpointed before optional CPU work.
                # One current official copy supplies both workforce and per-row
                # financial validation; the scheduler still guarantees completion.
                from .annual_accounts import DocumentProcessor, enrich_company
                processor = DocumentProcessor()
                document_scheduler = OpportunityScheduler(concurrency=2)
                document_works = [Opportunity(key=org, company=org, pass_name="annual_documents",
                    expected_company_family_gain=2, expected_atomic_claim_gain=4,
                    expected_requests=1, expected_seconds=30, sequence=index)
                    for index, (org, result) in enumerate(by_org.items()) if getattr(result, "account_records", [])]
                async def annual_document(item: Opportunity):
                    with request_company_scope(item.company):
                        return await enrich_company(by_org[item.company], item.company, gateway, cutoff, processor)
                for item in document_works:
                    by_org[item.company].section_states["hiring_activity"] = PublicState.BLOCKED
                    by_org[item.company].observations["annual_accounts_document"] = {"state": "blocked", "reason": "document_not_scheduled"}
                gateway.set_rate_limit("data.brreg.no", 1 / 2.1)
                document_results, document_cancelled = await _run_before_completion_reserve(
                    document_scheduler.run(document_works, annual_document,
                        permitted=lambda item: not run_budget.soft_expired and not run_budget.reserve_active), run_budget)
                by_org.update(document_results)
                gateway.set_rate_limit("data.brreg.no", 3.0)
                scheduler_report["annual_documents"] = {"passes": document_scheduler.metrics,
                    "companies": document_scheduler.company_metrics, "hard_deadline_cancelled": document_cancelled}
            output = []
            for row in rows:
                if row.row_number in prior_terminalized:
                    output.append(prior_terminalized[row.row_number])
                    continue
                if row.row_number in baseline_saved:
                    envelope = baseline_saved[row.row_number]
                    live_by_org[row.organisation_number] = SimpleNamespace(
                        observations=envelope.synthesis.get("brreg_observations", {}), claims=envelope.claims,
                        evidence=envelope.evidence)
                    output.append(envelope)
                    continue
                if live_brreg and row.organisation_number not in by_org:
                    output.append(_envelope(row, {}, batch_id, cutoff, previous))
                    continue
                baseline = fixture.get(row.organisation_number)
                if live_brreg:
                    result = by_org[row.organisation_number]
                    envelope = _live_envelope(row, result, batch_id, cutoff, previous, frozen_match=baseline is not None)
                    live_by_org[row.organisation_number] = result
                    if args.registry_snapshot:
                        envelope = _attach_frozen_baseline(envelope, baseline, registry_hash, cutoff,
                                                           args.registry_snapshot_as_of, args.registry_source_url)
                else:
                    envelope = _envelope(row, fixture, batch_id, cutoff, previous)
                output.append(envelope)
            if live_websites and not live_brreg:
                nav_results_by_org, nav_homepages = await nav_phase({envelope.organisation_number: envelope for envelope in output
                    if envelope.row_number not in prior_terminalized})
            if live_websites:
                for envelope in output:
                    if envelope.row_number in prior_terminalized:
                        continue
                    envelope.sections["hiring_activity"].diagnostics.append("nav_jobs:partial_coverage_no_negative_assertion")
                    result = nav_results_by_org.get(envelope.organisation_number)
                    if not result:
                        continue
                    envelope.claims.extend(result.claims)
                    _merge_website_provenance(envelope, result)
                    for section_name in ("hiring_activity", "claims_evidence_states"):
                        envelope.sections[section_name].claims.extend(result.claims)
                        envelope.sections[section_name].state = PublicState.AVAILABLE
            if args.live_websites:
                from .websites import WebsiteResearchResult, research_company, sanitize_registry_websites
                # Discover shared roots across input entities before evaluating any one company.
                profiles = {org: _website_profile(org, live_result=live_by_org.get(org), frozen=fixture.get(org),
                    frozen_sha=registry_hash, frozen_source_url=args.registry_source_url) for org in unique}
                for org, candidates in nav_homepages.items():
                    if org in profiles:
                        profiles[org].setdefault("discovery_candidates", []).extend(candidates)
                from .public_discovery import wikidata_candidates
                if (cutoff_source == "run_start" and not run_budget.soft_expired and not run_budget.reserve_active
                        and run_budget.physical_requests_remaining >= max(12, len(unique) * 4) + 4):
                    discovery_result, discovery_cancelled = await _run_before_completion_reserve(
                        wikidata_candidates(unique, gateway), run_budget)
                    scheduler_report["wikidata_discovery"] = {"state": "deadline_skipped"} if discovery_cancelled else discovery_result[1]
                    if not discovery_cancelled:
                        for org, candidates in discovery_result[0].items():
                            profiles[org].setdefault("discovery_candidates", []).extend(candidates)
                else:
                    scheduler_report["wikidata_discovery"] = {"state": "not_attempted",
                        "reason": "historical_cutoff_or_existing_research_reserve"}
                root_owners: dict[str, set[str]] = {}
                for org, profile in profiles.items():
                    for candidate in profile.get("website_candidates", []):
                        raw = candidate.get("raw", "") if isinstance(candidate, dict) else candidate
                        for item in sanitize_registry_websites(raw):
                            if item["kind"] == "website":
                                root = registered_domain(urlsplit(item["url"]).hostname or "")
                                if root: root_owners.setdefault(root, set()).add(org)
                shared_roots = {root for root, owners in root_owners.items() if len(owners) > 1}
                scheduler = OpportunityScheduler(concurrency=min(8, budget.global_http_concurrency))
                async def website(item: Opportunity, phase: str, previous: WebsiteResearchResult | None = None):
                    try:
                        with request_company_scope(item.company):
                            return await research_company(profiles[item.company], gateway, shared_domains=shared_roots,
                                enable_keyless=not args.no_keyless_websites, evidence_cutoff=cutoff,
                                phase=phase, previous=previous, rights_decisions=website_rights_decisions,
                                allow_current_registry_references=cutoff_source == "run_start")
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        raise OpportunityFailed(WebsiteResearchResult(state=PublicState.FAILED,
                            hiring_activity_state=PublicState.FAILED,
                            errors=[RunError(code="WEBSITE_RESEARCH_UNEXPECTED_FAILURE",
                                message=f"Optional website action failed: {type(exc).__name__}.", retryable=True)],
                            audit={"execution_state": "failed", "claims": []}))
                def website_permitted(item: Opportunity) -> bool:
                    # The jobs/activity pass only extracts the pages saved by
                    # shallow research. HTTP exhaustion must not discard those
                    # observations; time and completion-reserve gates still apply.
                    return (not run_budget.soft_expired and not run_budget.reserve_active
                        and (item.pass_name == "jobs_activity" or (
                            run_budget.physical_requests_remaining > 0
                            and run_budget.logical_requests_remaining != 0)))
                verify_works = [Opportunity(key=org, company=org, pass_name="website_verify",
                    expected_company_family_gain=0.15, expected_atomic_claim_gain=0.2,
                    identity_risk=0.05, expected_requests=0.2, expected_seconds=0.15, sequence=index)
                    for index, org in enumerate(profiles)]
                verified_by_org, verify_deadline_cancelled = await _run_before_completion_reserve(
                    scheduler.run(verify_works, lambda item: website(item, "verify"), permitted=website_permitted), run_budget)
                shallow_works = [Opportunity(key=org, company=org, pass_name="website_shallow",
                    expected_company_family_gain=0.3, expected_atomic_claim_gain=1.0,
                    identity_risk=0.02, expected_requests=0.2, expected_seconds=0.15, sequence=index)
                    for index, org in enumerate(profiles) if org in verified_by_org
                    and verified_by_org[org].phase_state.get("accepted_pages")]
                shallow_by_org, shallow_deadline_cancelled = await _run_before_completion_reserve(
                    scheduler.run(shallow_works, lambda item: website(item, "shallow", verified_by_org[item.company]), permitted=website_permitted), run_budget)
                activity_works = [Opportunity(key=org, company=org, pass_name="jobs_activity",
                    expected_company_family_gain=0.1, expected_atomic_claim_gain=0.5,
                    identity_risk=0.04, expected_requests=0.0, expected_seconds=0.1, sequence=index)
                    for index, org in enumerate(profiles) if org in shallow_by_org
                    and shallow_by_org[org].phase_state.get("accepted_pages")]
                activity_by_org, activity_deadline_cancelled = await _run_before_completion_reserve(
                    scheduler.run(activity_works, lambda item: website(item, "jobs", shallow_by_org[item.company]), permitted=website_permitted), run_budget)
                scheduler_report["website_opportunity_passes"] = {"passes": scheduler.metrics,
                    "companies": scheduler.company_metrics,
                    "hard_deadline_cancelled": {"website_verify": verify_deadline_cancelled,
                        "website_shallow": shallow_deadline_cancelled, "jobs_activity": activity_deadline_cancelled},
                    "stage_results": {"verified": len(verified_by_org), "shallow": len(shallow_by_org),
                        "jobs_activity": len(activity_by_org)}}
                by_website_org = {org: activity_by_org.get(org, shallow_by_org.get(org, verified_by_org.get(org)))
                    for org in set(verified_by_org) | set(shallow_by_org) | set(activity_by_org)}
                for envelope in output:
                    if envelope.row_number in prior_terminalized:
                        continue
                    result = by_website_org.get(envelope.organisation_number)
                    if not result:
                        outcome = "deadline_skipped" if (run_budget.soft_expired or run_budget.reserve_active) else "budget_skipped"
                        envelope.synthesis["website_research"] = {"execution_state": outcome,
                            "reason": "soft_deadline_or_completion_reserve" if outcome == "deadline_skipped" else "request_budget_exhausted", "claims": []}
                        envelope.sections["website_owned_profiles"].state = None
                        envelope.sections["website_owned_profiles"].attempt_outcome = outcome
                        if not envelope.sections["hiring_activity"].claims:
                            envelope.sections["hiring_activity"].state = None
                            envelope.sections["hiring_activity"].attempt_outcome = outcome
                        envelope.sections["website_owned_profiles"].diagnostics.append(
                            "scheduler_execution_state:budget_skipped")
                        envelope.sections["hiring_activity"].diagnostics.append(
                            "scheduler_execution_state:budget_skipped")
                        continue
                    envelope.claims.extend(result.claims)
                    _merge_website_provenance(envelope, result)
                    website_claims = [claim for claim in result.claims if claim.section == "website_owned_profiles"]
                    footprint_claims = [claim for claim in result.claims if claim.section == "hiring_activity"]
                    section = envelope.sections["website_owned_profiles"]
                    section.claims.extend(website_claims)
                    section.state = result.state if not website_claims else PublicState.AVAILABLE
                    section.attempt_outcome = result.attempt_outcome or ("completed" if result.phase_state.get("accepted_pages") else None)
                    hiring = envelope.sections["hiring_activity"]
                    hiring.claims.extend(footprint_claims)
                    hiring.state = PublicState.AVAILABLE if hiring.claims else result.hiring_activity_state
                    hiring.attempt_outcome = result.hiring_attempt_outcome or result.attempt_outcome
                    envelope.sections["claims_evidence_states"].claims.extend(result.claims)
                    if result.claims:
                        envelope.sections["claims_evidence_states"].state = PublicState.AVAILABLE
                    envelope.errors.extend(result.errors)
                    envelope.synthesis["website_research"] = result.audit
                    envelope.__class__.model_validate(envelope.model_dump())
            for envelope in output:
                checkpoint.put(envelope)
                checkpoint.connection.execute("UPDATE shells SET execution_state='terminalized' WHERE row_number=?", (envelope.row_number,))
            checkpoint.connection.commit()
            return output
        envelopes = asyncio.run(enrich())
    else:
        envelopes = [prior_terminalized[row.row_number] if row.row_number in prior_terminalized else
                     _envelope(row, fixture, batch_id, cutoff, previous, registry_as_of=args.registry_snapshot_as_of,
                               registry_source_url=args.registry_source_url) for row in rows]
    for envelope in envelopes:
        envelope.synthesis["evidence_cutoff"] = cutoff.isoformat()
        envelope.synthesis["evidence_cutoff_source"] = cutoff_source
    # Construct one canonical company state per organisation, independent of
    # duplicate input rows, then compare it against the explicitly supplied state.
    # Keep untouched companies when a refresh batch is only a subset; a handoff
    # artifact must not silently forget state outside today's input rows.
    current_states: dict[str, CompanyState] = (dict(previous_artifact.companies) if previous_artifact else {})
    representative: dict[str, Envelope] = {}
    for envelope in sorted(envelopes, key=lambda item: item.row_number):
        representative.setdefault(envelope.organisation_number, envelope)
    for org, envelope in sorted(representative.items()):
        old_state = previous_artifact.companies.get(org) if previous_artifact else None
        new_state = company_state(envelope, config_fingerprint, old_state)
        new_state = merge_prior_facts(new_state, old_state)
        current_states[org] = new_state
    state_payload = artifact_payload(current_states, config_fingerprint)
    current_ref = artifact_ref(state_payload)
    for envelope in envelopes:
        old_state = previous_artifact.companies.get(envelope.organisation_number) if previous_artifact else None
        if previous_state_error:
            envelope.refresh.mode = "incompatible_prior_state"
            envelope.errors.append(RunError(code="REFRESH_PRIOR_STATE_INCOMPATIBLE",
                message="Prior state was not used: " + previous_state_error[:400]))
        elif not old_state:
            envelope.refresh.mode = "baseline_no_prior_state"
        else:
            envelope.refresh.mode = "compared"
            envelope.refresh.previous_state_ref = previous_ref
            envelope.refresh.changes = compare_states(old_state, current_states[envelope.organisation_number],
                cutoff=cutoff, previous_ref=previous_ref, current_ref=current_ref)
        envelope.refresh.current_state_ref = current_ref
        envelope.refresh.last_attempt_at = envelope.created_at
        envelope.refresh.retained_claim_ids = sorted(claim.get("claim_id", "")
            for claim in current_states[envelope.organisation_number].claims)
        change_section = envelope.sections["refresh_changes"]
        change_section.state = PublicState.AVAILABLE if envelope.refresh.changes else PublicState.NOT_AVAILABLE
        change_section.attempt_outcome = envelope.refresh.mode
        change_section.diagnostics = [f"material_changes:{len(envelope.refresh.changes)}"]
        envelope.synthesis["summary"] = synthesize(envelope)
        checkpoint.put(envelope)
        checkpoint.connection.execute("UPDATE shells SET execution_state='terminalized' WHERE row_number=?", (envelope.row_number,))
    checkpoint.connection.commit()
    expected_rows = [(row.row_number, row.input_ref) for row in rows]
    actual_rows = [(item.row_number, item.input_ref) for item in sorted(envelopes, key=lambda item: item.row_number)]
    if len(actual_rows) != len(expected_rows) or actual_rows != expected_rows:
        raise RuntimeError("terminal output does not exactly match input row cardinality/order")
    finalization_started = time.monotonic()
    validate_batch_publication_graph(envelopes)
    publication_marker = publish_paired_artifacts(writer, state_writer, envelopes,
        canonical_json(state_payload) + b"\n", serializer=to_evaluator)
    finalization_seconds = time.monotonic() - finalization_started
    pending_path.unlink(missing_ok=True)
    ledger_purposes = {}
    ledger_hosts = {}
    ledger_outcomes = {}
    if gateway:
        for entry in gateway.ledger.entries:
            ledger_purposes[entry.purpose] = ledger_purposes.get(entry.purpose, 0) + 1
            host = urlsplit(entry.url).hostname or ""
            ledger_hosts[host] = ledger_hosts.get(host, 0) + 1
            outcome_key = f"{entry.purpose}:{entry.status or 0}:{entry.outcome}"
            ledger_outcomes[outcome_key] = ledger_outcomes.get(outcome_key, 0) + 1
    error_counts: dict[str, int] = {}
    for envelope in envelopes:
        for error in envelope.errors:
            error_counts[error.code] = error_counts.get(error.code, 0) + 1
    print(StructuredLogger.emit("batch_complete", batch_id=batch_id, rows=len(rows),
                                available=sum(item.terminal_state == PublicState.AVAILABLE for item in envelopes),
                                failed=sum(item.terminal_state == PublicState.FAILED for item in envelopes),
                                physical_requests=(gateway.ledger.physical_requests if gateway else 0), budget_seconds=budget.hard_seconds,
                                    registry_snapshot_sha256=registry_hash,
                                    evidence_cutoff=cutoff.isoformat(),
                                    evidence_cutoff_source=cutoff_source,
                                    physical_gateway_requests=(gateway.ledger.physical_requests if gateway else 0),
                                    logical_gateway_requests=(gateway.ledger.logical_requests if gateway else 0),
                                    requests_by_purpose=ledger_purposes, errors_by_code=error_counts,
                                    physical_requests_by_host=ledger_hosts,
                                    physical_requests_by_company=run_budget.requests_by_company,
                                    physical_request_outcomes=ledger_outcomes,
                                    scheduler_passes=scheduler_report,
                                    coalesced_requests=(getattr(gateway, "coalesced_requests", 0) if gateway else 0),
                                    runtime_seconds=round(time.monotonic() - run_started, 3),
                                    output_cardinality=len(envelopes),
                                    publication_marker=str(publication_marker),
                                    finalization_seconds=round(finalization_seconds, 3),
                                    completion_reserve_remaining_seconds=(
                                        round(max(0.0, budget.hard_seconds - run_budget.elapsed), 3)),
                                    completion_reserve_seconds=budget.completion_reserve_seconds,
                                    request_limit=budget.physical_request_limit,
                                    logical_request_limit=budget.logical_request_limit,
                                    per_company_physical_limit=budget.per_company_physical_limit,
                                    per_host_physical_limit=budget.per_host_physical_limit,
                                    paid_cost_limit=str(budget.paid_cost_limit)))
    checkpoint.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m signalpost.run")
    parser.add_argument("--input", default=os.environ.get("SIGNALPOST_INPUT"))
    parser.add_argument("--output")
    parser.add_argument("--format", choices=("auto", "json", "jsonl", "csv", "tsv", "plain"), default="auto")
    parser.add_argument("--registry-snapshot", default=os.environ.get("SIGNALPOST_REGISTRY_SNAPSHOT"))
    parser.add_argument("--registry-snapshot-as-of", default=os.environ.get("SIGNALPOST_REGISTRY_SNAPSHOT_AS_OF"))
    parser.add_argument("--registry-source-url", default=os.environ.get("SIGNALPOST_REGISTRY_SOURCE_URL"))
    parser.add_argument("--previous-state", default=os.environ.get("SIGNALPOST_PREVIOUS_STATE"))
    parser.add_argument("--state-output")
    parser.add_argument("--checkpoint", help="Internal SQLite checkpoint/resume file (separate from canonical state output)")
    parser.add_argument("--resume", action="store_true", help="Resume matching rows from the SQLite state checkpoint")
    parser.add_argument("--config", help="Reserved for the versioned runtime configuration")
    parser.add_argument("--evidence-cutoff", default=os.environ.get("SIGNALPOST_EVIDENCE_CUTOFF"))
    parser.add_argument("--network-policy", choices=("direct", "trusted-proxy"), default=os.environ.get("SIGNALPOST_NETWORK_POLICY", "direct"))
    parser.add_argument("--live-brreg", action="store_true", help="Fetch official BRREG sections through the centralized gateway")
    parser.add_argument("--live-websites", action="store_true", help="Discover and verify website candidates through the centralized gateway")
    parser.add_argument("--no-keyless-websites", action="store_true", help="Disable bounded distinctive-name .no discovery")
    parser.add_argument("--batch-id")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
