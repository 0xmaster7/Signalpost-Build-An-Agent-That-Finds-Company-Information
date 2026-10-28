from datetime import datetime, timezone

import pytest

from signalpost.brreg import _projection_helpers


def projection():
    claims, evidence, snapshots, errors = [], [], [], []
    _, add = _projection_helpers("100000008", None, claims, evidence, snapshots, errors)
    return add, claims, evidence, snapshots


def submit(add, *, value="STYR", pointer="/rollegrupper/0/type/kode", scope="person_role",
           family="role", source="https://data.brreg.no/enhetsregisteret/api/enheter/100000008/roller"):
    add("role.role_group_code", value, "leadership_workplaces", family, "100000008", scope,
        source, datetime(2026, 1, 1, tzinfo=timezone.utc), {"fixture": True}, pointer, "roles")


def test_repeated_role_group_observation_merges_all_provenance():
    add, claims, evidence, snapshots = projection()
    for _ in range(5):
        submit(add)
    assert len(claims) == 1
    assert len(evidence) == 5
    assert claims[0].evidence_ids == [item.evidence_id for item in evidence]
    assert claims[0].source_snapshot_ids == [snapshots[0].source_id]


@pytest.mark.parametrize("change", [{"value": "DAGL"}, {"pointer": "/rollegrupper/1/type/kode"},
    {"scope": "legal_entity"}, {"source": "https://data.brreg.no/enhetsregisteret/api/enheter/100000008"}])
def test_different_role_observations_remain_distinct(change):
    add, claims, _, _ = projection()
    submit(add)
    submit(add, **change)
    assert len(claims) == len({claim.claim_id for claim in claims}) == 2


def test_semantically_conflicting_identity_is_not_silently_dropped():
    add, _, _, _ = projection()
    submit(add)
    with pytest.raises(ValueError, match="conflicting BRREG claim identity"):
        submit(add, family="identity")
