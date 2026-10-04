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
