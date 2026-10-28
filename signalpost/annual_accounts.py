"""Bounded official filing FTE extraction; no network in document workers.

Production enrichment publishes company FTE only. Legacy financial reconciliation
remains available to direct callers and for incidental, audit-only cross-checks.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from .models import Claim, Evidence, PublicState, RunError, SourceSnapshot

COPY_ROOT = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi"
PARSER_VERSION = "official-filing-ocr-v4"
OCR_MODEL = "rapidocr-onnxruntime-default-pdfium-text-v1"
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_OCR_SECONDS = 90
PAGE_PRIORITY = (4, 3, 5, 2)
FTE_STRATEGY = "first_verified_company_fte_page_5_4_6_3_then_all_remaining_v1"
LABELS = {
    "sales_revenue": {'salgsinntekt', 'salgsinntekter'},
    "operating_costs": {'sum driftskostnader', 'sum kostnader'},
    "payroll_costs": {'lonnskostnad', 'lonnskostnader'},
    "net_financial_items": {'netto finansposter', 'netto finans'},
    "profit_before_tax": {'ordinaert resultat for skattekostnad', 'resultat for skattekostnad'},
    "tax_expense": {'skattekostnad pa resultat', 'skattekostnad'},
    "total_assets": {'sum eiendeler'},
    "fixed_assets": {'sum anleggsmidler'},
    "current_assets": {'sum omlopsmidler'},
    "receivables": {'sum fordringer'},
    "cash": {'sum bankinnskudd kontanter og lignende', 'bankinnskudd kontanter og lignende', 'sum bankinnskudd og kontanter'},
    "equity": {'sum egenkapital'},
    "paid_in_equity": {'sum innskutt egenkapital'},
    "retained_earnings": {'sum opptjent egenkapital'},
    "total_debt": {'sum gjeld'},
    "short_term_debt": {'sum kortsiktig gjeld'},
    "long_term_debt": {'sum langsiktig gjeld'},
    "financial_income": {'sum finansinntekter'},
    "financial_costs": {'sum finanskostnader'},
    "total_comprehensive_result": {'totalresultat'},

    "revenue": {"sum inntekter", "sum driftsinntekter", "driftsinntekter i alt"},
    "operating_result": {"driftsresultat"},
    "annual_result": {"arsresultat"},
}


def _page_order(count: int) -> list[int]:
    return [i for i in PAGE_PRIORITY if i < count] + [i for i in range(1, count) if i not in PAGE_PRIORITY]


def fold(text: str) -> str:
    value = text.casefold().replace("ø", "o").replace("æ", "ae")
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def lines(page: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Group OCR boxes on their actual baseline; retain columns and confidence."""
    groups: list[list[dict[str, Any]]] = []
    for word in sorted(page.get("words", []), key=lambda w: ((w["y1"] + w["y2"]) / 2, w["x1"])):
        center = (word["y1"] + word["y2"]) / 2
        match = next((g for g in reversed(groups[-3:]) if abs(center - sum((w["y1"] + w["y2"]) / 2 for w in g) / len(g))
            <= max(4, min(word["y2"] - word["y1"], g[0]["y2"] - g[0]["y1"]) * 0.55)), None)
        if match is None:
            groups.append([word])
        else:
            match.append(word)
    return [sorted(g, key=lambda w: w["x1"]) for g in groups]


def text_line(row: list[dict[str, Any]]) -> str:
    return " ".join(w["text"].strip() for w in row).strip()


def page_text(page: dict[str, Any]) -> str:
    return "\n".join(text_line(row) for row in lines(page))


def decimal_number(raw: str, *, workforce: bool = False) -> Decimal | None:
    """Parse only explicit digits/separators; never repair O/0 or a lost decimal."""
    value = raw.strip().replace("\u00a0", " ").replace("−", "-").replace("–", "-")
    if not re.fullmatch(r"-?\s*\d+(?:[ .,]\d+)*", value):
        return None
    if workforce:
        # Payroll templates print decimals. '1 00'/'100' are not repaired to 1.00.
        if " " in value or (re.fullmatch(r"\d{3,}", value) and value.endswith("00")):
            return None
        if value.count(",") + value.count(".") > 1:
            return None
        normalized = value.replace(",", ".")
    else:
        value = re.sub(r"^-\s+", "-", value)
        if "," in value:
            if value.count(",") != 1 or not re.search(r",\d{1,2}$", value):
                return None
            normalized = value.replace(" ", "").replace(".", "").replace(",", ".")
        elif "." in value:
            if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", value):
                normalized = value.replace(".", "")
            elif re.fullmatch(r"-?\d+\.\d{1,2}", value):
                normalized = value
            else:
                return None
        else:
            if " " in value and not re.fullmatch(r"-?\d{1,3}(?: \d{3})+", value):
                return None
            normalized = value.replace(" ", "")
    try:
        number = Decimal(normalized)
        return number if number.is_finite() and (not workforce or 0 <= number <= 100000) else None
    except InvalidOperation:
        return None


def _dates(text: str) -> list[str]:
    result = []
    for day, month, year in re.findall(r"\b(\d{2})\s*[./]\s*(\d{2})\s*[./]\s*(20\d{2})\b", text):
        try:
            result.append(datetime(int(year), int(month), int(day)).date().isoformat())
        except ValueError:
            pass
    return result


def verify_cover(page: dict[str, Any], org: str, record: dict[str, Any]) -> tuple[bool, str, bool]:
    text = page_text(page)
    folded = fold(text)
    # Exact labelled cover fields, rather than a number occurring anywhere in a PDF.
    labelled_orgs = re.findall(r"organisasjonsnummer\s*:?\s*((?:\d\s*){9})(?!\d)", folded)
    if not labelled_orgs or re.sub(r"\s", "", labelled_orgs[0]) != org:
        return False, "document_identity_mismatch", False
    journal = str(record.get("raw", {}).get("journalnr") or "")
    journal_match = re.search(r"journalnummer\s*:?\s*([\d ]+)", folded)
    if not journal or not journal_match or re.sub(r"\D", "", journal_match.group(1)) != journal:
        return False, "document_journal_mismatch", False
    period = re.search(r"(?:arsregnskapets\s+periode|regnskapsperiode)\s*:?\s*([^\n]*(?:\n[^\n]*)?)", folded)
    found_dates = _dates(period.group(1)) if period else []
    if found_dates[:2] != [record["period_start"], record["period_end"]]:
        return False, "document_period_mismatch", False
    parent = re.search(r"morselskap\s*i\s*konsern\s*:?\s*(ja|nei)\b", folded)
    attached = re.search(r"konsernregnskap\s*lagt\s*ved\s*:?\s*(ja|nei)\b", folded)
    # A parent is safe only when this exact filing explicitly says consolidated
    # accounts are not attached, or each financial page explicitly says SELSKAP.
    standalone = bool(parent and parent.group(1) == "nei" or attached and attached.group(1) == "nei")
    return True, "verified", standalone


def _company_page(page: dict[str, Any], org: str, *, nonparent: bool, notes: bool = False) -> bool:
    text = fold(page_text(page))
    heading = text[:700]
    if "konsernregnskap" in heading or re.search(r"(?:resultatregnskap|balanse|noteopplysninger)\s*[-:]?\s*konsern", heading):
        return False
    # Every accepted page itself carries the target's labelled header, not a subsidiary mention.
    number = re.search(r"organisasjonsnr\.?\s*:?\s*((?:\d\s*){9})(?!\d)", heading)
    if not number or re.sub(r"\s", "", number.group(1)) != org:
        return False
    if notes:
        return bool(re.search(r"noteopplysninger\s*[-:]?\s*selskap", heading))
    return bool(number) and (nonparent or bool(re.search(r"(?:resultatregnskap|balanse)\s*[-:]?\s*selskap", heading)))


def _money_unit(rows: list[list[dict[str, Any]]]) -> tuple[str, Decimal, str] | None:
    found = []
    for row in rows:
        span = text_line(row)
        text = fold(span)
        if not re.search(r"belop\s*i\s*:", text):
            continue
        if min(w["confidence"] for w in row) < 0.85:
            continue
        m = re.search(r"belop\s*i\s*:\s*(tnok|mnok|nok|eur)\b", text)
        if not m:
            continue
        currency = "EUR" if m.group(1) == "eur" else "NOK"
        scale = Decimal(1000 if m.group(1) == "tnok" else 1000000 if m.group(1) == "mnok" else 1)
        tail = text[m.end():].strip()
        # Parse the entire scale suffix: a thousands prefix must not consume a
        # million, and unknown/contradictory annotations cannot prove units.
        suffix = re.split(r"(?:^|\s+)(?:note|20\d{2})\b", tail, maxsplit=1)[0].strip()
        scales = {"": scale, "tusen": Decimal(1000), "million": Decimal(1000000),
                  "millioner": Decimal(1000000)}
        if re.fullmatch(r"1(?:[ .]?000){1,2}", suffix):
            explicit = Decimal(suffix.replace(" ", "").replace(".", ""))
        else:
            explicit = scales.get(suffix)
        if explicit is None or (m.group(1) in {"tnok", "mnok"} and explicit != scale):
            return None
        scale = explicit
        found.append((currency, scale, span))
    return found[0] if found and len({x[:2] for x in found}) == 1 else None


def financial_candidates(page: dict[str, Any], org: str, record: dict[str, Any], nonparent: bool) -> list[dict[str, Any]]:
    if not re.search(r"\b(?:resultatregnskap|balanse)\b", fold(page_text(page))[:700]) or not _company_page(page, org, nonparent=nonparent):
        return []
    rows = lines(page)
    unit = _money_unit(rows)
    if not unit or unit[0] != record["currency"]:
        return []
    year = record["period_end"][:4]
    headers = []
    for row in rows:
        years = [w for w in row if re.fullmatch(r"20\d\d", w["text"].strip()) and w["confidence"] >= 0.9]
        if len(years) >= 2 and any(w["text"].strip() == year for w in years):
            headers.append(years)
    if len(headers) != 1:
        return []
    columns = sorted(headers[0], key=lambda w: w["x1"])
    target = next(w for w in columns if w["text"].strip() == year)
    column_centers = [(w["x1"] + w["x2"]) / 2 for w in columns]
    target_index = columns.index(target)
    left = (column_centers[target_index - 1] + column_centers[target_index]) / 2 if target_index else column_centers[0] - page["width"] * 0.13
    right = (column_centers[target_index] + column_centers[target_index + 1]) / 2 if target_index + 1 < len(columns) else page["width"]
    result = []
    for row in rows:
        label_words = [w for w in row if w["x2"] < left]
        label = re.sub(r"[\W_]+", " ", fold(text_line(label_words))).strip()
        # A note reference can follow a row label; it is not part of its amount.
        label = re.sub(r"\s+\d+(?:\s+\d+)*$", "", label)
        metric = next((key for key, names in LABELS.items() if label in names), None)
        if metric is None:
            continue
        value_words = [w for w in row if left <= (w["x1"] + w["x2"]) / 2 < right]
        if not value_words or min(w["confidence"] for w in value_words + label_words) < 0.9:
            continue
        number = decimal_number(text_line(value_words))
        if number is None:
            continue
        normalized = number * unit[1]
        raw = record["metrics"].get(metric)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            continue
        if normalized != Decimal(str(raw)):
            result.append({"metric": metric, "conflict": True, "page": page["page"]})
            continue
        result.append({"metric": metric, "value": int(normalized) if normalized == normalized.to_integral() else float(normalized),
            "page": page["page"], "span": text_line(row), "unit_span": unit[2], "year": year, "currency": unit[0]})
    return result


def workforce_candidates(page: dict[str, Any], org: str, *, nonparent: bool,
                         year: str | None = None) -> list[dict[str, Any]]:
    if not _company_page(page, org, nonparent=nonparent, notes=True):
        return []
    rows = lines(page)
    found = []
    # Independently implemented explicit FTE grammars. Whole-row matching avoids
    # silently consuming a headcount, historical comparison or group statement.
    measure = r"(?:arsverk|aarsverk)"
    period = r"(?:regnskapsaret|rekneskapsaret|aret)"
    value = r"(?P<value>\d+(?:[.,]\d{1,2})?)"
    patterns = (
        rf"(?:antall|tal pa|tall pa)\s+{measure}\s+i\s+{period}(?:\s+(?P<year>20\d{{2}}))?\s*(?:er|:|=)?\s*{value}",
        rf"gjennomsnittlig\s+antall\s+{measure}(?:\s+i\s+{period})?(?:\s+(?P<year>20\d{{2}}))?\s*(?:er|:|=)?\s*{value}",
        rf"(?:selskapet|foretaket|virksomheten)\s+har\s+(?:hatt\s+)?{value}\s+{measure}",
    )
    for index, row in enumerate(rows):
        text = fold(text_line(row)).strip().rstrip(".")
        match = next((m for pattern in patterns if (m := re.fullmatch(pattern, text))), None)
        value_row = row
        if match is None and index + 1 < len(rows):
            following = rows[index + 1]
            # Only an immediately adjacent numeric row can complete a label.
            gap = min(w["y1"] for w in following) - max(w["y2"] for w in row)
            if 0 <= gap <= 2 * max(w["y2"] - w["y1"] for w in row):
                joined = text + " " + fold(text_line(following)).strip()
                match = next((m for pattern in patterns if (m := re.fullmatch(pattern, joined))), None)
                if match:
                    value_row = following
        if match is None:
            continue
        stated_year = match.groupdict().get("year")
        if stated_year and stated_year != year:
            continue
        # A nearby group heading must not turn group FTE into company FTE.
        context = " ".join(text_line(r) for r in rows[max(2, index - 1):index + 1])
        if re.search(r"\b(?:konsern|konsernet|group|datterselskap)\b", fold(context)):
            continue
        number = decimal_number(match.group("value"), workforce=True)
        if number is None or min(w["confidence"] for w in row + value_row) < 0.9:
            continue
        span = text_line(row) if value_row is row else text_line(row) + " | " + text_line(value_row)
        found.append({"value": float(number), "page": page["page"], "span": span})
    return found


def _first_workforce(pages: list[dict[str, Any]], org: str, record: dict[str, Any],
                     nonparent: bool) -> tuple[dict[str, Any] | None, bool]:
    for index in _page_order(max((p["page"] for p in pages), default=0)):
        page = next((p for p in pages if p["page"] == index + 1), None)
        if page is None:
            continue
        candidates = workforce_candidates(page, org, nonparent=nonparent, year=record["period_end"][:4])
        if candidates:
            conflict = len({item["value"] for item in candidates}) != 1
            return (None if conflict else candidates[0]), conflict
    return None, False


def reconcile(pages: list[dict[str, Any]], org: str, record: dict[str, Any], *,
              workforce_strategy: str = "global_cross_page_consensus") -> dict[str, Any]:
    """Legacy callers retain consensus; filing enrichment selects the first verified page.

    First-page selection rejects conflicting statements on that page and makes
    no assertion about later pages. Financial reconciliation remains per metric.
    """
    cover = next((p for p in pages if p["page"] == 1), None)
    if not cover:
        return {"state": "blocked", "reason": "cover_not_processed", "financial": [], "workforce": None}
    valid, reason, nonparent = verify_cover(cover, org, record)
    if not valid:
        return {"state": "ambiguous", "reason": reason, "financial": [], "workforce": None}
    finances = [item for page in pages for item in financial_candidates(page, org, record, nonparent)]
    accepted = []
    conflicts = []
    for metric in LABELS:
        candidates = [item for item in finances if item["metric"] == metric]
        if any(item.get("conflict") for item in candidates) or len({item.get("value") for item in candidates}) > 1:
            conflicts.append(metric)
        elif candidates:
            accepted.append(candidates[0])
    if workforce_strategy == FTE_STRATEGY:
        workforce_hit, workforce_conflict = _first_workforce(pages, org, record, nonparent)
    elif workforce_strategy == "global_cross_page_consensus":
        workforce = [item for page in pages for item in workforce_candidates(page, org, nonparent=nonparent, year=record["period_end"][:4])]
        workforce_hit = workforce[0] if workforce and len({item["value"] for item in workforce}) == 1 else None
        workforce_conflict = bool(workforce and workforce_hit is None)
    else:
        raise ValueError("unknown workforce selection strategy")
    if workforce_conflict:
        conflicts.append("full_time_equivalents")
    return {"state": "available" if accepted or workforce_hit else "not_available", "reason": "verified_document",
        "financial": accepted, "workforce": workforce_hit, "conflicts": conflicts}


class OCRPages(list):
    """List-compatible OCR results with explicit, request-scoped page coverage."""
    def __init__(self, pages: list[dict[str, Any]], coverage: dict[str, Any]):
        super().__init__(pages)
        self.coverage = coverage


def _searchable_words(page: Any) -> list[dict[str, Any]]:
    """Use positioned, printable PDF characters without inventing OCR confidence."""
    if not hasattr(page, "get_textpage"):
        return []
    if hasattr(page, "get_rotation") and page.get_rotation() != 0:
        return []
    from pypdfium2 import raw as pdfium_raw
    for obj in page.get_objects(max_depth=1):
        if obj.type in {pdfium_raw.FPDF_PAGEOBJ_IMAGE, pdfium_raw.FPDF_PAGEOBJ_FORM}:
            return []
        if obj.type == pdfium_raw.FPDF_PAGEOBJ_TEXT and pdfium_raw.FPDFTextObj_GetTextRenderMode(obj) not in {0, 1, 2}:
            return []
    textpage = page.get_textpage()
    try:
        words = []
        current: list[tuple[str, tuple[float, float, float, float]]] = []
        height = page.get_height()

        def flush() -> None:
            if current:
                words.append({"text": "".join(c for c, _ in current), "confidence": 1.0,
                    "x1": min(b[0] for _, b in current), "x2": max(b[2] for _, b in current),
                    "y1": height - max(b[3] for _, b in current), "y2": height - min(b[1] for _, b in current)})
                current.clear()

        for index in range(textpage.count_chars()):
            char = textpage.get_text_range(index, 1)
            if not char or char.isspace():
                flush()
                continue
            box = textpage.get_charbox(index, loose=True)
            if not char.isprintable() or not all(math.isfinite(v) for v in box) or box[2] <= box[0] or box[3] <= box[1]:
                return []
            if current:
                previous = current[-1][1]
                height_bound = max(box[3] - box[1], previous[3] - previous[1])
                if abs((box[1] + box[3] - previous[1] - previous[3]) / 2) > height_bound * .75 or box[0] - previous[2] > height_bound * .4:
                    flush()
            current.append((char, box))
        flush()
        return words
    finally:
        textpage.close()


def _ocr_worker(pdf: bytes, org: str | None = None,
                record: dict[str, Any] | None = None) -> list[dict[str, Any]] | dict[str, Any]:
    """Verify the cover and scan each remaining page at most once for company FTE."""
    import pypdfium2 as pdfium
    engine = None
    document = pdfium.PdfDocument(pdf)
    pages: list[dict[str, Any]] = []
    def read(index: int) -> dict[str, Any]:
        nonlocal engine
        page = document[index]
        try:
            try:
                words = _searchable_words(page)
            except (AttributeError, ValueError, RuntimeError):
                words = []
            if words:
                result = {"page": index + 1, "width": page.get_width(), "height": page.get_height(),
                    "words": words, "extraction": "pdf_text"}
                pages.append(result)
                return result
            import numpy as np
            from rapidocr_onnxruntime import RapidOCR
            if engine is None:
                engine = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
            bitmap = page.render(scale=1.1, grayscale=True)
            try:
                image = bitmap.to_pil().convert("RGB")
                try:
                    output, _ = engine(np.asarray(image), use_cls=False)
                    words = [{"text": text, "confidence": float(confidence), "x1": min(p[0] for p in box),
                        "x2": max(p[0] for p in box), "y1": min(p[1] for p in box), "y2": max(p[1] for p in box)}
                        for box, text, confidence in output or []]
                    result = {"page": index + 1, "width": image.width, "height": image.height, "words": words, "extraction": "ocr"}
                    pages.append(result)
                    return result
                finally:
                    image.close()
            finally:
                bitmap.close()
        finally:
            page.close()
    try:
        if org is None or record is None:
            for index in (0, 1, 4, 3, 5, 2, 6):
                if index < len(document):
                    read(index)
            return pages
        coverage = {"strategy": FTE_STRATEGY, "examined_pages": [], "fte_pages_examined": [],
            "financial_anchor_pages": [], "document_pages": len(document), "stopped_early": False,
            "coverage_complete": False, "stop_reason": "candidate_pages_exhausted"}
        if len(document):
            cover = read(0)
            valid, reason, nonparent = verify_cover(cover, org, record)
            if valid:
                order = _page_order(len(document))
                for position, index in enumerate(order):
                    page = read(index)
                    coverage["fte_pages_examined"].append(index + 1)
                    candidates = workforce_candidates(page, org, nonparent=nonparent, year=record["period_end"][:4])
                    if candidates:
                        coverage["stopped_early"] = position + 1 < len(order)
                        coverage["stop_reason"] = "same_page_fte_conflict" if len({c["value"] for c in candidates}) > 1 else "first_verified_company_fte"
                        break
            else:
                coverage.update(stop_reason=reason, stopped_early=len(document) > 1)
        else:
            coverage["stop_reason"] = "cover_not_processed"
        coverage["examined_pages"] = [p["page"] for p in pages]
        coverage["coverage_complete"] = len(pages) == len(document)
        return {"pages": pages, "coverage": coverage}
    finally:
        document.close()


class DocumentProcessor:
    """Two killable workers with context-bound, atomic persistent page results."""
    def __init__(self, seconds: float | None = None, *, deadline: float | None = None,
                 cache_path: str | Path | None = None):
        """Optional run budget uses an absolute time.monotonic deadline."""
        self.slots = asyncio.Semaphore(2)
        self.cache: dict[str, list[dict[str, Any]]] = {}
        self.cache_path = Path(cache_path or os.environ.get("SIGNALPOST_OCR_CACHE") or
            Path(__file__).resolve().parents[1] / ".signalpost-cache" / "ocr")
        self.model_versions = {}
        for package in ("rapidocr-onnxruntime", "pypdfium2"):
            try:
                self.model_versions[package] = version(package)
            except PackageNotFoundError:
                self.model_versions[package] = "unavailable"
        self.deadline = min(deadline if deadline is not None else math.inf,
            time.monotonic() + seconds if seconds is not None else math.inf)

    def _load(self, path: Path, identity: dict[str, Any]) -> list[dict[str, Any]] | None:
        try:
            saved = json.loads(path.read_text())
            if saved["identity"] != identity:
                return None
            payload = saved["payload"]
            if saved["payload_sha256"] != hashlib.sha256(json.dumps(payload, sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode()).hexdigest():
                return None
            pages = payload["pages"]
            if not isinstance(pages, list) or any(not isinstance(p, dict) or not isinstance(p["page"], int)
                    or not isinstance(p["words"], list) or not isinstance(p["width"], (int, float)) for p in pages):
                return None
            numbers = [p["page"] for p in pages]
            if len(set(numbers)) != len(numbers) or any(n < 1 for n in numbers):
                return None
            for page in pages:
                for word in page["words"]:
                    if not isinstance(word["text"], str) or any(isinstance(word[key], bool) or not isinstance(word[key], (int, float))
                            or not math.isfinite(word[key]) for key in ("x1", "x2", "y1", "y2", "confidence")):
                        return None
            coverage = payload["coverage"]
            if identity["context"] is not None:
                if not isinstance(coverage, dict) or coverage["strategy"] != identity["strategy"] or coverage["examined_pages"] != numbers:
                    return None
                count = coverage["document_pages"]
                if not isinstance(count, int) or count < 0 or any(n > count for n in numbers) or coverage["coverage_complete"] != (len(numbers) == count):
                    return None
                if coverage["fte_pages_examined"] != numbers[1:] or coverage["financial_anchor_pages"] != [] or not isinstance(coverage["stop_reason"], str):
                    return None
                return OCRPages(pages, coverage)
            return pages if coverage is None else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save(self, path: Path, identity: dict[str, Any], pages: list[dict[str, Any]]) -> None:
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix=".ocr-", dir=self.cache_path)
            with os.fdopen(descriptor, "w") as stream:
                payload = {"pages": pages, "coverage": getattr(pages, "coverage", None)}
                checksum = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                json.dump({"identity": identity, "payload": payload, "payload_sha256": checksum}, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    async def ocr(self, body: bytes, seconds: float, *, org: str | None = None,
                  record: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], bool]:
        if (org is None) != (record is None):
            raise ValueError("org and record must be supplied together")
        digest = hashlib.sha256(body).hexdigest()
        context = None
        if org is not None and record is not None:
            context = {"org": org, "record": {"period_start": record["period_start"], "period_end": record["period_end"],
                "currency": record["currency"], "metrics": record["metrics"], "raw": {"journalnr": record.get("raw", {}).get("journalnr")}}}
        context_json = json.dumps(context, sort_keys=True, separators=(",", ":"))
        identity = {"pdf_sha256": digest, "parser": PARSER_VERSION, "model": OCR_MODEL,
            "model_versions": self.model_versions,
            "strategy": FTE_STRATEGY if context is not None else "legacy_seven_pages", "context": context}
        cache_key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if cache_key in self.cache:
            return self.cache[cache_key], True
        if context is None and digest in self.cache:
            return self.cache[digest], True
        remaining = min(seconds, MAX_OCR_SECONDS, self.deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("ocr_deadline")
        async with asyncio.timeout(remaining):
            self.cache_path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = self.cache_path / (cache_key + ".json")
            import fcntl
            descriptor = os.open(self.cache_path / (cache_key + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
            with os.fdopen(descriptor, "w") as lock:
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        await asyncio.sleep(.02)
                if cache_key in self.cache:
                    return self.cache[cache_key], True
                cached = self._load(path, identity)
                if cached is not None:
                    self.cache[cache_key] = cached
                    return cached, True
                async with self.slots:
                    pages = await self._run_worker(body, context, context_json)
                self._save(path, identity, pages)
                self.cache[cache_key] = pages
                return pages, False

    async def _run_worker(self, body: bytes, context: dict[str, Any] | None,
                          context_json: str) -> list[dict[str, Any]]:
        env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        args = [sys.executable, "-m", "signalpost.annual_accounts", "--ocr-worker"]
        if context is not None:
            args.append(context_json)
        process = await asyncio.create_subprocess_exec(*args,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]), env=env)
        try:
            output, error = await process.communicate(body)
            if process.returncode:
                raise RuntimeError("local_ocr_dependency_or_document_error: " + error.decode(errors="replace")[-220:])
            payload = json.loads(output)
            pages = OCRPages(payload["pages"], payload["coverage"]) if isinstance(payload, dict) else payload
            return pages
        except BaseException:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
            raise


async def enrich_company(result: Any, org: str, gateway: Any, cutoff: datetime, processor: DocumentProcessor) -> Any:
    """Attach only automatically verified document facts to the existing BRREG graph."""
    started = time.monotonic()
    audit = {"state": "not_available", "reason": "no_eligible_company_filing", "pages_processed": 0,
        "ocr_seconds": 0.0, "processing_seconds": 0.0, "financial_claims": 0, "workforce_claims": 0, "cache_hit": False,
        "examined_pages": [], "strategy": FTE_STRATEGY, "stopped_early": False,
        "fte_pages_examined": [], "financial_anchor_pages": [], "coverage_complete": False,
        "document_pages": None, "stop_reason": "not_started"}
    result.observations["annual_accounts_document"] = audit
    result.section_states["hiring_activity"] = PublicState.NOT_AVAILABLE
    eligible = [r for r in result.account_records if r.get("scope") == "legal_entity"
        and r.get("raw", {}).get("virksomhet", {}).get("organisasjonsnummer") == org
        and r.get("period_start") and r.get("period_end") and r["period_end"] <= cutoff.date().isoformat()]
    if not eligible:
        return result
    latest_end = max(r["period_end"] for r in eligible)
    latest = [r for r in eligible if r["period_end"] == latest_end]
    if len(latest) != 1:
        audit.update(state="ambiguous", reason="multiple_current_filing_versions")
        result.section_states["hiring_activity"] = PublicState.AMBIGUOUS
        return result
    record = latest[0]
    url = f"{COPY_ROOT}/{org}/{record['period_end'][:4]}"
    retrieved = datetime.now(timezone.utc)
    try:
        status, headers, body, final_url, outcome = await gateway.fetch(url, purpose="annual_account_copy",
            max_bytes=MAX_PDF_BYTES, allowed_hosts={"data.brreg.no"}, access_profile="brreg_document_api")
        if status != 200 or outcome != "ok" or not body.startswith(b"%PDF"):
            audit.update(state="not_available" if status in {404, 410} else "blocked" if outcome.startswith("robots") or status in {401,403,429} or outcome == "budget_exhausted" else "failed",
                reason=f"pdf_{status}_{outcome}")
            return result
        digest = hashlib.sha256(body).hexdigest()
        budget = getattr(gateway, "budget", None)
        seconds = min(MAX_OCR_SECONDS, budget.config.soft_seconds - budget.elapsed if budget else MAX_OCR_SECONDS)
        if seconds < 2:
            audit.update(state="blocked", reason="ocr_deadline")
            return result
        ocr_started = time.monotonic()
        parameters = inspect.signature(processor.ocr).parameters
        if "org" in parameters and "record" in parameters:
            pages, cache_hit = await processor.ocr(body, seconds, org=org, record=record)
        else:
            pages, cache_hit = await processor.ocr(body, seconds)
        audit.update(ocr_seconds=round(time.monotonic() - ocr_started, 3), pages_processed=len(pages), cache_hit=cache_hit)
        audit.update(examined_pages=[p["page"] for p in pages], stop_reason="legacy_ocr_coverage_unknown")
        audit.update(getattr(pages, "coverage", {}))
        checked = reconcile(pages, org, record, workforce_strategy=FTE_STRATEGY)
        audit.update(state=checked["state"] if checked["state"] in {"blocked", "ambiguous"} else
            "available" if checked["workforce"] else "not_available", reason=checked["reason"],
            financial_cross_checks=[{**item, "inferred_api_unit": item["currency"], "api_value_multiplier": 1}
                for item in checked["financial"]], financial_cross_check_conflicts=[
                metric for metric in checked.get("conflicts", []) if metric != "full_time_equivalents"])
        if "full_time_equivalents" in checked.get("conflicts", []):
            result.errors.append(RunError(code="ANNUAL_DOCUMENT_CLAIM_CONFLICT", message="Conflicting document candidates withheld: full_time_equivalents"))
        if not checked["workforce"]:
            return result
        sid = f"{org}:annual-document:{digest[:20]}"
        result.snapshots.append(SourceSnapshot(source_id=sid, source_url=final_url, retrieved_at=retrieved,
            content_sha256=digest, http_status=200, cache_mode="transient", rights_status="public_official_filing_factual_extraction"))
        cover_id = sid + ":cover"
        cover = next(p for p in pages if p["page"] == 1)
        cover_quote = " | ".join(text_line(row) for row in lines(cover) if re.search(r"organisasjonsnummer|journalnummer|arsregnskapets periode|regnskapsperiode", fold(text_line(row))))
        result.evidence.append(Evidence(evidence_id=cover_id, source_url=final_url, retrieved_at=retrieved,
            content_sha256=digest, page_number=1, excerpt=cover_quote, extraction_method=PARSER_VERSION,
            subject_organisation_number=org, source_snapshot_ids=[sid]))
        subject = f"{org}:filing:{record['raw'].get('journalnr') or record.get('record_id')}:{record['period_start']}:{record['period_end']}"
        start = datetime.fromisoformat(record["period_start"]).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(record["period_end"]).replace(tzinfo=timezone.utc)
        item = checked["workforce"]
        if item:
            eid = sid + ":fte"
            result.evidence.append(Evidence(evidence_id=eid, source_url=final_url, retrieved_at=retrieved,
                content_sha256=digest, page_number=item["page"], excerpt=item["span"], extraction_method=PARSER_VERSION,
                subject_organisation_number=org, source_snapshot_ids=[sid]))
            from .identifiers import stable_claim_id
            identity = stable_claim_id(org, "full_time_equivalents", item["value"], source=final_url,
                content_sha256=digest, subject=subject, period_start=start, period_end=end, unit="FTE")
            result.claims.append(Claim(claim_id=identity, organisation_number=org,
                section="hiring_activity", field_family="workforce", subject_id=subject, field="full_time_equivalents",
                value=item["value"], state=PublicState.AVAILABLE, unit="FTE", period_start=start, period_end=end,
                scope="legal_entity", verification_rule_id="official_company_fte_statement_v1", verification_score="1.0",
                evidence_ids=[cover_id, eid], source_snapshot_ids=[sid]))
            audit["workforce_claims"] += 1
        return result
    except asyncio.CancelledError:
        audit.update(state="blocked", reason="document_deadline_cancelled")
        raise
    except (TimeoutError, asyncio.TimeoutError):
        audit.update(state="blocked", reason="ocr_deadline")
        return result
    except Exception as exc:
        audit.update(state="blocked" if "dependency" in str(exc) else "failed", reason=type(exc).__name__)
        result.errors.append(RunError(code="ANNUAL_DOCUMENT_PROCESSING_FAILED", message=str(exc)[:240]))
        return result
    finally:
        audit["processing_seconds"] = round(time.monotonic() - started, 3)
        result.section_states["hiring_activity"] = PublicState.AVAILABLE if audit["workforce_claims"] else PublicState(audit["state"] if audit["state"] != "available" else "not_available")
        if audit["state"] in {"blocked", "failed", "ambiguous"}:
            result.errors.append(RunError(code="ANNUAL_DOCUMENT_" + audit["state"].upper(), message=audit["reason"]))


if __name__ == "__main__" and sys.argv[1:2] == ["--ocr-worker"]:
    try:
        context = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        print(json.dumps(_ocr_worker(sys.stdin.buffer.read(MAX_PDF_BYTES + 1), **context), ensure_ascii=False))
    except Exception as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1)
