import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import patch

from signalpost import brreg, run
from signalpost.brreg import BrregResult
from signalpost.execution import ExecutionTrace
from signalpost.inputs import normalize_org_number
from signalpost.models import PublicState
from signalpost.network import NetworkGateway
from signalpost.operations import CheckpointStore
from signalpost.recording import HttpRecording
from signalpost.synthesis import validate_synthesis_schema


ORG = "987974249"


def test_identity_only_uses_one_endpoint_and_full_path_keeps_roles_and_workplaces(monkeypatch):
    calls = []

    class Transport:
        async def request(self, url, headers, timeout):
            if url.endswith(f"/enheter/{ORG}"):
                calls.append("entity")
                body = {"organisasjonsnummer": ORG, "navn": "Breadth AS", "organisasjonsform": {"kode": "AS"}}
            elif url.endswith(f"/enheter/{ORG}/roller"):
                calls.append("roles")
                body = {"rollegrupper": []}
            elif "/underenheter?" in url:
                calls.append("subunits")
                body = {"_embedded": {"underenheter": []}, "page": {"number": 0, "totalPages": 1}}
            else:
                raise AssertionError(url)
            return 200, {"Content-Type": "application/json"}, json.dumps(body).encode(), url

    gateway = NetworkGateway(Transport(), retries=0)
    monkeypatch.setattr(gateway, "_validate_host", lambda url: ("8.8.8.8",))
    async def robots(*args, **kwargs):
        return "allowed", None
    monkeypatch.setattr(gateway, "robots_decision", robots)
    cutoff = datetime.now(timezone.utc)
    broad = asyncio.run(brreg.fetch_company(ORG, gateway, cutoff, include_accounts=False, include_people=False,
        allow_current_identity_after_run_start=True))
    assert calls == ["entity"]
    assert broad.observations["foundation_breadth_only"] is True
    assert broad.section_states["accounts_history"] is None
    assert broad.section_states["leadership_workplaces"] is None
    assert broad.observations.get("roles_count") is None
    validate_synthesis_schema({"brreg_observations": broad.observations})
    calls.clear()
    full = asyncio.run(brreg.fetch_company(ORG, gateway, cutoff, include_accounts=False,
        allow_current_identity_after_run_start=True))
    assert calls == ["roles", "subunits"]
    assert "foundation_breadth_only" not in full.observations
    assert full.section_states["leadership_workplaces"] == PublicState.NOT_AVAILABLE
    calls.clear()
    standalone = NetworkGateway(Transport(), retries=0)
    monkeypatch.setattr(standalone, "_validate_host", lambda url: ("8.8.8.8",))
    monkeypatch.setattr(standalone, "robots_decision", robots)
    asyncio.run(brreg.fetch_company(ORG, standalone, cutoff, include_accounts=False,
        allow_current_identity_after_run_start=True))
    assert calls == ["entity", "roles", "subunits"]


def _valid_organisations(count):
    values = []
    prefix = 10000000
    while len(values) < count:
        for check in range(10):
            candidate = f"{prefix}{check}"
            if normalize_org_number(candidate)[1]:
                values.append(candidate)
                break
        prefix += 1
    return values


def test_thousand_company_batch_finishes_identity_and_finance_before_details(tmp_path, capsys):
    organisations = _valid_organisations(1000)
    input_path = tmp_path / "input.txt"
    input_path.write_text("\n".join(organisations))
    events = []

    def result(org, phase):
        return BrregResult(claims=[], evidence=[], snapshots=[], errors=[],
            section_states={"identity_brand": PublicState.NOT_AVAILABLE,
                "accounts_history": PublicState.NOT_AVAILABLE,
                "leadership_workplaces": PublicState.NOT_AVAILABLE},
            terminal_state=PublicState.NOT_AVAILABLE, observations={"foundation_breadth_only": True})

    async def fetch(org, gateway, cutoff, **kwargs):
        phase = "details" if kwargs.get("include_people", True) else "identity"
        events.append((phase, org))
        if phase == "identity":
            gateway.ledger.logical_requests += 1
        return result(org, phase)

    async def finance(value, org, gateway, cutoff):
        events.append(("finance", org))
        value.account_records = [{"year": 2025}]
        value.account_source = {"url": "https://data.brreg.no/accounts", "status": 200}
        value.observations["financial_calibration"] = {"state": "available"}
        return value

    with patch.object(run, "fetch_company", fetch), patch.object(run, "fetch_financial_statements", finance):
        assert run.main(["--input", str(input_path), "--output", str(tmp_path / "out.jsonl"),
            "--state-output", str(tmp_path / "state.json"), "--checkpoint", str(tmp_path / "checkpoint.sqlite"),
            "--live-brreg", "--budget-seconds", "1800"]) == 0
    capsys.readouterr()
    assert sum(phase == "identity" for phase, _ in events) == 1000
    assert sum(phase == "finance" for phase, _ in events) == 1000
    assert sum(phase == "details" for phase, _ in events) > 0
    assert max(index for index, (phase, _) in enumerate(events) if phase == "finance") < min(
        index for index, (phase, _) in enumerate(events) if phase == "details")
    checkpoint = CheckpointStore(tmp_path / "checkpoint.sqlite")
    try:
        for phase in ("official", "financial_statements", "official_details"):
            statuses = checkpoint.phase_statuses(phase)
            assert set(statuses) == set(organisations)
            assert all(item["outcome"] == "completed" for item in statuses.values())
        preserved = checkpoint.phase_results("official_details")[organisations[0]]
        assert preserved.account_records == [{"year": 2025}]
        assert preserved.account_source == {"url": "https://data.brreg.no/accounts", "status": 200}
        assert preserved.observations["financial_calibration"] == {"state": "available"}
    finally:
        checkpoint.close()


def test_optional_details_exception_keeps_all_final_rows(tmp_path, capsys):
    organisations = _valid_organisations(4)
    input_path = tmp_path / "input.txt"
    input_path.write_text("\n".join(organisations))

    def result(org):
        return BrregResult(claims=[], evidence=[], snapshots=[], errors=[],
            section_states={"identity_brand": PublicState.NOT_AVAILABLE,
                "accounts_history": PublicState.NOT_AVAILABLE,
                "leadership_workplaces": PublicState.NOT_AVAILABLE},
            terminal_state=PublicState.NOT_AVAILABLE, observations={})

    async def fetch(org, gateway, cutoff, **kwargs):
        if kwargs.get("include_people", True):
            raise RuntimeError("injected details transport failure")
        gateway.ledger.logical_requests += 1
        value = result(org)
        value.observations["foundation_breadth_only"] = True
        return value

    async def finance(value, *args):
        return value

    output = tmp_path / "out.jsonl"
    with patch.object(run, "fetch_company", fetch), patch.object(run, "fetch_financial_statements", finance):
        assert run.main(["--input", str(input_path), "--output", str(output),
            "--state-output", str(tmp_path / "state.json"), "--checkpoint", str(tmp_path / "checkpoint.sqlite"),
            "--live-brreg", "--budget-seconds", "10"]) == 0
    capsys.readouterr()
    published = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(published) == len(organisations)
    assert all(row["organisation_number"] in organisations for row in published)
    assert all(any(error["code"] == "BRREG_DETAILS_UNEXPECTED_FAILURE" for error in row["errors"])
        for row in published)


def test_strict_replay_uses_recorded_phase_admission_without_fact_payloads(tmp_path):
    capture = HttpRecording(tmp_path / "capture", replay=False)
    capture.record_execution("company_phase_outcomes", {
        "official": {ORG: {"outcome": "completed"}},
        "financial_statements": {ORG: {"outcome": "completed"}},
        "official_details": {ORG: {"outcome": "deadline_skipped"}},
    })
    capture.record_execution("official_details_allocation", 8.0)
    capture.record_execution("nav_dynamic_allocation", 3.0)
    capture.seal()
    replay = HttpRecording(tmp_path / "capture", replay=True)
    trace = ExecutionTrace(replay)
    assert trace.admitted("official", ORG)
    assert trace.admitted("financial_statements", ORG)
    assert not trace.admitted("official_details", ORG)
    assert trace.control("official_details_allocation") == 8.0
    assert trace.control("nav_dynamic_allocation") == 3.0
    assert replay.replay_execution("company_phase_outcomes")["official_details"][ORG]["outcome"] == "deadline_skipped"
    assert not (replay.root / "facts.json").exists()
    replay.assert_complete()
