"""Bounded official filing OCR and per-claim reconciliation; no network in OCR workers.

The JSON API's currency is not a scale contract. A financial claim requires a
matching, explicitly unit-labelled document row. This implementation is original;
it does not incorporate the unlicensed competitor implementation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import Claim, Evidence, PublicState, RunError, SourceSnapshot

COPY_ROOT = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi"
PARSER_VERSION = "official-filing-ocr-v2"
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_OCR_SECONDS = 90
PAGE_PRIORITY = (0, 1, 4, 3, 5, 2, 6)
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
    if journal and (not journal_match or re.sub(r"\D", "", journal_match.group(1)) != journal):
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


def reconcile(pages: list[dict[str, Any]], org: str, record: dict[str, Any]) -> dict[str, Any]:
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
    workforce = [item for page in pages for item in workforce_candidates(page, org, nonparent=nonparent, year=record["period_end"][:4])]
    workforce_hit = workforce[0] if workforce and len({item["value"] for item in workforce}) == 1 else None
    if workforce and workforce_hit is None:
        conflicts.append("full_time_equivalents")
    return {"state": "available" if accepted or workforce_hit else "not_available", "reason": "verified_document",
        "financial": accepted, "workforce": workforce_hit, "conflicts": conflicts}


def _ocr_worker(pdf: bytes) -> list[dict[str, Any]]:
    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
    document = pdfium.PdfDocument(pdf)
    pages = []
    for index in PAGE_PRIORITY:
        if index >= len(document):
            continue
        page = document[index]
        bitmap = page.render(scale=1.1, grayscale=True)
        image = bitmap.to_pil().convert("RGB")
        output, _ = engine(np.asarray(image), use_cls=False)
        words = []
        for box, text, confidence in output or []:
            words.append({"text": text, "confidence": float(confidence), "x1": min(p[0] for p in box),
                "x2": max(p[0] for p in box), "y1": min(p[1] for p in box), "y2": max(p[1] for p in box)})
        pages.append({"page": index + 1, "width": image.width, "height": image.height, "words": words})
        image.close()
        bitmap.close()
        page.close()
    document.close()
    return pages


class DocumentProcessor:
    """Two killable OCR subprocesses at most, with a run-scoped document-SHA cache."""
    def __init__(self):
        self.slots = asyncio.Semaphore(2)
        self.cache: dict[str, list[dict[str, Any]]] = {}

    async def ocr(self, body: bytes, seconds: float) -> tuple[list[dict[str, Any]], bool]:
        digest = hashlib.sha256(body).hexdigest()
        if digest in self.cache:
            return self.cache[digest], True
        # Queueing, worker startup and OCR share the caller's remaining budget.
        async with asyncio.timeout(max(0.001, min(seconds, MAX_OCR_SECONDS))):
            async with self.slots:
                if digest in self.cache:
                    return self.cache[digest], True
                env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
                process = await asyncio.create_subprocess_exec(sys.executable, "-m", "signalpost.annual_accounts", "--ocr-worker",
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]), env=env)
                try:
                    output, error = await asyncio.wait_for(process.communicate(body), timeout=max(0.1, min(seconds, MAX_OCR_SECONDS)))
                    if process.returncode:
                        raise RuntimeError("local_ocr_dependency_or_document_error: " + error.decode(errors="replace")[-220:])
                    pages = json.loads(output)
                    self.cache[digest] = pages
                    return pages, False
                except BaseException:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                    raise


async def enrich_company(result: Any, org: str, gateway: Any, cutoff: datetime, processor: DocumentProcessor) -> Any:
    """Attach only automatically verified document facts to the existing BRREG graph."""
    started = time.monotonic()
    audit = {"state": "not_available", "reason": "no_eligible_company_filing", "pages_processed": 0,
        "ocr_seconds": 0.0, "processing_seconds": 0.0, "financial_claims": 0, "workforce_claims": 0, "cache_hit": False}
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
        pages, cache_hit = await processor.ocr(body, seconds)
        audit.update(ocr_seconds=round(time.monotonic() - ocr_started, 3), pages_processed=len(pages), cache_hit=cache_hit)
        checked = reconcile(pages, org, record)
        audit.update(state=checked["state"], reason=checked["reason"])
        if checked.get("conflicts"):
            result.errors.append(RunError(code="ANNUAL_DOCUMENT_CLAIM_CONFLICT", message="Conflicting document candidates withheld: " + ", ".join(checked["conflicts"])))
        if not checked["financial"] and not checked["workforce"]:
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
        for item in checked["financial"]:
            metric = item["metric"]
            existing = [c for c in result.claims if c.field_family == "financial" and c.field == metric
                and c.period_start == start and c.period_end == end and c.scope == "legal_entity"]
            if existing:
                if any(Decimal(str(c.value)) != Decimal(str(item["value"])) for c in existing):
                    result.errors.append(RunError(code="ANNUAL_EXISTING_VALUE_CONFLICT", message=f"Document conflicts with existing {metric}; document claim withheld."))
                continue
            eid = sid + ":" + metric
            result.evidence.append(Evidence(evidence_id=eid, source_url=final_url, retrieved_at=retrieved,
                content_sha256=digest, page_number=item["page"], excerpt=f"{item['unit_span']} | year column {item['year']} | {item['span']}",
                extraction_method=PARSER_VERSION, subject_organisation_number=org, source_snapshot_ids=[sid]))
            from .brreg import METRICS
            source = result.account_source
            json_sid = next(s.source_id for s in result.snapshots if s.source_url == source["url"] and s.content_sha256 == source["content_sha256"])
            json_eid = eid + ":json"
            result.evidence.append(Evidence(evidence_id=json_eid, source_url=source["url"], retrieved_at=source["retrieved_at"],
                content_sha256=source["content_sha256"], json_pointer=record["_source_prefix"] + "/" + METRICS[metric],
                extraction_method="brreg_json_pointer_v1", subject_organisation_number=org, source_snapshot_ids=[json_sid]))
            result.claims.append(Claim(claim_id=subject + ":document:" + metric, organisation_number=org,
                section="accounts_history", field_family="financial", subject_id=subject, field=metric, value=item["value"],
                state=PublicState.AVAILABLE, unit=item["currency"], currency=item["currency"], period_start=start, period_end=end,
                scope="legal_entity", verification_rule_id="official_pdf_json_row_reconciliation_v1", verification_score="1.0",
                evidence_ids=[cover_id, eid, json_eid], source_snapshot_ids=[sid, json_sid]))
            audit["financial_claims"] += 1
        item = checked["workforce"]
        if item:
            eid = sid + ":fte"
            result.evidence.append(Evidence(evidence_id=eid, source_url=final_url, retrieved_at=retrieved,
                content_sha256=digest, page_number=item["page"], excerpt=item["span"], extraction_method=PARSER_VERSION,
                subject_organisation_number=org, source_snapshot_ids=[sid]))
            result.claims.append(Claim(claim_id=subject + ":full_time_equivalents", organisation_number=org,
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
        if audit["financial_claims"]:
            result.section_states["accounts_history"] = PublicState.AVAILABLE
        if audit["state"] in {"blocked", "failed", "ambiguous"}:
            result.errors.append(RunError(code="ANNUAL_DOCUMENT_" + audit["state"].upper(), message=audit["reason"]))


if __name__ == "__main__" and sys.argv[1:] == ["--ocr-worker"]:
    try:
        print(json.dumps(_ocr_worker(sys.stdin.buffer.read(MAX_PDF_BYTES + 1)), ensure_ascii=False))
    except Exception as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1)
