import asyncio

import pytest

from signalpost.annual_accounts import DocumentProcessor
from signalpost.recording import HttpRecording


def test_ocr_replay_reconciles_fresh_cached_pages_and_preserves_cache_annotation(tmp_path, monkeypatch):
    capture = HttpRecording(tmp_path / "capture", replay=False)
    processor = DocumentProcessor(cache_path=tmp_path / "ocr", recording=capture)
    pages = [{"page": 1, "width": 100, "height": 100, "words": []}]

    async def worker(*args, **kwargs):
        return pages

    monkeypatch.setattr(processor, "_run_worker", worker)
    original = asyncio.run(processor.ocr(b"%PDF fixture", 10))
    assert original == (pages, False)
    capture.seal()
    recording = HttpRecording(tmp_path / "capture", replay=True)
    replay = DocumentProcessor(cache_path=tmp_path / "ocr", cache_only=True, recording=recording)

    async def forbidden(*args, **kwargs):
        raise AssertionError("replay cannot spawn OCR")

    monkeypatch.setattr(replay, "_run_worker", forbidden)
    assert asyncio.run(replay.ocr(b"%PDF fixture", 10)) == original
    recording.assert_complete()


def test_recorded_ocr_timeout_replays_without_a_cache_or_worker(tmp_path, monkeypatch):
    capture = HttpRecording(tmp_path / "capture", replay=False)
    processor = DocumentProcessor(cache_path=tmp_path / "ocr", recording=capture)

    async def timeout(*args, **kwargs):
        raise TimeoutError("ocr_deadline")

    monkeypatch.setattr(processor, "_run_worker", timeout)
    with pytest.raises(TimeoutError):
        asyncio.run(processor.ocr(b"%PDF fixture", 10))
    capture.seal()
    recording = HttpRecording(tmp_path / "capture", replay=True)
    replay = DocumentProcessor(cache_path=tmp_path / "missing-cache", cache_only=True, recording=recording)
    monkeypatch.setattr(replay, "_run_worker", timeout)
    with pytest.raises(TimeoutError, match="ocr_deadline"):
        asyncio.run(replay.ocr(b"%PDF fixture", 10))
    assert replay.cache_misses == 0
    recording.assert_complete()
