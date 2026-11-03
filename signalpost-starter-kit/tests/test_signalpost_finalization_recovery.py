import json

import pytest

from signalpost import run
from signalpost.operations import CheckpointStore
from signalpost.adapter import validate_vendor_payload
from test_signalpost_crashsafe_phases import hundred_orgs
from test_signalpost_optional_reliability import ORG, scenario


@pytest.mark.parametrize("phase", ("company_state", "_finalize_company"))
def test_finalization_failure_does_not_prevent_hundred_final_envelopes(scenario, monkeypatch, phase):
    directory, arguments, _, _ = scenario
    organisations = hundred_orgs()
    (directory / "input").write_text("\n".join(organisations) + "\n")
    original = getattr(run, phase)

    def fail(envelope, *args, **kwargs):
        if envelope.organisation_number == ORG:
            raise RuntimeError("PRIVATE_FINALIZATION_DIAGNOSTIC")
        return original(envelope, *args, **kwargs)

    monkeypatch.setattr(run, phase, fail)
    assert run.main(arguments) == 0
    encoded = (directory / "output").read_text()
    assert "PRIVATE_FINALIZATION_DIAGNOSTIC" not in encoded
    rows = [json.loads(line) for line in encoded.splitlines()]
    assert len(rows) == 100
    assert [row["organisation_number"] for row in rows] == organisations
    for row in rows:
        validate_vendor_payload(row)
        assert len({claim["claim_id"] for claim in row["claims"]}) == len(row["claims"])
    with CheckpointStore(directory / "checkpoint").connection as database:
        assert database.execute("SELECT COUNT(*) FROM shells WHERE execution_state='terminalized'").fetchone()[0] == 100
    checkpoint = CheckpointStore(directory / "checkpoint")
    statuses = checkpoint.phase_statuses("finalization")
    assert len(statuses) == 100
    assert statuses[ORG]["status"] == "failed"
    assert len(statuses[ORG]["traceback_sha256"]) == 64
    assert all(statuses[org]["status"] == "ran" for org in organisations if org != ORG)
    checkpoint.close()
