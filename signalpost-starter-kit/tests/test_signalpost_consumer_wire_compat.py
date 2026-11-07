"""Consumer coverage for evaluator wire normalization at the adapter edge."""
from __future__ import annotations

import copy
import hashlib
import json

from signalpost.adapter import from_evaluator, to_evaluator
from signalpost.profile import build_profile
from signalpost.query import load_profiles
from signalpost.site_export import _read_envelope


STAMP = "2026-11-05T00:00:00Z"
SECTIONS = ("identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
            "hiring_activity", "claims_evidence_states", "refresh_changes")


def _wire_row():
    org = "001234567"
    snapshot = {"source_id": "snapshot:1", "source_url": "https://example.invalid/company",
                "retrieved_at": STAMP, "content_sha256": hashlib.sha256(b"evidence").hexdigest(),
                "http_status": 200, "rights_status": "public"}
    evidence = {"evidence_id": "evidence:1", "source_url": snapshot["source_url"], "retrieved_at": STAMP,
                "content_sha256": snapshot["content_sha256"], "extraction_method": "wire-compat-test",
                "json_pointer": "/name", "excerpt": "Example AS", "source_class": "official",
                "subject_organisation_number": org, "source_snapshot_ids": [snapshot["source_id"]]}
    claim = {"claim_id": "claim:1", "organisation_number": org, "section": "identity_brand",
             "field_family": "identity", "subject_id": org, "field": "name", "value": "Example AS",
             "state": "available", "scope": "legal_entity", "verification_rule_id": "wire-test-v1",
             "verification_score": "1", "evidence_ids": [evidence["evidence_id"]],
             "source_snapshot_ids": [snapshot["source_id"]]}
    sections = {name: {"state": "available", "attempt_outcome": None, "claims": [], "diagnostics": []}
                for name in SECTIONS}
    sections["identity_brand"]["claims"].append(copy.deepcopy(claim))
    sections["claims_evidence_states"]["claims"].append(copy.deepcopy(claim))
    return {"input_ref": "wire:1", "organisation_number": org, "terminal_state": "available",
            "sections": sections, "claims": [claim], "evidence": [evidence], "source_snapshots": [snapshot],
            "refresh": {"changes": []}, "synthesis": {}, "errors": [], "operations": [],
            "batch": {"batch_id": "wire-test", "evidence_cutoff": STAMP}, "run": {"created_at": STAMP}}


def _aliases(row):
    """Encode the alternate published names while leaving graph semantics intact."""
    result = copy.deepcopy(row)
    for item in result["evidence"]:
        item["id"] = item["evidence_id"]
        item["claim_span"] = item["excerpt"]
    for claim in result["claims"]:
        claim["evidence_ids"] = ["evidence:1"]
    for section in result["sections"].values():
        for claim in section["claims"]:
            claim["evidence_ids"] = ["evidence:1"]
    for name in ("website_owned_profiles", "hiring_activity"):
        result["sections"][name]["state"] = "not_available"
        result["sections"][name]["canonical_state"] = None
    result["operations"] = {"requests": 3, "runtime_ms": 17, "third_party_cost_usd": 0}
    result["operation_log"] = []
    return result


def test_profile_and_site_export_decode_alias_wire_claims_and_availability():
    raw = _aliases(_wire_row())
    profile = build_profile(raw)
    assert any(sentence["text"] == "Registered legal name: Example AS." for sentence in profile["sentences"])

    envelope = _read_envelope(raw, 7)
    assert envelope.row_number == 7
    assert envelope.evidence[0].evidence_id == "evidence:1"
    assert envelope.evidence[0].json_pointer == "/name"
    assert envelope.evidence[0].excerpt == "Example AS"
    assert envelope.sections["website_owned_profiles"].state is None
    assert envelope.operations == []


def test_wire_roundtrip_keeps_operation_metrics_and_canonical_claim_graph():
    row = _wire_row()
    envelope = from_evaluator(row, row_number=3)
    payload = to_evaluator(envelope, publication_context={"requests": 3, "runtime_ms": 17})
    restored = from_evaluator(payload, row_number=3)
    assert restored.claims == envelope.claims
    assert restored.evidence == envelope.evidence
    assert restored.operations == envelope.operations
    assert payload["operations"] == {"requests": 3, "runtime_ms": 17, "third_party_cost_usd": 0}


def test_query_loader_decodes_compatibility_aliases_without_losing_facts(tmp_path):
    canonical = from_evaluator(_wire_row())
    path = tmp_path / "output.jsonl"
    path.write_text(json.dumps(to_evaluator(canonical)) + "\n")
    profile = load_profiles(path)[canonical.organisation_number]
    assert profile.claims == canonical.claims
    assert list(profile.evidence.values()) == canonical.evidence
