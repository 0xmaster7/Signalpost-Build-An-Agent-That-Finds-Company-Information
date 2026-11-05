"""Offline adversarial checks for the additive, evidence-bounded human profile."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from signalpost.adapter import to_evaluator
from signalpost.models import (ChangeEvent, ChangeEvidenceRef, ChangeSnapshotRef, ChangeType, Claim,
                               Envelope, Evidence, PublicState, RefreshState, Section, SourceSnapshot)
from signalpost.profile import build_profile, validate_profile, validate_profile_schema
from signalpost.synthesis import synthesize, validate_synthesis, validate_synthesis_schema


ORGANISATION = "001234567"
CUTOFF = datetime(2026, 11, 5, tzinfo=timezone.utc)
PERIOD_START = datetime(2025, 4, 1, tzinfo=timezone.utc)
PERIOD_END = datetime(2026, 3, 31, tzinfo=timezone.utc)
SECTION_NAMES = ("identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
                 "hiring_activity", "claims_evidence_states", "refresh_changes")


def fact(field, value, **dimensions):
    return {"field": field, "value": value, **dimensions}


def financial(value, **dimensions):
    return fact("revenue", value, section="accounts_history", family="financial", subject_id="filing:latest",
                period_start=PERIOD_START, period_end=PERIOD_END, unit="TNOK", currency="NOK", **dimensions)


def publication(value="2026-10-01"):
    normalized = datetime.fromisoformat(value).replace(tzinfo=timezone.utc).isoformat()
    return {"source_value": value, "normalized_utc": normalized, "precision": "day"}


def envelope_with(facts=(), *, states=None, attempts=None):
    sections = {name: Section(state=(states or {}).get(name, PublicState.AVAILABLE),
                              attempt_outcome=(attempts or {}).get(name)) for name in SECTION_NAMES}
    claims, evidence, snapshots = [], [], {}
    for index, record in enumerate(facts):
        source_key = record.get("source_key", f"source:{index}")
        source_url = f"https://fixture.invalid/{source_key}"
        content_hash = hashlib.sha256(source_key.encode()).hexdigest()
        snapshot = SourceSnapshot(source_id=source_key, source_url=source_url, retrieved_at=CUTOFF,
                                  content_sha256=content_hash, http_status=200)
        snapshots[source_key] = snapshot
        evidence_item = Evidence(evidence_id=f"evidence:{index}", source_url=source_url, retrieved_at=CUTOFF,
                                 content_sha256=content_hash, json_pointer=record.get("pointer", "/value"),
                                 extraction_method="offline_profile_fixture", subject_organisation_number=ORGANISATION,
                                 source_snapshot_ids=[source_key])
        claim = Claim(claim_id=f"claim:{index}", organisation_number=ORGANISATION,
                      section=record.get("section", "identity_brand"), field_family=record.get("family", "identity"),
                      field=record["field"], value=record["value"], subject_id=record.get("subject_id", ORGANISATION),
                      scope=record.get("scope", "legal_entity"), state=record.get("state", PublicState.AVAILABLE),
                      unit=record.get("unit"), currency=record.get("currency"), as_of=record.get("as_of"),
                      period_start=record.get("period_start"), period_end=record.get("period_end"),
                      verification_rule_id="offline_profile_fixture", verification_score="1.0",
                      evidence_ids=[evidence_item.evidence_id], source_snapshot_ids=[source_key])
        claims.append(claim)
        evidence.append(evidence_item)
        sections[claim.section].claims.append(claim)
        sections["claims_evidence_states"].claims.append(claim)
    return Envelope(input_ref="offline-profile", row_number=1, organisation_number=ORGANISATION,
                    terminal_state=PublicState.AVAILABLE, sections=sections, refresh=RefreshState(),
                    claims=claims, evidence=evidence, source_snapshots=list(snapshots.values()),
                    batch_id="offline-profile", evidence_cutoff=CUTOFF, created_at=CUTOFF)


def sentences_for(profile, domain):
    return [sentence for sentence in profile["sentences"] if sentence["domain"] == domain]


def role(field, value, row):
    return fact(f"role.{field}", value, section="leadership_workplaces", family="role", scope="person_role",
                source_key="registry-roles", pointer=f"/rollegrupper/0/roller/{row}/" + ("person/navn" if field == "name" else field))


def footprint(field, value, *, family="public_activity", subject_id="article:1", **dimensions):
    return fact(field, value, section="hiring_activity", family=family, subject_id=subject_id,
                scope="job" if family == "jobs" else "event", **dimensions)


def test_supported_profile_covers_required_domains_and_resolves_every_sentence():
    envelope = envelope_with([
        fact("name", "Example AS"), fact("legal_form", "AS"),
        fact("industry_codes.0", {"kode": "62.100", "beskrivelse": "Computer programming"}),
        fact("registered_business_activity", ["Builds", "software."], family="business_description"),
        fact("employees", 17), fact("business_address", {"poststed": "OSLO", "adresse": ["Example street 1"]}),
        fact("full_time_equivalents", Decimal("15.25"), section="hiring_activity", family="workforce", unit="FTE",
             subject_id="filing:latest", period_start=PERIOD_START, period_end=PERIOD_END),
        role("name", "Alice Director", 0), role("role_description", "Managing director", 0),
        role("inactive", False, 0), financial(Decimal("12345.50")),
        footprint("activity_headline", "Launches a product"), footprint("source_published_at", publication()),
        footprint("job_title", "Engineer", family="jobs", subject_id="job:1"),
        footprint("posting_date", publication(), family="jobs", subject_id="job:1"),
        footprint("job_status", "open", family="jobs", subject_id="job:1"),
    ])
    profile = build_profile(envelope)
    assert {sentence["domain"] for sentence in profile["sentences"]} >= {
        "identity", "industry_activity", "size_fte", "location", "leadership", "financials", "hiring", "dated_activity"}
    claims = {claim.claim_id: claim for claim in envelope.claims}
    evidence = {item.evidence_id: item for item in envelope.evidence}
    snapshots = {item.source_id: item for item in envelope.source_snapshots}
    identifiers = [sentence["sentence_id"] for sentence in profile["sentences"]]
    assert len(identifiers) == len(set(identifiers))
    for sentence in profile["sentences"]:
        assert sentence["fact_ids"] and sentence["evidence_ids"]
        assert set(sentence["fact_ids"]) <= set(claims)
        assert set(sentence["evidence_ids"]) == {reference for claim_id in sentence["fact_ids"]
                                                  for reference in claims[claim_id].evidence_ids}
        for reference in sentence["evidence_ids"]:
            item = evidence[reference]
            assert item.subject_organisation_number == ORGANISATION
            assert all(snapshots[source_id].source_url == item.source_url
                       and snapshots[source_id].content_sha256 == item.content_sha256 for source_id in item.source_snapshot_ids)
    financial_text = sentences_for(profile, "financials")[0]["text"]
    assert "2025-04-01 to 2026-03-31" in financial_text
    assert "12345.50" in financial_text and "unit TNOK; currency NOK; scope legal_entity" in financial_text
    assert "15.25" in " ".join(sentence["text"] for sentence in sentences_for(profile, "size_fte"))
    validate_profile(envelope, profile)


def test_helper_and_additive_synthesis_match_canonical_and_evaluator_json():
    envelope = envelope_with([fact("name", "Example AS"), financial(0)])
    summary = synthesize(envelope)
    assert set(summary) == {"schema_version", "mode", "sentences", "unknown_sections", "profile"}
    envelope.synthesis["summary"] = summary
    validate_synthesis_schema(envelope.synthesis)
    validate_synthesis(envelope, summary)
    evaluator = to_evaluator(envelope)
    assert build_profile(evaluator) == summary["profile"] == build_profile(envelope.model_dump(mode="json"))
    assert evaluator["synthesis"]["summary"]["profile"] == summary["profile"]


def test_order_and_repeat_do_not_change_profile_or_sentence_ids():
    envelope = envelope_with([fact("name", "Example AS"), financial(10), fact("employees", 4)])
    original = build_profile(envelope)
    envelope.claims.reverse()
    envelope.evidence.reverse()
    envelope.source_snapshots.reverse()
    for section in envelope.sections.values():
        section.claims.reverse()
    assert build_profile(envelope) == original == build_profile(envelope)


@pytest.mark.parametrize("state", [PublicState.NOT_AVAILABLE, PublicState.AMBIGUOUS, PublicState.BLOCKED, PublicState.FAILED])
def test_unavailable_claims_are_unknowns_not_company_facts(state):
    profile = build_profile(envelope_with([fact("employees", 99999, state=state)]))
    assert not sentences_for(profile, "size_fte")
    unknown = next(record for record in profile["unknowns"] if record["domain"] == "size_fte")
    assert "unavailable_claims" in unknown["reasons"]


@pytest.mark.parametrize("scope", ["group", "unknown", "workplace"])
def test_other_scopes_are_not_legal_entity_facts(scope):
    profile = build_profile(envelope_with([fact("employees", 99999, scope=scope)]))
    assert not sentences_for(profile, "size_fte")
    assert "99999" not in json.dumps(profile["sentences"])


@pytest.mark.parametrize("state", [None, PublicState.AMBIGUOUS, PublicState.BLOCKED, PublicState.FAILED, PublicState.NOT_AVAILABLE])
def test_unverified_section_state_prevents_profile_facts(state):
    profile = build_profile(envelope_with([fact("name", "Do not publish")], states={"identity_brand": state}))
    assert not profile["sentences"]
    assert "Do not publish" not in json.dumps(profile)
    if state == PublicState.BLOCKED:
        assert any(record["domain"] == "identity" for record in profile["blocked"])


@pytest.mark.parametrize("attempt", ["not_attempted", "budget_skipped", "policy_skipped"])
def test_unattempted_sections_are_state_only(attempt):
    profile = build_profile(envelope_with([fact("employees", 8)], attempts={"identity_brand": attempt}))
    assert not profile["sentences"]
    context = next(record for record in profile["unknowns"] if record["domain"] == "size_fte")["state_context"]
    assert context[0]["attempt_outcome"] == attempt


def test_sparse_profile_always_has_explicit_resolvable_unknown_and_blocked_context():
    envelope = envelope_with(states={"accounts_history": PublicState.BLOCKED, "hiring_activity": None},
                             attempts={"hiring_activity": "not_attempted"})
    profile = build_profile(envelope)
    assert not profile["sentences"]
    assert len(profile["unknowns"]) == 10
    assert {record["domain"] for record in profile["blocked"]} == {"financials"}
    canonical = envelope.model_dump(mode="json")
    for unknown in profile["unknowns"]:
        assert "zero" not in unknown["text"] and "no jobs" not in unknown["text"]
        for context in unknown["state_context"]:
            resolved = canonical
            for component in context["json_pointer"].strip("/").split("/"):
                resolved = resolved[component]
            assert resolved["state"] == context["state"]
            assert resolved["attempt_outcome"] == context["attempt_outcome"]
    assert profile["refresh_context"]["mode"] == "baseline_no_prior_state"


def test_conflicting_claims_and_ambiguous_competitor_withhold_fact():
    for competing_state in (PublicState.AVAILABLE, PublicState.AMBIGUOUS):
        envelope = envelope_with([fact("employees", 5), fact("employees", 7, state=competing_state)])
        profile = build_profile(envelope)
        assert not sentences_for(profile, "size_fte")
        assert "conflicting_claims" in next(record for record in profile["unknowns"] if record["domain"] == "size_fte")["reasons"]


def test_duplicate_equal_claims_preserve_all_evidence_in_one_sentence():
    profile = build_profile(envelope_with([fact("employees", 0), fact("employees", 0)]))
    sentence = sentences_for(profile, "size_fte")[0]
    assert sentence["fact_ids"] == ["claim:0", "claim:1"]
    assert sentence["evidence_ids"] == ["evidence:0", "evidence:1"]
    assert "count: 0" in sentence["text"]


def test_latest_financials_never_mix_periods_or_borrow_group_values():
    older = {**financial(111), "period_start": datetime(2024, 1, 1, tzinfo=timezone.utc),
             "period_end": datetime(2024, 12, 31, tzinfo=timezone.utc)}
    group = {**financial(999999), "scope": "group", "period_end": datetime(2026, 10, 1, tzinfo=timezone.utc)}
    profile = build_profile(envelope_with([older, financial(-17), group]))
    text = " ".join(sentence["text"] for sentence in sentences_for(profile, "financials"))
    assert "-17" in text and "111" not in text and "999999" not in text
    assert "2025-04-01 to 2026-03-31" in text


def test_newer_metadata_without_verified_metrics_does_not_relabel_old_revenue_as_latest():
    metadata = fact("financial_record.period_end", "2026-10-01", section="accounts_history", family="financial_record_metadata",
                    subject_id="filing:newer", period_start=PERIOD_START,
                    period_end=datetime(2026, 10, 1, tzinfo=timezone.utc))
    profile = build_profile(envelope_with([financial(123), metadata]))
    assert not sentences_for(profile, "financials")


def test_ambiguous_latest_period_or_conflicting_metric_is_withheld():
    for changed_dimensions in ({"period_start": datetime(2025, 1, 1, tzinfo=timezone.utc)}, {"value": 456}, {"unit": "NOK"}):
        profile = build_profile(envelope_with([financial(123), {**financial(123), **changed_dimensions}]))
        assert not sentences_for(profile, "financials")


@pytest.mark.parametrize("value", [True, "unknown", float("inf")])
def test_invalid_financial_values_are_not_rendered(value):
    profile = build_profile(envelope_with([financial(value)]))
    assert not sentences_for(profile, "financials")


@pytest.mark.parametrize("dimensions", [{}, {"period_start": PERIOD_START},
                                          {"period_start": PERIOD_START, "period_end": datetime(2027, 3, 31, tzinfo=timezone.utc)},
                                          {"period_start": PERIOD_START, "period_end": PERIOD_END, "unit": "people"}])
def test_fte_requires_exact_past_period_and_fte_unit(dimensions):
    record = fact("full_time_equivalents", 17, section="hiring_activity", family="workforce", unit="FTE")
    profile = build_profile(envelope_with([{**record, **dimensions}]))
    assert not sentences_for(profile, "size_fte")


def test_financial_period_scope_unit_or_wrong_company_mutations_fail_closed():
    for attribute, value in (("period_start", None), ("scope", "unknown"), ("unit", "USD"),
                              ("organisation_number", "123456789")):
        envelope = envelope_with([financial(5)])
        setattr(envelope.claims[0], attribute, value)
        with pytest.raises(ValueError):
            build_profile(envelope)


def test_mutated_or_missing_evidence_cannot_cross_helper_boundary():
    for mutation in ("evidence_company", "snapshot_hash", "missing_evidence", "snapshot_url"):
        envelope = envelope_with([fact("name", "Example AS")])
        if mutation == "evidence_company":
            envelope.evidence[0].subject_organisation_number = "123456789"
        elif mutation == "snapshot_hash":
            envelope.source_snapshots[0].content_sha256 = "f" * 64
        elif mutation == "snapshot_url":
            envelope.source_snapshots[0].source_url = "https://other.invalid/"
        else:
            envelope.evidence.clear()
        with pytest.raises(ValueError):
            build_profile(envelope)


def test_role_names_are_joined_only_inside_their_exact_evidence_row():
    envelope = envelope_with([role("name", "Alice", 0), role("role_description", "CEO", 0),
                              role("name", "Bob", 1), role("role_description", "CFO", 1), role("inactive", True, 1)])
    sentences = sentences_for(build_profile(envelope), "leadership")
    assert len(sentences) == 2
    assert any("Alice; role CEO" in sentence["text"] for sentence in sentences)
    assert any("Bob; role CFO; inactive true" in sentence["text"] for sentence in sentences)
    assert not any("Alice; role CFO" in sentence["text"] for sentence in sentences)
    assert all("current" not in sentence["text"] for sentence in sentences)


def test_ambiguous_or_unbound_role_rows_do_not_create_leadership_fact():
    for facts in ([role("name", "Alice", 0), role("role_description", "CEO", 1)],
                  [role("name", "Alice", 0), role("name", "Bob", 0), role("role_description", "CEO", 0)]):
        assert not sentences_for(build_profile(envelope_with(facts)), "leadership")


@pytest.mark.parametrize("date_record", [None, fact("source_published_at", CUTOFF.isoformat()),
                                        footprint("source_published_at", {"normalized_utc": CUTOFF.isoformat()}),
                                        footprint("source_published_at", publication("2027-01-01")),
                                        footprint("source_published_at", {**publication(), "normalized_utc": CUTOFF.isoformat()})])
def test_activity_requires_real_source_date_not_retrieval_or_undated_title(date_record):
    facts = [footprint("activity_headline", "Undated launch", as_of=CUTOFF)]
    if date_record:
        facts.append(date_record)
    assert not sentences_for(build_profile(envelope_with(facts)), "dated_activity")


def test_activity_date_must_belong_to_same_subject():
    profile = build_profile(envelope_with([footprint("activity_headline", "Launch"),
                                          footprint("source_published_at", publication(), subject_id="article:other")]))
    assert not sentences_for(profile, "dated_activity")


def test_closed_job_is_not_presented_as_current_hiring_and_modified_date_is_not_publication():
    envelope = envelope_with([footprint("job_title", "Engineer", family="jobs", subject_id="job:1"),
                              footprint("posting_date", publication(), family="jobs", subject_id="job:1", as_of=CUTOFF),
                              footprint("job_status", "closed", family="jobs", subject_id="job:1")])
    sentence = sentences_for(build_profile(envelope), "hiring")[0]
    assert "recorded status closed" in sentence["text"] and "2026-10-01" in sentence["text"]
    assert "currently hiring" not in sentence["text"]


def test_refresh_summary_requires_resolvable_current_claim_and_full_event_evidence():
    envelope = envelope_with([fact("employees", 5)])
    event = ChangeEvent(event_id="change:1", type=ChangeType.CLAIM_CHANGED, organisation_number=ORGANISATION,
                        section="identity_brand", field="employees", old_value=3, new_value=5, observed_at=CUTOFF,
                        current_evidence=[ChangeEvidenceRef.model_validate(envelope.evidence[0].model_dump())],
                        current_source_snapshots=[ChangeSnapshotRef.model_validate(envelope.source_snapshots[0].model_dump())],
                        provenance_complete=True)
    envelope.refresh = RefreshState(mode="compared", previous_state_ref="previous", changes=[event])
    sentence = sentences_for(build_profile(envelope), "refresh_changes")[0]
    assert sentence["fact_ids"] == ["claim:0"] and sentence["change_ids"] == ["change:1"]
    assert "observed" in sentence["text"] and "effective" not in sentence["text"]
    event.new_value = None
    event.type = ChangeType.CLOSED_JOB
    profile = build_profile(envelope)
    assert not sentences_for(profile, "refresh_changes")
    assert next(record for record in profile["unknowns"] if record["domain"] == "refresh_changes")["change_ids"] == ["change:1"]


def test_profile_validation_rejects_edited_text_ids_evidence_states_and_injected_fields():
    envelope = envelope_with([fact("name", "Example AS")])
    for mutation in ("text", "fact_ids", "evidence_ids", "sentence_id", "state", "unknown_key"):
        profile = build_profile(envelope)
        if mutation == "state":
            profile["unknowns"][0]["state_context"][0]["state"] = "available_fake"
        elif mutation == "unknown_key":
            profile["unbound_financial_prose"] = "A billion in revenue"
        else:
            profile["sentences"][0][mutation] = ["missing"] if mutation.endswith("ids") else "Unsupported 99999"
        with pytest.raises(ValueError):
            validate_profile(envelope, profile)
    summary = synthesize(envelope)
    summary["profile"]["sentences"][0]["text"] = "Invented fact"
    with pytest.raises(ValueError):
        validate_synthesis(envelope, summary)


def test_profile_schema_extension_is_allowed_only_at_summary_profile_path():
    profile = build_profile(envelope_with())
    validate_profile_schema(profile)
    with pytest.raises(ValueError):
        validate_synthesis_schema({"website_research": {"profile": profile}})
    malformed = copy.deepcopy(profile)
    malformed["unknowns"][0]["state_context"][0]["invented_fact"] = "Unsupported"
    with pytest.raises(ValueError):
        validate_profile_schema(malformed)
