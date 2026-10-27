import copy
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone

import pytest

from signalpost import brreg, run
from signalpost.models import PublicState, validate_batch_publication_graph
from signalpost.operations import CheckpointStore
from signalpost.websites import PageRecord, WebsiteResearchResult


ORG = "987974249"


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    calls = Counter()
    failures = set()

    class OfficialGateway:
        def __init__(self, org):
            self.org = org

        async def fetch(self, url, **kwargs):
            purpose = kwargs["purpose"]
            if purpose == "entity":
                body = {"organisasjonsnummer": self.org, "navn": "Reliability AS", "organisasjonsform": {"kode": "AS"}}
            elif purpose == "accounts":
                body = []
            elif purpose == "roles":
                body = {"rollegrupper": []}
            else:
                body = {"_embedded": {"underenheter": []}, "page": {"number": 0, "totalPages": 1}}
            return 200, {}, json.dumps(body).encode(), url, "ok"

    async def official(org, gateway, cutoff, **kwargs):
        calls["official"] += 1
        result = await brreg.fetch_company(org, OfficialGateway(org), cutoff, **kwargs)
        result.account_records = [{"retained": "account-context"}]
        result.account_source = {"retained": "source-context"}
        return result

    async def document(result, *args):
        calls["annual_documents"] += 1
        assert result.account_records == [{"retained": "account-context"}]
        assert result.account_source == {"retained": "source-context"}
        if "annual_documents" in failures:
            result.claims.clear()
            raise RuntimeError("injected OCR failure")
        result.observations["annual_accounts_document"] = {"state": "available", "reason": "saved_document"}
        return result

    async def nav(*args, **kwargs):
        calls["nav_batch"] += 1
        if "nav_batch" in failures:
            raise RuntimeError("injected NAV failure")
        return {ORG: WebsiteResearchResult(audit={"nav_test": True})}, {"state": "completed"}, {}

    async def wiki(*args, **kwargs):
        calls["wiki_batch"] += 1
        if "wiki_batch" in failures:
            raise RuntimeError("injected Wiki failure")
        return {}, {"state": "completed"}

    async def website(*args, phase, previous=None, **kwargs):
        name = {"verify": "website_verify", "shallow": "website_shallow", "jobs": "jobs_activity"}[phase]
        calls[name] += 1
        if name in failures:
            if previous:
                previous.claims.clear()
            raise RuntimeError("injected website failure")
        result = copy.deepcopy(previous) if previous else WebsiteResearchResult()
        if previous:
            page = result.phase_state["accepted_pages"][0][1][0]
            assert isinstance(page, PageRecord) and page.body == b"saved-page"
        else:
            page = PageRecord("https://example.no/", "https://example.no/", 200, "text/html", b"saved-page",
                "a" * 64, datetime.now(timezone.utc), directives={"noarchive"})
            result.phase_state = {"accepted_pages": [({}, [page], {}, None)]}
        result.audit = {"execution_state": "completed", "reason": name, "claims": []}
        return result

    original_merge = run._merge_website_provenance

    def merge(envelope, result):
        if "nav_apply" in failures and result.audit.get("nav_test"):
            raise ValueError("injected NAV application failure")
        return original_merge(envelope, result)

    monkeypatch.setattr(run, "fetch_company", official)
    monkeypatch.setattr("signalpost.annual_accounts.enrich_company", document)
    monkeypatch.setattr("signalpost.financial_calibration.calibrate_company_financials", lambda *args: None)
    monkeypatch.setattr("signalpost.nav.research_jobs", nav)
    monkeypatch.setattr("signalpost.public_discovery.wikidata_candidates", wiki)
    monkeypatch.setattr("signalpost.websites.research_company", website)
    monkeypatch.setattr(run, "_merge_website_provenance", merge)
    (tmp_path / "input").write_text(ORG + "\n" + ORG + "\n")
    argv = ["--input", str(tmp_path / "input"), "--output", str(tmp_path / "output"),
        "--checkpoint", str(tmp_path / "checkpoint"), "--live-brreg", "--live-websites"]
    return tmp_path, argv, calls, failures


@pytest.mark.parametrize("phase,code", [
    ("annual_documents", "OCR_ENRICHMENT_UNEXPECTED_FAILURE"),
    ("website_verify", "WEBSITE_RESEARCH_UNEXPECTED_FAILURE"),
    ("website_shallow", "WEBSITE_RESEARCH_UNEXPECTED_FAILURE"),
    ("jobs_activity", "WEBSITE_RESEARCH_UNEXPECTED_FAILURE"),
    ("nav_batch", "NAV_BATCH_UNEXPECTED_FAILURE"),
    ("wiki_batch", "WIKI_BATCH_UNEXPECTED_FAILURE"),
    ("nav_apply", "NAV_APPLICATION_UNEXPECTED_FAILURE"),
])
def test_optional_exception_preserves_official_and_finishes_batch(scenario, phase, code, capsys):
    path, argv, calls, failures = scenario
    failures.add(phase)
    assert run.main(argv) == 0
    store = CheckpointStore(path / "checkpoint")
    envelopes = store.rows()
    validate_batch_publication_graph(envelopes)
    assert len(envelopes) == 2
    for envelope in envelopes:
        assert envelope.terminal_state == PublicState.AVAILABLE
        assert any(claim.value == "Reliability AS" for claim in envelope.claims)
        assert code in {error.code for error in envelope.errors}
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    metric = report["scheduler_passes"]["optional_phases"][phase]
    assert metric["failed"] == 1 and metric["ran"] == 1
    assert metric["wall_seconds"] >= 0
    store.close()


def test_optional_failure_continues_other_company(scenario):
    path, argv, calls, failures = scenario
    (path / "input").write_text(ORG + "\n930827088\n")
    failures.add("annual_documents")
    assert run.main(argv) == 0
    store = CheckpointStore(path / "checkpoint")
    envelopes = store.rows()
    assert {item.organisation_number for item in envelopes} == {ORG, "930827088"}
    assert all(item.terminal_state == PublicState.AVAILABLE for item in envelopes)
    assert calls["annual_documents"] == 2 and calls["jobs_activity"] == 2
    validate_batch_publication_graph(envelopes)
    store.close()


def test_cancelled_optional_phases_keep_deadline_outcomes(scenario, monkeypatch, capsys):
    path, argv, calls, failures = scenario
    async def slow(*args, **kwargs):
        await asyncio.sleep(10)

    (path / "config").write_text(json.dumps({"budget": {
        "hard_seconds": 4, "soft_seconds": 3, "completion_reserve_seconds": 1,
        "nav_seconds": 0.01, "wikidata_seconds": 0.01,
        "ocr_seconds": 0.01, "website_seconds": 0.01}}))
    monkeypatch.setattr("signalpost.nav.research_jobs", slow)
    monkeypatch.setattr("signalpost.public_discovery.wikidata_candidates", slow)
    monkeypatch.setattr("signalpost.annual_accounts.enrich_company", slow)
    monkeypatch.setattr("signalpost.websites.research_company", slow)
    assert run.main(argv + ["--config", str(path / "config")]) == 0
    store = CheckpointStore(path / "checkpoint")
    for envelope in store.rows():
        assert not any("UNEXPECTED_FAILURE" in error.code for error in envelope.errors)
        assert envelope.synthesis["website_research"]["execution_state"] == "deadline_skipped"
        assert envelope.sections["website_owned_profiles"].attempt_outcome == "deadline_skipped"
        assert envelope.synthesis["brreg_observations"]["annual_accounts_document"]["state"] == "deadline_skipped"
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    for name in ("nav_batch", "wiki_batch", "annual_documents", "website_verify"):
        assert report["scheduler_passes"]["optional_phases"][name]["deadline_skipped"] == 1
        assert report["scheduler_passes"]["optional_phases"][name]["failed"] == 0
    store.close()


def test_checkpoint_rejects_invalid_graph_without_partial_write(scenario):
    path, argv, calls, failures = scenario
    assert run.main(argv) == 0
    store = CheckpointStore(path / "checkpoint")
    before = [item.model_dump_json() for item in store.rows()]
    envelope = store.rows()[0]
    envelope.evidence.clear()
    with pytest.raises(ValueError):
        store.save_phase("invalid", ORG, {"state": "completed"}, [envelope])
    assert store.phase_results("invalid") == {}
    assert [item.model_dump_json() for item in store.rows()] == before
    store.close()


def test_checkpoint_roundtrip_keeps_typed_context_and_arbitrary_source_keys(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoint")
    value = {"state": PublicState.FAILED, "source": {"$model": "raw source value", "$bytes": "untouched"},
        "page": PageRecord("https://example.no/", "https://example.no/", 200, "text/html", b"page",
            "a" * 64, datetime.now(timezone.utc), directives={"noarchive"})}
    store.save_phase("codec", ORG, value)
    restored = store.phase_results("codec")[ORG]
    assert restored == value
    assert restored["state"] is PublicState.FAILED
    store.close()


@pytest.mark.parametrize("phase,code", [
    ("annual_documents", "OCR_ENRICHMENT_UNEXPECTED_FAILURE"),
    ("website_verify", "WEBSITE_RESEARCH_UNEXPECTED_FAILURE"),
    ("website_shallow", "WEBSITE_RESEARCH_UNEXPECTED_FAILURE"),
    ("jobs_activity", "WEBSITE_RESEARCH_UNEXPECTED_FAILURE"),
    ("nav_batch", "NAV_BATCH_UNEXPECTED_FAILURE"),
    ("wiki_batch", "WIKI_BATCH_UNEXPECTED_FAILURE"),
    ("nav_apply", "NAV_APPLICATION_UNEXPECTED_FAILURE"),
])
def test_resume_retains_failed_optional_observations(scenario, phase, code):
    path, argv, calls, failures = scenario
    failures.add(phase)
    assert run.main(argv) == 0
    store = CheckpointStore(path / "checkpoint")
    for envelope in store.rows():
        store.set_shell_state(envelope.row_number, "baseline_done")
    store.close()
    before = calls.copy()
    failures.clear()
    assert run.main(argv + ["--resume"]) == 0
    assert calls == before
    store = CheckpointStore(path / "checkpoint")
    for envelope in store.rows():
        assert code in {error.code for error in envelope.errors}
        assert any(claim.value == "Reliability AS" for claim in envelope.claims)
    validate_batch_publication_graph(store.rows())
    store.close()


@pytest.mark.parametrize("crash_phase", ["official", "nav_batch", "wiki_batch", "nav_apply",
    "annual_documents", "website_verify", "website_shallow", "jobs_activity"])
def test_crash_resume_keeps_completed_optional_work(scenario, monkeypatch, crash_phase):
    path, argv, calls, failures = scenario
    original = CheckpointStore.save_phase
    crashed = False

    def save(store, phase, org, value, envelopes=()):
        nonlocal crashed
        original(store, phase, org, value, envelopes)
        if phase == crash_phase and not crashed:
            crashed = True
            raise RuntimeError("simulated process interruption after committed phase")

    monkeypatch.setattr(CheckpointStore, "save_phase", save)
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        run.main(argv)
    store = CheckpointStore(path / "checkpoint")
    completed = {name for name in calls if store.phase_results(name)}
    before = calls.copy()
    validate_batch_publication_graph(store.rows())
    store.close()
    monkeypatch.setattr(CheckpointStore, "save_phase", original)
    assert run.main(argv + ["--resume"]) == 0
    for name in completed:
        assert calls[name] == before[name], name
    store = CheckpointStore(path / "checkpoint")
    envelopes = store.rows()
    validate_batch_publication_graph(envelopes)
    for envelope in envelopes:
        assert envelope.synthesis["website_research"]["reason"] == "jobs_activity"
        assert envelope.synthesis["brreg_observations"]["annual_accounts_document"]["reason"] == "saved_document"
        assert any(claim.value == "Reliability AS" for claim in envelope.claims)
    store.close()
