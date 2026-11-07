from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from norway_company_agent.batch import validate_envelopes
from signalpost.adapter import from_evaluator, to_evaluator
from signalpost.models import PublicState, RunError
from test_signalpost_checkpoint_publication import envelope_fixture
from test_signalpost_consumer_wire_compat import _wire_row


@pytest.mark.parametrize("state,legacy", [
    (PublicState.AVAILABLE, "complete"),
    (PublicState.NOT_AVAILABLE, "not_found"),
    (PublicState.NOT_APPLICABLE, "not_applicable"),
    (PublicState.BLOCKED, "blocked_policy"),
    (PublicState.AMBIGUOUS, "submission_error"),
    (PublicState.FAILED, "submission_error"),
])
def test_public_and_legacy_terminal_vocabularies(state, legacy):
    envelope = envelope_fixture(graph=False)
    envelope.terminal_state = state
    payload = to_evaluator(envelope)
    assert payload["terminal_state"] == state.value
    assert payload["state"] == legacy
    assert payload["run"]["terminal_status"] == legacy
    assert validate_envelopes([payload], 1)["passed"]
    assert all(section["state"] in {value.value for value in PublicState}
               for section in payload["sections"].values())


@pytest.mark.parametrize("outcome", [None, "", "not_checked", "deadline_skipped"])
def test_null_section_outcome_roundtrip_is_lossless(outcome):
    envelope = envelope_fixture(graph=False)
    for section in envelope.sections.values():
        section.attempt_outcome = outcome
    published = to_evaluator(envelope)
    restored = from_evaluator(published, envelope.row_number)
    assert restored.sections == envelope.sections
    assert from_evaluator(to_evaluator(restored), restored.row_number) == restored


def test_modules_include_only_executed_phases_and_confidence_stays_null():
    payload = to_evaluator(from_evaluator(_wire_row()), {
        "phase_statuses": {"official": {"outcome": "completed", "seconds": 1.25},
                           "finance": {"outcome": "failed", "seconds": 0.75},
                           "website": {"outcome": "not_attempted", "seconds": 0}},
        "requests": 2, "runtime_ms": 2000,
    })
    assert set(payload["modules"]) == {"official", "finance"}
    assert validate_envelopes([payload], 1)["passed"]
    assert payload["operations"] == {"requests": 2, "runtime_ms": 2000, "third_party_cost_usd": 0}
    assert payload["operation_log"] == []
    assert all(claim["confidence"] is None for claim in payload["claims"])
    assert all(claim["availability"] == claim["state"] for claim in payload["claims"])
    assert all(evidence["id"] == evidence["evidence_id"] for evidence in payload["evidence"])
    assert all(evidence["claim_span"] == evidence["excerpt"] for evidence in payload["evidence"])


def test_conflicting_section_state_alias_is_rejected():
    payload = to_evaluator(envelope_fixture())
    modified = copy.deepcopy(payload)
    modified["sections"]["identity_brand"]["state"] = "available"
    modified["sections"]["identity_brand"]["availability"] = "available"
    with pytest.raises(ValueError, match="section state aliases"):
        from_evaluator(modified)


def test_robots_blocked_run_has_consistent_terminal_aliases():
    envelope = envelope_fixture(graph=False)
    envelope.terminal_state = PublicState.BLOCKED
    envelope.errors = [RunError(code="ROBOTS_DENIED", message="robots disallow")]
    payload = to_evaluator(envelope)
    assert payload["state"] == payload["run"]["terminal_status"] == "blocked_robots"
    assert from_evaluator(payload).terminal_state == PublicState.BLOCKED
    payload["run"]["terminal_status"] = "blocked_policy"
    with pytest.raises(ValueError, match="run terminal status"):
        from_evaluator(payload)
