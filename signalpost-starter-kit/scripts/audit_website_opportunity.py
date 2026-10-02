#!/usr/bin/env python3
"""Freeze and audit one registry website candidate per sampled company.

This is an M00 audit utility. It does not alter the production runner or publish
claims. The input is Builderr's public gzip JSONL universe. Sample selection is
deterministic and proportional across legal-form, employee-band, and website
presence strata. In fetch mode, only the registry-provided homepage is fetched.
Robots checks may add one request per unique origin.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.identity import assess_website_identity  # noqa: E402
from norway_company_agent.website import (  # noqa: E402
    SAFE_OPENER,
    SOCIAL_HOSTS,
    USER_AGENT,
    _jsonld_organisations,
    _registered_domain,
    assert_public_url,
    normalize_homepage,
)
from bs4 import BeautifulSoup  # noqa: E402
import extruct  # noqa: E402
import trafilatura  # noqa: E402


def employee_band(value: Any) -> str:
    if value is None:
        return "missing"
    value = int(value)
    return "0" if value == 0 else "1-4" if value < 5 else "5-19" if value < 20 else "20-99" if value < 100 else "100+"


def website_stratum(row: dict[str, Any]) -> str:
    form = row.get("legal_form") if row.get("legal_form") in {"AS", "ASA", "ENK"} else "OTHER"
    return "|".join((form, employee_band(row.get("employees")), "web" if row.get("website") else "no-web"))


def read_population(path: Path) -> tuple[list[dict[str, Any]], str, int]:
    archive_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    content_hash = hashlib.sha256()
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rb") as raw:
        for line in raw:
            content_hash.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("latest_submitted_accounts") == "2025" and not row.get("bankrupt") and not row.get("liquidating"):
                rows.append(row)
    return rows, archive_hash, int(content_hash.hexdigest(), 16)


def choose_sample(rows: list[dict[str, Any]], count: int, seed: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for row in rows:
        key = website_stratum(row)
        rank = hashlib.sha256(f"{seed}:{row['organisation_number']}:sample".encode()).hexdigest()
        groups[key].append((rank, row))
    if count > len(rows):
        raise ValueError(f"Requested {count}; eligible universe contains {len(rows)}")

    sizes = {key: len(items) for key, items in groups.items()}
    quotas = {key: count * size // len(rows) for key, size in sizes.items()}
    remainder = count - sum(quotas.values())
    for key in sorted(groups, key=lambda k: (-(count * sizes[k] % len(rows)), k))[:remainder]:
        quotas[key] += 1
    selected = []
    for key, items in groups.items():
        items.sort(key=lambda pair: (pair[0], pair[1]["organisation_number"]))
        selected.extend((rank, row, key) for rank, row in items[: quotas[key]])
    selected.sort(key=lambda item: (hashlib.sha256(f"{seed}:order:{item[1]['organisation_number']}".encode()).hexdigest(), item[1]["organisation_number"]))
    sample = []
    for rank, row, key in selected:
        sample.append({**row, "m00_sample_seed": seed, "m00_stratum": key, "m00_sample_rank": rank})
    orgs = sorted(row["organisation_number"] for row in sample)
    return sample, {
        "seed": seed,
        "requested": count,
        "selected": len(sample),
        "selected_organisation_numbers_sha256": hashlib.sha256("\n".join(orgs).encode()).hexdigest(),
        "population_strata": dict(sorted(Counter(website_stratum(row) for row in rows).items())),
        "sample_strata": dict(sorted(Counter(website_stratum(row) for row in sample).items())),
    }


def _request(url: str, *, limit: int = 1_500_000) -> tuple[int, bytes, str, str, str | None]:
    """Fetch a bounded response, validating every URL before automatic redirect."""
    started = time.monotonic()
    try:
        assert_public_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.2"})
        with SAFE_OPENER.open(request, timeout=8) as response:
            body = response.read(limit + 1)
            return response.status, body, response.headers.get("content-type", ""), response.geturl(), None
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(4096), exc.headers.get("content-type", ""), exc.geturl(), None
    except Exception as exc:
        return 0, b"", "", url, f"{type(exc).__name__}: {str(exc)[:160]}"
    finally:
        _ = int((time.monotonic() - started) * 1000)


def fetch_candidate(row: dict[str, Any], robots_cache: dict[str, tuple[str, bool, str | None, float | None]]) -> dict[str, Any]:
    supplied = str(row.get("website") or "").strip()
    result: dict[str, Any] = {
        "organisation_number": row["organisation_number"],
        "name": row.get("name", ""),
        "registry_website": supplied or None,
        "status": "missing",
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    url = normalize_homepage(supplied)
    if not url:
        result["status"] = "syntactically_unusable" if supplied else "missing"
        return result
    parsed = urllib.parse.urlparse(url)
    if parsed.username is not None or parsed.password is not None:
        result["status"] = "syntactically_unusable"
        result["error"] = "URL user information is not allowed"
        return result
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    social = next((platform for domain, platform in SOCIAL_HOSTS.items() if host == domain or host.endswith("." + domain)), None)
    if social:
        result.update(status="platform_only", platform=social)
        return result

    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in robots_cache:
        robots_status, robots_body, _, robots_final, robots_error = _request(urllib.parse.urljoin(origin, "/robots.txt"), limit=256_000)
        if robots_status in {404, 410}:
            allowed, state, error, crawl_delay = True, "no_rules", None, None
        elif 200 <= robots_status < 300:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(robots_final)
            parser.parse(robots_body.decode("utf-8", errors="replace").splitlines())
            allowed, state, error, crawl_delay = parser.can_fetch(USER_AGENT, url), "parsed", None, parser.crawl_delay(USER_AGENT)
        else:
            allowed, state, error, crawl_delay = False, "unreachable", robots_error or f"HTTP {robots_status}", None
        robots_cache[origin] = (state, allowed, error, crawl_delay)
    robots_state, allowed, robots_error, crawl_delay = robots_cache[origin]
    result["robots"] = {"state": robots_state, "error": robots_error, "crawl_delay_seconds": crawl_delay}
    if not allowed:
        result["status"] = "robots_unreachable" if robots_state == "unreachable" else "blocked_robots"
        return result
    if crawl_delay is not None and crawl_delay > 60:
        result["status"] = "crawl_delay_over_60"
        return result
    if crawl_delay is not None and crawl_delay > 0:
        time.sleep(crawl_delay)

    status, body, content_type, final_url, error = _request(url)
    result.update(http_status=status or None, content_type=content_type or None, final_url=final_url, error=error)
    if error:
        result["status"] = "fetch_error"
        return result
    if status < 200 or status >= 300:
        result["status"] = "dead" if status in {404, 410} else "responded_error"
        return result
    if len(body) > 1_500_000 or "html" not in content_type.casefold():
        result["status"] = "responded_non_html"
        return result

    html = body.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    text = trafilatura.extract(html, url=final_url, include_links=False, include_tables=False, favor_precision=True) or ""
    try:
        structured = extruct.extract(html, base_url=final_url, syntaxes=["json-ld", "microdata", "opengraph"])
    except Exception:
        structured = {}
    title = soup.title.get_text(" ", strip=True)[:500] if soup.title else ""
    description_node = soup.select_one('meta[name="description"],meta[property="og:description"]')
    description = str(description_node.get("content") or "").strip()[:1000] if description_node else ""
    record = {
        "status": "available",
        "source_url": final_url,
        "value": {
            "requested_url": url,
            "final_url": final_url,
            "title": title,
            "description": description,
            "main_text_excerpt": text[:2500],
            "structured_organisations": _jsonld_organisations(structured),
            "content_sha256": hashlib.sha256(body).hexdigest(),
        },
    }
    assessment = assess_website_identity({
        "organisation_number": row["organisation_number"],
        "name": row.get("name", ""),
        "evidence": {"website": record},
    })
    requested_domain = _registered_domain(url)
    final_domain = _registered_domain(final_url)
    result.update(
        status=("redirect_to_unrelated" if requested_domain != final_domain and not assessment["publishable"] else "responding"),
        requested_domain=requested_domain,
        final_domain=final_domain,
        identity=assessment,
        page={"content_sha256": record["value"]["content_sha256"]},
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", required=True, type=Path, help="Builderr public signalpost-company-universe-2025.jsonl.gz")
    parser.add_argument("--sample-output", required=True, type=Path, help="Frozen sampled company JSONL")
    parser.add_argument("--report-output", required=True, type=Path, help="Opportunity audit JSON report")
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261003)
    args = parser.parse_args()

    rows, archive_hash, content_hash_int = read_population(args.universe)
    content_hash = f"{content_hash_int:064x}"
    sample, sampling = choose_sample(rows, args.count, args.seed)
    args.sample_output.parent.mkdir(parents=True, exist_ok=True)
    with args.sample_output.open("w", encoding="utf-8") as handle:
        for row in sample:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    robots_cache: dict[str, tuple[str, bool, str | None, float | None]] = {}
    results = [fetch_candidate(row, robots_cache) for row in sample]
    hosts = Counter(item.get("final_domain") for item in results if item.get("final_domain"))
    shared = {host for host, count in hosts.items() if count > 1}
    for item in results:
        item["shared_group_domain"] = item.get("final_domain") in shared if item.get("final_domain") else False
    counts = Counter(item["status"] for item in results)
    identity = Counter(item.get("identity", {}).get("status", "not_assessed") for item in results)
    report = {
        "audit": "M00 fast registry-website opportunity audit",
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "universe": {
            "url": "https://builderr.ai/signalpost-company-universe-2025.jsonl.gz",
            "downloaded_archive_sha256": archive_hash,
            "published_archive_sha256": "1c89710e5b01f8617e86d09fbdff4a52f2f8dbbba297e74f7164b5984f5a0384",
            "uncompressed_sha256": content_hash,
            "published_uncompressed_sha256": "b82d6a3e7231d1759a958c282bc4366b80ec2fab8095053d8ed7fa9cd01bc838",
            "published_uncompressed_hash_matches": content_hash == "b82d6a3e7231d1759a958c282bc4366b80ec2fab8095053d8ed7fa9cd01bc838",
            "eligible_rows": len(rows),
        },
        "sampling": sampling,
        "request_policy": "At most one registry website homepage candidate fetch per sampled company; robots.txt checked once per unique website origin; only public HTTP(S) URLs; only HTML homepage content retained as title/description/excerpt transiently and hash in report.",
        "results": {
            "companies": len(results),
            "website_opportunity_statuses": dict(sorted(counts.items())),
            "website_identity_statuses": dict(sorted(identity.items())),
            "candidate_fetches": sum(item.get("http_status") is not None for item in results),
            "unique_robots_origins": len(robots_cache),
            "robots_outcomes": dict(sorted(Counter(state for state, _, _, _ in robots_cache.values()).items())),
            "distinct_responded_registered_domains": len(hosts),
            "companies_on_shared_registered_domains": sum(item.get("shared_group_domain", False) for item in results),
        },
        "companies": results,
    }
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["universe"] | {"sampling": sampling, "results": report["results"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
