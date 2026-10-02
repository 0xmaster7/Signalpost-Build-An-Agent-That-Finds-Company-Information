from __future__ import annotations

import csv
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
    weights = (2, 3, 4, 5, 6, 7, 2, 3)
    total = sum(int(digit) * weight for digit, weight in zip(text[:8], weights))
    check = 11 - total % 11
    expected = 0 if check == 11 else check
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
        mode = "json" if stripped.startswith(("[", "{")) else "csv" if "\t" in text.partition("\n")[0] else "csv" if "," in text.partition("\n")[0] else "plain"
    if mode == "jsonl":
        values = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                values.append(json.loads(line))
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
                    values.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    values.append({"_malformed": line, "_parse_error": str(exc)})
    elif mode in {"csv", "tsv"}:
        delimiter = "\t" if mode == "tsv" else ","
        reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
        values = list(reader)
    elif mode == "plain":
        values = [line.strip() for line in text.splitlines() if line.strip()]
    else:
        raise ValueError(f"unsupported input format: {fmt}")
    return [_record(value, idx) for idx, value in enumerate(values, 1)]


def load_input(path: str | Path, fmt: str | None = None) -> list[InputRow]:
    return parse_records(Path(path).read_text(encoding="utf-8-sig"), fmt)


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
