"""Synthetic production FTE selection and persistent worker-cache regressions."""
import asyncio
from copy import deepcopy
import hashlib
import json
import stat
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import signalpost.annual_accounts as annual
from test_signalpost_annual_earlystop import ORG, Process, filing, mock_native_worker, note, word


@pytest.mark.parametrize("first", [5, 4, 6, 3, 2, 7, 8, 11])
def test_priority_then_every_remaining_page_and_first_stop(monkeypatch, first):
    pages, record = filing()
    pages[first] = note(first, "Selskapet har 0,00 arsverk")
    pages[12] = note(12, "Selskapet har 9,00 arsverk")
    rendered, recognized, resources = mock_native_worker(monkeypatch, pages, count=12)
    payload = annual._ocr_worker(b"synthetic", ORG, record)
    order = [1, 5, 4, 6, 3, 2, 7, 8, 9, 10, 11, 12]
    expected = order[:order.index(first) + 1]
    assert rendered == recognized == expected
    assert len(set(rendered)) == len(rendered)
    assert all(resource.closed for resource in resources)
    assert payload["coverage"]["examined_pages"] == expected
    assert payload["coverage"]["fte_pages_examined"] == expected[1:]
    assert payload["coverage"]["financial_anchor_pages"] == []
    assert payload["coverage"]["stopped_early"] is True
    assert payload["coverage"]["coverage_complete"] is False
    checked = annual.reconcile(payload["pages"], ORG, record, workforce_strategy=annual.FTE_STRATEGY)
    assert checked["workforce"]["page"] == first and checked["workforce"]["value"] == 0


def test_all_pages_once_without_fte(monkeypatch):
    pages, record = filing()
    rendered, _, _ = mock_native_worker(monkeypatch, pages, count=13)
    payload = annual._ocr_worker(b"synthetic", ORG, record)
    assert rendered == [1, 5, 4, 6, 3, 2, 7, 8, 9, 10, 11, 12, 13]
    assert payload["coverage"]["coverage_complete"] is True
    assert payload["coverage"]["stopped_early"] is False


@pytest.mark.parametrize("field,text", [
    (0, "Organisasjonsnummer: 999999999"), (1, "Journalnummer: 123"),
    (2, "Arsregnskapets periode: 01.07.2025 - 31.12.2025")])
def test_cover_failure_reads_nothing_else(monkeypatch, field, text):
    pages, record = filing()
    pages[1]["words"][field]["text"] = text
    pages[5] = note(5)
    rendered, _, _ = mock_native_worker(monkeypatch, pages)
    payload = annual._ocr_worker(b"synthetic", ORG, record)
    assert rendered == [1]
    assert annual.reconcile(payload["pages"], ORG, record, workforce_strategy=annual.FTE_STRATEGY)["workforce"] is None


def test_missing_journal_cannot_verify_cover():
    pages, record = filing()
    record["raw"].pop("journalnr")
    assert annual.verify_cover(pages[1], ORG, record) == (False, "document_journal_mismatch", False)


@pytest.mark.parametrize("statement", ["Antall ansatte: 10", "Konsernet har 2,00 arsverk",
    "Antall arsverk i regnskapsaret 100", "Antall arsverk i regnskapsaret 1 00",
    "Antall arsverk i regnskapsaret 1O,00", "Antall arsverk i regnskapsaret 2024 er 2,00"])
def test_rejected_statement_falls_through(monkeypatch, statement):
    pages, record = filing()
    pages[5], pages[4] = note(5, statement), note(4, "Selskapet har 1,00 arsverk")
    rendered, _, _ = mock_native_worker(monkeypatch, pages)
    payload = annual._ocr_worker(b"synthetic", ORG, record)
    assert rendered == [1, 5, 4]
    checked = annual.reconcile(payload["pages"], ORG, record, workforce_strategy=annual.FTE_STRATEGY)
    assert checked["workforce"] is not None, [annual.page_text(p) for p in payload["pages"]]
    assert checked["workforce"]["value"] == 1


def test_same_page_conflict_abstains_without_further_pages(monkeypatch):
    pages, record = filing()
    pages[5] = note(5)
    pages[5]["words"].append(word("Selskapet har 3,00 arsverk", y=110))
    pages[4] = note(4)
    rendered, _, _ = mock_native_worker(monkeypatch, pages)
    payload = annual._ocr_worker(b"synthetic", ORG, record)
    assert rendered == [1, 5]
    assert payload["coverage"]["stop_reason"] == "same_page_fte_conflict"
    checked = annual.reconcile(payload["pages"], ORG, record, workforce_strategy=annual.FTE_STRATEGY)
    assert checked["workforce"] is None and "full_time_equivalents" in checked["conflicts"]


def cache_payload():
    pages, record = filing()
    pages[5] = note(5)
    return {"pages": [pages[1], pages[5]], "coverage": {
        "strategy": annual.FTE_STRATEGY, "examined_pages": [1, 5], "fte_pages_examined": [5],
        "financial_anchor_pages": [], "document_pages": 12, "stopped_early": True,
        "coverage_complete": False, "stop_reason": "first_verified_company_fte"}}, record


def test_persistent_partial_hit_offline_new_instance_and_private_atomic_files(monkeypatch, tmp_path):
    payload, record = cache_payload()
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        return Process(payload)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def check():
        first, hit = await annual.DocumentProcessor(cache_path=tmp_path).ocr(b"pdf", 1, org=ORG, record=record)
        assert not hit

        async def offline(*args, **kwargs):
            raise AssertionError("cache hit must not start OCR")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", offline)
        second, hit = await annual.DocumentProcessor(cache_path=tmp_path).ocr(b"pdf", 1, org=ORG, record=deepcopy(record))
        assert hit and first == second and first.coverage == second.coverage
        assert second.coverage["examined_pages"] == [1, 5]
        assert second.coverage["coverage_complete"] is False

    asyncio.run(check())
    assert len(calls) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert not list(tmp_path.glob(".ocr-*"))
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in tmp_path.iterdir())


@pytest.mark.parametrize("change", ["content", "org", "journal", "start", "end", "currency", "metrics", "parser", "model", "dependency_version", "strategy", "contextless"])
def test_cache_invalidates_content_context_and_implementation(monkeypatch, tmp_path, change):
    payload, record = cache_payload()
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        return Process(payload if args[-1].startswith("{") else payload["pages"])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def check():
        await annual.DocumentProcessor(cache_path=tmp_path).ocr(b"pdf", 1, org=ORG, record=record)
        other, org, body = deepcopy(record), ORG, b"pdf"
        if change == "content":
            body = b"new-pdf"
        elif change == "org":
            org = "999999999"
        elif change == "journal":
            other["raw"]["journalnr"] = "other"
        elif change in {"start", "end"}:
            other["period_" + change] = "2024-01-01"
        elif change == "currency":
            other["currency"] = "EUR"
        elif change == "metrics":
            other["metrics"]["revenue"] += 1
        elif change in {"parser", "model", "strategy"}:
            monkeypatch.setattr(annual, {"parser": "PARSER_VERSION", "model": "OCR_MODEL", "strategy": "FTE_STRATEGY"}[change], "new-version")
        elif change == "dependency_version":
            monkeypatch.setattr(annual, "version", lambda package: "new-version")
        elif change == "contextless":
            org = other = None
        _, hit = await annual.DocumentProcessor(cache_path=tmp_path).ocr(body, 1, org=org, record=other)
        assert not hit and len(calls) == 2

    asyncio.run(check())


@pytest.mark.parametrize("damage", ["truncated", "wrong_identity", "wrong_coverage", "bad_schema"])
def test_corrupt_cache_is_rebuilt(monkeypatch, tmp_path, damage):
    payload, record = cache_payload()
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        return Process(payload)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def check():
        await annual.DocumentProcessor(cache_path=tmp_path).ocr(b"pdf", 1, org=ORG, record=record)
        path = next(tmp_path.glob("*.json"))
        saved = json.loads(path.read_text())
        if damage == "wrong_identity":
            saved["identity"]["pdf_sha256"] = "wrong"
        elif damage == "wrong_coverage":
            saved["payload"]["coverage"]["coverage_complete"] = True
        elif damage == "bad_schema":
            saved["payload"]["pages"] = [{}]
        if damage in {"wrong_coverage", "bad_schema"}:
            saved["payload_sha256"] = hashlib.sha256(json.dumps(saved["payload"], sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()
        path.write_text("{" if damage == "truncated" else json.dumps(saved))
        _, hit = await annual.DocumentProcessor(cache_path=tmp_path).ocr(b"pdf", 1, org=ORG, record=record)
        assert not hit and len(calls) == 2
        assert json.loads(path.read_text())["payload"] == payload

    asyncio.run(check())


def test_concurrent_instances_share_one_worker(monkeypatch, tmp_path):
    payload, record = cache_payload()
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        return Process(payload, delay=.04)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def check():
        results = await asyncio.gather(*(annual.DocumentProcessor(cache_path=tmp_path).ocr(
            b"pdf", 1, org=ORG, record=record) for _ in range(4)))
        assert sum(not hit for _, hit in results) == 1 and len(calls) == 1
        assert all(p.coverage["examined_pages"] == [1, 5] for p, _ in results)

    asyncio.run(check())


def test_queue_startup_and_worker_keep_one_hard_deadline(monkeypatch, tmp_path):
    worker = Process(delay=10)

    async def spawn(*args, **kwargs):
        await asyncio.sleep(.02)
        return worker

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def check():
        processor = annual.DocumentProcessor(cache_path=tmp_path)
        await processor.slots.acquire()
        await processor.slots.acquire()

        async def release():
            await asyncio.sleep(.02)
            processor.slots.release()
            processor.slots.release()

        releasing = asyncio.create_task(release())
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await processor.ocr(b"pdf", .08)
        await releasing
        assert time.monotonic() - started < .2
        assert worker.killed and processor.slots._value == 2 and not processor.cache
        assert not list(tmp_path.glob("*.json"))

    asyncio.run(check())


def test_cache_env_path(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGNALPOST_OCR_CACHE", str(tmp_path))
    assert annual.DocumentProcessor().cache_path == tmp_path
    assert annual.DocumentProcessor(cache_path=tmp_path / "explicit").cache_path == tmp_path / "explicit"


def test_partial_context_cannot_fall_back_to_unbound_cache(tmp_path):
    _, record = filing()

    async def check():
        processor = annual.DocumentProcessor(cache_path=tmp_path)
        with pytest.raises(ValueError, match="supplied together"):
            await processor.ocr(b"pdf", 1, org=ORG)
        with pytest.raises(ValueError, match="supplied together"):
            await processor.ocr(b"pdf", 1, record=record)

    asyncio.run(check())


def test_cache_lock_wait_is_bounded_by_request_deadline(monkeypatch, tmp_path):
    payload, record = cache_payload()
    started = asyncio.Event()
    workers = []

    async def spawn(*args, **kwargs):
        worker = Process(payload, delay=.1)
        workers.append(worker)
        started.set()
        return worker

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def check():
        first = asyncio.create_task(annual.DocumentProcessor(cache_path=tmp_path).ocr(b"pdf", 1, org=ORG, record=record))
        await started.wait()
        with pytest.raises(TimeoutError):
            await annual.DocumentProcessor(cache_path=tmp_path).ocr(b"pdf", .02, org=ORG, record=record)
        await first
        assert len(workers) == 1 and not workers[0].killed

    asyncio.run(check())


def test_production_enrichment_creates_only_fte_and_keeps_incidental_money_in_audit():
    pages, record = filing()
    pages[5] = note(5, "Selskapet har 0,00 arsverk")
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)

    class Gateway:
        async def fetch(self, url, **kwargs):
            return 200, {}, b"%PDF synthetic", url, "ok"

    class Processor:
        async def ocr(self, body, seconds):
            return list(pages.values()), False

    result = SimpleNamespace(observations={}, section_states={}, account_records=[record],
        errors=[], claims=[], evidence=[], snapshots=[])
    asyncio.run(annual.enrich_company(result, ORG, Gateway(), now, Processor()))
    audit = result.observations["annual_accounts_document"]
    assert audit["financial_claims"] == 0 and audit["workforce_claims"] == 1
    assert len(audit["financial_cross_checks"]) == 2
    assert len(result.claims) == 1 and result.claims[0].field == "full_time_equivalents"
    assert result.claims[0].value == 0
    assert {e.page_number for e in result.evidence} == {1, 5}
    assert "accounts_history" not in result.section_states and not result.errors


def test_two_workers_and_cancelled_work_never_cached(monkeypatch, tmp_path):
    workers = []

    class Held(Process):
        async def communicate(self, body):
            await asyncio.Event().wait()

    async def spawn(*args, **kwargs):
        worker = Held()
        workers.append(worker)
        return worker

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def check():
        processor = annual.DocumentProcessor(cache_path=tmp_path)
        tasks = [asyncio.create_task(processor.ocr(str(i).encode(), 1)) for i in range(4)]
        for _ in range(40):
            if len(workers) == 2:
                break
            await asyncio.sleep(.001)
        assert len(workers) == 2
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert len(workers) == 2 and all(w.killed for w in workers)
        assert processor.slots._value == 2 and not processor.cache
        assert not list(tmp_path.glob("*.json"))

    asyncio.run(check())


def test_searchable_pdf_uses_positioned_text_without_ocr(monkeypatch):
    from io import BytesIO
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    texts = [
        ["Organisasjonsnummer: " + ORG, "Journalnummer: 2026488063",
         "Arsregnskapets periode: 01.01.2025 - 31.12.2025", "Morselskap i konsern: Nei"],
        ["Organisasjonsnr: " + ORG, "NOTEOPPLYSNINGER - SELSKAP", "Selskapet har 1,00 arsverk"]]
    for rows in texts:
        page = writer.add_blank_page(1000, 1400)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(("BT /F1 12 Tf 20 1350 Td 22 TL " + " T* ".join("(" + text + ") Tj" for text in rows) + " ET").encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    pdf = BytesIO()
    writer.write(pdf)
    _, record = filing()

    def forbidden(*args, **kwargs):
        raise AssertionError("searchable pages must not start OCR")

    import rapidocr_onnxruntime
    monkeypatch.setattr(rapidocr_onnxruntime, "RapidOCR", forbidden)
    payload = annual._ocr_worker(pdf.getvalue(), ORG, record)
    assert payload["coverage"]["examined_pages"] == [1, 2]
    assert all(p["extraction"] == "pdf_text" for p in payload["pages"])
    checked = annual.reconcile(payload["pages"], ORG, record, workforce_strategy=annual.FTE_STRATEGY)
    assert checked["workforce"] is not None, [annual.page_text(p) for p in payload["pages"]]
    assert checked["workforce"]["value"] == 1


@pytest.mark.parametrize("kind", ["image", "form", "invisible_text"])
def test_image_mixed_or_invisible_text_page_requires_ocr(monkeypatch, kind):
    import pypdfium2.raw as raw
    types = {"image": raw.FPDF_PAGEOBJ_IMAGE, "form": raw.FPDF_PAGEOBJ_FORM,
        "invisible_text": raw.FPDF_PAGEOBJ_TEXT}

    class Page:
        def get_objects(self, **kwargs):
            return [SimpleNamespace(type=types[kind])]

        def get_textpage(self):
            raise AssertionError("unsafe text must not bypass OCR")

    monkeypatch.setattr(raw, "FPDFTextObj_GetTextRenderMode", lambda obj: 3)
    assert annual._searchable_words(Page()) == []
