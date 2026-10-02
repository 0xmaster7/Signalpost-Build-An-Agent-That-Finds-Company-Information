from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .models import Envelope


@dataclass(frozen=True)
class RunBudget:
    hard_seconds: float = 1800
    soft_seconds: float = 1350
    completion_reserve_seconds: float = 300
    physical_request_limit: int = 1000
    paid_cost_limit: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.hard_seconds <= 0 or self.soft_seconds < 0 or self.completion_reserve_seconds < 0:
            raise ValueError("budget durations must be non-negative and hard_seconds positive")
        if self.soft_seconds + self.completion_reserve_seconds > self.hard_seconds:
            raise ValueError("soft deadline plus completion reserve exceeds hard deadline")
        if self.physical_request_limit < 0 or self.paid_cost_limit < 0:
            raise ValueError("request and cost limits must be non-negative")

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
            paid_cost_limit=Decimal(str(value("paid_cost_limit", "SIGNALPOST_PAID_COST_LIMIT", "0"))),
        )


class Budget:
    def __init__(self, config: RunBudget):
        self.config = config
        self.started = time.monotonic()
        self._request_count = 0
        self._cost = Decimal("0")
        self._lock = asyncio.Lock()

    @property
    def soft_expired(self) -> bool:
        return time.monotonic() - self.started >= self.config.soft_seconds

    @property
    def hard_expired(self) -> bool:
        return time.monotonic() - self.started >= self.config.hard_seconds

    async def reserve_request(self, cost: Decimal = Decimal("0")) -> bool:
        async with self._lock:
            if self.soft_expired or self.hard_expired:
                return False
            if self._request_count + 1 > self.config.physical_request_limit:
                return False
            if self._cost + cost > self.config.paid_cost_limit:
                return False
            self._request_count += 1
            self._cost += cost
            return True

    @property
    def physical_requests(self) -> int:
        return self._request_count

    @property
    def cost(self) -> Decimal:
        return self._cost


class CheckpointStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS envelopes (row_number INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        self.connection.commit()

    def put(self, envelope: Envelope) -> None:
        self.connection.execute("INSERT OR REPLACE INTO envelopes(row_number,payload) VALUES (?,?)", (envelope.row_number, envelope.model_dump_json()))
        self.connection.commit()

    def rows(self) -> list[Envelope]:
        return [Envelope.model_validate_json(row[0]) for row in self.connection.execute("SELECT payload FROM envelopes ORDER BY row_number")]

    def close(self) -> None:
        self.connection.close()


class OrderedAtomicWriter:
    def __init__(self, output_path: str | Path, estimated_bytes: int = 1024 * 1024):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if not os.access(self.output_path.parent, os.W_OK):
            raise OSError(f"output directory is not writable: {self.output_path.parent}")
        required = max(1024 * 1024, estimated_bytes)
        if shutil.disk_usage(self.output_path.parent).free < required:
            raise OSError(f"insufficient free space for atomic output (need {required} bytes)")

    def write(self, envelopes: Iterable[Envelope]) -> None:
        ordered = sorted(envelopes, key=lambda item: item.row_number)
        if len({item.row_number for item in ordered}) != len(ordered):
            raise ValueError("duplicate row_number in output")
        fd, temporary = tempfile.mkstemp(prefix=f".{self.output_path.name}.", suffix=".tmp", dir=self.output_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                for envelope in ordered:
                    stream.write(envelope.model_dump_json() + "\n")
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

    def write_shells(self, rows: Iterable[object]) -> Path:
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
                        "execution_state": "pending",
                    }, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, pending)
            return pending
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
