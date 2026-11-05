"""Official, employer-bound job observations independent of company websites."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from .models import Claim, Evidence, PublicState, SourceSnapshot
from .network import NetworkGateway
from .recording import ReplayError
from .websites import (WebsiteResearchResult, _contains_direct_contact_or_identifier,
                       _date_value, normalize_name, sanitize_registry_websites)


ORIGIN = "https://pam-stilling-feed.nav.no"
RIGHTS = "NAV API terms: https://arbeidsplassen.nav.no/vilkar-api"
UUID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}")
APPROVED_NAV_REQUEST_PURPOSES = frozenset({"nav_public_access", "nav_feed", "nav_job"})
NAV_CACHE_VERSION = 1


def _cache_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _detail_context(item: dict[str, Any], entry: dict[str, Any], detail_id: str) -> dict[str, Any] | None:
    modified = _date_value(entry.get("sistEndret"))
    if not modified or modified.tzinfo is None or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", detail_id):
        return None
    return {"version": NAV_CACHE_VERSION, "uuid": entry["uuid"], "detail_id": detail_id,
        "status": entry["status"], "last_modified": modified.isoformat(),
        "feed_item_sha256": hashlib.sha256(_cache_bytes(item)).hexdigest()}


def _complete_detail(payload: dict[str, Any]) -> bool:
    content = payload.get("ad_content")
    employer = content.get("employer") if isinstance(content, dict) else None
    return bool(isinstance(employer, dict) and isinstance(employer.get("orgnr"), str)
        and re.fullmatch(r"\d{9}", employer["orgnr"])
        and isinstance(content.get("title"), str) and content["title"].strip()
        and all(_date_value(value) for value in (payload.get("sistEndret"),
            content.get("published"), content.get("expires"))))


def _cache_record(context: dict[str, Any], body: bytes, url: str, retrieved: datetime) -> dict[str, Any]:
    return {"version": NAV_CACHE_VERSION, "context": context,
        "request_url": ORIGIN + "/api/v1/feedentry/" + context["detail_id"],
        "source_url": url, "retrieved_at": retrieved.isoformat(),
        "content_sha256": hashlib.sha256(body).hexdigest(), "body": base64.b64encode(body).decode()}


def _read_cache_record(record: dict[str, Any], context: dict[str, Any], cutoff: datetime
                       ) -> tuple[dict[str, Any], bytes, str, datetime]:
    if (record.get("version") != NAV_CACHE_VERSION or record.get("context") != context
            or record.get("request_url") != ORIGIN + "/api/v1/feedentry/" + context["detail_id"]
            or record.get("source_url") != record.get("request_url")):
        raise ValueError("NAV cache identity mismatch")
    body = base64.b64decode(record["body"], validate=True)
    if len(body) > 1024 * 1024 or hashlib.sha256(body).hexdigest() != record.get("content_sha256"):
        raise ValueError("NAV cache content mismatch")
    retrieved = datetime.fromisoformat(record["retrieved_at"])
    payload = json.loads(body)
    if (retrieved.tzinfo is None or retrieved > cutoff or not isinstance(payload, dict)
            or payload.get("uuid") != context["uuid"] or payload.get("status") != context["status"]
            or not _complete_detail(payload)
            or _date_value(payload.get("sistEndret")) != _date_value(context["last_modified"])
            or _date_value(payload["sistEndret"]) > retrieved
            or _date_value(payload["ad_content"]["published"]) > retrieved):
        raise ValueError("NAV cache observation mismatch")
    if (re.search(rb"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b|\bBearer\s+\S+", body)
            or re.search(rb'"(?:authorization|access_token|refresh_token|api_key|password|token)"\s*:', body, re.I)):
        raise ValueError("credential-bearing NAV detail cannot be cached")
    return payload, body, record["source_url"], retrieved


class _NavDetailCache:
    def __init__(self, directory: str | Path):
        supplied = Path(directory).expanduser()
        if not supplied.is_absolute():
            supplied = Path(__file__).resolve().parents[1] / "cache" / supplied
        if supplied.is_symlink():
            raise ValueError("NAV cache symlink rejected")
        self.root = supplied.parent.resolve() / supplied.name
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._private_directory()

    def _private_directory(self) -> None:
        info = self.root.stat()
        if (self.root.is_symlink() or not stat.S_ISDIR(info.st_mode)
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.getuid()):
            raise ValueError("NAV cache directory must be private")

    def _path(self, context: dict[str, Any]) -> Path:
        return self.root / (hashlib.sha256(_cache_bytes(context)).hexdigest() + ".json")

    def load(self, context: dict[str, Any]) -> dict[str, Any] | None:
        self._private_directory()
        try:
            descriptor = os.open(self._path(context), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                    or info.st_uid != os.getuid() or info.st_size > 2 * 1024 * 1024):
                raise ValueError("NAV cache file must be a private regular file")
            wrapped = json.load(stream)
        record = wrapped["record"]
        if (not isinstance(record, dict)
                or hashlib.sha256(_cache_bytes(record)).hexdigest() != wrapped["sha256"]):
            raise ValueError("NAV cache record hash mismatch")
        return record

    def save(self, context: dict[str, Any], record: dict[str, Any]) -> None:
        self._private_directory()
        wrapped = {"record": record, "sha256": hashlib.sha256(_cache_bytes(record)).hexdigest()}
        descriptor, temporary = tempfile.mkstemp(prefix=".nav-detail-", dir=self.root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(_cache_bytes(wrapped))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path(context))
            directory_descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


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
                    cutoff: datetime, *, json_pointer: str = "/",
                    valid_at: datetime | None = None) -> WebsiteResearchResult:
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
    if (not expires or expires <= max(retrieved, valid_at or retrieved)
            or not published or published > cutoff or not modified or modified > cutoff):
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
        content_sha256=digest, extraction_method="nav_exact_employer_job_v1", json_pointer=json_pointer,
        subject_organisation_number=org, source_snapshot_ids=[source_id]))
    relation = bindings[employer["orgnr"]]
    evidence_ids = list(dict.fromkeys([evidence_id] + [ref for claim in relation for ref in claim.evidence_ids]))
    source_ids = list(dict.fromkeys([source_id] + [ref for claim in relation for ref in claim.source_snapshot_ids]))
    values = {"job_title": title.strip(), "canonical_job_url": f"https://arbeidsplassen.nav.no/stillinger/stilling/{vacancy}",
              "job_status": "open", "posting_date": {"source_value": content["published"],
                  "normalized_utc": published.isoformat(), "precision": "second"},
              "job_employer_organisation_number": employer["orgnr"]}
    for field, value in values.items():
        from .identifiers import stable_claim_id
        identity = stable_claim_id(org, field, value, source=url, content_sha256=digest,
            subject=f"nav:{vacancy}", scope="job", as_of=modified)
        result.claims.append(Claim(claim_id=identity, organisation_number=org,
            section="hiring_activity", field_family="jobs", subject_id=f"nav:{vacancy}", field=field,
            value=value, state=PublicState.AVAILABLE, scope="job", as_of=modified,
            verification_rule_id="nav_exact_employer_job_v1", verification_score="1.0",
            evidence_ids=evidence_ids, source_snapshot_ids=source_ids))
    return result


def _embedded_entry(item: dict[str, Any], entry: dict[str, Any]) -> tuple[dict[str, Any], str]:
    for candidate, pointer in ((entry, "/_feed_entry"), (item, "")):
        if isinstance(candidate.get("ad_content"), dict):
            return {**entry, **candidate}, pointer
        if isinstance(candidate.get("employer"), dict):
            return {**entry, "ad_content": candidate}, pointer
    for key in ("content_text", "json"):
        candidate = item.get(key)
        if isinstance(candidate, str) and candidate.lstrip().startswith("{"):
            try:
                candidate = json.loads(candidate)
            except ValueError:
                continue
        if isinstance(candidate, dict):
            if isinstance(candidate.get("ad_content"), dict):
                return {**entry, **candidate}, "/" + key
            if isinstance(candidate.get("employer"), dict):
                return {**entry, "ad_content": candidate}, "/" + key
    return entry, "/_feed_entry"


def _continuation(value: Any, base: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid NAV continuation")
    parsed = urlsplit(urljoin(base, value))
    if (parsed.scheme != "https" or parsed.netloc != "pam-stilling-feed.nav.no"
            or parsed.fragment or not re.fullmatch(r"/api/v1/feed/[A-Za-z0-9-]+", parsed.path)
            or set(dict(parse_qsl(parsed.query, keep_blank_values=True))) - {"pageSize"}):
        raise ValueError("invalid NAV continuation")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode({"pageSize": "1000"}), ""))


class _ScanStopped(Exception):
    pass


def _employer_name_keys(value: str) -> set[str]:
    normalized = normalize_name(value)
    head = re.split(r"\b(?:avd|avdeling)\b|\s[-–,(]", normalized, maxsplit=1)[0]
    keys = {normalize_name(re.sub(r"\b(?:as|asa|ans|da|sa|ba|enk|nuf|ks|hf|iks|kf)\b", " ", item))
        for item in (normalized, head)}
    return {key for key in keys if len(key) >= 4}


async def research_jobs(targets: dict[str, Any], gateway: NetworkGateway, cutoff: datetime, *,
                        allow_current: bool = False, previous_claims: dict[str, list[dict[str, Any]]] | None = None,
                        max_pages: int = 256, max_details: int = 4096, time_seconds: float = 180,
                        max_requests: int = 4608, cache_dir: str | Path | None = None
                        ) -> tuple[dict[str, WebsiteResearchResult], dict[str, Any], dict[str, list[dict[str, str]]]]:
    """Persist details privately; cache_dir or SIGNALPOST_NAV_CACHE overrides the project cache.

    HTTP captures include raw cache hits and lookup/write controls. Replay uses
    those controls exclusively and never reads or writes the mutable NAV cache.
    """
    results: dict[str, WebsiteResearchResult] = {}
    homepages: dict[str, list[dict[str, str]]] = {}
    started = time.monotonic()
    audit: dict[str, Any] = {"state": "partial", "pages": 0, "details": 0, "matched_jobs": 0,
        "window_days": 40, "negative_coverage": False, "complete": False, "feed_complete": False,
        "truncated": False, "max_pages": max_pages, "max_details": max_details,
        "time_seconds": time_seconds, "max_requests": max_requests, "requests": 0,
        "request_count_scope": "logical_gateway_calls", "gateway_retries_use_shared_physical_budget": True,
        "items": 0, "malformed_items": 0, "detail_failures": 0, "unresolved_entries": 0,
        "cache_hits": 0, "cache_misses": 0, "cache_writes": 0, "cache_errors": 0}
    if not allow_current or not targets:
        audit.update(state="not_attempted", reason=("historical_cutoff_current_feed_not_reproducible"
            if not allow_current else "no_registry_targets"), elapsed_seconds=0.0)
        return results, audit, homepages
    if min(max_pages, max_details, max_requests, time_seconds) <= 0:
        audit.update(reason="zero_scan_budget", truncated=True, elapsed_seconds=0.0)
        return results, audit, homepages
    bindings = {org: employer_bindings(org, target.claims) for org, target in targets.items()}
    wanted = {employer for bound in bindings.values() for employer in bound}
    names = {key for target in targets.values() for claim in target.claims
        if claim.field in {"name", "legal_name", "workplace.navn"} and isinstance(claim.value, str)
        for key in _employer_name_keys(claim.value)}
    index: dict[str, set[str]] = {}
    employer_by_vacancy: dict[str, str] = {}
    observations: dict[str, tuple[dict[str, Any], bytes, str, datetime, str]] = {}
    pending: dict[str, int] = {}
    resolved: set[str] = set()
    requested: set[str] = set()
    detail_ids: dict[str, str] = {}
    detail_contexts: dict[str, dict[str, Any]] = {}
    reasons: set[str] = set()
    recording = getattr(gateway, "http_recording", None)
    replay = bool(getattr(gateway, "replay_mode", False) or (recording and recording.replay))
    if replay and recording is None:
        raise ReplayError("NAV replay requires recorded cache controls; live fallback forbidden")
    cache = None
    cache_path = cache_dir if cache_dir is not None else os.environ.get("SIGNALPOST_NAV_CACHE",
        str(Path(__file__).resolve().parents[1] / ".signalpost-cache" / "nav"))
    cache_state = "disabled"
    if cache_path and not replay:
        try:
            cache = _NavDetailCache(cache_path)
            cache_state = "miss"
        except (OSError, ValueError):
            cache_state = "error"
    gateway.set_rate_limit("pam-stilling-feed.nav.no", 4.0)

    def cache_control(name: str, actual: dict[str, Any]) -> dict[str, Any]:
        if recording is None:
            return actual
        if replay:
            return recording.replay_execution(name)
        recording.record_execution(name, actual)
        return actual

    def cache_lookup(vacancy: str) -> tuple[dict[str, Any], bytes, str, datetime] | None:
        context = detail_contexts.get(vacancy)
        decision: dict[str, Any] = {"state": cache_state, "context": context, "record": None}
        if cache is not None and context is not None:
            try:
                record = cache.load(context)
                if record is not None:
                    _read_cache_record(record, context, cutoff)
                    decision.update(state="hit", record=record)
            except (OSError, ValueError, KeyError, TypeError):
                decision["state"] = "error"
        decision = cache_control("nav_detail_cache:lookup:" + vacancy, decision)
        if (not isinstance(decision, dict) or decision.get("context") != context
                or decision.get("state") not in {"disabled", "miss", "hit", "error"}
                or (decision["state"] == "hit") != isinstance(decision.get("record"), dict)):
            if replay:
                recording._fail("invalid NAV cache lookup control")
            raise ValueError("invalid NAV cache lookup control")
        if decision["state"] == "hit":
            try:
                observation = _read_cache_record(decision["record"], context, cutoff)
            except (ValueError, KeyError, TypeError):
                if replay:
                    recording._fail("invalid recorded NAV cache input")
                raise
            audit["cache_hits"] += 1
            return observation
        if decision["state"] != "disabled":
            audit["cache_misses"] += 1
        if decision["state"] == "error":
            audit["cache_errors"] += 1
        return None

    def cache_save(vacancy: str, body: bytes, url: str, retrieved: datetime) -> None:
        context = detail_contexts.get(vacancy)
        outcome = {"state": "skipped"}
        if cache is not None and context is not None:
            record = _cache_record(context, body, url, retrieved)
            try:
                _read_cache_record(record, context, max(cutoff, retrieved))
            except (ValueError, KeyError, TypeError):
                pass
            else:
                try:
                    cache.save(context, record)
                    outcome["state"] = "saved"
                except (OSError, ValueError):
                    outcome["state"] = "error"
        outcome = cache_control("nav_detail_cache:write:" + vacancy, outcome)
        if not isinstance(outcome, dict) or outcome.get("state") not in {"skipped", "saved", "error"}:
            if replay:
                recording._fail("invalid NAV cache write control")
            raise ValueError("invalid NAV cache write control")
        audit["cache_writes"] += outcome["state"] == "saved"
        audit["cache_errors"] += outcome["state"] == "error"

    def stop(reason: str):
        reasons.add(reason)
        audit["truncated"] = True
        raise _ScanStopped()

    async def fetch(url: str, purpose: str, headers: dict[str, str], cap: int):
        if time.monotonic() - started >= time_seconds:
            stop("deadline")
        if audit["requests"] >= max_requests:
            stop("request_cap")
        audit["requests"] += 1
        status, response_headers, body, final_url, outcome = await gateway.fetch(url, purpose=purpose,
            allowed_hosts={"pam-stilling-feed.nav.no"}, access_profile="nav_feed_api",
            api_headers=headers, max_bytes=cap)
        if outcome == "budget_exhausted":
            stop("gateway_budget")
        if purpose == "nav_feed" and status == 304:
            return None, final_url
        if status != 200 or outcome != "ok":
            raise ValueError("NAV request unavailable")
        return body, final_url

    def remove(vacancy: str):
        employer = employer_by_vacancy.pop(vacancy, None)
        if employer is not None:
            index[employer].discard(vacancy)
        observations.pop(vacancy, None)

    def remember(payload: dict[str, Any], body: bytes, url: str, retrieved: datetime, pointer: str):
        vacancy = payload["uuid"]
        remove(vacancy)
        content = payload.get("ad_content")
        employer = content.get("employer") if isinstance(content, dict) else None
        number = employer.get("orgnr") if isinstance(employer, dict) else None
        if payload.get("status") != "ACTIVE":
            resolved.add(vacancy)
            return
        if not isinstance(number, str) or not re.fullmatch(r"\d{9}", number):
            return
        index.setdefault(number, set()).add(vacancy)
        employer_by_vacancy[vacancy] = number
        if number in wanted:
            observations[vacancy] = (payload, body, url, retrieved, pointer)
        resolved.add(vacancy)

    async def detail(vacancy: str, headers: dict[str, str]):
        if vacancy in requested:
            return
        if time.monotonic() - started >= time_seconds:
            stop("deadline")
        requested.add(vacancy)
        try:
            cached = cache_lookup(vacancy)
            if cached is not None:
                payload, body, url, retrieved = cached
                remember(payload, body, url, retrieved, "/")
                return
            if audit["details"] >= max_details:
                stop("detail_cap")
            audit["details"] += 1
            body, url = await fetch(ORIGIN + "/api/v1/feedentry/" + detail_ids.get(vacancy, vacancy), "nav_job", headers, 1024 * 1024)
            payload = json.loads(body)
            if (not isinstance(payload, dict) or payload.get("uuid") != vacancy
                    or payload.get("status") not in {"ACTIVE", "INACTIVE"}):
                raise ValueError("invalid NAV detail")
            if payload["status"] == "ACTIVE" and (not isinstance(payload.get("ad_content"), dict)
                    or not isinstance(payload["ad_content"].get("employer"), dict)):
                raise ValueError("invalid NAV employer detail")
            retrieved = getattr(gateway, "observed_at", None) or datetime.now(timezone.utc)
            remember(payload, body, url, retrieved, "/")
            if payload["status"] == "ACTIVE" and not _complete_detail(payload):
                resolved.discard(vacancy)
            if vacancy not in resolved:
                audit["unbound_details"] = audit.get("unbound_details", 0) + 1
            cache_save(vacancy, body, url, retrieved)
        except _ScanStopped:
            raise
        except Exception:
            audit["detail_failures"] += 1
            reasons.add("detail_failures")

    scan_time = cutoff
    detail_started = None
    audit["window_start"] = (scan_time - timedelta(days=40)).isoformat()
    audit["window_end"] = scan_time.isoformat()
    try:
        async with asyncio.timeout(time_seconds):
            token_body, _ = await fetch(ORIGIN + "/api/publicToken", "nav_public_access", {}, 16384)
            tokens = re.findall(rb"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", token_body)
            if len(tokens) != 1:
                raise ValueError("NAV public token missing")
            headers = {"Authorization": "Bearer " + tokens[0].decode("ascii")}
            for org, claims in (previous_claims or {}).items():
                if org in targets:
                    for claim in claims:
                        subject = str(claim.get("subject_id", ""))
                        if (claim.get("verification_rule_id") == "nav_exact_employer_job_v1"
                                and subject.startswith("nav:") and UUID.fullmatch(subject[4:])):
                            pending[subject[4:]] = 0
            page_url = ORIGIN + "/api/v1/feed?pageSize=1000"
            visited: set[str] = set()
            since = format_datetime(scan_time - timedelta(days=40), usegmt=True)
            while page_url:
                if time.monotonic() - started >= time_seconds * 0.85:
                    reasons.add("feed_deadline")
                    audit["truncated"] = True
                    break
                if page_url in visited:
                    reasons.add("pagination_cycle")
                    audit["truncated"] = True
                    break
                if audit["pages"] >= max_pages:
                    reasons.add("page_cap")
                    audit["truncated"] = True
                    break
                visited.add(page_url)
                try:
                    body, url = await fetch(page_url, "nav_feed", {**headers, "If-Modified-Since": since}, 2 * 1024 * 1024)
                    if body is None:
                        audit["feed_complete"] = True
                        break
                    audit["pages"] += 1
                    page = json.loads(body)
                    if not isinstance(page, dict) or not isinstance(page.get("items"), list) or len(page["items"]) > 1000:
                        raise ValueError("invalid NAV feed items")
                except _ScanStopped:
                    raise
                except Exception as exc:
                    reasons.add("request_or_feed_failure")
                    audit["error_type"] = type(exc).__name__
                    break
                retrieved = getattr(gateway, "observed_at", None) or datetime.now(timezone.utc)
                for position, item in enumerate(page["items"]):
                    audit["items"] += 1
                    entry = item.get("_feed_entry") if isinstance(item, dict) else None
                    if entry is None and isinstance(item, dict) and "ad_content" in item:
                        entry = item
                    if (not isinstance(entry, dict) or not UUID.fullmatch(str(entry.get("uuid", "")))
                            or entry.get("status") not in {"ACTIVE", "INACTIVE"}):
                        audit["malformed_items"] += 1
                        reasons.add("malformed_items")
                        continue
                    vacancy = entry["uuid"]
                    detail_id = item.get("id", vacancy)
                    if isinstance(detail_id, str) and re.fullmatch(r"[A-Za-z0-9-]{1,128}", detail_id):
                        detail_ids[vacancy] = detail_id
                    if entry["status"] != "ACTIVE":
                        remove(vacancy)
                        pending.pop(vacancy, None)
                        detail_contexts.pop(vacancy, None)
                        continue
                    context = _detail_context(item, entry, detail_ids.get(vacancy, vacancy))
                    if context is None:
                        detail_contexts.pop(vacancy, None)
                    else:
                        detail_contexts[vacancy] = context
                    payload, pointer = _embedded_entry(item, entry)
                    if payload.get("uuid") != vacancy or payload.get("status") != entry["status"]:
                        audit["malformed_items"] += 1
                        reasons.add("malformed_items")
                        continue
                    content = payload.get("ad_content")
                    employer = content.get("employer") if isinstance(content, dict) else None
                    number = employer.get("orgnr") if isinstance(employer, dict) else None
                    if isinstance(number, str) and re.fullmatch(r"\d{9}", number):
                        remember(payload, body, url, retrieved, f"/items/{position}" + pointer)
                        if number not in wanted or _complete_detail(payload):
                            pending.pop(vacancy, None)
                            continue
                        resolved.discard(vacancy)
                        priority = 0
                    else:
                        remove(vacancy)
                        resolved.discard(vacancy)
                        priority = 1 if _employer_name_keys(str(entry.get("businessName", ""))) & names else 2
                    pending[vacancy] = min(priority, pending.get(vacancy, priority))
                next_url = page.get("next_url")
                if next_url is None or next_url == "":
                    audit["feed_complete"] = True
                    break
                try:
                    page_url = _continuation(next_url, url)
                except ValueError:
                    reasons.add("invalid_continuation")
                    audit["truncated"] = True
                    break
            audit["feed_elapsed_seconds"] = round(time.monotonic() - started, 3)
            detail_started = time.monotonic()
            for vacancy in sorted(pending, key=lambda value: (pending[value], value)):
                await detail(vacancy, headers)
            audit["detail_elapsed_seconds"] = round(time.monotonic() - detail_started, 3)
    except _ScanStopped:
        pass
    except TimeoutError:
        reasons.add("deadline")
        audit["truncated"] = True
    except asyncio.CancelledError:
        reasons.add("cancelled")
        audit["truncated"] = True
    except Exception as exc:
        reasons.add("request_or_feed_failure")
        audit["error_type"] = type(exc).__name__

    for org, bound in bindings.items():
        vacancies = {vacancy for employer in bound for vacancy in index.get(employer, ())}
        for vacancy in sorted(vacancies):
            record = observations.get(vacancy)
            if record is None:
                continue
            payload, body, url, retrieved, pointer = record
            observation = job_observation(org, payload, body, url, retrieved, bound, retrieved,
                json_pointer=pointer, valid_at=cutoff)
            if not observation.claims:
                continue
            result = results.setdefault(org, WebsiteResearchResult())
            result.claims.extend(observation.claims)
            result.evidence.extend(observation.evidence)
            result.snapshots.extend(observation.snapshots)
            audit["matched_jobs"] += 1
            for candidate in sanitize_registry_websites(payload["ad_content"]["employer"].get("homepage")):
                homepage = {"raw": candidate["url"], "source": "nav_employer"}
                if candidate["kind"] == "website" and homepage not in homepages.get(org, []):
                    homepages.setdefault(org, []).append(homepage)
    audit["unresolved_entries"] = len(set(pending) - resolved)
    audit["indexed_employers"] = sum(bool(vacancies) for vacancies in index.values())
    audit["indexed_jobs"] = sum(len(vacancies) for vacancies in index.values())
    audit["complete"] = audit["feed_complete"] and not reasons and not audit["unresolved_entries"]
    audit["truncated"] = not audit["complete"]
    if audit["complete"]:
        audit.update(state="complete", reason="window_index_complete")
    else:
        audit["state"] = "partial" if audit["pages"] or audit["details"] or results else "blocked"
        audit["reason"] = ",".join(sorted(reasons)) or "unresolved_entries"
    audit["elapsed_seconds"] = round(time.monotonic() - started, 3)
    audit.setdefault("feed_elapsed_seconds", audit["elapsed_seconds"])
    audit.setdefault("detail_elapsed_seconds", round(time.monotonic() - detail_started, 3) if detail_started is not None else 0.0)
    return results, audit, homepages
