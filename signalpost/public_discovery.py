"""Bounded batch discovery; external metadata never establishes site ownership."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlencode

from .network import NetworkGateway
from .websites import sanitize_registry_websites


APPROVED_DISCOVERY_REQUEST_PURPOSES = frozenset({"wikidata_batch_candidates"})


async def wikidata_candidates(organisations: list[str], gateway: NetworkGateway) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    selected = list(dict.fromkeys(org for org in organisations if re.fullmatch(r"\d{9}", org)))[:200]
    audit: dict[str, Any] = {"state": "not_attempted", "requested_companies": len(selected),
                             "omitted_companies": len(set(organisations)) - len(selected)}
    result: dict[str, list[dict[str, Any]]] = {}
    if not selected:
        return result, audit
    values = " ".join('"' + org + '"' for org in selected)
    query = ('SELECT DISTINCT ?org ?item ?website WHERE { VALUES ?org { ' + values
             + ' } ?item wdt:P2333 ?org; wdt:P856 ?website. } LIMIT 1000')
    url = "https://query.wikidata.org/sparql?" + urlencode({"query": query, "format": "json"})
    try:
        async with asyncio.timeout(12):
            status, headers, body, final_url, outcome = await gateway.fetch(url,
                purpose="wikidata_batch_candidates", allowed_hosts={"query.wikidata.org"}, max_bytes=1024 * 1024)
        audit.update(state="blocked", outcome=outcome, http_status=status)
        if status != 200 or outcome != "ok":
            return result, audit
        rows = json.loads(body)["results"]["bindings"]
        if not isinstance(rows, list):
            raise ValueError("invalid bindings")
        digest = hashlib.sha256(body).hexdigest()
        for row in rows[:1000]:
            org = row.get("org", {}).get("value")
            item = row.get("item", {}).get("value", "")
            website = row.get("website", {}).get("value")
            if org not in selected or not re.fullmatch(r"https?://www\.wikidata\.org/entity/Q\d+", item):
                continue
            for candidate in sanitize_registry_websites(website):
                if candidate["kind"] == "website" and len(result.get(org, [])) < 2:
                    result.setdefault(org, []).append({"raw": candidate["url"], "source": "wikidata",
                        "discovery": {"provider_id": "wikidata", "provider_version": "P2333-P856-v1",
                            "query_id": org, "result_id": item, "rank": len(result.get(org, [])) + 1,
                            "response_sha256": digest}})
        audit.update(state="completed", candidate_count=sum(map(len, result.values())), response_sha256=digest)
    except Exception:
        audit["state"] = "failed"
    return result, audit
