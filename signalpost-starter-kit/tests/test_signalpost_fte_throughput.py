"""Synthetic PDF throughput, attribution, timing and replay regressions."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from types import SimpleNamespace

import pytest

import signalpost.annual_accounts as annual
from test_signalpost_annual_earlystop import ORG, Process, filing


COVER_ROWS = ["Organisasjonsnummer: " + ORG, "Journalnummer: 2026488063",
    "Arsregnskapets periode: 01.01.2025 - 31.12.2025", "Morselskap i konsern: Nei"]
NOTE_ROWS = ["Organisasjonsnr: " + ORG, "NOTEOPPLYSNINGER - SELSKAP"]


def synthetic_pdf(page_rows, scanned_pages=()):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    for number, rows in enumerate(page_rows, start=1):
        if number in scanned_pages:
            from PIL import Image, ImageDraw, ImageFont

            image = Image.new("RGB", (1000, 1400), "white")
            draw = ImageDraw.Draw(image)
            scan_font = ImageFont.truetype("DejaVuSans.ttf", 24)
            for position, text in enumerate(rows):
                horizontal = 20
                for token in text.split():
                    draw.text((horizontal, 40 + position * 42), token, fill="black", font=scan_font)
                    horizontal += draw.textlength(token, font=scan_font) + 55
            scanned = BytesIO()
            image.save(scanned, format="PDF")
            image.close()
            writer.add_page(PdfReader(scanned).pages[0])
        else:
            page = writer.add_blank_page(1000, 1400)
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
                DictionaryObject({NameObject("/F1"): font})})
            stream = DecodedStreamObject()
            stream.set_data(("BT /F1 20 Tf 20 1350 Td 42 TL " +
                " T* ".join("(" + text + ") Tj" for text in rows) + " ET").encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def checked_workforce(payload, record):
    return annual.reconcile(payload["pages"], ORG, record,
        workforce_strategy=annual.FTE_STRATEGY)["workforce"]


def decorated_pdf(document, *, form=False, large_image=False):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject

    writer = PdfWriter()
    for page in PdfReader(BytesIO(document)).pages:
        writer.add_page(page)
        current = writer.pages[-1]
        contents = current["/Contents"].get_data()
        resources = current["/Resources"]
        asset = DecodedStreamObject()
        if form:
            asset.set_data(contents)
            asset.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/BBox"): ArrayObject([NumberObject(value) for value in (0, 0, 1000, 1400)]),
                NameObject("/Resources"): DictionaryObject({NameObject("/Font"): resources["/Font"]})})
            contents = b"q /Asset Do Q"
        else:
            asset.set_data(b"\x00\x80\x00")
            asset.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(1), NameObject("/Height"): NumberObject(1),
                NameObject("/ColorSpace"): NameObject("/DeviceRGB"), NameObject("/BitsPerComponent"): NumberObject(8)})
            contents += b" q 800 0 0 1000 20 100 cm /Asset Do Q" if large_image else b" q 20 0 0 20 900 1350 cm /Asset Do Q"
        resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Asset"): writer._add_object(asset)})
        stream = DecodedStreamObject()
        stream.set_data(contents)
        current[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("form", [False, True])
def test_visible_text_with_logo_or_form_does_not_require_ocr(monkeypatch, form):
    import rapidocr_onnxruntime

    def forbidden(*args, **kwargs):
        raise AssertionError("visible text must not initialize OCR")

    monkeypatch.setattr(rapidocr_onnxruntime, "RapidOCR", forbidden)
    document = decorated_pdf(synthetic_pdf([COVER_ROWS, NOTE_ROWS + ["Selskapet har 2,00 arsverk"]]), form=form)
    payload = annual._ocr_worker(document, ORG, filing()[1])
    assert checked_workforce(payload, filing()[1])["value"] == 2
    assert {page["extraction"] for page in payload["pages"]} == {"pdf_text"}


def test_large_image_body_does_not_qualify_as_a_usable_text_page():
    import pypdfium2

    document = pypdfium2.PdfDocument(decorated_pdf(synthetic_pdf([COVER_ROWS]), large_image=True))
    page = document[0]
    try:
        assert annual._searchable_words(page) == []
    finally:
        page.close()
        document.close()


def test_searchable_priority_never_initializes_ocr_and_measures_text(monkeypatch):
    import rapidocr_onnxruntime

    def forbidden(*args, **kwargs):
        raise AssertionError("searchable document must not initialize OCR")

    monkeypatch.setattr(rapidocr_onnxruntime, "RapidOCR", forbidden)
    document = synthetic_pdf([COVER_ROWS, NOTE_ROWS, NOTE_ROWS,
        NOTE_ROWS + ["Selskapet har 9,00 arsverk"], NOTE_ROWS + ["Selskapet har 1,00 arsverk"], NOTE_ROWS])
    record = filing()[1]
    payload = annual._ocr_worker(document, ORG, record)
    assert payload["coverage"]["examined_pages"] == [1, 5]
    assert checked_workforce(payload, record)["value"] == 1
    assert {page["extraction"] for page in payload["pages"]} == {"pdf_text"}
    assert payload["metrics"]["text_layer_seconds"] > 0
    assert payload["metrics"]["ocr_engine_seconds"] == 0
    assert payload["metrics"]["worker_seconds"] >= payload["metrics"]["text_layer_seconds"]


@pytest.mark.parametrize("scanned_pages,expected_methods", [
    ((1, 2), ["ocr", "ocr"]), ((2,), ["pdf_text", "ocr"]), ((1,), ["ocr", "pdf_text"])])
def test_real_scanned_and_mixed_documents_keep_attribution(scanned_pages, expected_methods):
    document = synthetic_pdf([COVER_ROWS, NOTE_ROWS + ["Selskapet har 2,00 arsverk"]], scanned_pages)
    record = filing()[1]
    payload = annual._ocr_worker(document, ORG, record)
    assert payload["coverage"]["examined_pages"] == [1, 2]
    assert [page["extraction"] for page in payload["pages"]] == expected_methods
    workforce = checked_workforce(payload, record)
    assert workforce is not None, [annual.page_text(page) for page in payload["pages"]]
    assert workforce["value"] == 2
    assert payload["metrics"]["ocr_engine_seconds"] > 0


@pytest.mark.parametrize("statement", ["Selskapet har 100 arsverk", "Konsernet har 1,00 arsverk",
    "Antall arsverk i regnskapsaret 2024 er 1,00"])
def test_searchable_ambiguous_group_and_historical_values_abstain(statement):
    payload = annual._ocr_worker(synthetic_pdf([COVER_ROWS, NOTE_ROWS + [statement]]), ORG, filing()[1])
    assert checked_workforce(payload, filing()[1]) is None


def test_searchable_same_page_conflict_stops_and_abstains():
    payload = annual._ocr_worker(synthetic_pdf([COVER_ROWS, NOTE_ROWS, NOTE_ROWS, NOTE_ROWS,
        NOTE_ROWS + ["Selskapet har 1,00 arsverk", "Selskapet har 2,00 arsverk"],
        NOTE_ROWS + ["Selskapet har 3,00 arsverk"]]), ORG, filing()[1])
    assert payload["coverage"]["examined_pages"] == [1, 5]
    assert payload["coverage"]["stop_reason"] == "same_page_fte_conflict"
    assert checked_workforce(payload, filing()[1]) is None


@pytest.mark.parametrize("cores,requested,expected", [(1, "4", 1), (3, "4", 3),
    (32, "99", 4), (8, "1", 1), (8, "2", 2)])
def test_worker_limit_caps_requested_workers_by_cores_and_conservative_max(monkeypatch, tmp_path, cores, requested, expected):
    monkeypatch.setattr(annual.os, "cpu_count", lambda: cores)
    monkeypatch.setattr(annual.os, "sched_getaffinity", lambda process: set(range(cores)), raising=False)
    monkeypatch.setenv("SIGNALPOST_OCR_WORKERS", requested)
    processor = annual.DocumentProcessor(cache_path=tmp_path)
    assert processor.worker_count == processor.slots._value == expected


@pytest.mark.parametrize("requested", ["0", "-1", "invalid"])
def test_worker_limit_rejects_invalid_configuration(monkeypatch, requested):
    monkeypatch.setenv("SIGNALPOST_OCR_WORKERS", requested)
    with pytest.raises(ValueError):
        annual.DocumentProcessor()


def test_configured_four_worker_pool_remains_bounded_killable_and_uncached(monkeypatch, tmp_path):
    monkeypatch.setattr(annual.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(annual.os, "sched_getaffinity", lambda process: set(range(8)), raising=False)
    monkeypatch.setenv("SIGNALPOST_OCR_WORKERS", "4")
    workers = []

    class Held(Process):
        async def communicate(self, body):
            await asyncio.Event().wait()

    async def spawn(*args, **kwargs):
        assert all(kwargs["env"][key] == "1" for key in
            ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"))
        worker = Held()
        workers.append(worker)
        return worker

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def check():
        processor = annual.DocumentProcessor(cache_path=tmp_path)
        tasks = [asyncio.create_task(processor.ocr(str(number).encode(), 1)) for number in range(6)]
        try:
            for attempt in range(100):
                if len(workers) == 4:
                    break
                await asyncio.sleep(.001)
            assert len(workers) == 4
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert all(worker.killed for worker in workers)
        assert processor.slots._value == 4 and not processor.cache
        assert not list(tmp_path.glob("*.json"))

    asyncio.run(check())


def test_real_pdf_cache_preserves_provenance_without_reusing_elapsed_metrics(monkeypatch, tmp_path):
    document = synthetic_pdf([COVER_ROWS, NOTE_ROWS + ["Selskapet har 1,00 arsverk"]])
    record = filing()[1]

    async def check():
        first, hit = await annual.DocumentProcessor(cache_path=tmp_path).ocr(document, 10, org=ORG, record=record)
        assert not hit and first.metrics["worker_seconds"] > 0

        async def forbidden(*args, **kwargs):
            raise AssertionError("persistent cache must not start a worker")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
        second, hit = await annual.DocumentProcessor(cache_path=tmp_path, cache_only=True).ocr(
            document, 10, org=ORG, record=deepcopy(record))
        assert hit and first == second and first.coverage == second.coverage
        assert second.metrics["worker_seconds"] == second.metrics["text_layer_seconds"] == 0
        assert second.metrics["ocr_engine_seconds"] == 0
        assert second.metrics["request_seconds"] > 0
        saved = json.loads(next(tmp_path.glob("*.json")).read_text())
        assert "metrics" not in saved["payload"]

    asyncio.run(check())


def test_enrichment_audits_cache_method_counts_and_fresh_retrieval(monkeypatch, tmp_path):
    document = synthetic_pdf([COVER_ROWS, NOTE_ROWS + ["Selskapet har 1,00 arsverk"]])
    record = filing()[1]

    class Gateway:
        observed_at = datetime(2026, 10, 27, tzinfo=timezone.utc)

        async def fetch(self, url, **kwargs):
            return 200, {}, document, url, "ok"

    def result():
        return SimpleNamespace(observations={}, section_states={}, account_records=[record],
            errors=[], claims=[], evidence=[], snapshots=[])

    async def check():
        gateway = Gateway()
        first = await annual.enrich_company(result(), ORG, gateway, gateway.observed_at,
            annual.DocumentProcessor(cache_path=tmp_path))
        first_audit = first.observations["annual_accounts_document"]
        assert first_audit["text_layer_pages"] == 2 and first_audit["ocr_pages"] == 0
        assert first_audit["resolved_method"] == first_audit["extraction_method"] == "pdf_text"
        assert first_audit["worker_seconds"] > 0 and first_audit["text_layer_seconds"] > 0
        assert first_audit["ocr_engine_seconds"] == 0 and first_audit["download_seconds"] >= 0
        gateway.observed_at = datetime(2026, 10, 28, tzinfo=timezone.utc)

        async def forbidden(*args, **kwargs):
            raise AssertionError("fresh retrieval of identical PDF must reuse its extraction cache")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
        second = await annual.enrich_company(result(), ORG, gateway, gateway.observed_at,
            annual.DocumentProcessor(cache_path=tmp_path, cache_only=True))
        audit = second.observations["annual_accounts_document"]
        assert audit["cache_hit"] and audit["text_layer_pages"] == 2
        assert audit["worker_seconds"] == 0 and audit["resolved_method"] == "pdf_text"
        assert {snapshot.retrieved_at for snapshot in second.snapshots} == {gateway.observed_at}
        assert {evidence.retrieved_at for evidence in second.evidence} == {gateway.observed_at}
        assert second.claims[0].claim_id == first.claims[0].claim_id
        assert not first.errors and not second.errors

    asyncio.run(check())


def test_enrichment_attributes_resolved_scanned_page_to_ocr(tmp_path):
    document = synthetic_pdf([COVER_ROWS, NOTE_ROWS + ["Selskapet har 1,00 arsverk"]], scanned_pages=(2,))
    record = filing()[1]

    class Gateway:
        observed_at = datetime(2026, 10, 27, tzinfo=timezone.utc)

        async def fetch(self, url, **kwargs):
            return 200, {}, document, url, "ok"

    result = SimpleNamespace(observations={}, section_states={}, account_records=[record],
        errors=[], claims=[], evidence=[], snapshots=[])

    async def check():
        gateway = Gateway()
        enriched = await annual.enrich_company(result, ORG, gateway, gateway.observed_at,
            annual.DocumentProcessor(cache_path=tmp_path))
        audit = enriched.observations["annual_accounts_document"]
        assert audit["text_layer_pages"] == 1 and audit["ocr_pages"] == 1
        assert audit["extraction_method"] == "mixed"
        assert audit["resolved_method"] == "ocr"
        assert audit["ocr_engine_seconds"] > 0 and audit["text_layer_seconds"] > 0
        assert audit["workforce_claims"] == 1 and not enriched.errors

    asyncio.run(check())


def test_recording_restores_only_timing_controls_and_rechecks_cached_page_identity(monkeypatch, tmp_path):
    document = synthetic_pdf([COVER_ROWS, NOTE_ROWS + ["Selskapet har 1,00 arsverk"]])
    record = filing()[1]

    class Recording:
        replay = False

        def __init__(self):
            self.controls = {}
            self.identities = {}

        def record_execution(self, key, control):
            self.controls[key] = control

        def replay_execution(self, key):
            return self.controls[key]

        def assert_identity(self, key, payload):
            digest = hashlib.sha256(payload).hexdigest()
            if self.replay:
                assert digest == self.identities[key]
            else:
                self.identities[key] = digest

    async def check():
        recording = Recording()
        first, hit = await annual.DocumentProcessor(cache_path=tmp_path, recording=recording).ocr(
            document, 10, org=ORG, record=record)
        assert not hit
        assert all("pages" not in control for control in recording.controls.values())
        recording.replay = True

        async def forbidden(*args, **kwargs):
            raise AssertionError("offline replay must use the PDF-context cache")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
        second, replayed_hit = await annual.DocumentProcessor(cache_path=tmp_path, recording=recording,
            cache_only=True).ocr(document, 10, org=ORG, record=record)
        assert not replayed_hit and first.metrics == second.metrics
        assert first == second and first.coverage == second.coverage

    asyncio.run(check())
