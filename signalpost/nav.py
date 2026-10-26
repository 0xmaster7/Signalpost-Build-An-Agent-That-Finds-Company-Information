"""Official, employer-bound job observations independent of company websites."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from .models import Claim, Evidence, PublicState, SourceSnapshot
from .network import NetworkGateway
from .websites import (WebsiteResearchResult, _contains_direct_contact_or_identifier,
                       _date_value, normalize_name, sanitize_registry_websites)


ORIGIN = "https://pam-stilling-feed.nav.no"
RIGHTS = "NAV API terms: https://arbeidsplassen.nav.no/vilkar-api"
UUID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}")
APPROVED_NAV_REQUEST_PURPOSES = frozenset({"nav_public_access", "nav_feed", "nav_job"})


def employer_bindings(org: str, claims: list[Claim]) -> dict[str, list[Claim]]:
    bindings: dict[str, list[Claim]] = {org: []}
    for claim in claims:
        if (claim.organisation_number != org or claim.state != PublicState.AVAILABLE
                or claim.scope != "workplace" or claim.field != "workplace.overordnetEnhet"
                or claim.value != org or not re.fullmatch(r"\d{9}", claim.subject_id or "")):
            continue
        bindings[claim.subject_id] = [claim]
    return bindings


def job_observation(org: str, payload: dict[str, Any], body: bytes, url: str,
                    retrieved: datetime, bindings: dict[str, list[Claim]],
                    cutoff: datetime) -> WebsiteResearchResult:
    result = WebsiteResearchResult()
    content = payload.get("ad_content")
    vacancy = payload.get("uuid")
    if not isinstance(content, dict) or payload.get("status") != "ACTIVE" or not UUID.fullmatch(str(vacancy)):
        return result
    employer = content.get("employer")
    if not isinstance(employer, dict) or not isinstance(employer.get("orgnr"), str) or employer["orgnr"] not in bindings:
        return result
    expires = _date_value(content.get("expires"))
    published = _date_value(content.get("published"))
    modified = _date_value(payload.get("sistEndret"))
    if not expires or expires <= retrieved or not published or published > cutoff or not modified or modified > cutoff:
        return result
    title = content.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 500 or _contains_direct_contact_or_identifier(title):
        return result
    digest = hashlib.sha256(body).hexdigest()
    source_id = f"nav:{vacancy}:{digest[:16]}"
    evidence_id = f"{org}:{source_id}"
    result.snapshots.append(SourceSnapshot(source_id=source_id, source_url=url, retrieved_at=retrieved,
        content_sha256=digest, http_status=200, cache_mode="transient", rights_status=RIGHTS))
    result.evidence.append(Evidence(evidence_id=evidence_id, source_url=url, retrieved_at=retrieved,
        content_sha256=digest, extraction_method="nav_exact_employer_job_v1", json_pointer="/",
        subject_organisation_number=org, source_snapshot_ids=[source_id]))
    relation = bindings[employer["orgnr"]]
    evidence_ids = list(dict.fromkeys([evidence_id] + [ref for claim in relation for ref in claim.evidence_ids]))
    source_ids = list(dict.fromkeys([source_id] + [ref for claim in relation for ref in claim.source_snapshot_ids]))
    values = {"job_title": title.strip(), "canonical_job_url": f"https://arbeidsplassen.nav.no/stillinger/stilling/{vacancy}",
              "job_status": "open", "posting_date": {"source_value": content["published"],
                  "normalized_utc": published.isoformat(), "precision": "second"},
              "job_employer_organisation_number": employer["orgnr"]}
    for field, value in values.items():
        result.claims.append(Claim(claim_id=f"{org}:nav:{vacancy}:{field}", organisation_number=org,
            section="hiring_activity", field_family="jobs", subject_id=f"nav:{vacancy}", field=field,
            value=value, state=PublicState.AVAILABLE, scope="job", as_of=modified,
            verification_rule_id="nav_exact_employer_job_v1", verification_score="1.0",
            evidence_ids=evidence_ids, source_snapshot_ids=source_ids))
    return result


async def research_jobs(targets: dict[str, Any], gateway: NetworkGateway, cutoff: datetime, *,
                        allow_current: bool = False, previous_claims: dict[str, list[dict[str, Any]]] | None = None,
                        max_pages: int = 4, max_details: int = 8) -> tuple[dict[str, WebsiteResearchResult], dict[str, Any], dict[str, list[dict[str, str]]]]:
    results: dict[str, WebsiteResearchResult] = {}
    homepages: dict[str, list[dict[str, str]]] = {}
    audit: dict[str, Any] = {"state": "partial", "pages": 0, "details": 0, "matched_jobs": 0,
        "window_days": 40, "negative_coverage": False, "reason": "bounded_name_shortlist_not_exhaustive"}
    if not allow_current:
        audit.update(state="not_attempted", reason="historical_cutoff_current_feed_not_reproducible")
        return results, audit, homepages
    bindings = {org: employer_bindings(org, target.claims) for org, target in targets.items()}
    names: dict[str, set[str]] = {}
    for org, target in targets.items():
        for claim in target.claims:
            if claim.field in {"name", "legal_name", "workplace.navn"} and isinstance(claim.value, str):
                name = normalize_name(claim.value)
                if len(name) >= 4:
                    names.setdefault(name, set()).add(org)
    requested: set[str] = set()
    if not targets:
        audit.update(state="not_attempted", reason="no_registry_targets")
        return results, audit, homepages
    gateway.set_rate_limit("pam-stilling-feed.nav.no", 4.0)

    async def fetch(url: str, purpose: str, headers: dict[str, str], cap: int):
        status, response_headers, body, final_url, outcome = await gateway.fetch(url, purpose=purpose,
            allowed_hosts={"pam-stilling-feed.nav.no"}, access_profile="nav_feed_api", api_headers=headers, max_bytes=cap)
        if status != 200 or outcome != "ok":
            raise ValueError("NAV request unavailable")
        return body, final_url

    try:
        async with asyncio.timeout(20):
            token_body, _ = await fetch(ORIGIN + "/api/publicToken", "nav_public_access", {}, 16384)
            tokens = re.findall(rb"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", token_body)
            if len(tokens) != 1:
                raise ValueError("NAV public token missing")
            headers = {"Authorization": "Bearer " + tokens[0].decode("ascii")}

            async def detail(vacancy: str, expected: set[str]):
                if vacancy in requested or len(requested) >= max_details or not UUID.fullmatch(vacancy):
                    return
                requested.add(vacancy)
                audit["details"] += 1
                try:
                    body, url = await fetch(ORIGIN + "/api/v1/feedentry/" + vacancy, "nav_job", headers, 1024 * 1024)
                    payload = json.loads(body)
                    if not isinstance(payload, dict):
                        raise ValueError("invalid NAV detail")
                except Exception:
                    audit["detail_failures"] = audit.get("detail_failures", 0) + 1
                    return
                if payload.get("uuid") != vacancy:
                    return
                now = datetime.now(timezone.utc)
                for org in sorted(expected):
                    observation = job_observation(org, payload, body, url, now, bindings[org], now)
                    if not observation.claims:
                        continue
                    result = results.setdefault(org, WebsiteResearchResult())
                    result.claims.extend(observation.claims)
                    result.evidence.extend(observation.evidence)
                    result.snapshots.extend(observation.snapshots)
                    audit["matched_jobs"] += 1
                    for candidate in sanitize_registry_websites(payload["ad_content"]["employer"].get("homepage")):
                        if candidate["kind"] == "website":
                            homepages.setdefault(org, []).append({"raw": candidate["url"], "source": "nav_employer"})

            known: dict[str, set[str]] = {}
            for org, claims in (previous_claims or {}).items():
                if org not in targets:
                    continue
                for claim in claims:
                    subject = str(claim.get("subject_id", ""))
                    if claim.get("verification_rule_id") == "nav_exact_employer_job_v1" and subject.startswith("nav:"):
                        known.setdefault(subject[4:], set()).add(org)
            for vacancy, owners in sorted(known.items()):
                await detail(vacancy, owners)
            page_url = ORIGIN + "/api/v1/feed?pageSize=1000"
            visited = set()
            since = format_datetime(datetime.now(timezone.utc) - timedelta(days=40), usegmt=True)
            for page_index in range(max_pages):
                if page_url in visited or len(requested) >= max_details:
                    break
                visited.add(page_url)
                body, _ = await fetch(page_url, "nav_feed", {**headers, "If-Modified-Since": since}, 2 * 1024 * 1024)
                audit["pages"] += 1
                page = json.loads(body)
                items = page.get("items")
                if not isinstance(items, list) or len(items) > 1000:
                    raise ValueError("invalid NAV feed items")
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    entry = item.get("_feed_entry", {})
                    if not isinstance(entry, dict) or entry.get("status") != "ACTIVE":
                        continue
                    owners = names.get(normalize_name(str(entry.get("businessName", ""))), set())
                    if owners:
                        await detail(str(entry.get("uuid", "")), owners)
                next_url = page.get("next_url")
                if not next_url:
                    break
                parsed = urlsplit(urljoin(ORIGIN, next_url))
                if (parsed.scheme != "https" or parsed.netloc != "pam-stilling-feed.nav.no"
                        or not re.fullmatch(r"/api/v1/feed/[A-Za-z0-9-]+", parsed.path)
                        or set(dict(parse_qsl(parsed.query))) - {"pageSize"}):
                    raise ValueError("invalid NAV continuation")
                page_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                    urlencode({"pageSize": "1000"}), ""))
    except Exception as exc:
        audit.update(state="blocked", error_type=type(exc).__name__)
    return results, audit, homepages
