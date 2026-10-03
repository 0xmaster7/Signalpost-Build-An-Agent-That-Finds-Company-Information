from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .models import InputRow

ORG_RE = re.compile(r"^\d{9}$")


def normalize_org_number(value: Any) -> tuple[str, bool]:
    """Keep identifiers textual, remove separators, and return checksum sanity separately."""
    if value is None or isinstance(value, (float, bool, dict, list)):
        return "", False
    text = str(value).replace("\ufeff", "").strip()
    text = re.sub(r"[\s.\-]", "", text)
    valid_shape = bool(ORG_RE.fullmatch(text))
    if not valid_shape:
        return text, False
    # BRREG specifies weights 3, 2, 7, 6, 5, 4, 3, 2 over the first eight digits.
    weights = (3, 2, 7, 6, 5, 4, 3, 2)
    total = sum(int(digit) * weight for digit, weight in zip(text[:8], weights))
    remainder = total % 11
    expected = 0 if remainder == 0 else 11 - remainder
    if expected == 10:
        return text, False
    return text, int(text[8]) == expected


def _record(value: Any, row_number: int) -> InputRow:
    if isinstance(value, str):
        raw = {"organisation_number": value}
    elif isinstance(value, dict):
        raw = value
    else:
        raw = {"_malformed": repr(value)}
    candidate = next((raw[key] for key in ("organisation_number", "orgnr", "organization_number", "org_number") if key in raw), None)
    normalized, _ = normalize_org_number(candidate)
    return InputRow(input_ref=f"row:{row_number}", row_number=row_number, organisation_number=normalized, raw=raw)


def parse_records(text: str, fmt: str | None = None) -> list[InputRow]:
    text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    mode = (fmt or "auto").lower()
    if mode == "auto":
        stripped = text.lstrip()
        header = text.partition("\n")[0]
        mode = "json" if stripped.startswith(("[", "{")) else "tsv" if "\t" in header else "csv" if "," in header else "plain"
    if mode == "jsonl":
        values = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                values.append({"_malformed": line, "_parse_error": "invalid UTF-8"} if "\ufffd" in line else json.loads(line))
            except json.JSONDecodeError as exc:
                values.append({"_malformed": line, "_parse_error": str(exc)})
    elif mode == "json":
        try:
            data = json.loads(text)
            values = data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            # JSONL begins with an object too; preserve each independently parseable row.
            values = []
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    values.append({"_malformed": line, "_parse_error": "invalid UTF-8"} if "\ufffd" in line else json.loads(line))
                except json.JSONDecodeError as exc:
                    values.append({"_malformed": line, "_parse_error": str(exc)})
    elif mode in {"csv", "tsv"}:
        delimiter = "\t" if mode == "tsv" else ","
        reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
        values = []
        for row in reader:
            values.append({"_malformed": str(row), "_parse_error": "invalid UTF-8"}
                          if "\ufffd" in json.dumps(row, ensure_ascii=False) else row)
    elif mode == "plain":
        values = [line.strip() for line in text.splitlines() if line.strip()]
    else:
        raise ValueError(f"unsupported input format: {fmt}")
    return [_record(value, idx) for idx, value in enumerate(values, 1)]


def load_input(path: str | Path, fmt: str | None = None) -> list[InputRow]:
    return parse_records(Path(path).read_bytes().decode("utf-8-sig", errors="replace"), fmt)


def registry_fixture(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        org, _ = normalize_org_number(record.get("organisation_number", record.get("orgnr")))
        if not org or org in result:
            raise ValueError(f"invalid or duplicate registry fixture row {index}")
        result[org] = record
    return result


def stream_registry_matches(path: str | Path | None, requested: set[str]) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Filter a frozen JSONL/CSV snapshot in streaming passes, retaining only matches.

    The digest is streamed over the compressed or plain source bytes, so reports
    identify the exact supplied snapshot without retaining the full universe.
    """
    if not path:
        return {}, None
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as raw:
        while chunk := raw.read(1024 * 1024):
            digest.update(chunk)
    opener = gzip.open if source.suffix.casefold() == ".gz" else open
    matches: dict[str, dict[str, Any]] = {}
    with opener(source, "rt", encoding="utf-8-sig", newline="") as stream:
        first = stream.readline()
        if not first:
            return matches, digest.hexdigest()
        # This API targets documented frozen registry formats: JSONL or CSV.
        # JSON arrays are deliberately excluded because they require whole-file parsing.
        if first.lstrip().startswith(("{", "[")):
            def records():
                yield first
                yield from stream
            for index, line in enumerate(records(), 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    continue
                org, _ = normalize_org_number(row.get("organisation_number", row.get("orgnr")))
                if org in requested:
                    if org in matches:
                        raise ValueError(f"duplicate organisation number in registry snapshot at row {index}")
                    row["__signalpost_snapshot_row_sha256"] = hashlib.sha256(line.encode("utf-8")).hexdigest()
                    row["__signalpost_snapshot_row_number"] = index
                    matches[org] = row
        else:
            def lines():
                yield first
                yield from stream
            for row in csv.DictReader(lines()):
                org, _ = normalize_org_number(row.get("organisation_number", row.get("orgnr")))
                if org in requested:
                    if org in matches:
                        raise ValueError(f"duplicate organisation number in registry snapshot: {org}")
                    matches[org] = dict(row)
    return matches, digest.hexdigest()
