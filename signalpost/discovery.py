"""Candidate-only search discovery contracts.

Provider adapters are deliberately optional. Search metadata is reduced to a
URL and trace identifiers; titles and snippets never enter fact evidence.
Any production adapter must use the supplied NetworkGateway (or an equivalent
physical-request ledger) and declare reproducible, permitted source rights.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from .network import NetworkGateway
from .websites import sanitize_registry_websites


@dataclass(frozen=True)
class SearchQuery:
    query_id: str
    text: str
    target_organisation_number: str


@dataclass(frozen=True)
class SearchHit:
    url: str
    result_id: str
    rank: int
    # Provider title/snippet are intentionally accepted only at the adapter
    # boundary and discarded when normalized to SearchCandidate.
    title: str = ""
    snippet: str = ""
    raw_item: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class SearchResponse:
    hits: tuple[SearchHit, ...]
    provider_id: str
    provider_version: str
    physical_requests: int
    elapsed_ms: float
    cost_usd: str = "0"
    response_sha256: str | None = None


@dataclass(frozen=True)
class SearchCandidate:
    """Minimal discovery trace; it is not claim evidence or identity proof."""

    url: str
    provider_id: str
    provider_version: str
    query_id: str
    result_id: str
    rank: int
    response_sha256: str | None

    def as_website_candidate(self) -> dict[str, Any]:
        return {
            "raw": self.url,
            "source": "search_provider",
            "discovery": {
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "query_id": self.query_id,
                "result_id": self.result_id,
                "rank": self.rank,
                "response_sha256": self.response_sha256,
            },
        }


class SearchProvider(Protocol):
    """A provider adapter must route every physical call through `gateway`."""

    provider_id: str
    provider_version: str
    reproducible: bool
    rights_approved: bool
    retries_visible: bool
    cost_per_query_usd: str | None

    async def search(self, query: SearchQuery, gateway: NetworkGateway, *, timeout_seconds: float) -> SearchResponse: ...


@dataclass
class MockSearchProvider:
    """Deterministic fixture adapter used only in tests and local simulations."""

    results: dict[str, tuple[SearchHit, ...]]
    provider_id: str = "mock-search"
    provider_version: str = "fixture-v1"
    reproducible: bool = True
    rights_approved: bool = False
    retries_visible: bool = True
    cost_per_query_usd: str | None = "0"
    calls: list[str] = field(default_factory=list)

    async def search(self, query: SearchQuery, gateway: NetworkGateway, *, timeout_seconds: float) -> SearchResponse:
        del gateway  # Mock results generate no network requests.
        del timeout_seconds
        self.calls.append(query.query_id)
        hits = self.results.get(query.query_id, ())
        digest = hashlib.sha256(repr(hits).encode("utf-8")).hexdigest()
        return SearchResponse(tuple(hits), self.provider_id, self.provider_version,
                              physical_requests=0, elapsed_ms=0, response_sha256=digest)


def build_search_queries(*, organisation_number: str, legal_name: str,
                         municipality: str | None = None,
                         verified_public_brand: str | None = None) -> list[SearchQuery]:
    """Build the audited minimal ordered query set from already verified inputs."""
    queries = [SearchQuery("org_and_legal_name", f'"{organisation_number}" "{legal_name}"', organisation_number)]
    if municipality:
        queries.append(SearchQuery("legal_name_and_municipality", f'"{legal_name}" {municipality}', organisation_number))
    if verified_public_brand and municipality:
        queries.append(SearchQuery("verified_brand_and_municipality", f'"{verified_public_brand}" {municipality}', organisation_number))
    return queries


def normalize_search_hits(query: SearchQuery, response: SearchResponse) -> list[SearchCandidate]:
    """Keep safe HTTP URLs and discovery provenance; discard result content."""
    candidates: list[SearchCandidate] = []
    seen: set[str] = set()
    for hit in response.hits:
        if hit.rank < 1 or not hit.result_id:
            continue
        for item in sanitize_registry_websites(hit.url):
            if item["kind"] != "website" or item["url"] in seen:
                continue
            seen.add(item["url"])
            candidates.append(SearchCandidate(item["url"], response.provider_id,
                response.provider_version, query.query_id, hit.result_id, hit.rank,
                response.response_sha256))
    return candidates


async def discover_with_provider(provider: SearchProvider | None, queries: list[SearchQuery],
                                 gateway: NetworkGateway, *, timeout_seconds: float = 10.0,
                                 max_queries: int = 3, max_candidates: int = 10,
                                 paid_cost_cap_usd: str = "0") -> tuple[list[SearchCandidate], dict[str, Any]]:
    """Run one bounded, ordered pass with retries disabled and visible accounting."""
    started = time.monotonic()
    audit: dict[str, Any] = {
        "provider_id": provider.provider_id if provider else None,
        "provider_version": provider.provider_version if provider else None,
        "enabled": False,
        "status": "not_run",
        "physical_requests": 0,
        "logical_requests": 0,
        "cost_usd": "0",
        "queries": [],
        "candidate_count": 0,
    }
    if provider is None:
        audit["status"] = "disabled_no_provider"
        audit["elapsed_ms"] = 0
        return [], audit
    if timeout_seconds <= 0 or max_queries < 1 or max_candidates < 1:
        raise ValueError("search timeout and result limits must be positive")
    if not (provider.reproducible and provider.rights_approved and provider.retries_visible):
        audit["status"] = "provider_not_eligible"
        audit["elapsed_ms"] = 0
        return [], audit
    candidates: list[SearchCandidate] = []
    declared_cost = Decimal(str(provider.cost_per_query_usd)) if provider.cost_per_query_usd is not None else None
    if declared_cost is None or declared_cost < 0:
        audit["status"] = "provider_cost_unknown"
        audit["elapsed_ms"] = 0
        return [], audit
    cap = Decimal(paid_cost_cap_usd)
    if cap < 0 or declared_cost * min(len(queries), max_queries) > cap:
        audit["status"] = "provider_cost_cap_exceeded"
        audit["elapsed_ms"] = 0
        return [], audit
    for query in queries[:max_queries]:
        row: dict[str, Any] = {"query_id": query.query_id, "status": "failed"}
        audit["logical_requests"] += 1
        ledger = getattr(gateway, "ledger", None)
        before_physical = getattr(ledger, "physical_requests", 0)
        query_started = time.monotonic()
        call_failed = False
        # Reserve the declared upper bound in the audit. A failed request may
        # still be billable, so never record it as a free miss by default.
        audit["cost_usd"] = str(Decimal(audit["cost_usd"]) + declared_cost)
        row["cost_usd_upper_bound"] = str(declared_cost)
        try:
            response = await provider.search(query, gateway, timeout_seconds=timeout_seconds)
            if response.provider_id != provider.provider_id or response.provider_version != provider.provider_version:
                raise ValueError("search response provider identity does not match the configured adapter")
            if response.physical_requests < 0 or response.elapsed_ms < 0:
                raise ValueError("search response request and latency metrics must be non-negative")
            actual_cost = Decimal(response.cost_usd)
            if actual_cost < 0 or actual_cost > declared_cost:
                raise ValueError("provider cost exceeded its predeclared per-query cap")
            row["status"] = "completed"
            after_physical = getattr(getattr(gateway, "ledger", None), "physical_requests", before_physical)
            row["physical_requests"] = max(response.physical_requests, after_physical - before_physical)
            row["elapsed_ms"] = response.elapsed_ms
            row["cost_usd"] = str(actual_cost)
            row["response_sha256"] = response.response_sha256
            audit["physical_requests"] += row["physical_requests"]
            audit["cost_usd"] = str(Decimal(audit["cost_usd"]) - declared_cost + actual_cost)
            candidates.extend(normalize_search_hits(query, response))
        except TimeoutError:
            row["status"] = "timeout"
            call_failed = True
        except Exception as exc:  # provider outage is a discovery miss, never an evidence value
            row["status"] = "provider_error"
            row["error_type"] = type(exc).__name__
            call_failed = True
        row["observed_elapsed_ms"] = round((time.monotonic() - query_started) * 1000, 3)
        after_physical = getattr(getattr(gateway, "ledger", None), "physical_requests", before_physical)
        failed_call_physical = after_physical - before_physical
        if call_failed and failed_call_physical > 0:
            row["physical_requests"] = failed_call_physical
            audit["physical_requests"] += failed_call_physical
        audit["queries"].append(row)
        if len(candidates) >= max_candidates:
            candidates = candidates[:max_candidates]
            break
    audit["enabled"] = True
    audit["status"] = "completed"
    audit["candidate_count"] = len(candidates)
    audit["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
    return candidates, audit
