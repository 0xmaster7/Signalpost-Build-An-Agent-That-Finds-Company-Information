from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from signalpost.adapter import _evaluator_change, to_evaluator
from signalpost.history import (SOURCE_POLICY_VERSION, CompanyState, PriorStateError, artifact_payload, claim_fingerprint,
    compare_states, company_state, merge_prior_facts, sha256_json, validate_artifact)
from signalpost.models import (Claim, Envelope, Evidence, PublicState, RefreshState, Section,
    SourceSnapshot, website_claim_value_digest)
from signalpost.run import main

ORG = "923609016"
CUTOFF = datetime(2026, 10, 4, tzinfo=timezone.utc)
CONFIG = "a" * 64
SECTIONS = {name: Section(state=PublicState.AVAILABLE) for name in (
    "identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
    "hiring_activity", "claims_evidence_states", "refresh_changes")}


def make_envelope(specs: list[dict], *, retrieved: datetime | None = None,
                  roles_complete: bool = False, workplaces_complete: bool = False,
                  identity_state: PublicState = PublicState.AVAILABLE,
                  website_state: PublicState = PublicState.AVAILABLE,
                  job_outcome: str | None = "completed") -> Envelope:
    retrieved = retrieved or CUTOFF - timedelta(hours=1)
    claims, evidence, snapshots = [], [], []
    for index, spec in enumerate(specs):
        digest = hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        evidence_id, snapshot_id = f"e{index}", f"s{index}"
        url = spec.get("source_url", "https://data.brreg.no/enhetsregisteret/api/enheter/" + ORG)
        evidence.append(Evidence(evidence_id=evidence_id, source_url=url, retrieved_at=retrieved,
            content_sha256=digest, extraction_method=spec.get("extraction_method", "json_pointer_v1"),
            json_pointer=spec.get("json_pointer", "/value"), subject_organisation_number=ORG,
            source_snapshot_ids=[snapshot_id]))
        snapshots.append(SourceSnapshot(source_id=snapshot_id, source_url=url, retrieved_at=retrieved,
            content_sha256=digest, http_status=200))
        claims.append(Claim(claim_id=(f"c{index}:" + website_claim_value_digest(spec["field"], spec["value"])
            if spec.get("family") == "owned_web" else f"c{index}"), organisation_number=ORG,
            section=spec.get("section", "identity_brand"), field_family=spec.get("family", "identity"),
            subject_id=spec.get("subject", ORG), field=spec["field"], value=spec["value"],
            state=spec.get("state", PublicState.AVAILABLE),
            unit=spec.get("unit", "NOK" if spec.get("family") == "financial" else None),
            currency=spec.get("currency"), period_start=spec.get("period_start"),
            period_end=spec.get("period_end"), as_of=spec.get("as_of"), scope=spec.get("scope", "legal_entity"),
            verification_rule_id="fixture_exact_org_v1", verification_score="1.0",
            evidence_ids=[evidence_id], source_snapshot_ids=[snapshot_id]))
    if roles_complete or workplaces_complete:
        digest = hashlib.sha256(b"complete collection").hexdigest()
        snapshot_id = "s-complete"
        evidence_id = "e-roles-complete" if roles_complete else "e-workplaces-complete"
        url = "https://data.brreg.no/enhetsregisteret/api/enheter/" + ORG + ("/roller" if roles_complete else "/underenheter")
        evidence.append(Evidence(evidence_id=evidence_id, source_url=url, retrieved_at=retrieved,
            content_sha256=digest, extraction_method="brreg_complete_collection_v1", json_pointer="/",
            subject_organisation_number=ORG, source_snapshot_ids=[snapshot_id]))
        snapshots.append(SourceSnapshot(source_id=snapshot_id, source_url=url, retrieved_at=retrieved,
            content_sha256=digest, http_status=200))
    sections = copy.deepcopy(SECTIONS)
    for claim in claims:
        sections[claim.section].claims.append(claim)
        sections["claims_evidence_states"].claims.append(claim)
    if roles_complete:
        sections["leadership_workplaces"].diagnostics.append("roles_completeness_evidence_id:e-roles-complete")
    if workplaces_complete:
        sections["leadership_workplaces"].diagnostics.append(
            "workplaces_completeness_evidence_id:e-workplaces-complete")
    sections["identity_brand"].state = identity_state
    sections["website_owned_profiles"].state = website_state
    sections["website_owned_profiles"].attempt_outcome = "completed" if website_state == PublicState.AVAILABLE else "failed"
    sections["hiring_activity"].attempt_outcome = job_outcome
    synthesis = {"brreg_observations": {
        "roles_completeness_evidence_id": "e-roles-complete" if roles_complete else None,
        "workplaces_complete": workplaces_complete,
        "workplaces_completeness_evidence_id": "e-workplaces-complete" if workplaces_complete else None,
    }}
    return Envelope(input_ref="row:1", row_number=1, organisation_number=ORG,
        terminal_state=PublicState.AVAILABLE, sections=sections, refresh=RefreshState(),
        synthesis=synthesis, claims=claims, evidence=evidence, source_snapshots=snapshots,
        batch_id="m07-test", evidence_cutoff=CUTOFF)


def state(envelope: Envelope, previous: CompanyState | None = None) -> CompanyState:
    return company_state(envelope, CONFIG, previous)


def changes(old: Envelope, new: Envelope) -> list[dict]:
    return compare_states(state(old), state(new), cutoff=CUTOFF,
        previous_ref="sha256:old", current_ref="sha256:new")


class CanonicalRefreshTests(unittest.TestCase):
    def test_page_descriptions_compare_only_the_same_source_resource(self):
        def description(value, url):
            return {"field": "website_description", "value": value, "family": "owned_web",
                    "section": "website_owned_profiles", "source_url": url,
                    "extraction_method": "website_html_extract_v1"}
        home = description("Company overview.", "https://company.no/")
        article = description("A legal article.", "https://company.no/news/article")
        old = make_envelope([home])
        expanded = make_envelope([home, article])
        events = changes(old, expanded)
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["old_value"])
        self.assertEqual(events[0]["new_value"], "A legal article.")
        self.assertEqual(changes(expanded, expanded), [])
        edited = make_envelope([description("Updated company overview.", "https://company.no/"), article])
        updates = changes(expanded, edited)
        self.assertEqual([(e["old_value"], e["new_value"]) for e in updates],
                         [("Company overview.", "Updated company overview.")])
        corroborated = make_envelope([home, description("Company overview.", "https://company.no/about")])
        self.assertEqual(changes(old, corroborated), [])

    def test_unchanged_snapshot_and_repeated_refresh_are_idempotent(self):
        env = make_envelope([{"field": "legal_name", "value": "Example AS"}])
        prior, current = state(env), state(env)
        first = compare_states(prior, current, cutoff=CUTOFF, previous_ref="old", current_ref="new")
        second = compare_states(prior, current, cutoff=CUTOFF, previous_ref="old", current_ref="new")
        self.assertEqual(first, [])
        self.assertEqual(second, first)

    def test_retrieval_timestamp_does_not_create_material_change(self):
        old = make_envelope([{"field": "legal_name", "value": "Example AS"}], retrieved=CUTOFF - timedelta(days=2))
        new = make_envelope([{"field": "legal_name", "value": "Example AS"}], retrieved=CUTOFF - timedelta(days=1))
        self.assertEqual(changes(old, new), [])
        self.assertNotEqual(state(old).observation_ids, state(new).observation_ids)
        self.assertEqual(state(old).snapshot_content_ids, state(new).snapshot_content_ids)

    def test_changed_source_bytes_with_same_canonical_claim_are_not_a_value_change(self):
        old = make_envelope([{"field": "legal_name", "value": "Example AS", "extraction_method": "extractor-v1"}])
        new = make_envelope([{"field": "legal_name", "value": "Example AS", "extraction_method": "extractor-v2"}])
        self.assertNotEqual(state(old).snapshots[0]["content_sha256"], state(new).snapshots[0]["content_sha256"])
        self.assertEqual(changes(old, new), [])

    def test_claim_and_evidence_order_does_not_create_change(self):
        specs = [{"field": "legal_name", "value": "Example AS"}, {"field": "legal_form", "value": "AS"}]
        old, new = make_envelope(specs), make_envelope(list(reversed(specs)))
        self.assertEqual({claim_fingerprint(item) for item in state(old).claims},
                         {claim_fingerprint(item) for item in state(new).claims})
        self.assertEqual(changes(old, new), [])

    def test_duplicate_observations_are_collapsed_without_duplicate_events(self):
        one = make_envelope([{"field": "legal_name", "value": "Example AS"}])
        duplicate = make_envelope([{"field": "legal_name", "value": "Example AS"},
                                   {"field": "legal_name", "value": "Example AS"}])
        self.assertEqual(len(state(duplicate).claims), 1)
        events = changes(one, duplicate)
        self.assertEqual(events, [])

    def test_real_scalar_update_and_legitimate_addition(self):
        old = make_envelope([{"field": "legal_name", "value": "Example AS"}])
        update = make_envelope([{"field": "legal_name", "value": "Example Norge AS"}])
        addition = make_envelope([{"field": "legal_name", "value": "Example AS"},
                                  {"field": "legal_form", "value": "AS"}])
        self.assertEqual([event["type"] for event in changes(old, update)], ["brand_changed"])
        self.assertEqual([event["type"] for event in changes(old, addition)], ["claim_changed"])

    def test_website_and_brand_identity_changes_have_typed_events(self):
        old = make_envelope([{"field": "website", "value": "https://example.no/"}])
        new = make_envelope([{"field": "website", "value": "https://example.org"}])
        self.assertEqual(changes(old, make_envelope([{"field": "website", "value": "example.no"}])), [])
        self.assertEqual([event["type"] for event in changes(old, new)], ["website_changed"])
        brand_old = make_envelope([{"field": "legal_name", "value": "Example AS"}])
        brand_new = make_envelope([{"field": "legal_name", "value": "New Example AS"}])
        self.assertEqual([event["type"] for event in changes(brand_old, brand_new)], ["brand_changed"])
        malformed_url = make_envelope([{"field": "website_url", "value": "https://example.no:notaport"}])
        self.assertEqual(changes(malformed_url, malformed_url), [])

    def test_supported_role_and_workplace_removals_need_complete_current_source(self):
        role = {"field": "role.name", "family": "role", "section": "leadership_workplaces",
                "scope": "person_role", "value": "Person A"}
        old = make_envelope([role])
        omitted_incomplete = make_envelope([], roles_complete=False)
        omitted_complete = make_envelope([], roles_complete=True)
        self.assertEqual(changes(old, omitted_incomplete), [])
        ended = changes(old, omitted_complete)
        self.assertEqual([event["type"] for event in ended], ["ended_role"])
        self.assertTrue(ended[0]["provenance_complete"])
        self.assertEqual(ended[0]["removal_confirmation_evidence_ids"], ["e-roles-complete"])

        workplace = {"field": "workplace.organisasjonsnummer", "family": "workplace", "section": "leadership_workplaces",
                     "subject": "923609025", "scope": "workplace", "value": "Office"}
        old_workplace = make_envelope([workplace])
        self.assertEqual(changes(old_workplace, make_envelope([], workplaces_complete=False)), [])
        closed = changes(old_workplace, make_envelope([], workplaces_complete=True))
        self.assertEqual([event["type"] for event in closed], ["closed_workplace"])
        self.assertTrue(closed[0]["removal_confirmation_evidence_ids"])

    def test_unbound_synthesis_cannot_claim_complete_role_or_website_coverage(self):
        role = {"field": "role.name", "family": "role", "section": "leadership_workplaces",
                "scope": "person_role", "value": "Person A"}
        old = make_envelope([role], roles_complete=True)
        incomplete = make_envelope([], roles_complete=False, website_state=PublicState.FAILED)
        incomplete.synthesis["brreg_observations"] = {
            "roles_completeness_evidence_id": "e-roles-complete",
            "workplaces_complete": True,
            "workplaces_completeness_evidence_id": "forged-evidence",
        }
        incomplete.synthesis["website_research"] = {"execution_state": "completed", "crawl_state": "available"}
        events = changes(old, incomplete)
        self.assertFalse(any(event["type"] in {"ended_role", "closed_workplace"} for event in events))
        coverage = state(incomplete).coverage
        self.assertFalse(coverage["_roles"]["complete"])
        self.assertFalse(coverage["_workplaces"]["complete"])
        self.assertFalse(coverage["_website"]["complete"])

    def test_role_and_workplace_additions_are_typed_and_deduplicated(self):
        role = {"field": "role.name", "family": "role", "section": "leadership_workplaces",
                "scope": "person_role", "value": "Person A"}
        self.assertEqual([event["type"] for event in changes(make_envelope([]), make_envelope([role]))], ["new_role"])
        workplace = {"field": "workplace.organisasjonsnummer", "family": "workplace", "section": "leadership_workplaces",
                     "subject": "923609025", "scope": "workplace", "value": "Office"}
        duplicated = make_envelope([workplace, workplace])
        self.assertEqual([event["type"] for event in changes(make_envelope([]), duplicated)], ["new_workplace"])

    def test_failed_blocked_malformed_partial_and_unattempted_sources_do_not_remove(self):
        old = make_envelope([{"field": "legal_name", "value": "Example AS"}])
        for state_value, outcome in ((PublicState.FAILED, "transport_failed"),
                                     (PublicState.BLOCKED, "policy_skipped"),
                                     (PublicState.AMBIGUOUS, "malformed"),
                                     (None, "not_attempted"),
                                     (None, "budget_skipped")):
            current = make_envelope([], identity_state=state_value)
            current.sections["identity_brand"].attempt_outcome = outcome
            self.assertEqual(changes(old, current), [], outcome)

    def test_source_became_unavailable_is_an_observation_not_a_fact_removal(self):
        old = make_envelope([{"field": "legal_name", "value": "Example AS"}])
        failed = make_envelope([], identity_state=PublicState.FAILED)
        digest = hashlib.sha256(b"503 source response").hexdigest()
        failed.evidence.append(Evidence(evidence_id="source-state", source_url="https://data.brreg.no/state",
            retrieved_at=CUTOFF, content_sha256=digest, extraction_method="brreg_entity_state_v1",
            json_pointer="/", subject_organisation_number=ORG, source_snapshot_ids=["source-state-snapshot"]))
        failed.source_snapshots.append(SourceSnapshot(source_id="source-state-snapshot",
            source_url="https://data.brreg.no/state", retrieved_at=CUTOFF, content_sha256=digest, http_status=503))
        failed.sections["identity_brand"].diagnostics = ["identity_state_evidence:source-state"]
        events = changes(old, failed)
        self.assertEqual([item["type"] for item in events], ["source_became_unavailable"])
        self.assertEqual(events[0]["old_value"], "available")
        self.assertEqual(events[0]["new_value"], "failed")
        self.assertTrue(events[0]["provenance_complete"])

    def test_job_open_close_and_missing_after_failed_crawl(self):
        base = {"family": "jobs", "section": "hiring_activity", "scope": "job", "subject": "https://example.no/jobs/1"}
        opened = make_envelope([{**base, "field": "job_title", "value": "Engineer"},
                                {**base, "field": "job_status", "value": "open"}])
        opened_events = changes(make_envelope([]), opened)
        self.assertEqual(sum(event["type"] == "new_job" for event in opened_events), 1)
        current_open = make_envelope([{**base, "field": "job_status", "value": "open"}])
        current_closed = make_envelope([{**base, "field": "job_status", "value": "closed"}])
        self.assertEqual([event["type"] for event in changes(current_open, current_closed)], ["closed_job"])
        missing = make_envelope([], job_outcome="transport_failed")
        self.assertEqual(changes(opened, missing), [])

    def test_activity_addition_and_wrong_subject_claim_is_not_target_history(self):
        activity = {"family": "public_activity", "section": "hiring_activity", "scope": "event",
                    "subject": "event:target-1", "field": "activity_headline", "value": "Target event"}
        self.assertEqual([event["type"] for event in changes(make_envelope([]), make_envelope([activity]))], ["new_activity"])
        # An ambiguous rival/customer/subsidiary observation is not a published claim.
        rival = make_envelope([{**activity, "subject": "event:rival", "source_url": "https://rival.example/news",
                                "state": PublicState.AMBIGUOUS}])
        self.assertEqual(changes(make_envelope([]), rival), [])

    def test_temporal_effective_date_is_preserved_and_post_cutoff_change_excluded(self):
        old = make_envelope([{"field": "legal_name", "value": "Old AS", "as_of": "2026-10-01T00:00:00Z"}])
        new_known = make_envelope([{"field": "legal_name", "value": "New AS", "as_of": "2026-10-02T00:00:00Z"}])
        event = changes(old, new_known)[0]
        self.assertEqual(event["effective_at"], "2026-10-02T00:00:00Z")
        self.assertNotEqual(event["observed_at"], event["effective_at"])
        future = make_envelope([{"field": "legal_name", "value": "Future AS", "as_of": "2026-10-05T00:00:00Z"}])
        self.assertEqual(changes(old, future), [])
        unknown = make_envelope([{"field": "legal_name", "value": "Unknown Date AS"}])
        self.assertIsNone(changes(old, unknown)[0]["effective_at"])

    def test_new_financial_period_is_not_overwrite_and_corrected_filing_is_typed(self):
        common = {"family": "financial", "section": "accounts_history", "scope": "legal_entity",
                  "currency": "NOK", "field": "operating_revenue", "value": 100}
        old = make_envelope([{**common, "period_start": "2024-01-01T00:00:00Z", "period_end": "2024-12-31T00:00:00Z"}])
        new_period = make_envelope([{**common, "period_start": "2024-01-01T00:00:00Z", "period_end": "2024-12-31T00:00:00Z"},
                                    {**common, "period_start": "2025-01-01T00:00:00Z", "period_end": "2025-12-31T00:00:00Z", "value": 120}])
        self.assertEqual([event["type"] for event in changes(old, new_period)], ["new_filing"])
        corrected = make_envelope([{**common, "period_start": "2024-01-01T00:00:00Z",
                                    "period_end": "2024-12-31T00:00:00Z", "value": 110}])
        self.assertEqual([event["type"] for event in changes(old, corrected)], ["corrected_filing"])
        zero = make_envelope([{**common, "period_start": "2024-01-01T00:00:00Z",
                               "period_end": "2024-12-31T00:00:00Z", "value": 0}])
        self.assertEqual(changes(make_envelope([{**common, "period_start": "2024-01-01T00:00:00Z",
            "period_end": "2024-12-31T00:00:00Z", "value": 1}]), zero)[0]["new_value"], 0)

    def test_prior_financial_versions_remain_in_state_when_corrected_or_new_period_arrives(self):
        common = {"family": "financial", "section": "accounts_history", "scope": "legal_entity",
                  "currency": "NOK", "field": "operating_revenue", "value": 100}
        old = state(make_envelope([{**common, "period_start": "2024-01-01T00:00:00Z",
                                   "period_end": "2024-12-31T00:00:00Z"}]))
        corrected = state(make_envelope([{**common, "period_start": "2024-01-01T00:00:00Z",
            "period_end": "2024-12-31T00:00:00Z", "value": 110}]), old)
        corrected = merge_prior_facts(corrected, old)
        self.assertEqual({item["value"] for item in corrected.claims}, {100, 110})
        self.assertEqual([item["type"] for item in compare_states(old, corrected, cutoff=CUTOFF,
            previous_ref="old", current_ref="new")], ["corrected_filing"])
        next_period = state(make_envelope([{**common, "period_start": "2025-01-01T00:00:00Z",
            "period_end": "2025-12-31T00:00:00Z", "value": 120}]), old)
        next_period = merge_prior_facts(next_period, old)
        self.assertEqual({item["period_start"][:4] for item in next_period.claims}, {"2024", "2025"})
        self.assertEqual([item["type"] for item in compare_states(old, next_period, cutoff=CUTOFF,
            previous_ref="old", current_ref="new")], ["new_filing"])

    def test_unsupported_financial_metadata_is_not_published_as_fact_or_change(self):
        invalid = {"family": "financial", "section": "accounts_history", "scope": "unknown",
                   "currency": None, "field": "operating_revenue", "value": 100,
                   "state": PublicState.AMBIGUOUS}
        env = make_envelope([invalid])
        self.assertEqual(state(env).claims, [])
        self.assertEqual(changes(make_envelope([]), env), [])


class PriorStateAndProvenanceTests(unittest.TestCase):
    def test_artifact_round_trip_is_deterministic_and_versioned(self):
        company = state(make_envelope([{"field": "legal_name", "value": "Example AS"}]))
        artifact = artifact_payload({ORG: company}, CONFIG)
        validated = validate_artifact(artifact)
        serialized = json.dumps(validated.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        self.assertEqual(json.loads(serialized)["schema_version"], 1)
        self.assertEqual(artifact_payload({ORG: company}, CONFIG), artifact)

    def test_wrong_company_claim_and_identity_mismatch_are_rejected(self):
        company = state(make_envelope([{"field": "legal_name", "value": "Example AS"}])).model_dump(mode="json")
        company["claims"][0]["organisation_number"] = "923609025"
        raw = {"schema_version": 1, "source_policy_version": SOURCE_POLICY_VERSION,
               "configuration_fingerprint": CONFIG, "companies": {ORG: company}}
        with self.assertRaises(PriorStateError):
            validate_artifact(raw)
        company = state(make_envelope([])).model_dump(mode="json")
        company["organisation_number"] = "923609025"
        raw["companies"] = {ORG: company}
        with self.assertRaises(PriorStateError):
            validate_artifact(raw)

    def test_malformed_and_incompatible_prior_state_are_rejected(self):
        for raw in ({"garbage": True}, {"schema_version": 2, "source_policy_version": SOURCE_POLICY_VERSION,
                      "configuration_fingerprint": CONFIG, "companies": {}}):
            with self.assertRaises(PriorStateError):
                validate_artifact(raw)

    def test_missing_evidence_or_snapshot_reference_is_rejected(self):
        company = state(make_envelope([{"field": "legal_name", "value": "Example AS"}])).model_dump(mode="json")
        company["claims"][0]["evidence_ids"] = ["missing"]
        raw = {"schema_version": 1, "source_policy_version": SOURCE_POLICY_VERSION,
               "configuration_fingerprint": CONFIG, "companies": {ORG: company}}
        with self.assertRaises(PriorStateError):
            validate_artifact(raw)

    def test_tampered_snapshot_content_or_observation_identity_is_rejected(self):
        company = state(make_envelope([{"field": "legal_name", "value": "Example AS"}])).model_dump(mode="json")
        company["snapshot_content_ids"] = ["snapshot:" + "0" * 64]
        raw = {"schema_version": 1, "source_policy_version": SOURCE_POLICY_VERSION,
               "configuration_fingerprint": CONFIG, "companies": {ORG: company}}
        with self.assertRaisesRegex(PriorStateError, "snapshot or observation identities"):
            validate_artifact(raw)

    def test_retrieval_only_changes_update_observation_but_not_fact_fingerprint(self):
        old = state(make_envelope([{"field": "legal_name", "value": "Example AS"}], retrieved=CUTOFF - timedelta(days=2)))
        new = state(make_envelope([{"field": "legal_name", "value": "Example AS"}], retrieved=CUTOFF - timedelta(days=1)), previous=old)
        self.assertEqual(set(old.first_observed), set(new.first_observed))
        self.assertEqual(old.first_observed, new.first_observed)
        self.assertNotEqual(old.last_observed, new.last_observed)

    def test_every_change_has_prior_current_fingerprints_and_traceable_evidence(self):
        old = make_envelope([{"field": "legal_name", "value": "Old AS"}])
        new = make_envelope([{"field": "legal_name", "value": "New AS"}])
        event = changes(old, new)[0]
        self.assertTrue(event["previous_claim_fingerprint"])
        self.assertTrue(event["current_claim_fingerprint"])
        self.assertTrue(event["previous_evidence"])
        self.assertTrue(event["current_evidence"])
        self.assertEqual(event["previous_evidence"][0]["content_sha256"], state(old).evidence[0]["content_sha256"])
        self.assertEqual(event["previous_source_snapshots"][0]["content_sha256"], state(old).snapshots[0]["content_sha256"])
        self.assertTrue(event["provenance_complete"])
        self.assertTrue(event["previous_state_ref"] and event["current_state_ref"])

    def test_adapter_maps_only_supported_canonical_change_enums(self):
        env = make_envelope([{"field": "legal_name", "value": "Example AS"}])
        env.refresh.changes = [{"event_id": "c1", "type": "brand_changed", "organisation_number": ORG,
            "observed_at": CUTOFF, "previous_state_ref": "old", "current_state_ref": "new",
            "provenance_complete": True}]
        self.assertEqual(to_evaluator(env)["refresh"]["changes"][0]["type"], "brand_changed")
        with self.assertRaisesRegex(ValueError, "unsupported canonical change type"):
            _evaluator_change({"event_id": "c1", "type": "invented_type"})
        with self.assertRaises(ValueError):
            env.refresh.changes = [{"event_id": "c1", "type": "invented_type", "organisation_number": ORG,
                "observed_at": CUTOFF, "provenance_complete": True}]

    def test_self_or_wrong_parent_workplace_relations_cannot_become_removal_facts(self):
        # The production BRREG normalizer withholds these rows; history receives
        # no workplace claim, so it cannot publish a relationship transition.
        self.assertEqual(changes(make_envelope([]), make_envelope([], workplaces_complete=True)), [])


class RunnerHandoffIntegrationTests(unittest.TestCase):
    def _run(self, root: Path, name: str, input_path: Path, registry: Path,
             state_out: Path, checkpoint: Path, previous: Path | None = None, resume: bool = False,
             config: Path | None = None) -> list[dict]:
        output = root / f"{name}.jsonl"
        args = ["--input", str(input_path), "--format", "jsonl", "--registry-snapshot", str(registry),
                "--output", str(output), "--state-output", str(state_out), "--checkpoint", str(checkpoint),
                "--evidence-cutoff", "2026-10-03T00:00:00Z", "--batch-id", name]
        if previous:
            args.extend(["--previous-state", str(previous)])
        if config:
            args.extend(["--config", str(config)])
        if resume:
            args.append("--resume")
        self.assertEqual(main(args), 0)
        return [json.loads(line) for line in output.read_text().splitlines()]

    def test_runner_baseline_compare_duplicate_rows_and_atomic_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            input_path.write_text(json.dumps({"organisation_number": ORG}) + "\n" +
                                  json.dumps({"organisation_number": ORG}) + "\n")
            old_registry, new_registry = root / "old.jsonl", root / "new.jsonl"
            old_registry.write_text(json.dumps({"orgnr": ORG, "name": "Old Example AS"}) + "\n")
            new_registry.write_text(json.dumps({"orgnr": ORG, "name": "New Example AS"}) + "\n")
            old_state, new_state = root / "old-state.json", root / "new-state.json"
            old_rows = self._run(root, "baseline", input_path, old_registry, old_state, root / "old.sqlite")
            self.assertEqual(len(old_rows), 2)
            self.assertTrue(all(row["refresh"]["mode"] == "baseline_no_prior_state" for row in old_rows))
            self.assertTrue(all(not row["refresh"]["changes"] for row in old_rows))
            new_rows = self._run(root, "refresh", input_path, new_registry, new_state, root / "new.sqlite", old_state)
            self.assertEqual([row["input_ref"] for row in new_rows], ["row:1", "row:2"])
            self.assertTrue(all(row["refresh"]["mode"] == "compared" for row in new_rows))
            self.assertEqual([len(row["refresh"]["changes"]) for row in new_rows], [1, 1])
            self.assertEqual(new_rows[0]["refresh"]["changes"][0]["event_id"],
                             new_rows[1]["refresh"]["changes"][0]["event_id"])
            self.assertTrue(new_state.exists())
            self.assertNotEqual(json.loads(old_state.read_text())["companies"][ORG]["snapshot_content_ids"],
                                json.loads(new_state.read_text())["companies"][ORG]["snapshot_content_ids"])

    def test_unavailable_source_retains_prior_facts_without_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.jsonl"
            input_path.write_text(json.dumps({"organisation_number": ORG}) + "\n")
            populated, missing = root / "populated.jsonl", root / "missing.jsonl"
            populated.write_text(json.dumps({"orgnr": ORG, "name": "Example AS"}) + "\n")
            missing.write_text("")
            old_state = root / "old-state.json"
            self._run(root, "baseline", input_path, populated, old_state, root / "old.sqlite")
            rows = self._run(root, "failed-refresh", input_path, missing, root / "new-state.json",
                             root / "new.sqlite", old_state)
            self.assertEqual(rows[0]["refresh"]["changes"], [])
            current_state = json.loads((root / "new-state.json").read_text())["companies"][ORG]
            retained = current_state["claims"]
            self.assertEqual([item["value"] for item in retained], ["Example AS"])
            self.assertEqual(rows[0]["refresh"]["retained_claim_ids"], [retained[0]["claim_id"]])
            self.assertIn(retained[0]["evidence_ids"][0], {item["evidence_id"] for item in current_state["evidence"]})

    def test_malformed_previous_state_is_reported_and_does_not_make_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, registry, previous = root / "input.jsonl", root / "registry.jsonl", root / "broken.json"
            input_path.write_text(json.dumps({"organisation_number": ORG}) + "\n")
            registry.write_text(json.dumps({"orgnr": ORG, "name": "Example AS"}) + "\n")
            previous.write_text("{broken")
            rows = self._run(root, "malformed-prior", input_path, registry, root / "state.json",
                             root / "checkpoint.sqlite", previous)
            self.assertEqual(rows[0]["refresh"]["mode"], "incompatible_prior_state")
            self.assertEqual(rows[0]["refresh"]["changes"], [])
            self.assertIn("REFRESH_PRIOR_STATE_INCOMPATIBLE", [item["code"] for item in rows[0]["errors"]])

    def test_source_configuration_change_is_explicitly_incompatible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, registry = root / "input.jsonl", root / "registry.jsonl"
            input_path.write_text(json.dumps({"organisation_number": ORG}) + "\n")
            registry.write_text(json.dumps({"orgnr": ORG, "name": "Example AS"}) + "\n")
            config_old, config_new = root / "old-config.json", root / "new-config.json"
            config_old.write_text(json.dumps({"website_rights_decisions": {"example.test": "allowed"}}))
            config_new.write_text(json.dumps({"website_rights_decisions": {"example.test": "blocked"}}))
            old_state = root / "old-state.json"
            self._run(root, "config-old", input_path, registry, old_state, root / "old.sqlite", config=config_old)
            rows = self._run(root, "config-changed", input_path, registry, root / "new-state.json",
                             root / "new.sqlite", old_state, config=config_new)
            self.assertEqual(rows[0]["refresh"]["mode"], "incompatible_prior_state")
            self.assertEqual(rows[0]["refresh"]["changes"], [])

    def test_other_organisation_state_is_preserved_but_never_used_for_target(self):
        other = "923609024"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_input, old_registry = root / "old-input.jsonl", root / "old-registry.jsonl"
            old_input.write_text(json.dumps({"organisation_number": ORG}) + "\n")
            old_registry.write_text(json.dumps({"orgnr": ORG, "name": "Same Name AS"}) + "\n")
            prior = root / "prior.json"
            self._run(root, "old-company", old_input, old_registry, prior, root / "old.sqlite")
            target_input, target_registry = root / "target-input.jsonl", root / "target-registry.jsonl"
            target_input.write_text(json.dumps({"organisation_number": other}) + "\n")
            target_registry.write_text(json.dumps({"orgnr": other, "name": "Same Name AS"}) + "\n")
            rows = self._run(root, "other-company", target_input, target_registry, root / "next.json",
                             root / "next.sqlite", prior)
            self.assertEqual(rows[0]["refresh"]["mode"], "baseline_no_prior_state")
            self.assertEqual(rows[0]["refresh"]["changes"], [])
            companies = json.loads((root / "next.json").read_text())["companies"]
            self.assertEqual(set(companies), {ORG, other})

    def test_checkpoint_resume_replays_identical_history_and_snapshot_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, registry = root / "input.jsonl", root / "registry.jsonl"
            input_path.write_text(json.dumps({"organisation_number": ORG}) + "\n")
            registry.write_text(json.dumps({"orgnr": ORG, "name": "Example AS"}) + "\n")
            checkpoint = root / "checkpoint.sqlite"
            first = self._run(root, "first", input_path, registry, root / "state.json", checkpoint)
            second = self._run(root, "resume", input_path, registry, root / "state.json", checkpoint, resume=True)
            self.assertEqual(first[0]["refresh"]["changes"], second[0]["refresh"]["changes"])
            registry.write_text(json.dumps({"orgnr": ORG, "name": "Mutated Snapshot AS"}) + "\n")
            with self.assertRaisesRegex(ValueError, "fingerprint does not match"):
                self._run(root, "stale-resume", input_path, registry, root / "state.json", checkpoint, resume=True)


if __name__ == "__main__":
    unittest.main()
