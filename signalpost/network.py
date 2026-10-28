from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import gzip
import http.client
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from email.utils import parsedate_to_datetime
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from html.parser import HTMLParser

from tldextract import TLDExtract

from .operations import Budget
from .recording import HttpRecording


_REQUEST_COMPANY: ContextVar[str | None] = ContextVar("signalpost_request_company", default=None)
_HTTP_OBSERVED_AT: ContextVar[datetime | None] = ContextVar("signalpost_http_observed_at", default=None)


@contextmanager
def request_company_scope(company: str):
    """Attribute concurrent optional-source requests to their scheduled company."""
    token = _REQUEST_COMPANY.set(company)
    try:
        yield
    finally:
        _REQUEST_COMPANY.reset(token)


class NetworkPolicyError(ValueError):
    pass


_BRREG_API_PURPOSES = {"entity", "accounts", "roles", "subunits", "subunits_page", "group"}
APPROVED_BRREG_REQUEST_PURPOSES = frozenset(_BRREG_API_PURPOSES)
_BRREG_ORG_PATH = re.compile(r"^/enhetsregisteret/api/(?:enheter|konsernstruktur)/\d{9}(?:/roller)?/?$")
_BRREG_ACCOUNTS_PATH = re.compile(r"^/regnskapsregisteret/regnskap/\d{9}/?$")
_BRREG_COPY_PATH = re.compile(r"^/regnskapsregisteret/regnskap/aarsregnskap/kopi/\d{9}/\d{4}$")


def _brreg_document_api_url(url: str, purpose: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return (purpose == "annual_account_copy" and parsed.scheme == "https"
        and parsed.hostname == "data.brreg.no" and parsed.port in {None, 443}
        and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
        and bool(_BRREG_COPY_PATH.fullmatch(parsed.path)))


def _nav_api_url(url: str, purpose: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    paths = {"nav_public_access": r"/api/publicToken", "nav_feed": r"/api/v1/feed(?:/[A-Za-z0-9-]+)?",
             "nav_job": r"/api/v1/feedentry/[A-Za-z0-9-]+"}
    return (parsed.scheme == "https" and parsed.hostname == "pam-stilling-feed.nav.no"
        and parsed.port in {None, 443} and not parsed.username and not parsed.password and not parsed.fragment
        and purpose in paths and bool(re.fullmatch(paths[purpose], parsed.path))
        and set(urllib.parse.parse_qs(parsed.query, keep_blank_values=True)) <= {"pageSize", "last"})


def _wikidata_api_url(url: str, purpose: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        parameters = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        return (purpose == "wikidata_batch_candidates" and parsed.scheme == "https"
            and parsed.hostname == "query.wikidata.org" and parsed.port in {None, 443}
            and not parsed.username and not parsed.password and not parsed.fragment
            and parsed.path == "/sparql" and len(parameters) == 2
            and {name for name, value in parameters} == {"query", "format"}
            and dict(parameters)["format"] == "json" and bool(dict(parameters)["query"].strip()))
    except ValueError:
        return False


def _brreg_structured_api_url(url: str, purpose: str) -> bool:
    """Constrain the robots-outage exception to documented BRREG API paths."""
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "data.brreg.no"
            or parsed.port not in {None, 443} or parsed.username or parsed.password
            or purpose not in _BRREG_API_PURPOSES):
        return False
    org_match = _BRREG_ORG_PATH.fullmatch(parsed.path)
    if org_match:
        if parsed.query:
            return False
        if parsed.path.startswith("/regnskapsregisteret/"):
            return purpose == "accounts"
        if "/konsernstruktur/" in parsed.path:
            return purpose == "group"
        if parsed.path.endswith("/roller"):
            return purpose == "roles"
        return purpose == "entity"
    if _BRREG_ACCOUNTS_PATH.fullmatch(parsed.path):
        return purpose == "accounts" and not parsed.query
    if parsed.path == "/enhetsregisteret/api/underenheter":
        query = urllib.parse.parse_qs(parsed.query, strict_parsing=False)
        allowed = {"overordnetEnhet", "size", "page", "sort"}
        if set(query) - allowed or len(query.get("overordnetEnhet", [])) != 1:
            return False
        if not re.fullmatch(r"\d{9}", query["overordnetEnhet"][0]):
            return False
        return purpose in {"subunits", "subunits_page"}
    return False


class Transport(Protocol):
    async def request(self, url: str, headers: dict[str, str], timeout: float) -> tuple[int, dict[str, str], bytes, str]: ...


@dataclass
class LedgerEntry:
    request_id: str
    url: str
    purpose: str
    status: int | None
    bytes_received: int
    elapsed_ms: float
    outcome: str
    redirect_location: str | None = None


@dataclass
class RequestLedger:
    entries: list[LedgerEntry] = field(default_factory=list)
    logical_requests: int = 0

    @property
    def physical_requests(self) -> int:
        return len(self.entries)


class _AdaptiveHostLimit:
    def __init__(self, limit: int):
        self.limit = limit
        self.minimum = 1
        self.active = 0
        self.condition = asyncio.Condition()

    async def __aenter__(self):
        async with self.condition:
            await self.condition.wait_for(lambda: self.active < self.limit)
            self.active += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        async with self.condition:
            self.active -= 1
            self.condition.notify_all()

    async def reduce(self) -> None:
        async with self.condition:
            self.limit = max(self.minimum, self.limit // 2)
            self.condition.notify_all()

    async def recover(self, maximum: int) -> None:
        async with self.condition:
            self.limit = min(maximum, self.limit + 1)
            self.condition.notify_all()


class UrlLibTransport:
    """HTTP transport with redirects and implicit proxy discovery disabled."""
    def __init__(self, proxy_url: str | None = None, trust_env: bool = False):
        self.proxy_enabled = bool(proxy_url or trust_env)
        handlers: list[Any] = [_NoRedirect(), urllib.request.HTTPSHandler()]
        if proxy_url:
            handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
        elif trust_env:
            handlers.append(urllib.request.ProxyHandler())
        else:
            handlers.append(urllib.request.ProxyHandler({}))
        self._opener = urllib.request.build_opener(*handlers)

    async def request(self, url: str, headers: dict[str, str], timeout: float, approved_ips: tuple[str, ...] | None = None,
                      max_bytes: int = 2 * 1024 * 1024) -> tuple[int, dict[str, str], bytes, str]:
        if approved_ips and not self.proxy_enabled:
            return await asyncio.to_thread(self._pinned_request, url, headers, timeout, approved_ips, max_bytes)
        def read() -> tuple[int, dict[str, str], bytes, str]:
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                response = self._opener.open(request, timeout=timeout)
            except urllib.error.HTTPError as exc:
                response = exc
            try:
                body = response.read(max_bytes + 1)
                return int(response.status), dict(response.headers.items()), body, response.geturl()
            finally:
                response.close()
        return await asyncio.to_thread(read)

    @staticmethod
    def _pinned_request(url: str, headers: dict[str, str], timeout: float, addresses: tuple[str, ...], max_bytes: int) -> tuple[int, dict[str, str], bytes, str]:
        if len(addresses) != 1:
            raise NetworkPolicyError("each pinned connection requires its own gateway reservation")
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        last_error: OSError | None = None
        for address in addresses:
            connection: http.client.HTTPConnection
            if parsed.scheme == "https":
                connection = http.client.HTTPSConnection(host, port, timeout=timeout)
                original_connect = connection.connect
                def pinned_tls_connect(c=connection, ip=address, original=original_connect):
                    sock = socket.create_connection((ip, port), timeout=timeout)
                    try:
                        c.sock = c._context.wrap_socket(sock, server_hostname=host)
                    except BaseException:
                        sock.close()
                        raise
                connection.connect = pinned_tls_connect  # type: ignore[method-assign]
            else:
                connection = http.client.HTTPConnection(host, port, timeout=timeout)
                def pinned_connect(c=connection, ip=address):
                    c.sock = socket.create_connection((ip, port), timeout=timeout)
                connection.connect = pinned_connect  # type: ignore[method-assign]
            try:
                connection.request("GET", path, headers=headers)
                response = connection.getresponse()
                body = response.read(max_bytes + 1)
                return response.status, dict(response.getheaders()), body, url
            except OSError as exc:
                last_error = exc
            finally:
                connection.close()
        if last_error:
            raise last_error
        raise OSError("no approved address to connect")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def canonical_url(raw: str) -> str:
    parsed = urllib.parse.urlsplit(raw.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise NetworkPolicyError("only http and https URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise NetworkPolicyError("URL credentials are forbidden")
    if not parsed.hostname:
        raise NetworkPolicyError("URL must include a hostname")
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port
    except (UnicodeError, ValueError) as exc:
        raise NetworkPolicyError("invalid URL hostname or port") from exc
    netloc = f"[{host}]" if ":" in host else host
    if port and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
        netloc += f":{port}"
    safe_path = "/:@!$&'()*+,;=-._~"
    path = "".join((part.upper() if re.fullmatch(r"%[0-9a-fA-F]{2}", part)
                    else urllib.parse.quote(part, safe=safe_path))
                   for part in re.split(r"(%[0-9a-fA-F]{2})", parsed.path or "/"))
    return urllib.parse.urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def _public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    return ip.is_global and not (ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved)


def validate_public_host(url: str, *, trusted_proxy: bool = False) -> tuple[str, ...] | None:
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _public_ip(str(literal)):
            raise NetworkPolicyError("non-public IP destination rejected")
        return (str(literal),)
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal", ".test")):
        raise NetworkPolicyError("local hostname destination rejected")
    if trusted_proxy:
        return None
    try:
        addresses = {result[4][0] for result in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise NetworkPolicyError("hostname did not resolve") from exc
    if not addresses or any(not _public_ip(address) for address in addresses):
        raise NetworkPolicyError("hostname resolves to a non-public address")
    return tuple(sorted(addresses))


def classify_response(status: int, headers: dict[str, str], body: bytes) -> str:
    header_map = {key.casefold(): value.casefold() for key, value in headers.items()}
    sample = body[:50000].decode("utf-8", "ignore").casefold()
    if status == 200 and ("cf-chl-" in sample or "just a moment..." in sample or "captcha" in sample and "verify you are human" in sample):
        return "waf_challenge"
    if status == 200 and ("<title>404" in sample or "page not found" in sample or "not found</h1>" in sample):
        return "soft_404"
    if status in {401, 403, 429}:
        return "blocked"
    if status >= 500:
        return "server_error"
    return "ok" if 200 <= status < 400 else "http_error"


class NetworkGateway:
    """Apply identical source policy to live HTTP and private offline captures.

    Only exact BRREG/NAV API profiles tolerate unreachable robots; explicit
    disallows still win. The exact Wikidata SPARQL profile skips robots.
    Replay requires the same request settings and exact If-Modified-Since.
    Captures preserve retrieval timestamps and must stay outside Git. Complete
    pipeline replay also requires the persistent OCR cache to be warm.
    """

    def __init__(self, transport: Transport | None = None, *, timeout: float = 15, retries: int = 1,
                 redirect_limit: int = 5, response_cap: int = 2 * 1024 * 1024,
                 trusted_proxy: bool = False, proxy_url: str | None = None,
                 budget: Budget | None = None, global_concurrency: int | None = None,
                 record_http: str | None = None, replay_http: str | None = None,
                 run_metadata: dict[str, Any] | None = None):
        if record_http is not None and replay_http is not None:
            raise ValueError("record_http and replay_http are mutually exclusive")
        self.http_recording = (HttpRecording(replay_http or record_http, replay=replay_http is not None,
                                            run_metadata=run_metadata)
                               if replay_http is not None or record_http is not None else None)
        self.replay_mode = replay_http is not None
        self.transport = transport if self.replay_mode else transport or UrlLibTransport(proxy_url=proxy_url, trust_env=trusted_proxy)
        self.timeout = timeout
        self.retries = retries
        self.redirect_limit = redirect_limit
        self.response_cap = response_cap
        self.trusted_proxy = trusted_proxy
        if proxy_url and not trusted_proxy:
            raise ValueError("explicit proxies are allowed only in trusted-proxy mode")
        self.proxy_url = proxy_url
        self.budget = budget
        self.ledger = RequestLedger()
        concurrency = (global_concurrency if global_concurrency is not None else
                       budget.config.global_http_concurrency if budget else 32)
        if concurrency < 1:
            raise ValueError("global concurrency must be positive")
        self._global_slots = asyncio.Semaphore(concurrency)
        self._host_slots: dict[str, _AdaptiveHostLimit] = {}
        self._rates: dict[str, float] = {}
        self._last_request: dict[str, float] = {}
        self._rate_slots: dict[str, asyncio.Lock] = {}
        self._robots: dict[str, tuple[str, float | None, str]] = {}
        self._robots_slots: dict[str, asyncio.Lock] = {}
        self._inflight: dict[tuple[Any, ...], asyncio.Future[tuple[int, dict[str, str], bytes, str, str]]] = {}
        self.coalesced_requests = 0
        self._default_rates: dict[str, float] = {}
        self._rate_adjustments: dict[str, int] = {}
        self._host_successes: dict[str, int] = {}

    @property
    def replay_misses(self) -> int:
        return self.http_recording.misses if self.http_recording else 0

    @property
    def observed_at(self) -> datetime:
        return _HTTP_OBSERVED_AT.get() or datetime.now(timezone.utc)

    @property
    def replay_failures(self) -> int:
        return self.http_recording.failures if self.http_recording else 0

    def _validate_host(self, url: str) -> tuple[str, ...] | None:
        return validate_public_host(url, trusted_proxy=self.replay_mode or self.trusted_proxy)

    def _assert_recordable_url(self, url: str) -> None:
        if self.http_recording and any(
                re.search(r"(?i)(token|authorization|password|secret|api[_-]?key|credential)", name)
                for name, value in urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query, keep_blank_values=True)):
            raise NetworkPolicyError("credential-bearing query parameters cannot be recorded or replayed")

    async def _http_request(self, target: str, *, purpose: str, user_agent: str, cap: int,
                            use_robots: bool, allowed_hosts: set[str] | None, access_profile: str | None,
                            api_headers: dict[str, str] | None,
                            approved_ips: tuple[str, ...] | None) -> tuple[int, dict[str, str], bytes, str]:
        self._assert_recordable_url(target)
        request = {"url": target, "purpose": purpose, "user_agent": user_agent, "max_bytes": cap,
                   "use_robots": use_robots, "access_profile": access_profile,
                   "allowed_hosts": sorted(h.casefold() for h in allowed_hosts) if allowed_hosts is not None else None,
                   "if_modified_since": (api_headers or {}).get("If-Modified-Since"),
                   "retries": self.retries, "redirect_limit": self.redirect_limit,
                   "trusted_proxy": self.trusted_proxy, "timeout": self.timeout}
        if self.replay_mode:
            captured = self.http_recording.load(request)
            _HTTP_OBSERVED_AT.set(datetime.fromisoformat(captured["retrieved_at"]))
            try:
                if any(not _public_ip(ip) for ip in captured["approved_ips"] or []):
                    raise ValueError("non-public recorded address")
                response = captured["response"]
                if response is not None:
                    self._validate_host(canonical_url(response["final_url"]))
            except ValueError:
                self.http_recording._fail("recorded destination violates host policy")
            if captured["outcome"] == "timeout":
                raise asyncio.TimeoutError()
            if captured["outcome"] == "transport_error":
                raise OSError("recorded transport failure")
            return response["status"], response["headers"], response["body"], response["final_url"]
        start = time.monotonic()
        headers = {"User-Agent": user_agent, "Accept-Encoding": "identity", **(api_headers or {})}
        try:
            response = await asyncio.wait_for(
                self.transport.request(target, headers, self.timeout, approved_ips=approved_ips, max_bytes=cap)
                if isinstance(self.transport, UrlLibTransport) else
                self.transport.request(target, headers, self.timeout), timeout=self.timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError, OSError, urllib.error.URLError) as exc:
            if self.http_recording:
                outcome = ("cancelled" if isinstance(exc, asyncio.CancelledError) else
                           "timeout" if isinstance(exc, asyncio.TimeoutError) else "transport_error")
                self.http_recording.save(request, response=None, outcome=outcome, approved_ips=approved_ips,
                                         elapsed_ms=(time.monotonic() - start) * 1000)
            raise
        if self.http_recording:
            self.http_recording.save(request, response=response, outcome="received", approved_ips=approved_ips,
                                     elapsed_ms=(time.monotonic() - start) * 1000)
        _HTTP_OBSERVED_AT.set(datetime.now(timezone.utc))
        return response

    def set_rate_limit(self, host: str, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        normalized = host.casefold()
        self._rates[normalized] = 1.0 / requests_per_second
        self._default_rates[normalized] = 1.0 / requests_per_second

    async def fetch(self, url: str, *, purpose: str = "page", user_agent: str = "SignalpostBot/1.0 (+contact pending)",
                    max_bytes: int | None = None, use_robots: bool = True,
                    allowed_hosts: set[str] | None = None, access_profile: str | None = None,
                    api_headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes, str, str]:
        self.ledger.logical_requests += 1
        if access_profile == "wikidata_sparql_api" and not _wikidata_api_url(url, purpose):
            raise NetworkPolicyError("Wikidata API profile requires the exact documented SPARQL endpoint")
        target = canonical_url(url)
        self._assert_recordable_url(target)
        if self.replay_mode:
            self._validate_host(target)
        if api_headers and (access_profile != "nav_feed_api" or not _nav_api_url(target, purpose)
                or set(api_headers) - {"Authorization", "If-Modified-Since"}
                or any("\r" in value or "\n" in value for value in api_headers.values())):
            raise NetworkPolicyError("API headers are limited to the official NAV feed")
        if self.budget and not await self.budget.reserve_logical_request():
            return 0, {}, b"", target, "budget_exhausted"
        key = (target, purpose, user_agent, max_bytes or self.response_cap, use_robots,
               tuple(sorted(h.casefold() for h in allowed_hosts)) if allowed_hosts is not None else None,
               access_profile, self.trusted_proxy, (api_headers or {}).get("If-Modified-Since"),
               _REQUEST_COMPANY.get() if self.budget and self.budget.config.per_company_physical_limit is not None else None)
        existing = self._inflight.get(key)
        if existing is not None:
            self.coalesced_requests += 1
            return await asyncio.shield(existing)
        future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            result = await self._fetch_uncached(target, purpose=purpose, user_agent=user_agent,
                max_bytes=max_bytes, use_robots=use_robots, allowed_hosts=allowed_hosts,
                access_profile=access_profile, api_headers=api_headers)
            future.set_result(result)
            return result
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
                try:
                    future.exception()
                except BaseException:
                    pass
            raise
        finally:
            self._inflight.pop(key, None)

    async def _fetch_uncached(self, url: str, *, purpose: str, user_agent: str = "SignalpostBot/1.0 (+contact pending)",
                    max_bytes: int | None = None, use_robots: bool = True,
                    allowed_hosts: set[str] | None = None, access_profile: str | None = None,
                    api_headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes, str, str]:
        target = canonical_url(url)
        if allowed_hosts is not None and (urllib.parse.urlsplit(target).hostname or "").casefold() not in {h.casefold() for h in allowed_hosts}:
            raise NetworkPolicyError("destination host is outside the caller's source allowlist")
        if access_profile not in {None, "brreg_structured_api", "brreg_document_api", "nav_feed_api", "wikidata_sparql_api"}:
            raise NetworkPolicyError("unknown source access profile")
        if access_profile == "wikidata_sparql_api":
            if not _wikidata_api_url(url, purpose):
                raise NetworkPolicyError("Wikidata API profile requires the exact documented SPARQL endpoint")
            use_robots = False
        if access_profile == "nav_feed_api" and not _nav_api_url(target, purpose):
            raise NetworkPolicyError("NAV API profile requires an exact official feed endpoint")
        if access_profile == "brreg_structured_api" and not _brreg_structured_api_url(target, purpose):
            raise NetworkPolicyError("BRREG structured API profile is limited to documented BRREG endpoints")
        if access_profile == "brreg_document_api" and not _brreg_document_api_url(target, purpose):
            raise NetworkPolicyError("BRREG document profile requires an exact official filing-copy URL")
        self._assert_proxy_route(target)
        if use_robots and purpose != "robots":
            robots_state, delay = await self.robots_decision(target, user_agent, allowed_hosts=allowed_hosts)
            if robots_state == "disallowed":
                return 0, {}, b"", target, "robots_disallowed"
            if robots_state == "policy_skip":
                return 0, {}, b"", target, "robots_policy_skip"
            if robots_state == "budget_skipped":
                return 0, {}, b"", target, "budget_exhausted"
            if robots_state == "unusable":
                return 0, {}, b"", target, "robots_unusable"
            if robots_state == "unreachable" and access_profile not in {"brreg_structured_api", "brreg_document_api", "nav_feed_api"}:
                return 0, {}, b"", target, "robots_unreachable"
        else:
            delay = None
        cap = max_bytes or self.response_cap
        redirects_seen: set[str] = set()
        for hop in range(self.redirect_limit + 1):
            if target in redirects_seen:
                return 0, {}, b"", target, "redirect_loop"
            redirects_seen.add(target)
            approved_ips = self._validate_host(target)
            # Prefer IPv4 on hosts where IPv6 is unreachable. Each failed
            # address consumes a separately paced, budgeted, logged retry;
            # the transport must not fan out below the request ledger.
            ordered_ips = tuple(sorted(approved_ips or (), key=lambda ip: (ipaddress.ip_address(ip).version != 4, ip)))
            address_index = 0
            parsed = urllib.parse.urlsplit(target)
            slot = self._host_slots.setdefault(parsed.hostname or "", _AdaptiveHostLimit(
                self.budget.config.per_host_concurrency if self.budget else 2))
            async with self._global_slots, slot:
                for attempt in range(self.retries + 1):
                    await self._pace(target, delay or 0.0)
                    org_match = re.search(r"(?:enheter|regnskap|konsernstruktur|kopi)/(\d{9})", urllib.parse.urlsplit(target).path)
                    if org_match is None:
                        query_org = urllib.parse.parse_qs(urllib.parse.urlsplit(target).query).get("overordnetEnhet", [])
                        if len(query_org) == 1 and re.fullmatch(r"\d{9}", query_org[0]):
                            org_match = re.match(r"(\d{9})", query_org[0])
                    if self.budget and not await self.budget.reserve_request(
                            required=access_profile == "brreg_structured_api",
                            company=org_match.group(1) if org_match else _REQUEST_COMPANY.get(),
                            host=urllib.parse.urlsplit(target).hostname):
                        return 0, {}, b"", target, "budget_exhausted"
                    start = time.monotonic()
                    status = None
                    body = b""
                    headers: dict[str, str] = {}
                    outcome = "transport_error"
                    response_recorded = False
                    try:
                        status, headers, body, _ = await self._http_request(
                            target, purpose=purpose, user_agent=user_agent, cap=cap, use_robots=use_robots,
                            allowed_hosts=allowed_hosts, access_profile=access_profile, api_headers=api_headers,
                            approved_ips=(ordered_ips[address_index % len(ordered_ips)],) if ordered_ips else None)
                        self._record(target, purpose, status, len(body), start, "received")
                        response_recorded = True
                        location = headers.get("Location") or headers.get("location")
                        if status in {301, 302, 303, 307, 308} and location:
                            self.ledger.entries[-1].redirect_location = canonical_url(urllib.parse.urljoin(target, location))
                            if hop >= self.redirect_limit:
                                return status, headers, b"", target, "redirect_limit"
                            target = canonical_url(urllib.parse.urljoin(target, location))
                            if allowed_hosts is not None and (urllib.parse.urlsplit(target).hostname or "").casefold() not in {h.casefold() for h in allowed_hosts}:
                                raise NetworkPolicyError("redirect host is outside the caller's source allowlist")
                            if access_profile == "brreg_structured_api" and not _brreg_structured_api_url(target, purpose):
                                raise NetworkPolicyError("BRREG structured API profile is limited to documented BRREG endpoints")
                            if access_profile == "brreg_document_api" and (
                                    not _brreg_document_api_url(target, purpose) or target != canonical_url(url)):
                                raise NetworkPolicyError("BRREG document redirect left its exact permitted endpoint")
                            if access_profile == "nav_feed_api" and target != canonical_url(url):
                                raise NetworkPolicyError("NAV API redirects are not permitted")
                            if access_profile == "wikidata_sparql_api" and target != canonical_url(url):
                                raise NetworkPolicyError("Wikidata API redirects are not permitted")
                            self._assert_proxy_route(target)
                            self._validate_host(target)
                            if use_robots and purpose != "robots":
                                robots_state, delay = await self.robots_decision(target, user_agent, allowed_hosts=allowed_hosts)
                                if robots_state == "disallowed":
                                    return 0, {}, b"", target, "robots_disallowed"
                                if robots_state == "policy_skip":
                                    return 0, {}, b"", target, "robots_policy_skip"
                                if robots_state == "budget_skipped":
                                    return 0, {}, b"", target, "budget_exhausted"
                                if robots_state == "unusable":
                                    return 0, {}, b"", target, "robots_unusable"
                                if robots_state == "unreachable" and access_profile not in {"brreg_structured_api", "brreg_document_api", "nav_feed_api"}:
                                    return 0, {}, b"", target, "robots_unreachable"
                            break
                        if status in {429, 503}:
                            await self._adapt_host_rate(parsed.hostname or "")
                        if status in {429, 503} and attempt < self.retries:
                            retry_after = headers.get("Retry-After") or headers.get("retry-after")
                            try:
                                wait_seconds = min(60.0, max(0.0, float(retry_after))) if retry_after else min(1.0 * (attempt + 1), 5.0)
                            except ValueError:
                                try:
                                    retry_at = parsedate_to_datetime(retry_after)
                                    wait_seconds = min(60.0, max(0.0, retry_at.timestamp() - time.time()))
                                except (TypeError, ValueError, OverflowError):
                                    wait_seconds = min(1.0 * (attempt + 1), 5.0)
                            if not self.replay_mode:
                                await asyncio.sleep(wait_seconds)
                            continue
                        if len(body) > cap:
                            return status, headers, b"", target, "response_too_large"
                        encoding = (headers.get("Content-Encoding") or headers.get("content-encoding") or "").lower()
                        if encoding == "gzip":
                            try:
                                decompressor = gzip.GzipFile(fileobj=__import__("io").BytesIO(body))
                                body = decompressor.read(cap + 1)
                            except (OSError, EOFError):
                                return status, headers, b"", target, "invalid_compression"
                            try:
                                compressed_size = int(headers.get("Content-Length") or headers.get("content-length") or len(body))
                            except ValueError:
                                compressed_size = len(body)
                            if len(body) > cap or len(body) > max(1, compressed_size) * 100:
                                return status, headers, b"", target, "decompression_limit"
                        elif encoding not in {"", "identity"}:
                            return status, headers, b"", target, "unsupported_encoding"
                        if 200 <= status < 400:
                            await self._recover_host_rate(parsed.hostname or "")
                        return status, headers, body, target, classify_response(status, headers, body)
                    except asyncio.CancelledError:
                        if not response_recorded:
                            self._record(target, purpose, status, len(body), start, "cancelled")
                        raise
                    except (asyncio.TimeoutError, OSError, urllib.error.URLError) as exc:
                        outcome = "timeout" if isinstance(exc, asyncio.TimeoutError) else "transport_error"
                        address_index += 1
                        self._record(target, purpose, status, len(body), start, outcome)
                        if attempt >= self.retries:
                            return status or 0, headers, b"", target, outcome
                        if not self.replay_mode:
                            await asyncio.sleep(min(0.1 * (attempt + 1), 0.5))
                else:
                    return 0, {}, b"", target, "transport_error"
                # Redirect: continue outer hop loop using the newly checked target.
                if status in {301, 302, 303, 307, 308}:
                    continue
        return 0, {}, b"", target, "redirect_limit"

    async def _adapt_host_rate(self, host: str) -> None:
        host = host.casefold()
        self._rate_adjustments[host] = self._rate_adjustments.get(host, 0) + 1
        self._rates[host] = max(self._rates.get(host, 0.0), self._default_rates.get(host, 0.0)) * 2
        limiter = self._host_slots.get(host)
        if limiter:
            await limiter.reduce()

    async def _recover_host_rate(self, host: str) -> None:
        host = host.casefold()
        self._host_successes[host] = self._host_successes.get(host, 0) + 1
        if self._rate_adjustments.get(host, 0) > 0 and self._host_successes[host] >= 5:
            self._rate_adjustments[host] -= 1
            self._rates[host] = max(self._default_rates.get(host, 0.0), self._rates.get(host, 0.0) / 2)
            self._host_successes[host] = 0
            limiter = self._host_slots.get(host)
            if limiter:
                await limiter.recover(self.budget.config.per_host_concurrency if self.budget else 2)

    def _assert_proxy_route(self, url: str) -> None:
        if self.replay_mode or not self.trusted_proxy:
            return
        parsed = urllib.parse.urlsplit(url)
        proxies = urllib.request.getproxies()
        if not self.proxy_url and not proxies.get(parsed.scheme):
            raise NetworkPolicyError("trusted-proxy mode has no configured proxy for this scheme")
        # urllib honors NO_PROXY by connecting directly. Refuse that fallback in
        # evaluator-proxy mode so the proxy remains the sole egress authority.
        if parsed.hostname and urllib.request.proxy_bypass(parsed.hostname):
            raise NetworkPolicyError("trusted-proxy destination matches NO_PROXY; direct fallback is forbidden")

    async def robots_allowed(self, url: str, user_agent: str, *, allowed_hosts: set[str] | None = None) -> tuple[bool, float | None]:
        state, delay = await self.robots_decision(url, user_agent, allowed_hosts=allowed_hosts)
        return state == "allowed", delay

    async def robots_decision(self, url: str, user_agent: str, *, allowed_hosts: set[str] | None = None) -> tuple[str, float | None]:
        """Return allowed, disallowed, or unreachable without conflating policy and transport."""
        parsed = urllib.parse.urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        lock = self._robots_slots.setdefault(origin, asyncio.Lock())
        async with lock:
            cached = self._robots.get(origin)
            if cached:
                rules, delay, state = cached
                if state in {"unreachable", "unusable", "policy_skip", "budget_skipped"}:
                    return state, delay
                request_path = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
                return ("disallowed" if _robots_disallows(rules, request_path, user_agent) else "allowed"), delay
            robots_url = origin + "/robots.txt"
            status, headers, body, final_url, outcome = await self.fetch(robots_url, purpose="robots", user_agent=user_agent,
                                                                         use_robots=False, max_bytes=256 * 1024, allowed_hosts=allowed_hosts)
            delay = None
            if outcome in {"timeout", "transport_error"} or status >= 500:
                self._robots[origin] = ("", None, "unreachable")
                return "unreachable", None
            if outcome == "budget_exhausted":
                # A company-specific budget denial says nothing about robots
                # on this origin. Do not poison another company's permission.
                return "budget_skipped", None
            if outcome in {"response_too_large", "decompression_limit", "unsupported_encoding",
                           "waf_challenge", "soft_404", "redirect_limit"}:
                self._robots[origin] = ("", None, "unusable")
                return "unusable", None
            if 400 <= status < 500:
                rules = ""
            elif 200 <= status < 300:
                rules = body.decode("utf-8", "replace")
                delay_values = [float(m.group(1)) for m in re.finditer(r"(?im)^\s*crawl-delay\s*:\s*([0-9.]+)", rules)]
                delay = max(delay_values, default=None)
                if delay is not None and delay > 60:
                    self._robots[origin] = (rules, delay, "policy_skip")
                    return "policy_skip", delay
            else:
                rules = ""
            request_path = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
            state = "disallowed" if _robots_disallows(rules, request_path, user_agent) else "allowed"
            self._robots[origin] = (rules, delay, "allowed")
            # A redirected /robots.txt response is also an observation of the
            # destination origin's exact robots resource. Reuse those bytes
            # when a later page redirects there, rather than spending another
            # request. Never infer permission for an alias not actually fetched.
            final_parts = urllib.parse.urlsplit(final_url)
            final_origin = f"{final_parts.scheme}://{final_parts.netloc}"
            if (200 <= status < 300 and outcome == "ok"
                    and final_parts.path == "/robots.txt" and not final_parts.query
                    and not final_parts.fragment and final_origin != origin):
                self._robots.setdefault(final_origin, (rules, delay, "allowed"))
            return state, delay

    async def _pace(self, url: str, minimum: float = 0.0) -> None:
        if self.replay_mode:
            return
        host = (urllib.parse.urlsplit(url).hostname or "").casefold()
        # Serialize slot reservation as well as the wait. Without holding this
        # host lock, simultaneous callers wake together and violate the rate.
        lock = self._rate_slots.setdefault(host, asyncio.Lock())
        async with lock:
            delay = max(minimum, self._rates.get(host, 0.0))
            elapsed = time.monotonic() - self._last_request.get(host, 0)
            if elapsed < delay:
                await asyncio.sleep(delay - elapsed)
            self._last_request[host] = time.monotonic()

    def _record(self, url: str, purpose: str, status: int | None, size: int, start: float, outcome: str) -> None:
        self.ledger.entries.append(LedgerEntry(str(uuid.uuid4()), url, purpose, status, size, (time.monotonic() - start) * 1000, outcome))


def _robots_disallows(text: str, path: str, user_agent: str) -> bool:
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    rules_started = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key.casefold() == "user-agent":
            if current is None or rules_started:
                current = {"agents": [], "rules": []}
                groups.append(current)
                rules_started = False
            current["agents"].append(value.casefold())
        elif current is not None and key.casefold() in {"allow", "disallow"}:
            current["rules"].append((key.casefold(), value))
            rules_started = True
    ua = user_agent.casefold()
    matched_groups = [group for group in groups
                      if any(agent == "*" or agent in ua for agent in group["agents"])]
    if not matched_groups:
        return False
    specificity = max((len(agent) for group in matched_groups for agent in group["agents"]
                       if agent != "*" and agent in ua), default=0)
    rules = [rule for group in matched_groups
             if any((specificity == 0 and agent == "*") or (agent != "*" and agent in ua and len(agent) == specificity)
                    for agent in group["agents"])
             for rule in group["rules"]]
    normalized_path = _robots_percent_normalize(path)
    decisions: list[tuple[int, bool]] = []
    for directive, raw_pattern in rules:
        if not raw_pattern:
            continue
        pattern = _robots_percent_normalize(raw_pattern)
        anchored = pattern.endswith("$")
        if anchored:
            pattern = pattern[:-1]
        pieces = pattern.split("*")
        expression = "^" + ".*".join(re.escape(piece) for piece in pieces)
        if anchored:
            expression += "$"
        if re.search(expression, normalized_path):
            literal_bytes = len("".join(pieces).encode("utf-8"))
            decisions.append((literal_bytes, directive == "allow"))
    return bool(decisions) and not max(decisions, key=lambda item: (item[0], item[1]))[1]


def _robots_percent_normalize(value: str) -> str:
    """Normalize percent escapes per robots matching while retaining reserved bytes."""
    def escape(match: re.Match[str]) -> str:
        byte = int(match.group(1), 16)
        char = chr(byte)
        if char.isascii() and (char.isalnum() or char in "-._~"):
            return char
        return f"%{byte:02X}"
    value = re.sub(r"%([0-9a-fA-F]{2})", escape, value)
    return urllib.parse.quote(value, safe="/%*-$!~'();:@&=+,?%")


class _RobotsMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.directives: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "meta":
            return
        values = {key.casefold(): (value or "") for key, value in attrs}
        if values.get("name", "").casefold() in {"robots", "signalpostbot"}:
            self.directives.update(part.strip().casefold() for part in values.get("content", "").split(","))


def robots_directives(headers: dict[str, str], html: bytes | str = b"", user_agent: str = "SignalpostBot") -> set[str]:
    """Return applicable noindex/nofollow/noarchive directives from headers and HTML."""
    result: set[str] = set()
    for name, value in headers.items():
        if name.casefold() != "x-robots-tag":
            continue
        segments = value.split(":", 1)
        if len(segments) == 2 and (segments[0].strip() in {"*", user_agent}):
            result.update(part.strip().casefold() for part in segments[1].split(","))
        elif len(segments) == 1:
            result.update(part.strip().casefold() for part in value.split(","))
    parser = _RobotsMetaParser()
    parser.feed(html.decode("utf-8", "replace") if isinstance(html, bytes) else html)
    result.update(parser.directives)
    return result & {"noindex", "nofollow", "noarchive", "none", "all"}


# Use the Public Suffix List bundled with the pinned tldextract distribution.
# No user cache, network fetch, or developer-specific state is part of identity.
_EXTRACT = TLDExtract(cache_dir=None, suffix_list_urls=())


def registered_domain(host: str) -> str | None:
    """Return registrable domain using the bundled PSL snapshot; IPs have no domain."""
    try:
        ipaddress.ip_address(host.strip("[]"))
        return None
    except ValueError:
        pass
    extracted = _EXTRACT(host)
    return f"{extracted.domain}.{extracted.suffix}" if extracted.domain and extracted.suffix else None


class StructuredLogger:
    SECRET = re.compile(r"(?i)(api[_-]?key|token|password|secret|authorization)([\"'\s:=]+)([^\"',}]+)")

    @classmethod
    def _redact_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: "[REDACTED]" if re.search(r"(?i)(api[_-]?key|token|password|secret|authorization)", str(key)) else cls._redact_fields(item)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [cls._redact_fields(item) for item in value]
        if isinstance(value, str):
            return re.sub(r"(?i)bearer\s+[^\s,]+", "Bearer [REDACTED]", value)
        return value

    @classmethod
    def emit(cls, event: str, **fields: Any) -> str:
        payload = cls._redact_fields({"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **fields})
        safe = cls.SECRET.sub(r"\1\2[REDACTED]", json.dumps(payload, default=str))
        return safe
