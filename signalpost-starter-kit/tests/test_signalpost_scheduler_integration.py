import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from signalpost import run
from signalpost.adapter import to_evaluator
from signalpost.brreg import BrregResult
from signalpost.models import PublicState
from signalpost.operations import Budget, OrderedAtomicWriter, PartialEnvelopePublisher, RunBudget


@pytest.mark.parametrize("row_count", [100, 1000])
def test_synthetic_batch_has_complete_unknown_rows_before_source_work(tmp_path, row_count):
    now = datetime.now(timezone.utc)
    cutoff = datetime(2026, 11, 5, tzinfo=timezone.utc)
    rows = [SimpleNamespace(input_ref=f"synthetic-{index}", row_number=index + 1,
        organisation_number=f"{index:09d}") for index in range(row_count)]
    envelopes = [run._provisional_envelope(row, "batch", cutoff, now) for row in rows]
    writer = OrderedAtomicWriter(tmp_path / "output.jsonl", estimated_bytes=row_count * 2048)
    PartialEnvelopePublisher(writer, envelopes, serializer=to_evaluator)
    budget = run._with_global_budget(RunBudget(), 0.05)

    async def stalled_source():
        await asyncio.sleep(1)

    _, deadline_hit = asyncio.run(run._run_before_completion_reserve(
        stalled_source(), Budget(budget), reserved_seconds=0))
    assert deadline_hit

    published = [json.loads(line) for line in (tmp_path / "output.jsonl").read_text().splitlines()]
    assert len(published) == row_count
    assert [row["input_ref"] for row in published] == [f"synthetic-{index}" for index in range(row_count)]
    assert all(row["terminal_state"] == "ambiguous" for row in published)
    assert all(not row["claims"] and not row["evidence"] for row in published)
    assert all(all(section["state"] is None for section in row["sections"].values())
               for row in published)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_global_budget_override_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        run._with_global_budget(RunBudget(), value)


def test_global_budget_reserves_finalization_and_uses_requested_hard_limit():
    budget = run._with_global_budget(RunBudget(), 60)
    assert budget.hard_seconds == 60
    assert budget.completion_reserve_seconds == 9
    assert budget.soft_seconds == 51


@pytest.mark.parametrize("source", ["flag", "environment"])
def test_global_budget_cli_and_environment_overrides(tmp_path, capsys, monkeypatch, source):
    input_path = tmp_path / "input.txt"
    input_path.write_text("bad\n")
    arguments = ["--input", str(input_path), "--output", str(tmp_path / "output.jsonl"),
        "--state-output", str(tmp_path / "state.json"), "--checkpoint", str(tmp_path / "checkpoint.sqlite")]
    if source == "flag":
        arguments.extend(["--budget-seconds", "0.1"])
    else:
        monkeypatch.setenv("SIGNALPOST_BUDGET_SECONDS", "0.1")
    assert run.main(arguments) == 0
    receipt = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert receipt["budget_seconds"] == 0.1


def test_tiny_budget_checkpoints_foundation_and_finance_as_complete_or_skipped(
        tmp_path, capsys, monkeypatch):
    async def foundation(organisation_number, *args, **kwargs):
        await asyncio.sleep(0.01)
        return BrregResult(claims=[], evidence=[], snapshots=[], errors=[],
            section_states={name: PublicState.NOT_AVAILABLE for name in (
                "identity_brand", "accounts_history", "leadership_workplaces")},
            terminal_state=PublicState.AVAILABLE, observations={"organisation_number": organisation_number})

    async def finance(result, *args, **kwargs):
        return result

    input_path = tmp_path / "input.txt"
    organisation_numbers = [f"{number:09d}" for number in range(1, 21)]
    input_path.write_text("\n".join(organisation_numbers) + "\n")
    output_path = tmp_path / "output.jsonl"
    state_path = tmp_path / "state.json"
    checkpoint_path = tmp_path / "checkpoint.sqlite"
    monkeypatch.setattr(run, "fetch_company", foundation)
    monkeypatch.setattr(run, "fetch_financial_statements", finance)

    assert run.main(["--input", str(input_path), "--output", str(output_path),
        "--state-output", str(state_path), "--checkpoint", str(checkpoint_path),
        "--live-brreg", "--budget-seconds", "0.05"]) == 0
    capsys.readouterr()
    published = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert len(published) == len(organisation_numbers)
    assert {row["organisation_number"] for row in published} == set(organisation_numbers)
    connection = sqlite3.connect(checkpoint_path)
    try:
        for phase in ("official", "financial_statements"):
            outcomes = {company: json.loads(payload)["outcome"] for company, payload in connection.execute(
                "SELECT company,payload FROM phase_status WHERE phase=?", (phase,))}
            assert set(outcomes) == set(organisation_numbers)
            assert set(outcomes.values()) <= {"completed", "failed", "deadline_skipped", "budget_skipped"}
    finally:
        connection.close()


def test_breadth_percentiles_are_queue_inclusive_elapsed_values():
    values = run._timing_percentiles([1, 2, 3, 4, 5])
    assert values == {"p50_seconds": 3, "p95_seconds": 4.8}
