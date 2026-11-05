from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
from collections import ChainMap
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Awaitable, Callable, Iterable, TypeVar

from .models import Envelope

_FINANCIAL_REQUEST = ContextVar("financial_request", default=False)


@contextmanager
def financial_request_scope():
    token = _FINANCIAL_REQUEST.set(True)
    try:
        yield
    finally:
        _FINANCIAL_REQUEST.reset(token)


def _checkpoint_encode(value: object) -> object:
    from pydantic import BaseModel
    from .models import PublicState
    if isinstance(value, PublicState):
        return {"$state": value.value}
    if isinstance(value, BaseModel):
        return {"$model": type(value).__name__, "value": value.model_dump(mode="json")}
    if is_dataclass(value) and not isinstance(value, type):
        return {"$record": type(value).__name__, "value": {
            field.name: _checkpoint_encode(getattr(value, field.name)) for field in fields(value)}}
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, (set, tuple)):
        return {"$collection": type(value).__name__, "value": [_checkpoint_encode(item) for item in value]}
    if isinstance(value, list):
        return [_checkpoint_encode(item) for item in value]
    if isinstance(value, dict):
        return {"$mapping": [[key, _checkpoint_encode(item)] for key, item in value.items()]}
    return value


def _checkpoint_decode(value: object) -> object:
    from . import models
    from .brreg import BrregResult
    from .websites import PageRecord, WebsiteResearchResult
    if isinstance(value, list):
        return [_checkpoint_decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "$mapping" in value:
        return {key: _checkpoint_decode(item) for key, item in value["$mapping"]}
    if "$model" in value:
        allowed = {name: getattr(models, name) for name in ("Claim", "Evidence", "SourceSnapshot", "RunError")}
        return allowed[value["$model"]].model_validate(value["value"])
    if "$state" in value:
        return models.PublicState(value["$state"])
    if "$record" in value:
        allowed = {cls.__name__: cls for cls in (BrregResult, PageRecord, WebsiteResearchResult)}
        return allowed[value["$record"]](**_checkpoint_decode(value["value"]))
    if "$bytes" in value:
        return base64.b64decode(value["$bytes"])
    if "$datetime" in value:
        return datetime.fromisoformat(value["$datetime"])
    if "$decimal" in value:
        return Decimal(value["$decimal"])
    if "$collection" in value:
        return {"set": set, "tuple": tuple}[value["$collection"]](_checkpoint_decode(value["value"]))
    return {key: _checkpoint_decode(item) for key, item in value.items()}


@dataclass(frozen=True)
class RunBudget:
    hard_seconds: float = 1800
    soft_seconds: float = 1350
    completion_reserve_seconds: float = 300
    physical_request_limit: int = 1000
    logical_request_limit: int | None = None
    paid_cost_limit: Decimal = Decimal("0")
    global_http_concurrency: int = 32
    per_host_concurrency: int = 2
    per_company_physical_limit: int | None = None
    per_host_physical_limit: int | None = None
    nav_seconds: float = 360
    financial_seconds: float = 180
    financial_requests_per_company: int = 1
    wikidata_seconds: float = 12
    website_seconds: float = 480
    ocr_seconds: float = 900
    ocr_budget_share: float = 0.65

    def __post_init__(self) -> None:
        if (not all(math.isfinite(value) for value in
                    (self.hard_seconds, self.soft_seconds, self.completion_reserve_seconds))
                or self.hard_seconds <= 0 or self.soft_seconds < 0 or self.completion_reserve_seconds < 0):
            raise ValueError("budget durations must be non-negative and hard_seconds positive")
        if self.soft_seconds + self.completion_reserve_seconds > self.hard_seconds:
            raise ValueError("soft deadline plus completion reserve exceeds hard deadline")
        if (self.physical_request_limit < 0 or (self.logical_request_limit is not None and self.logical_request_limit < 0)
                or (self.per_company_physical_limit is not None and self.per_company_physical_limit < 0)
                or (self.per_host_physical_limit is not None and self.per_host_physical_limit < 0)
                or not self.paid_cost_limit.is_finite() or self.paid_cost_limit < 0):
            raise ValueError("request and cost limits must be non-negative")
        if min(self.global_http_concurrency, self.per_host_concurrency) < 1:
            raise ValueError("global and per-host concurrency limits must be positive")
        if (not all(math.isfinite(value) and value >= 0 for value in
                    (self.nav_seconds, self.financial_seconds, self.wikidata_seconds, self.website_seconds, self.ocr_seconds))
                or self.financial_requests_per_company < 1
                or not math.isfinite(self.ocr_budget_share) or not 0 <= self.ocr_budget_share <= 1):
            raise ValueError("phase durations must be finite/non-negative and OCR share between zero and one")

    @classmethod
    def from_mapping(cls, values: dict[str, object] | None = None, *, environ: dict[str, str] | None = None, batch_rows: int = 0) -> "RunBudget":
        values = values or {}
        environ = environ or os.environ
        def value(key: str, env_key: str, default: object) -> object:
            return environ.get(env_key, values.get(key, default))
        return cls(
            hard_seconds=float(value("hard_seconds", "SIGNALPOST_HARD_SECONDS", 1800)),
            soft_seconds=float(value("soft_seconds", "SIGNALPOST_SOFT_SECONDS", 1350)),
            completion_reserve_seconds=float(value("completion_reserve_seconds", "SIGNALPOST_COMPLETION_RESERVE_SECONDS", 300)),
            physical_request_limit=int(value("physical_request_limit", "SIGNALPOST_PHYSICAL_REQUEST_LIMIT", 12 * batch_rows + 1000)),
            logical_request_limit=(int(environ["SIGNALPOST_LOGICAL_REQUEST_LIMIT"])
                if "SIGNALPOST_LOGICAL_REQUEST_LIMIT" in environ else
                int(values["logical_request_limit"]) if "logical_request_limit" in values else None),
            paid_cost_limit=Decimal(str(value("paid_cost_limit", "SIGNALPOST_PAID_COST_LIMIT", "0"))),
            global_http_concurrency=int(value("global_http_concurrency", "SIGNALPOST_GLOBAL_HTTP_CONCURRENCY", 32)),
            per_host_concurrency=int(value("per_host_concurrency", "SIGNALPOST_PER_HOST_CONCURRENCY", 2)),
            per_company_physical_limit=(int(environ["SIGNALPOST_PER_COMPANY_PHYSICAL_LIMIT"])
                if "SIGNALPOST_PER_COMPANY_PHYSICAL_LIMIT" in environ else
                int(values["per_company_physical_limit"]) if "per_company_physical_limit" in values else None),
            per_host_physical_limit=(int(environ["SIGNALPOST_PER_HOST_PHYSICAL_LIMIT"])
                if "SIGNALPOST_PER_HOST_PHYSICAL_LIMIT" in environ else
                int(values["per_host_physical_limit"]) if "per_host_physical_limit" in values else None),
            nav_seconds=float(value("nav_seconds", "SIGNALPOST_NAV_SECONDS", 360)),
            financial_seconds=float(value("financial_seconds", "SIGNALPOST_FINANCIAL_SECONDS", 180)),
            financial_requests_per_company=int(value("financial_requests_per_company", "SIGNALPOST_FINANCIAL_REQUESTS_PER_COMPANY", 1)),
            wikidata_seconds=float(value("wikidata_seconds", "SIGNALPOST_WIKIDATA_SECONDS", 12)),
            website_seconds=float(value("website_seconds", "SIGNALPOST_WEBSITE_SECONDS", 480)),
            ocr_seconds=float(value("ocr_seconds", "SIGNALPOST_OCR_SECONDS", 900)),
            ocr_budget_share=float(value("ocr_budget_share", "SIGNALPOST_OCR_BUDGET_SHARE", 0.65)),
        )


class Budget:
    def __init__(self, config: RunBudget, *, monotonic: Callable[[], float] = time.monotonic,
                 started_at: float | None = None):
        self.config = config
        self._monotonic = monotonic
        self.started = monotonic() if started_at is None else started_at
        self._max_elapsed = 0.0
        self._request_count = 0
        self.financial_request_reserve = 0
        self.financial_logical_reserve = 0
        self._logical_request_count = 0
        self._cost = Decimal("0")
        self._company_counts: dict[str, int] = {}
        self._host_counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    @property
    def soft_expired(self) -> bool:
        return self.elapsed >= self.config.soft_seconds

    @property
    def hard_expired(self) -> bool:
        return self.elapsed >= self.config.hard_seconds

    @property
    def elapsed(self) -> float:
        # A monotonic source makes wall-clock rollback irrelevant to the deadline.
        observed = max(0.0, self._monotonic() - self.started)
        self._max_elapsed = max(self._max_elapsed, observed)
        return self._max_elapsed

    @property
    def reserve_active(self) -> bool:
        return self.config.hard_seconds - self.elapsed <= self.config.completion_reserve_seconds

    async def reserve_request(self, cost: Decimal = Decimal("0"), *, required: bool = False,
                              company: str | None = None, host: str | None = None) -> bool:
        cost = Decimal(str(cost))
        if not cost.is_finite() or cost < 0:
            raise ValueError("request cost must be finite and non-negative")
        async with self._lock:
            if self.hard_expired or self.reserve_active:
                return False
            if self.soft_expired and not required:
                return False
            if self._request_count + 1 > self.config.physical_request_limit:
                return False
            if (not _FINANCIAL_REQUEST.get()
                    and self._request_count + 1 > self.config.physical_request_limit - self.financial_request_reserve):
                return False
            if self._cost + cost > self.config.paid_cost_limit:
                return False
            company_key = company.casefold() if company else None
            host_key = host.casefold() if host else None
            if (company_key and self.config.per_company_physical_limit is not None
                    and self._company_counts.get(company_key, 0) >= self.config.per_company_physical_limit
                        - (self.config.financial_requests_per_company if self.financial_request_reserve
                            and not _FINANCIAL_REQUEST.get() else 0)):
                return False
            if (host_key and self.config.per_host_physical_limit is not None
                    and self._host_counts.get(host_key, 0) >= self.config.per_host_physical_limit
                        - (self.financial_request_reserve if host_key == "data.brreg.no"
                            and not _FINANCIAL_REQUEST.get() else 0)):
                return False
            self._request_count += 1
            if _FINANCIAL_REQUEST.get():
                self.financial_request_reserve = max(0, self.financial_request_reserve - 1)
            self._cost += cost
            if company_key:
                self._company_counts[company_key] = self._company_counts.get(company_key, 0) + 1
            if host_key:
                self._host_counts[host_key] = self._host_counts.get(host_key, 0) + 1
            return True

    async def reserve_logical_request(self) -> bool:
        async with self._lock:
            if self.hard_expired or self.reserve_active:
                return False
            if self.config.logical_request_limit is not None and self._logical_request_count + 1 > self.config.logical_request_limit:
                return False
            if (not _FINANCIAL_REQUEST.get() and self.config.logical_request_limit is not None
                    and self._logical_request_count + 1 > self.config.logical_request_limit - self.financial_logical_reserve):
                return False
            self._logical_request_count += 1
            if _FINANCIAL_REQUEST.get():
                self.financial_logical_reserve = max(0, self.financial_logical_reserve - 1)
            return True

    def host_request_count(self, host: str) -> int:
        return self._host_counts.get(host.casefold(), 0)

    def company_request_count(self, company: str) -> int:
        return self._company_counts.get(company.casefold(), 0)

    @property
    def requests_by_company(self) -> dict[str, int]:
        return dict(sorted(self._company_counts.items()))

    @property
    def physical_requests(self) -> int:
        return self._request_count

    @property
    def logical_requests(self) -> int:
        return self._logical_request_count

    @property
    def physical_requests_remaining(self) -> int:
        return max(0, self.config.physical_request_limit - self._request_count)

    @property
    def logical_requests_remaining(self) -> int | None:
        if self.config.logical_request_limit is None:
            return None
        return max(0, self.config.logical_request_limit - self._logical_request_count)

    @property
    def cost(self) -> Decimal:
        return self._cost


def _envelope_identity_graph(envelope: Envelope) -> dict:
    snapshots = {}
    for item in envelope.source_snapshots:
        signature = item.model_dump(mode="json")
        signature.pop("retrieved_at", None)
        snapshots[item.source_id] = signature
    return {"evidence": {item.evidence_id: item.model_dump(mode="json") for item in envelope.evidence},
            "snapshots": snapshots}


class _EnvelopeIdentityIndex:
    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.references: dict[str, dict[str, tuple[dict, int]]] = {"evidence": {}, "snapshots": {}}

    def prepare(self, envelopes: Iterable[Envelope]) -> tuple[list[Envelope], dict[int, dict]]:
        from .models import validate_batch_publication_graph
        checked = validate_batch_publication_graph(list(envelopes))
        if len({item.row_number for item in checked}) != len(checked):
            raise ValueError("duplicate row_number in checkpoint update")
        changes = {item.row_number: _envelope_identity_graph(item) for item in checked}
        for kind, references in self.references.items():
            removed: dict[str, int] = {}
            for row_number in changes:
                for identifier in self.rows.get(row_number, {}).get(kind, {}):
                    removed[identifier] = removed.get(identifier, 0) + 1
            for graph in changes.values():
                for identifier, signature in graph[kind].items():
                    previous = references.get(identifier)
                    if (previous is not None and previous[1] > removed.get(identifier, 0)
                            and previous[0] != signature):
                        raise ValueError(f"conflicting {kind} identifier across envelopes: {identifier}")
        return checked, changes

    def apply(self, changes: dict[int, dict]) -> None:
        for kind, references in self.references.items():
            for row_number in changes:
                for identifier in self.rows.get(row_number, {}).get(kind, {}):
                    signature, count = references[identifier]
                    if count == 1:
                        del references[identifier]
                    else:
                        references[identifier] = signature, count - 1
            for graph in changes.values():
                for identifier, signature in graph[kind].items():
                    previous = references.get(identifier)
                    references[identifier] = signature, (previous[1] if previous else 0) + 1
        self.rows.update(changes)


class CheckpointStore:
    def __init__(self, path: str | Path):
        self._identity_graphs = None
        self._identity_index: _EnvelopeIdentityIndex | None = None
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS envelopes (row_number INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS run_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS shells (row_number INTEGER PRIMARY KEY, input_ref TEXT, organisation_number TEXT, execution_state TEXT)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS phase_results (phase TEXT, company TEXT, payload TEXT NOT NULL, PRIMARY KEY(phase,company))")
        self.connection.execute("CREATE TABLE IF NOT EXISTS phase_status (phase TEXT, company TEXT, payload TEXT NOT NULL, PRIMARY KEY(phase,company))")
        self.connection.commit()

    def save_phase_status(self, phase: str, company: str, state: str, seconds: float = 0.0,
                          *, reason: str | None = None, traceback_sha256: str | None = None) -> None:
        """Commit progress independently of later phase or process failures."""
        status = state if state in {"failed", "deadline_skipped"} else "ran" if state == "completed" else "skipped"
        if reason is None and state != "completed":
            reason = "source_reported_failure" if state == "failed" else state
        payload = dict(status=status, outcome=state, seconds=max(0.0, seconds),
                       ran=state in {"completed", "failed"}, skipped=status == "skipped",
                       deadline_skipped=status == "deadline_skipped", failed=status == "failed",
                       reason=reason, traceback_sha256=traceback_sha256)
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO phase_status VALUES (?,?,?)",
                                    (phase, company, json.dumps(payload)))

    def phase_statuses(self, phase: str) -> dict[str, dict]:
        return {company: json.loads(payload) for company, payload in self.connection.execute(
            "SELECT company,payload FROM phase_status WHERE phase=?", (phase,))}

    def phase_status(self, phase: str, company: str) -> dict | None:
        row = self.connection.execute("SELECT payload FROM phase_status WHERE phase=? AND company=?",
                                      (phase, company)).fetchone()
        return json.loads(row[0]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.connection.execute("INSERT OR REPLACE INTO run_meta(key,value) VALUES (?,?)", (key, value))
        self.connection.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM run_meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else None

    def terminalized(self) -> dict[int, Envelope]:
        rows = self.connection.execute("SELECT e.row_number,e.payload FROM envelopes e JOIN shells s USING(row_number) WHERE s.execution_state='terminalized'")
        return {int(row): Envelope.model_validate_json(payload) for row, payload in rows}

    def envelopes_for_state(self, state: str) -> dict[int, Envelope]:
        if state not in {"pending", "baseline_done", "terminalized"}:
            raise ValueError("invalid internal row state")
        rows = self.connection.execute("SELECT e.row_number,e.payload FROM envelopes e JOIN shells s USING(row_number) WHERE s.execution_state=?",
                                       (state,))
        return {int(row): Envelope.model_validate_json(payload) for row, payload in rows}

    def set_shell_state(self, row_number: int, state: str) -> None:
        if state not in {"pending", "baseline_done", "terminalized"}:
            raise ValueError("invalid internal row state")
        self.connection.execute("UPDATE shells SET execution_state=? WHERE row_number=?", (state, row_number))
        self.connection.commit()

    def shell_states(self) -> dict[int, str]:
        return {int(row): str(state) for row, state in self.connection.execute(
            "SELECT row_number,execution_state FROM shells ORDER BY row_number")}

    def put(self, envelope: Envelope) -> None:
        identity_index = self._get_identity_index()
        checked, changes = identity_index.prepare([envelope])
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO envelopes(row_number,payload) VALUES (?,?)",
                                    (checked[0].row_number, checked[0].model_dump_json()))
        identity_index.apply(changes)

    def _get_identity_index(self) -> _EnvelopeIdentityIndex:
        if self._identity_index is None:
            identity_index = _EnvelopeIdentityIndex()
            for payload, in self.connection.execute("SELECT payload FROM envelopes"):
                envelope = Envelope.model_validate_json(payload)
                _, changes = identity_index.prepare([envelope])
                identity_index.apply(changes)
            self._identity_index = identity_index
            self._identity_graphs = identity_index.rows
        return self._identity_index

    def validate_phase_update(self, envelopes: Iterable[Envelope]) -> Mapping[int, dict]:
        """Validate without mutation and return a read-only combined row graph view."""
        identity_index = self._get_identity_index()
        _, changes = identity_index.prepare(envelopes)
        return MappingProxyType(ChainMap(changes, identity_index.rows))

    def phase_results(self, phase: str) -> dict[str, object]:
        return {company: _checkpoint_decode(json.loads(payload)) for company, payload in
                self.connection.execute("SELECT company,payload FROM phase_results WHERE phase=?", (phase,))}

    def save_phase(self, phase: str, company: str, result: object,
                   envelopes: Iterable[Envelope] = ()) -> None:
        identity_index = self._get_identity_index()
        envelopes, changes = identity_index.prepare(envelopes)
        payload = json.dumps(_checkpoint_encode(result), ensure_ascii=False)
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO phase_results VALUES (?,?,?)", (phase, company, payload))
            for envelope in envelopes:
                self.connection.execute("INSERT OR REPLACE INTO envelopes VALUES (?,?)",
                                        (envelope.row_number, envelope.model_dump_json()))
                self.connection.execute("UPDATE shells SET execution_state='baseline_done' WHERE row_number=?",
                                        (envelope.row_number,))
        identity_index.apply(changes)

    def rows(self) -> list[Envelope]:
        return [Envelope.model_validate_json(row[0]) for row in self.connection.execute("SELECT payload FROM envelopes ORDER BY row_number")]

    def close(self) -> None:
        self.connection.close()


T = TypeVar("T")


class OpportunityDeferred(Exception):
    """A valid scheduler decision to skip work after a budget gate."""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class OpportunityFailed(Exception):
    """An isolated work-item failure with a caller-built terminal result."""
    def __init__(self, result: object):
        super().__init__("opportunity failed")
        self.result = result


@dataclass(frozen=True)
class Opportunity:
    """One permitted unit of work in a global pass."""
    key: str
    pass_name: str
    company: str
    expected_company_family_gain: float = 0.0
    expected_atomic_claim_gain: float = 0.0
    identity_risk: float = 0.0
    expected_requests: float = 0.0
    expected_seconds: float = 0.0
    expected_paid_cost: Decimal = Decimal("0")
    sequence: int = 0

    @property
    def score(self) -> float:
        return (4 * self.expected_company_family_gain + self.expected_atomic_claim_gain
                - 8 * self.identity_risk - self.expected_requests
                - 0.2 * self.expected_seconds - 10 * float(self.expected_paid_cost))


class OpportunityScheduler:
    """Deterministic global work queue with source-pass priority and queue aging."""
    PASS_ORDER = {"official_foundation": 0, "website_verify": 1, "website_shallow": 2,
                  "jobs_activity": 3, "search": 4, "deep": 5}

    def __init__(self, *, concurrency: int = 4, aging_per_second: float = 0.01,
                 monotonic: Callable[[], float] = time.monotonic):
        if concurrency < 1 or aging_per_second < 0:
            raise ValueError("invalid scheduler limits")
        self.concurrency = concurrency
        self.aging_per_second = aging_per_second
        self._monotonic = monotonic
        self.metrics: dict[str, dict[str, float | int]] = {}
        self.company_metrics: dict[str, dict[str, float | int]] = {}

    async def run(self, opportunities: Iterable[Opportunity],
                  worker: Callable[[Opportunity], Awaitable[T]], *,
                  permitted: Callable[[Opportunity], bool] | None = None,
                  on_complete: Callable[[Opportunity, T], Awaitable[None] | None] | None = None) -> dict[str, T]:
        results: dict[str, T] = {}
        groups: dict[str, list[Opportunity]] = {}
        for item in opportunities:
            groups.setdefault(item.pass_name, []).append(item)
        for pass_name in sorted(groups, key=lambda name: (self.PASS_ORDER.get(name, 99), name)):
            queued = groups[pass_name]
            enqueued_at = {item.key: self._monotonic() for item in queued}
            lock = asyncio.Lock()

            async def take() -> Opportunity | None:
                async with lock:
                    if not queued:
                        return None
                    now = self._monotonic()
                    eligible = [item for item in queued if permitted is None or permitted(item)]
                    if not eligible:
                        for item in queued:
                            self._metric(item.pass_name, "deferred")
                            self._company_metric(item.company, "deferred")
                        queued.clear()
                        return None
                    item = max(eligible, key=lambda candidate: (
                        candidate.score + self.aging_per_second * max(0.0, now - enqueued_at[candidate.key]),
                        -candidate.sequence, candidate.company, candidate.key))
                    queued.remove(item)
                    self._metric(item.pass_name, "expected_company_family_gain", item.expected_company_family_gain)
                    self._metric(item.pass_name, "expected_atomic_claim_gain", item.expected_atomic_claim_gain)
                    self._metric(item.pass_name, "expected_requests", item.expected_requests)
                    self._metric(item.pass_name, "expected_seconds", item.expected_seconds)
                    self._metric(item.pass_name, "expected_paid_cost", float(item.expected_paid_cost))
                    self._metric(item.pass_name, "opportunity_score", item.score)
                    self._company_metric(item.company, "queue_wait_seconds",
                                         max(0.0, now - enqueued_at[item.key]))
                    return item

            async def run_worker() -> None:
                while item := await take():
                    started = self._monotonic()
                    try:
                        value = await worker(item)
                        if on_complete is not None:
                            # Awaiting the hook lets a single checkpoint task serialize
                            # writes while workers keep their results accounted.
                            completion = on_complete(item, value)
                            if asyncio.iscoroutine(completion):
                                await completion
                        results[item.key] = value
                        self._metric(item.pass_name, "completed")
                        self._company_metric(item.company, "completed")
                    except asyncio.CancelledError:
                        self._metric(item.pass_name, "cancelled")
                        self._company_metric(item.company, "cancelled")
                        raise
                    except OpportunityDeferred:
                        self._metric(item.pass_name, "deferred")
                        self._company_metric(item.company, "deferred")
                    except OpportunityFailed as failure:
                        result = failure.result
                        if on_complete is not None:
                            completion = on_complete(item, result)  # type: ignore[arg-type]
                            if asyncio.iscoroutine(completion):
                                await completion
                        results[item.key] = result  # type: ignore[assignment]
                        self._metric(item.pass_name, "failed")
                        self._company_metric(item.company, "failed")
                    except Exception:
                        self._metric(item.pass_name, "failed")
                        self._company_metric(item.company, "failed")
                        raise
                    finally:
                        self._metric(item.pass_name, "worker_seconds", self._monotonic() - started)

            await asyncio.gather(*(run_worker() for _ in range(self.concurrency)))
        return results

    def _metric(self, name: str, field: str, value: float | int = 1) -> None:
        row = self.metrics.setdefault(name, {"completed": 0, "deferred": 0, "cancelled": 0,
            "failed": 0, "worker_seconds": 0.0, "expected_company_family_gain": 0.0,
            "expected_atomic_claim_gain": 0.0, "expected_requests": 0.0,
            "expected_seconds": 0.0, "expected_paid_cost": 0.0, "opportunity_score": 0.0})
        row[field] = row.get(field, 0) + value  # type: ignore[operator]

    def _company_metric(self, company: str, field: str, value: float | int = 1) -> None:
        row = self.company_metrics.setdefault(company, {"completed": 0, "deferred": 0,
                                                        "cancelled": 0, "failed": 0,
                                                        "queue_wait_seconds": 0.0})
        row[field] = row.get(field, 0) + value  # type: ignore[operator]


class OrderedAtomicWriter:
    def __init__(self, output_path: str | Path, estimated_bytes: int = 1024 * 1024):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if not os.access(self.output_path.parent, os.W_OK):
            raise OSError(f"output directory is not writable: {self.output_path.parent}")
        required = max(1024 * 1024, estimated_bytes)
        if shutil.disk_usage(self.output_path.parent).free < required:
            raise OSError(f"insufficient free space for atomic output (need {required} bytes)")

    def write(self, envelopes: Iterable[Envelope], *, serializer: Callable[[Envelope], dict[str, object]] | None = None) -> None:
        ordered = sorted(envelopes, key=lambda item: item.row_number)
        if len({item.row_number for item in ordered}) != len(ordered):
            raise ValueError("duplicate row_number in output")
        fd, temporary = tempfile.mkstemp(prefix=f".{self.output_path.name}.", suffix=".tmp", dir=self.output_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                for envelope in ordered:
                    payload = serializer(envelope) if serializer else envelope.model_dump(mode="json")
                    stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.output_path)
            directory_fd = os.open(self.output_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def write_bytes(self, payload: bytes) -> None:
        """Atomically replace a related canonical artifact after path preflight."""
        fd, temporary = tempfile.mkstemp(prefix=f".{self.output_path.name}.", suffix=".tmp", dir=self.output_path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.output_path)
            directory_fd = os.open(self.output_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def write_shells(self, rows: Iterable[object], states: dict[int, str] | None = None) -> Path:
        """Persist restartable pending shells beside output without inventing public states."""
        pending = self.output_path.with_name(self.output_path.name + ".pending.jsonl")
        fd, temporary = tempfile.mkstemp(prefix=f".{pending.name}.", suffix=".tmp", dir=pending.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                for row in rows:
                    stream.write(json.dumps({
                        "input_ref": getattr(row, "input_ref"),
                        "row_number": getattr(row, "row_number"),
                        "organisation_number": getattr(row, "organisation_number"),
                        "execution_state": (states or {}).get(getattr(row, "row_number"), "pending"),
                    }, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, pending)
            directory_fd = os.open(pending.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return pending


class PartialEnvelopePublisher:
    """Publish complete provisional rows immediately and at bounded flush intervals."""

    def __init__(self, writer: OrderedAtomicWriter, envelopes: Iterable[Envelope], *,
                 serializer: Callable[[Envelope], dict[str, object]] | None = None,
                 max_seconds: float = 5.0, max_updates: int = 25,
                 monotonic: Callable[[], float] = time.monotonic):
        if not math.isfinite(max_seconds) or max_seconds <= 0 or max_updates < 1:
            raise ValueError("partial publication limits must be positive and finite")
        self.writer = writer
        self.max_seconds = max_seconds
        self.max_updates = max_updates
        self._monotonic = monotonic
        self._serializer = serializer
        self._identity_index = _EnvelopeIdentityIndex()
        checked, changes = self._identity_index.prepare(envelopes)
        self._rows = {item.row_number: item for item in checked}
        self._payloads = {item.row_number: self._serialize(item) for item in checked}
        self._identity_index.apply(changes)
        self._pending_updates = 0
        self._last_flush = monotonic()
        self.marker_path = writer.output_path.with_name(writer.output_path.name + ".publication.json")
        self._marker = OrderedAtomicWriter(self.marker_path, estimated_bytes=4096)
        self.flush(force=True)

    def _serialize(self, envelope: Envelope) -> dict[str, object]:
        payload = self._serializer(envelope) if self._serializer else envelope.model_dump(mode="json")
        if not isinstance(payload, dict):
            raise ValueError("partial publication serializer must return an object")
        return json.loads(json.dumps(payload, ensure_ascii=False))

    def update(self, envelope: Envelope) -> bool:
        return self.update_rows([envelope])

    def update_rows(self, envelopes: Iterable[Envelope]) -> bool:
        checked, changes = self._identity_index.prepare(envelopes)
        for envelope in checked:
            previous = self._rows.get(envelope.row_number)
            if previous is None or (previous.input_ref, previous.organisation_number, previous.batch_id) != (
                    envelope.input_ref, envelope.organisation_number, envelope.batch_id):
                raise ValueError("partial publication update must preserve the input row identity")
        payloads = {item.row_number: self._serialize(item) for item in checked}
        self._identity_index.apply(changes)
        self._rows.update({item.row_number: item for item in checked})
        self._payloads.update(payloads)
        self._pending_updates += len(checked)
        return self.flush()

    def flush(self, *, force: bool = False) -> bool:
        if not force and (not self._pending_updates or (
                self._pending_updates < self.max_updates
                and self._monotonic() - self._last_flush < self.max_seconds)):
            return False
        self._marker.write_bytes(json.dumps({
            "status": "partial", "output_path": str(self.writer.output_path),
            "row_count": len(self._rows), "canonical_pair_committed": False,
        }, sort_keys=True).encode("utf-8") + b"\n")
        self.writer.write(self._rows.values(), serializer=lambda envelope: self._payloads[envelope.row_number])
        self._pending_updates = 0
        self._last_flush = self._monotonic()
        return True

    async def run(self, stop: asyncio.Event) -> None:
        """Run beside workers; stop and await this runner before final paired publication."""
        try:
            while not stop.is_set():
                remaining = (max(0.0, self.max_seconds - (self._monotonic() - self._last_flush))
                             if self._pending_updates else self.max_seconds)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=remaining)
                except TimeoutError:
                    self.flush()
        finally:
            self.flush(force=True)


def publish_paired_artifacts(output_writer: OrderedAtomicWriter, state_writer: OrderedAtomicWriter,
                             envelopes: list[Envelope], state_payload: bytes,
                             *, serializer: Callable[[Envelope], dict[str, object]] | None = None) -> Path:
    """Publish output/state with a durable commit marker consumers can verify."""
    output_path, state_path = output_writer.output_path, state_writer.output_path
    marker_path = output_path.with_name(output_path.name + ".publication.json")
    if marker_path.resolve() in {output_path.resolve(), state_path.resolve()}:
        raise ValueError("paired publication marker must have a distinct path")
    marker = OrderedAtomicWriter(marker_path, estimated_bytes=4096)
    publication_id = str(uuid.uuid4())
    marker.write_bytes(json.dumps({"status": "publishing", "publication_id": publication_id,
        "output_path": str(output_path), "state_path": str(state_path)}, sort_keys=True).encode() + b"\n")
    output_writer.write(envelopes, serializer=serializer)
    state_writer.write_bytes(state_payload)
    final = {"status": "committed", "publication_id": publication_id,
        "output_path": str(output_path), "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "state_path": str(state_path), "state_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest()}
    final["marker_sha256"] = _publication_marker_digest(final)
    marker.write_bytes(json.dumps(final, sort_keys=True).encode() + b"\n")
    return marker_path


def _publication_marker_digest(marker: dict[str, object]) -> str:
    content = {key: value for key, value in marker.items() if key != "marker_sha256"}
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_paired_publication(marker_path: str | Path, *, bundle_root: str | Path | None = None,
                                expected_marker_sha256: str | None = None) -> dict[str, object]:
    """Validate an active pair or a relocated release bundle.

    Active markers keep their original absolute-path behavior. Archived absolute
    paths can be rebased only with an explicit bundle root; an external marker
    hash is required for legacy markers that predate the embedded metadata hash.
    """
    marker_file = Path(marker_path)
    if marker_file.is_symlink():
        raise ValueError("publication marker must not be a symlink")
    marker_bytes = marker_file.read_bytes()
    marker_file_hash = hashlib.sha256(marker_bytes).hexdigest()
    if expected_marker_sha256 is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_marker_sha256) or marker_file_hash != expected_marker_sha256:
            raise ValueError("publication marker does not match its external release hash")
    elif bundle_root is not None:
        raise ValueError("relocated publication requires an external marker hash")
    marker = json.loads(marker_bytes)
    if not isinstance(marker, dict):
        raise ValueError("publication marker must be a JSON object")
    if marker.get("status") != "committed":
        raise ValueError("output/state publication is incomplete")
    if not isinstance(marker.get("publication_id"), str) or not marker["publication_id"]:
        raise ValueError("publication marker has no publication identity")
    for key in ("output_sha256", "state_sha256"):
        if not isinstance(marker.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", marker[key]):
            raise ValueError(f"publication marker has invalid {key}")
    embedded_marker_hash = marker.get("marker_sha256")
    if embedded_marker_hash is not None:
        if (not isinstance(embedded_marker_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", embedded_marker_hash)
                or embedded_marker_hash != _publication_marker_digest(marker)):
            raise ValueError("publication marker metadata integrity check failed")

    artifact_paths: dict[str, Path] = {}
    if bundle_root is None:
        artifact_paths = {role: Path(str(marker[f"{role}_path"])) for role in ("output", "state")}
    else:
        root = Path(bundle_root).resolve(strict=True)
        marker_resolved = marker_file.resolve(strict=True)
        if not root.is_dir() or marker_file.is_symlink() or not _inside(root, marker_resolved):
            raise ValueError("publication marker is outside the release bundle root")
        output_name = Path(str(marker.get("output_path", ""))).name
        expected_output_name = marker_file.name.removesuffix(".publication.json")
        state_name = Path(str(marker.get("state_path", ""))).name
        if (not output_name or output_name != expected_output_name or not state_name
                or output_name == state_name):
            raise ValueError("publication artifact names do not match the archived pair")
        for role, name in (("output", output_name), ("state", state_name)):
            raw = str(marker[f"{role}_path"])
            raw_path = Path(raw)
            if raw_path.is_absolute():
                # An archived absolute path is rebased by its basename only;
                # the marker name fixes output identity and state is colocated.
                path = marker_resolved.parent / name
            else:
                if ".." in raw_path.parts:
                    raise ValueError("relative publication path escapes its bundle")
                path = root / raw_path
            if path.is_symlink():
                raise ValueError("publication artifact must not be a symlink")
            resolved = path.resolve(strict=True)
            if not _inside(root, resolved):
                raise ValueError("publication artifact escapes its bundle root")
            artifact_paths[role] = resolved
    for role in ("output", "state"):
        path = artifact_paths[role]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != marker.get(f"{role}_sha256"):
            raise ValueError(f"{role} artifact does not match its committed publication marker")
    return {**marker, "verified_output_path": str(artifact_paths["output"]),
            "verified_state_path": str(artifact_paths["state"])}
