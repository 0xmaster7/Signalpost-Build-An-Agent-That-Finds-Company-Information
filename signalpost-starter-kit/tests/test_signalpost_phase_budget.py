import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from signalpost import run
from signalpost.brreg import BrregResult
from signalpost.models import PublicState
from signalpost.operations import Budget, RunBudget
from signalpost.websites import WebsiteResearchResult


@pytest.mark.parametrize("values", [{"ocr_budget_share": -0.1}, {"ocr_budget_share": 1.1},
    {"ocr_seconds": float("nan")}, {"nav_seconds": -1}, {"website_seconds": float("inf")}])
def test_phase_budget_rejects_invalid_limits(values):
    with pytest.raises(ValueError):
        RunBudget(**values)


def test_phase_budget_mapping_and_environment():
    limits = RunBudget.from_mapping({"ocr_seconds": 100, "nav_seconds": 20},
        environ={"SIGNALPOST_OCR_BUDGET_SHARE": "0.4", "SIGNALPOST_WEBSITE_SECONDS": "80"})
    assert limits.ocr_seconds == 100 and limits.nav_seconds == 20
    assert limits.ocr_budget_share == 0.4 and limits.website_seconds == 80


def test_source_phase_timeout_drains_only_its_own_work():
    async def check():
        cancelled = asyncio.Event()
        other_finished = asyncio.Event()

        async def slow():
            try:
                await asyncio.sleep(5)
            finally:
                cancelled.set()

        async def network():
            await asyncio.sleep(0.04)
            other_finished.set()

        budget = Budget(RunBudget(hard_seconds=2, soft_seconds=1, completion_reserve_seconds=1))
        result, network_result = await asyncio.gather(run._run_source_phase(slow(), budget, 0.01), network())
        assert result == ({}, True) and network_result is None
        assert cancelled.is_set() and other_finished.is_set()

    asyncio.run(check())


def test_production_runs_batch_sources_before_concurrent_ocr_and_websites(tmp_path, capsys):
    calls = []
    ocr_started = asyncio.Event()
    web_started = asyncio.Event()

    async def official(*args, **kwargs):
        return BrregResult(claims=[], evidence=[], snapshots=[], errors=[],
            section_states={name: PublicState.NOT_AVAILABLE for name in
                ("identity_brand", "accounts_history", "leadership_workplaces")},
            terminal_state=PublicState.AVAILABLE, observations={}, account_records=[{}])

    async def nav(*args, **kwargs):
        calls.append("nav")
        return {}, {"state": "complete", "negative_coverage": False}, {}

    async def wikidata(*args, **kwargs):
        calls.append("wikidata")
        return {}, {"state": "completed"}

    async def document(result, *args, **kwargs):
        calls.append("ocr_start")
        ocr_started.set()
        await web_started.wait()
        calls.append("ocr_finished")
        return result

    async def website(*args, **kwargs):
        calls.append("web_start")
        web_started.set()
        await ocr_started.wait()
        calls.append("web_finished")
        return WebsiteResearchResult(state=PublicState.NOT_AVAILABLE,
            audit={"execution_state": "completed", "claims": []})

    (tmp_path / "input").write_text("987974249\n987974249\nbad\n")
    (tmp_path / "config").write_text(json.dumps({"budget": {"hard_seconds": 3, "soft_seconds": 2,
        "completion_reserve_seconds": 1, "nav_seconds": 0.3, "wikidata_seconds": 0.3,
        "website_seconds": 0.3, "ocr_seconds": 0.3}}))
    with patch.object(run, "fetch_company", official), \
            patch("signalpost.nav.research_jobs", nav), \
            patch("signalpost.public_discovery.wikidata_candidates", wikidata), \
            patch("signalpost.annual_accounts.enrich_company", document), \
            patch("signalpost.financial_calibration.calibrate_company_financials", side_effect=lambda result, *args: result), \
            patch("signalpost.websites.research_company", website):
        assert run.main(["--input", str(tmp_path / "input"), "--output", str(tmp_path / "output"),
            "--state-output", str(tmp_path / "state"), "--checkpoint", str(tmp_path / "checkpoint"),
            "--config", str(tmp_path / "config"), "--live-brreg", "--live-websites"]) == 0
    assert calls.index("nav") < calls.index("ocr_start")
    assert calls.index("wikidata") < calls.index("ocr_start")
    assert "ocr_finished" in calls and "web_finished" in calls
    rows = [json.loads(line) for line in (tmp_path / "output").read_text().splitlines()]
    assert len(rows) == 3 and rows[-1]["terminal_state"] == "failed"
    receipt = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert receipt["physical_gateway_requests"] == 0
    assert receipt["scheduler_passes"]["phase_reservations"]["ocr_and_websites_concurrent"]
