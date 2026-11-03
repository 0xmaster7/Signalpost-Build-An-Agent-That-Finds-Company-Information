"""Batch cardinality, private failure fingerprints, and committed phase progress."""
import copy
import asyncio
import json
import re

import pytest

from signalpost import run
from signalpost.inputs import normalize_org_number
from signalpost.models import validate_batch_publication_graph
from signalpost.operations import CheckpointStore
from signalpost.websites import WebsiteResearchResult
from test_signalpost_optional_reliability import ORG, SimulatedCrash, scenario


PHASES = ("official", "financial_statements", "nav_batch", "wiki_batch", "nav_apply",
          "annual_documents", "website_verify", "website_shallow", "jobs_activity")


def hundred_orgs():
    orgs = [ORG]
    candidate = 100000000
    while len(orgs) < 100:
        value = str(candidate)
        if normalize_org_number(value)[1] and value != ORG:
            orgs.append(value)
        candidate += 1
    return orgs


@pytest.mark.parametrize("broken", ("official_fetch", "official_projection", "official_projector", *PHASES[1:]))
def test_hundred_inputs_isolate_every_phase_and_resume(scenario, monkeypatch, broken):
    from signalpost import annual_accounts, nav, public_discovery, websites

    path, argv, calls, failures = scenario
    orgs = hundred_orgs()
    (path / "input").write_text("\n".join(orgs) + "\n")
    original_official = run.fetch_company
    original_finance = run.fetch_financial_statements
    original_document = annual_accounts.enrich_company
    original_website = websites.research_company
    original_merge = run._merge_website_provenance
    original_projector = run._live_envelope
    secret = "private-token-and-local-path-DO-NOT-PUBLISH"

    def explode():
        raise RuntimeError(secret)

    async def official(org, *args, **kwargs):
        if org == ORG and broken == "official_fetch":
            explode()
        result = await original_official(org, *args, **kwargs)
        if org == ORG and broken == "official_projection":
            result.claims.append(copy.deepcopy(result.claims[0]))
        return result

    async def finance(result, org, *args, **kwargs):
        if org == ORG and broken == "financial_statements":
            result.claims.clear()
            explode()
        return await original_finance(result, org, *args, **kwargs)

    async def document(result, org, *args, **kwargs):
        if org == ORG and broken == "annual_documents":
            result.claims.clear()
            explode()
        return await original_document(result, org, *args, **kwargs)

    async def jobs(targets, *args, **kwargs):
        calls["nav_batch"] += 1
        if broken == "nav_batch":
            explode()
        return {org: WebsiteResearchResult(audit={"nav_test": True}) for org in targets}, {"state": "completed"}, {}

    async def wiki(*args, **kwargs):
        calls["wiki_batch"] += 1
        if broken == "wiki_batch":
            explode()
        return {}, {"state": "completed"}

    async def website(profile, *args, phase, **kwargs):
        name = {"verify": "website_verify", "shallow": "website_shallow", "jobs": "jobs_activity"}[phase]
        if profile["organisation_number"] == ORG and broken == name:
            if kwargs.get("previous"):
                kwargs["previous"].claims.clear()
            explode()
        return await original_website(profile, *args, phase=phase, **kwargs)

    def merge(envelope, result):
        if envelope.organisation_number == ORG and broken == "nav_apply" and result.audit.get("nav_test"):
            explode()
        return original_merge(envelope, result)

    def project(row, *args, **kwargs):
        if row.organisation_number == ORG and broken == "official_projector":
            explode()
        return original_projector(row, *args, **kwargs)

    monkeypatch.setattr(run, "fetch_company", official)
    monkeypatch.setattr(run, "fetch_financial_statements", finance)
    monkeypatch.setattr(annual_accounts, "enrich_company", document)
    monkeypatch.setattr(nav, "research_jobs", jobs)
    monkeypatch.setattr(public_discovery, "wikidata_candidates", wiki)
    monkeypatch.setattr(websites, "research_company", website)
    monkeypatch.setattr(run, "_merge_website_provenance", merge)
    monkeypatch.setattr(run, "_live_envelope", project)
    assert run.main(argv) == 0
    public = (path / "output").read_text()
    assert secret not in public
    rows = [json.loads(line) for line in public.splitlines()]
    assert len(rows) == 100 and [row["organisation_number"] for row in rows] == orgs
    store = CheckpointStore(path / "checkpoint")
    validate_batch_publication_graph(store.rows())
    for envelope in store.rows():
        for values, field in ((envelope.claims, "claim_id"), (envelope.evidence, "evidence_id"),
                              (envelope.source_snapshots, "source_id")):
            ids = [getattr(value, field) for value in values]
            assert len(ids) == len(set(ids))
        if not broken.startswith("official_") or envelope.organisation_number != ORG:
            assert any(claim.value == "Reliability AS" for claim in envelope.claims)
    phase = "official" if broken.startswith("official_") else broken
    for name in PHASES:
        metrics = store.phase_statuses(name)
        assert set(metrics) == set(orgs), name
        assert all(item["status"] in {"ran", "skipped", "deadline_skipped", "failed"}
                   and item["seconds"] >= 0 for item in metrics.values())
    failed = store.phase_statuses(phase)[ORG]
    assert failed["failed"] and failed["ran"]
    assert re.fullmatch("[0-9a-f]{64}", failed["traceback_sha256"])
    assert "traceback_sha256=" in " ".join(error.message for error in store.rows()[0].errors)
    if phase in {"nav_batch", "wiki_batch"}:
        assert all(item["failed"] and item["traceback_sha256"] for item in store.phase_statuses(phase).values())
    before_statuses = {name: store.phase_statuses(name) for name in PHASES}
    store.connection.execute("UPDATE shells SET execution_state='baseline_done'")
    store.connection.commit()
    store.close()
    before_calls = calls.copy()
    assert run.main(argv + ["--resume"]) == 0
    assert calls == before_calls
    store = CheckpointStore(path / "checkpoint")
    assert {name: store.phase_statuses(name) for name in PHASES} == before_statuses
    assert len(store.rows()) == 100
    validate_batch_publication_graph(store.rows())
    store.close()


@pytest.mark.parametrize("phase", PHASES)
def test_progress_is_durable_at_each_committed_phase_even_when_process_dies(scenario, monkeypatch, phase):
    path, argv, calls, failures = scenario
    original = CheckpointStore.save_phase

    def save(store, name, company, result, envelopes=()):
        original(store, name, company, result, envelopes)
        if name == phase:
            raise SimulatedCrash("kill after commit")

    monkeypatch.setattr(CheckpointStore, "save_phase", save)
    with pytest.raises(SimulatedCrash):
        run.main(argv)
    store = CheckpointStore(path / "checkpoint")
    assert store.phase_results(phase)
    assert store.phase_statuses(phase)[ORG]["seconds"] >= 0
    validate_batch_publication_graph(store.rows())
    store.close()


@pytest.mark.parametrize("phase", PHASES[1:])
def test_bad_phase_payload_is_rejected_without_losing_official_facts(scenario, monkeypatch, phase):
    from signalpost import annual_accounts, nav, public_discovery, websites

    path, argv, calls, failures = scenario
    secret = "private-invalid-payload"
    if phase in {"financial_statements", "annual_documents"}:
        owner, name = (run, "fetch_financial_statements") if phase == "financial_statements" else (annual_accounts, "enrich_company")
        original = getattr(owner, name)

        async def corrupt(result, *args, **kwargs):
            result = await original(result, *args, **kwargs)
            result.claims.append(copy.deepcopy(result.claims[0]))
            return result

        monkeypatch.setattr(owner, name, corrupt)
    elif phase in {"nav_batch", "wiki_batch"}:
        if phase == "nav_batch":
            async def batch(*args, **kwargs):
                return {}, {"state": "completed"}, {ORG: None}
            monkeypatch.setattr(nav, "research_jobs", batch)
        else:
            async def batch(*args, **kwargs):
                return {ORG: None}, {"state": "completed"}
            monkeypatch.setattr(public_discovery, "wikidata_candidates", batch)
    elif phase == "nav_apply":
        original = nav.research_jobs

        async def corrupt(*args, **kwargs):
            results, report, homepages = await original(*args, **kwargs)
            results[ORG].claims = [object()]
            return results, report, homepages

        monkeypatch.setattr(nav, "research_jobs", corrupt)
    else:
        original = websites.research_company

        async def corrupt(*args, **kwargs):
            result = await original(*args, **kwargs)
            current = {"verify": "website_verify", "shallow": "website_shallow", "jobs": "jobs_activity"}[kwargs["phase"]]
            if current == phase:
                result.audit["unrecognized_private_field"] = secret
            return result

        monkeypatch.setattr(websites, "research_company", corrupt)
    assert run.main(argv) == 0
    assert secret not in (path / "output").read_text()
    store = CheckpointStore(path / "checkpoint")
    assert len(store.rows()) == 2
    validate_batch_publication_graph(store.rows())
    assert all(any(claim.value == "Reliability AS" for claim in item.claims) for item in store.rows())
    status = store.phase_statuses(phase)[ORG]
    assert status["failed"] and re.fullmatch("[0-9a-f]{64}", status["traceback_sha256"])
    store.close()


def test_hundred_frozen_inputs_keep_cardinality_on_projector_failure(tmp_path, monkeypatch):
    orgs = hundred_orgs()
    (tmp_path / "input").write_text("\n".join(orgs) + "\n")
    (tmp_path / "registry").write_text("".join(json.dumps({"organisation_number": org,
        "name": "Frozen AS", "as_of": "2024-01-01"}) + "\n" for org in orgs))
    original = run._envelope
    calls = []

    def project(row, *args, **kwargs):
        calls.append(row.organisation_number)
        if row.organisation_number == ORG:
            raise RuntimeError("private frozen projection failure")
        return original(row, *args, **kwargs)

    monkeypatch.setattr(run, "_envelope", project)
    argv = ["--input", str(tmp_path / "input"), "--registry-snapshot", str(tmp_path / "registry"),
        "--output", str(tmp_path / "output"), "--checkpoint", str(tmp_path / "checkpoint")]
    original_save = CheckpointStore.save_phase

    def crash(store, phase, company, result, envelopes=()):
        original_save(store, phase, company, result, envelopes)
        if phase == "frozen_foundation":
            raise SimulatedCrash("kill after frozen foundation commit")

    monkeypatch.setattr(CheckpointStore, "save_phase", crash)
    with pytest.raises(SimulatedCrash):
        run.main(argv)
    assert calls == [ORG]
    monkeypatch.setattr(CheckpointStore, "save_phase", original_save)
    assert run.main(argv + ["--resume"]) == 0
    assert calls == orgs
    assert len((tmp_path / "output").read_text().splitlines()) == 100
    assert "private frozen projection failure" not in (tmp_path / "output").read_text()
    store = CheckpointStore(tmp_path / "checkpoint")
    validate_batch_publication_graph(store.rows())
    status = store.phase_statuses("official")[ORG]
    assert status["failed"] and status["traceback_sha256"]
    assert all(any(claim.value == "Frozen AS" for claim in item.claims) for item in store.rows()[1:])
    assert all(store.phase_statuses(phase)[ORG]["skipped"] for phase in PHASES[1:])
    store.close()


def test_foundation_deadline_keeps_elapsed_time_and_final_cardinality(scenario, monkeypatch):
    path, argv, calls, failures = scenario

    async def slow(*args, **kwargs):
        await asyncio.sleep(10)

    monkeypatch.setattr(run, "fetch_company", slow)
    (path / "config").write_text(json.dumps({"budget": {"hard_seconds": 2, "soft_seconds": 1,
        "completion_reserve_seconds": 0.5, "financial_seconds": 0}}))
    assert run.main(argv + ["--config", str(path / "config")]) == 0
    store = CheckpointStore(path / "checkpoint")
    status = store.phase_statuses("official")[ORG]
    assert status["deadline_skipped"] and not status["failed"]
    assert status["seconds"] > 0
    assert len(store.rows()) == 2
    validate_batch_publication_graph(store.rows())
    store.close()
