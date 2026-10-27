"""Stable semantic identity helpers for fact families with content-derived IDs."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


def canonical_product_heading(value: str) -> str:
    """Fold Unicode compatibility forms, whitespace, and case for heading identity."""
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def website_claim_value_digest(field: str, value: Any) -> str:
    semantic_value = (canonical_product_heading(value)
        if field == "product_or_service_heading" and isinstance(value, str) else value)
    canonical = json.dumps(semantic_value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def legacy_website_claim_value_digest(value: Any) -> str:
    """Recognize claim IDs emitted before semantic 24-hex website identities."""
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def stable_claim_id(org: str, field: str, value: Any, *, source: str,
                    content_sha256: str | None = None, subject: str | None = None,
                    period_start: Any = None, period_end: Any = None, scope: str = "legal_entity",
                    unit: str | None = None, currency: str | None = None,
                    unit_state: str = "explicit", as_of: Any = None) -> str:
    semantic_value = canonical_product_heading(value) if field == "product_or_service_heading" and isinstance(value, str) else value
    payload = {"organisation_number": org, "field": field, "value": semantic_value,
        "source": source, "content_sha256": content_sha256, "subject": subject,
        "period_start": str(period_start) if period_start is not None else None,
        "period_end": str(period_end) if period_end is not None else None,
        "scope": scope, "unit": unit, "currency": currency, "unit_state": unit_state,
        "as_of": str(as_of) if as_of is not None else None}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return org + ":fact:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
