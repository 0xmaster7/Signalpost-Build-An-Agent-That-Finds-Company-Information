"""Private, versioned HTTP captures, never suitable for Git or publication.

Responses include original raw PDF bytes and may include NAV's public access
token. Request credentials are never stored or hashed. If-Modified-Since is an
audited exact-match header: callers must restore the original run clock/cutoff.
Each key is an ordered sequence of physical attempts; exhaustion is a miss.
Hashes detect damage, not malicious rewriting by somebody who owns the store.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from datetime import datetime, timezone
from typing import Any
import uuid


class ReplayError(RuntimeError):
    pass


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class HttpRecording:
    """One writer per new capture directory; replay never writes to the store."""

    def __init__(self, directory: str | Path, *, replay: bool,
                 run_metadata: dict[str, Any] | None = None):
        supplied = Path(directory).absolute()
        if supplied.is_symlink():
            raise ReplayError("recording directory may not be a symlink")
        self.root = supplied.parent.resolve() / supplied.name
        self.replay = replay
        self.misses = 0
        self.failures = 0
        self.hits = 0
        self.missing_requests: list[dict[str, Any]] = []
        self._positions: dict[str, int] = {}
        self._counts: dict[str, int] = {}
        self._pending: set[tuple[str, int]] = set()
        self._unreplayable = False
        if any(part.is_symlink() for part in [self.root, *self.root.parents]):
            raise ReplayError("recording path may not contain symlinks")
        if replay:
            self.metadata = self._read("manifest.json")
            if (self.metadata.get("version") != 2 or
                    self.metadata.get("variant_policy") != "ordered-physical-attempts" or
                    self.metadata.get("header_policy") != "exact-if-modified-since-no-credentials" or
                    not isinstance(self.metadata.get("run"), dict) or
                    not isinstance(self.metadata.get("complete"), bool) or
                    not isinstance(self.metadata.get("attempts"), dict)):
                self._fail("unsupported recording manifest")
            for key, entry in self.metadata["attempts"].items():
                if (not re.fullmatch(r"[0-9a-f]{64}", key) or not isinstance(entry, dict) or
                        not isinstance(entry.get("count"), int) or entry["count"] < 1 or
                        not isinstance(entry.get("request"), dict) or
                        hashlib.sha256(_encoded(entry["request"])).hexdigest() != key):
                    self._fail("malformed recording attempt index")
            if run_metadata is not None and run_metadata != self.metadata["run"]:
                self._fail("run metadata mismatch")
        else:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if any(self.root.iterdir()):
                raise ReplayError("recording requires an empty private directory")
            os.chmod(self.root, 0o700)
            self.metadata = {"version": 2, "variant_policy": "ordered-physical-attempts",
                             "header_policy": "exact-if-modified-since-no-credentials",
                             "attempts": {}, "complete": False,
                             "run": run_metadata if run_metadata is not None else
                             {"run_started_at": datetime.now(timezone.utc).isoformat()}}
            self._write("manifest.json", self.metadata)

    def _fail(self, message: str):
        self.failures += 1
        raise ReplayError(message)

    def _path(self, name: str) -> Path:
        if name not in {"manifest.json", "execution.json"} and not re.fullmatch(r"[0-9a-f]{64}-[0-9]+\.json", name):
            self._fail("invalid recording filename")
        path = self.root / name
        if self.root.is_symlink() or path.is_symlink():
            self._fail("recording symlink rejected")
        return path

    def _write(self, name: str, payload: dict[str, Any]) -> None:
        if self.replay:
            self._fail("replay cannot write to its recording")
        wrapped = _encoded({"sha256": hashlib.sha256(_encoded(payload)).hexdigest(), "payload": payload})
        descriptor, temporary = tempfile.mkstemp(prefix=".capture-", dir=self.root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(wrapped)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path(name))
            directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            self._fail("cannot atomically write private recording")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _read(self, name: str) -> dict[str, Any]:
        path = self._path(name)
        try:
            if stat.S_IMODE(self.root.stat().st_mode) & 0o077:
                self._fail("recording directory is not private")
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                    self._fail("recording file is not a private regular file")
                wrapped = json.load(stream)
            payload = wrapped["payload"]
            if not isinstance(payload, dict) or hashlib.sha256(_encoded(payload)).hexdigest() != wrapped["sha256"]:
                self._fail("recording content hash mismatch")
            return payload
        except FileNotFoundError:
            self.misses += 1
            raise ReplayError(f"recording missing: {name}; live fallback forbidden") from None
        except (OSError, ValueError, KeyError, TypeError):
            self._fail("malformed recording")

    def begin(self, request: dict[str, Any], *, approved_ips: tuple[str, ...] | None) -> dict[str, Any]:
        """Reserve order before I/O; a crash leaves an explicit incomplete attempt."""
        if self.replay or self.metadata["complete"]:
            self._fail("cannot append to a replay or sealed capture")
        key = hashlib.sha256(_encoded(request)).hexdigest()
        position = self._counts.get(key, 0)
        attempt = {"key": key, "position": position, "request_id": str(uuid.uuid4()),
                   "started_at": datetime.now(timezone.utc).isoformat()}
        self._write(f"{key}-{position}.json", {**attempt, "request": request, "outcome": "incomplete",
                    "approved_ips": approved_ips})
        self._counts[key] = position + 1
        self._pending.add((key, position))
        self.metadata["attempts"][key] = {"request": request, "count": position + 1}
        self._write("manifest.json", self.metadata)
        return attempt

    def save(self, request: dict[str, Any], *, response: tuple[int, dict[str, str], bytes, str] | None,
             outcome: str, approved_ips: tuple[str, ...] | None, elapsed_ms: float,
             retrieved_at: datetime | None = None, attempt: dict[str, Any] | None = None,
             error_type: str | None = None) -> dict[str, Any]:
        if error_type is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", error_type):
            self._fail("invalid transport exception type")
        attempt = attempt or self.begin(request, approved_ips=approved_ips)
        key, position = attempt["key"], attempt["position"]
        if (self.replay or (key, position) not in self._pending or
                hashlib.sha256(_encoded(request)).hexdigest() != key):
            self._fail("invalid attempt reservation")
        payload = {"request": request, "outcome": outcome, "approved_ips": approved_ips,
                   **attempt, "retrieved_at": (retrieved_at or datetime.now(timezone.utc)).isoformat(),
                   "elapsed_ms": elapsed_ms, "error_type": error_type,
                   "response": None if response is None else
                   {"status": response[0], "headers": response[1],
                    "body": base64.b64encode(response[2]).decode(), "final_url": response[3]}}
        self._write(f"{key}-{position}.json", payload)
        self._pending.remove((key, position))
        self._unreplayable |= outcome == "unexpected_error"
        return payload

    def load(self, request: dict[str, Any]) -> dict[str, Any]:
        key = hashlib.sha256(_encoded(request)).hexdigest()
        position = self._positions.get(key, 0)
        entry = self.metadata["attempts"].get(key)
        if entry is None or position >= entry["count"]:
            self.misses += 1
            self._missing(request, key, position)
        misses_before = self.misses
        try:
            payload = self._read(f"{key}-{position}.json")
        except ReplayError:
            if self.misses > misses_before:
                self._missing(request, key, position)
            raise
        try:
            if payload.get("outcome") == "incomplete":
                self._fail(f"incomplete physical attempt: key={key} position={position}")
            if (payload["request"] != request or
                    payload["outcome"] not in {"received", "timeout", "transport_error", "cancelled"} or
                    not isinstance(payload["retrieved_at"], str) or
                    not isinstance(payload["elapsed_ms"], (int, float)) or
                    not math.isfinite(payload["elapsed_ms"]) or payload["elapsed_ms"] < 0 or
                    not isinstance(payload["request_id"], str) or not payload["request_id"] or
                    payload["key"] != key or payload["position"] != position):
                self._fail("recording request or outcome mismatch")
            if datetime.fromisoformat(payload["retrieved_at"]).tzinfo is None:
                self._fail("recording retrieval time requires a timezone")
            if payload.get("error_type") is not None and (not isinstance(payload["error_type"], str)
                    or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", payload["error_type"])):
                self._fail("invalid recorded transport exception type")
            ips = payload["approved_ips"]
            if ips is not None and (not isinstance(ips, list) or not ips or not all(isinstance(ip, str) for ip in ips)):
                self._fail("malformed recorded addresses")
            response = payload["response"]
            if payload["outcome"] == "received":
                if (not isinstance(response["status"], int) or not 100 <= response["status"] <= 599 or
                        not isinstance(response["headers"], dict) or
                        not all(isinstance(k, str) and isinstance(v, str) for k, v in response["headers"].items()) or
                        not isinstance(response["final_url"], str)):
                    self._fail("malformed recorded response")
                response["body"] = base64.b64decode(response["body"], validate=True)
            elif response is not None:
                self._fail("unexpected response on recorded failure")
        except (KeyError, TypeError, ValueError, OverflowError):
            self._fail("malformed recording payload")
        self._positions[key] = position + 1
        self.hits += 1
        return payload

    def _missing(self, request: dict[str, Any], key: str, position: int) -> None:
        missing = {"key": key, "position": position, "request": request}
        self.missing_requests.append(missing)
        raise ReplayError("recording missing: " + _encoded(missing).decode() +
                          "; live fallback forbidden") from None

    def diagnostics(self) -> dict[str, Any]:
        """Safe request descriptors only: request headers/credentials are never keys."""
        remaining = [{"key": key, "request": entry["request"],
                      "positions": list(range(self._positions.get(key, 0), entry["count"]))}
                     for key, entry in self.metadata["attempts"].items()
                     if self._positions.get(key, 0) < entry["count"]]
        return {"http_misses": self.misses, "http_failures": self.failures, "http_hits": self.hits,
                "missing_requests": list(self.missing_requests), "unconsumed_requests": remaining,
                "capture_complete": self.metadata["complete"]}

    def assert_complete(self) -> None:
        """Run before publication, even if extractors caught ReplayError locally."""
        if not self.replay:
            self._fail("completeness assertion requires replay")
        diagnostic = self.diagnostics()
        if (not diagnostic["capture_complete"] or self.misses or self.failures or
                diagnostic["unconsumed_requests"]):
            self._fail("replay incomplete: " + _encoded(diagnostic).decode())

    def _execution(self) -> dict[str, Any]:
        payload = (self._read("execution.json") if self._path("execution.json").exists()
                   else {"controls": {}, "identities": {}})
        if not isinstance(payload.get("controls"), dict) or not isinstance(payload.get("identities"), dict):
            self._fail("malformed execution metadata")
        return payload

    def record_execution(self, name: str, value: Any) -> None:
        """Store scheduler/clock controls, never extractor facts or final output."""
        if self.replay or self.metadata["complete"]:
            self._fail("execution controls require an unsealed live capture")
        payload = self._execution()
        if name in payload["controls"]:
            self._fail("duplicate execution control")
        payload["controls"][name] = value
        self._write("execution.json", payload)

    def replay_execution(self, name: str) -> Any:
        if not self.replay:
            self._fail("execution control lookup requires replay")
        payload = self._execution()
        if name not in payload["controls"]:
            self._fail(f"missing execution control: {name}")
        return payload["controls"][name]

    def assert_identity(self, name: str, actual: bytes) -> None:
        """Compare fresh extractor/output bytes to a digest; never return saved output."""
        payload = self._execution()
        identity = {"sha256": hashlib.sha256(actual).hexdigest(), "bytes": len(actual)}
        if self.replay:
            if payload["identities"].get(name) != identity:
                self._fail(f"replay identity mismatch: {name}")
        else:
            if self.metadata["complete"] or name in payload["identities"]:
                self._fail("identity requires an unused name in an unsealed capture")
            payload["identities"][name] = identity
            self._write("execution.json", payload)

    def seal(self) -> None:
        """Mark successful, fully drained capture after identity digests are saved."""
        if self.replay or self._pending or self._unreplayable or self.metadata["complete"]:
            self._fail("cannot seal replay, pending, unreplayable, or already sealed capture")
        self.metadata["complete"] = True
        self._write("manifest.json", self.metadata)
