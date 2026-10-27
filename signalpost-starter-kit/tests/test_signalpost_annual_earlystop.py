"""Isolated filing-worker coverage, selection, subprocess and compatibility checks."""
from copy import deepcopy
from datetime import datetime, timezone
import asyncio
import hashlib
import json
import sys
import time
from types import SimpleNamespace

import pytest

from signalpost.annual_accounts import (
    DocumentProcessor, FTE_STRATEGY, OCRPages, _ocr_worker, enrich_company, reconcile,
)
from signalpost.models import SourceSnapshot


ORG = "987974249"


def word(text, x=10, y=10, width=500, confidence=.99):
    return dict(text=text, x1=x, x2=x + width, y1=y, y2=y + 12, confidence=confidence)


def note(page, statement="Antall arsverk i regnskapsaret 2025 er 10,00"):
    return dict(page=page, width=1000, height=1400, words=[
        word("Organisasjonsnr: " + ORG),
        word("NOTEOPPLYSNINGER - SELSKAP", y=30), word(statement, y=70, width=800)])


def filing():
    cover = dict(page=1, width=1000, height=1400, words=[
        word("Organisasjonsnummer: " + ORG), word("Journalnummer: 2026488063", y=30),
        word("Arsregnskapets periode: 01.01.2025 - 31.12.2025", y=50, width=800),
        word("Morselskap i konsern: Nei", y=70)])
    financial = dict(page=2, width=1000, height=1400, words=[
        word("Organisasjonsnr: " + ORG), word("RESULTATREGNSKAP", y=30),
        word("Belop i: NOK", y=50, width=200), word("2025", 650, 50, 50),
        word("2024", 850, 50, 50), word("Sum inntekter", 10, 90, 300),
        word("5 135 536", 610, 90, 120), word("5 590 589", 820, 90, 120),
        word("Driftsresultat", 10, 110, 300), word("-22 366", 610, 110, 120),
        word("1 099 625", 820, 110, 120)])
    record = dict(period_start="2025-01-01", period_end="2025-12-31", currency="NOK",
        raw={"journalnr": "2026488063", "virksomhet": {"organisasjonsnummer": ORG}},
        metrics=dict(revenue=5135536, operating_result=-22366), scope="legal_entity", _source_prefix="/0")
    return {1: cover, 2: financial}, record


def mock_native_worker(monkeypatch, pages, count=9):
    """Exercise the actual worker control flow without loading native libraries."""
    rendered, recognized, resources = [], [], []

    class Resource:
        closed = False

        def __init__(self, index):
            self.index = index
            resources.append(self)

        def close(self):
            self.closed = True

    class Image(Resource):
        width, height = 1000, 1400

        def convert(self, mode):
            assert mode == "RGB"
            return self

    class Bitmap(Resource):
        def to_pil(self):
            return Image(self.index)

    class Page(Resource):
        def render(self, **kwargs):
            rendered.append(self.index + 1)
            return Bitmap(self.index)

    class Document(Resource):
        def __len__(self):
            return count

        def __getitem__(self, index):
            assert 0 <= index < count
            return Page(index)

    class Engine:
        def __init__(self, **kwargs):
            assert kwargs == dict(intra_op_num_threads=1, inter_op_num_threads=1)

        def __call__(self, image, **kwargs):
            number = image.index + 1
            recognized.append(number)
            page = pages.get(number, note(number, "Antall ansatte: 10"))
            output = [([[w["x1"], w["y1"]], [w["x2"], w["y1"]],
                [w["x2"], w["y2"]], [w["x1"], w["y2"]]], w["text"], w["confidence"])
                for w in page["words"]]
            return output, None

    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace(asarray=lambda image: image))
    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=lambda pdf: Document(-1)))
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", SimpleNamespace(RapidOCR=Engine))
    return rendered, recognized, resources


@pytest.mark.parametrize("first,expected", [
    (5, [1, 5, 2]), (4, [1, 5, 4, 2]), (6, [1, 5, 4, 6, 2]),
    (3, [1, 5, 4, 6, 3, 2]), (7, [1, 5, 4, 6, 3, 7, 2]),
    (2, [1, 5, 4, 6, 3, 7, 2]),
])
def test_real_worker_stops_rendering_and_retains_one_financial_anchor(monkeypatch, first, expected):
    pages, record = filing()
    pages[first] = note(first, "Selskapet har hatt 0,00 arsverk")
    rendered, recognized, resources = mock_native_worker(monkeypatch, pages)
    payload = _ocr_worker(b"pdf", ORG, record)
    assert rendered == recognized == expected
    assert all(resource.closed for resource in resources)
    coverage = payload["coverage"]
    assert coverage["examined_pages"] == expected
    assert coverage["strategy"] == FTE_STRATEGY
    assert coverage["financial_anchor_pages"] == [2]
    assert coverage["fte_pages_examined"] == (expected[1:-1] if first != 2 else expected[1:])
    assert coverage["stopped_early"] is (first != 2)
    assert coverage["coverage_complete"] is False
    assert coverage["document_pages"] == 9
    assert coverage["stop_reason"] == "first_verified_company_fte"
    checked = reconcile(payload["pages"], ORG, record, workforce_strategy=FTE_STRATEGY)
    assert checked["workforce"]["value"] == 0
    assert checked["workforce"]["page"] == first
    assert len(checked["financial"]) == (0 if first == 2 else 2)


@pytest.mark.parametrize("bad", ["org", "period", "journal"])
def test_worker_checks_exact_cover_before_notes_or_anchor(monkeypatch, bad):
    pages, record = filing()
    field, value = {"org": (0, "Organisasjonsnummer: 999999999"),
        "period": (2, "Arsregnskapets periode: 01.07.2025 - 31.12.2025"),
        "journal": (1, "Journalnummer: 123")}[bad]
    pages[1]["words"][field]["text"] = value
    rendered, _, _ = mock_native_worker(monkeypatch, pages)
    payload = _ocr_worker(b"pdf", ORG, record)
    assert rendered == [1]
    assert payload["coverage"]["financial_anchor_pages"] == []
    assert payload["coverage"]["fte_pages_examined"] == []
    assert payload["coverage"]["coverage_complete"] is False
    assert reconcile(payload["pages"], ORG, record, workforce_strategy=FTE_STRATEGY)["workforce"] is None


@pytest.mark.parametrize("invalid", ["headcount", "group", "company", "year", "confidence", "decimal"])
def test_worker_rejects_invalid_first_page_and_continues(monkeypatch, invalid):
    pages, record = filing()
    pages[5], pages[4] = note(5), note(4, "Selskapet har 2,50 arsverk")
    if invalid == "headcount":
        pages[5]["words"][-1]["text"] = "Antall ansatte: 10,00"
    elif invalid == "group":
        pages[5]["words"][1]["text"] = "NOTEOPPLYSNINGER - KONSERN"
    elif invalid == "company":
        pages[5]["words"][0]["text"] = "Organisasjonsnr: 999999999"
    elif invalid == "year":
        pages[5]["words"][-1]["text"] = "Antall arsverk i regnskapsaret 2024 er 10,00"
    elif invalid == "confidence":
        pages[5]["words"][-1]["confidence"] = .5
    else:
        pages[5]["words"][-1]["text"] = "Antall arsverk i regnskapsaret 100"
    rendered, _, _ = mock_native_worker(monkeypatch, pages)
    payload = _ocr_worker(b"pdf", ORG, record)
    assert rendered == [1, 5, 4, 2]
    out = reconcile(payload["pages"], ORG, record, workforce_strategy=FTE_STRATEGY)
    assert out["workforce"]["page"] == 4 and out["workforce"]["value"] == 2.5


def test_same_page_conflict_is_terminal_abstention_and_cross_page_is_not_consensus(monkeypatch):
    pages, record = filing()
    pages[5], pages[4] = note(5), note(4, "Selskapet har 2,00 arsverk")
    pages[5]["words"].append(word("Selskapet har 3,00 arsverk", y=110))
    rendered, _, _ = mock_native_worker(monkeypatch, pages)
    payload = _ocr_worker(b"pdf", ORG, record)
    assert rendered == [1, 5, 2]
    assert payload["coverage"]["stop_reason"] == "same_page_fte_conflict"
    checked = reconcile(payload["pages"], ORG, record, workforce_strategy=FTE_STRATEGY)
    assert checked["workforce"] is None
    assert "full_time_equivalents" in checked["conflicts"]
    assert len(checked["financial"]) == 2
    pages[5]["words"].pop()
    all_pages = list(pages.values())
    assert reconcile(all_pages, ORG, record)["workforce"] is None
    selected = reconcile(all_pages, ORG, record, workforce_strategy=FTE_STRATEGY)
    assert selected["workforce"]["page"] == 5
    assert "full_time_equivalents" not in selected["conflicts"]


@pytest.mark.parametrize("count,expected,complete", [(2, [1, 2], True),
    (7, [1, 5, 4, 6, 3, 7, 2], True), (12, [1, 5, 4, 6, 3, 7, 2], False)])
def test_no_fte_exhausts_only_bounded_candidates(monkeypatch, count, expected, complete):
    pages, record = filing()
    rendered, _, _ = mock_native_worker(monkeypatch, pages, count=count)
    payload = _ocr_worker(b"pdf", ORG, record)
    assert rendered == expected
    assert payload["coverage"]["coverage_complete"] is complete
    assert payload["coverage"]["stopped_early"] is False
    assert payload["coverage"]["stop_reason"] == "candidate_pages_exhausted"


def test_legacy_worker_keeps_list_interface_and_seven_page_cap(monkeypatch):
    pages, _ = filing()
    rendered, _, _ = mock_native_worker(monkeypatch, pages)
    result = _ocr_worker(b"pdf")
    assert isinstance(result, list)
    assert rendered == [1, 2, 5, 4, 6, 3, 7]


class Process:
    returncode = None
    killed = False

    def __init__(self, payload=None, delay=0):
        self.payload = [] if payload is None else payload
        self.delay = delay

    async def communicate(self, body):
        await asyncio.sleep(self.delay)
        self.returncode = 0
        return json.dumps(self.payload).encode(), b""

    def kill(self):
        self.killed, self.returncode = True, -9

    async def wait(self):
        return self.returncode


def test_cache_binds_partial_pages_to_filing_context_and_strategy(monkeypatch):
    pages, record = filing()
    pages[5] = note(5)
    mock_native_worker(monkeypatch, pages)
    payload = _ocr_worker(b"pdf", ORG, record)
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        return Process(payload if args[-1].startswith("{") else list(pages.values()))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def check():
        processor = DocumentProcessor()
        partial, hit = await processor.ocr(b"pdf", 1, org=ORG, record=record)
        assert not hit and isinstance(partial, OCRPages)
        assert partial.coverage["examined_pages"] == [1, 5, 2]
        assert partial.coverage["coverage_complete"] is False
        assert hashlib.sha256(b"pdf").hexdigest() not in processor.cache
        repeated, hit = await processor.ocr(b"pdf", 1, org=ORG, record=deepcopy(record))
        assert hit and repeated.coverage == partial.coverage and len(calls) == 1
        context = json.loads(calls[0][-1])
        assert context["org"] == ORG and context["record"]["period_start"] == record["period_start"]
        assert context["record"]["raw"]["journalnr"] == record["raw"]["journalnr"]
        assert context["record"]["currency"] == "NOK"
        assert context["record"]["metrics"] == record["metrics"]
        await processor.ocr(b"pdf", 1)
        assert len(calls) == 2
        other = deepcopy(record)
        other["raw"]["journalnr"] = "other"
        await processor.ocr(b"pdf", 1, org=ORG, record=other)
        assert len(calls) == 3
        await processor.ocr(b"pdf", 1, org="999999999", record=record)
        assert len(calls) == 4
        other = deepcopy(record)
        other["metrics"]["revenue"] += 1
        await processor.ocr(b"pdf", 1, org=ORG, record=other)
        assert len(calls) == 5
        other = deepcopy(record)
        other["period_start"] = "2025-07-01"
        await processor.ocr(b"pdf", 1, org=ORG, record=other)
        assert len(calls) == 6

    asyncio.run(check())


def test_queue_startup_and_ocr_share_one_deadline(monkeypatch):
    async def check():
        worker = Process(delay=10)
        processor = DocumentProcessor()
        await processor.slots.acquire()
        await processor.slots.acquire()

        async def spawn(*args, **kwargs):
            await asyncio.sleep(.025)
            return worker

        async def release():
            await asyncio.sleep(.025)
            processor.slots.release()
            processor.slots.release()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        releasing = asyncio.create_task(release())
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await processor.ocr(b"pdf", .08)
        assert time.monotonic() - started < .14
        await releasing
        assert worker.killed and processor.slots._value == 2 and not processor.cache

    asyncio.run(check())


def test_startup_is_inside_deadline_and_global_budget_expires(monkeypatch):
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        await asyncio.sleep(10)
        raise AssertionError("startup should have been cancelled")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def check():
        processor = DocumentProcessor(seconds=.03)
        with pytest.raises(TimeoutError):
            await processor.ocr(b"one", 90)
        assert processor.slots._value == 2 and not processor.cache
        with pytest.raises(TimeoutError):
            await processor.ocr(b"two", 90)
        assert len(calls) == 1
        expired = DocumentProcessor(deadline=time.monotonic() - 1)
        with pytest.raises(TimeoutError):
            await expired.ocr(b"three", 90)
        assert len(calls) == 1

    asyncio.run(check())


def test_two_workers_maximum_and_cancellation_kills_without_caching(monkeypatch):
    workers = []
    active = 0
    maximum = 0

    class HeldProcess(Process):
        async def communicate(self, body):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1

    async def spawn(*args, **kwargs):
        worker = HeldProcess()
        workers.append(worker)
        return worker

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def check():
        processor = DocumentProcessor()
        tasks = [asyncio.create_task(processor.ocr(str(i).encode(), 1)) for i in range(4)]
        for _ in range(20):
            if len(workers) == 2 and active == 2:
                break
            await asyncio.sleep(.001)
        assert maximum == 2 and len(workers) == 2
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert all(worker.killed for worker in workers)
        assert not processor.cache and processor.slots._value == 2

    asyncio.run(check())


def test_enrichment_keeps_generic_stub_and_publishes_actual_coverage(monkeypatch):
    pages, record = filing()
    pages[5] = note(5, "Selskapet har 0,00 arsverk")
    mock_native_worker(monkeypatch, pages)
    payload = _ocr_worker(b"pdf", ORG, record)
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    source = dict(url="https://example.test/accounts", retrieved_at=now, content_sha256="a" * 64)

    class Gateway:
        async def fetch(self, url, **kwargs):
            return 200, {}, b"%PDF mock", url, "ok"

    class LegacyStub:
        async def ocr(self, body, seconds):
            assert body == b"%PDF mock" and seconds > 0
            return OCRPages(payload["pages"], payload["coverage"]), False

    result = SimpleNamespace(observations={}, section_states={}, account_records=[record],
        errors=[], claims=[], evidence=[], account_source=source, snapshots=[SourceSnapshot(
            source_id="json", source_url=source["url"], retrieved_at=now, content_sha256="a" * 64,
            http_status=200, cache_mode="transient", rights_status="public_official_filing_factual_extraction")])
    asyncio.run(enrich_company(result, ORG, Gateway(), now, LegacyStub()))
    audit = result.observations["annual_accounts_document"]
    assert audit["examined_pages"] == [1, 5, 2]
    assert audit["fte_pages_examined"] == [5]
    assert audit["financial_anchor_pages"] == [2]
    assert audit["strategy"] == FTE_STRATEGY and audit["stopped_early"] is True
    assert audit["coverage_complete"] is False
    assert audit["workforce_claims"] == 1 and audit["financial_claims"] == 2
    assert not result.errors
    assert {e.page_number for e in result.evidence if e.page_number is not None} == {1, 2, 5}
    assert next(c for c in result.claims if c.field == "full_time_equivalents").value == 0
