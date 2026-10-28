import asyncio
import json
import socket

import pytest

from signalpost import network, run
from signalpost.annual_accounts import FTE_STRATEGY
from test_signalpost_annual_earlystop import ORG, Process, filing, note
from test_signalpost_financial_calibration import raw_record


def test_record_and_replay_full_pipeline_with_warm_ocr_and_no_network(tmp_path, monkeypatch, capsys):
    original_gateway = network.NetworkGateway
    original_validate = network.validate_public_host
    calls = []

    class FixtureTransport:
        async def request(self, url, headers, timeout):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return 200, {}, b"User-agent: *\nAllow: /\n", url
            if "/api/publicToken" in url:
                return 200, {}, b"eyJfixture.public.token", url
            if "pam-stilling-feed.nav.no" in url:
                body = {"items": []}
            elif "query.wikidata.org" in url:
                body = {"results": {"bindings": []}}
            elif "/aarsregnskap/kopi/" in url:
                return 200, {"Content-Type": "application/pdf"}, b"%PDF fixture", url
            elif "/regnskapsregisteret/regnskap/" in url:
                record = raw_record()
                record["journalnr"] = "2026488063"
                body = [record]
            elif "/roller" in url:
                body = {"rollegrupper": []}
            elif "/underenheter?" in url:
                body = {"_embedded": {"underenheter": []}, "page": {"number": 0, "totalPages": 1}}
            else:
                body = {"organisasjonsnummer": ORG, "navn": "Replay AS", "organisasjonsform": {"kode": "AS"}}
            return 200, {"Content-Type": "application/json"}, json.dumps(body).encode(), url

    def gateway(**kwargs):
        instance = original_gateway(transport=FixtureTransport(), **kwargs)
        async def no_wait(*args, **options):
            return None
        instance._pace = no_wait
        return instance

    monkeypatch.setattr(run, "NetworkGateway", gateway)
    monkeypatch.setattr(network, "validate_public_host", lambda *args, **kwargs: ("8.8.8.8",))
    pages, _ = filing()
    pages[5] = note(5, "Selskapet har 0,00 arsverk")
    payload = {"pages": [pages[1], pages[5]], "coverage": {"strategy": FTE_STRATEGY,
        "examined_pages": [1, 5], "fte_pages_examined": [5], "financial_anchor_pages": [],
        "document_pages": 12, "stopped_early": True, "coverage_complete": False,
        "stop_reason": "first_verified_company_fte"}}

    async def worker(*args, **kwargs):
        return Process(payload)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", worker)
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps({"organisation_number": ORG}) + "\n")
    capture = tmp_path / "capture"

    def arguments(name):
        return ["--input", str(source), "--output", str(tmp_path / (name + ".jsonl")),
            "--state-output", str(tmp_path / (name + ".state")), "--checkpoint", str(tmp_path / (name + ".sqlite")),
            "--live-brreg", "--live-websites", "--no-keyless-websites"]

    assert run.main(arguments("live") + ["--record-http", str(capture)]) == 0
    before = json.loads((tmp_path / "live.jsonl").read_text())
    assert any(claim["field"] == "full_time_equivalents" for claim in before["claims"])
    assert any(claim["unit_assumed_currency"] for claim in before["claims"])
    assert any("aarsregnskap/kopi" in url for url in calls)

    def forbidden(*args, **kwargs):
        raise AssertionError("replay cannot resolve DNS, access transport or start OCR")

    monkeypatch.setattr(network, "validate_public_host", original_validate)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(FixtureTransport, "request", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    assert run.main(arguments("replay") + ["--replay-http", str(capture)]) == 0
    after = json.loads((tmp_path / "replay.jsonl").read_text())
    assert before["claims"] == after["claims"]
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["research_mode"] == "replay" and report["actual_network_requests"] == 0
    assert not report["scheduler_passes"]["ocr_replay_misses"]

    source.write_text(json.dumps({"organisation_number": "923609016"}) + "\n")
    assert run.main(arguments("mismatch") + ["--replay-http", str(capture)]) == 2
    assert not (tmp_path / "mismatch.jsonl").exists()


def test_replay_only_ocr_miss_never_starts_a_worker(tmp_path, monkeypatch):
    from signalpost.annual_accounts import DocumentProcessor

    async def forbidden(*args, **kwargs):
        raise AssertionError("offline cache miss must not invoke OCR")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    processor = DocumentProcessor(cache_path=tmp_path, cache_only=True)
    with pytest.raises(RuntimeError, match="offline_ocr_cache_miss"):
        asyncio.run(processor.ocr(b"uncaptured PDF", 1))
    assert processor.cache_misses == 1
