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
import os
from pathlib import Path
import re
import stat
import tempfile
from datetime import datetime, timezone
from typing import Any


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
        self._positions: dict[str, int] = {}
        self._counts: dict[str, int] = {}
        if any(part.is_symlink() for part in [self.root, *self.root.parents]):
            raise ReplayError("recording path may not contain symlinks")
        if replay:
            self.metadata = self._read("manifest.json")
            if (self.metadata.get("version") != 1 or
                    self.metadata.get("variant_policy") != "ordered-physical-attempts" or
                    self.metadata.get("header_policy") != "exact-if-modified-since-no-credentials" or
                    not isinstance(self.metadata.get("run"), dict)):
                self._fail("unsupported recording manifest")
            if run_metadata is not None and run_metadata != self.metadata["run"]:
                self._fail("run metadata mismatch")
        else:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if any(self.root.iterdir()):
                raise ReplayError("recording requires an empty private directory")
            os.chmod(self.root, 0o700)
            self.metadata = {"version": 1, "variant_policy": "ordered-physical-attempts",
                             "header_policy": "exact-if-modified-since-no-credentials",
                             "run": run_metadata if run_metadata is not None else
                             {"run_started_at": datetime.now(timezone.utc).isoformat()}}
            self._write("manifest.json", self.metadata)

    def _fail(self, message: str):
        self.failures += 1
        raise ReplayError(message)

    def _path(self, name: str) -> Path:
        if name != "manifest.json" and not re.fullmatch(r"[0-9a-f]{64}-[0-9]+\.json", name):
            self._fail("invalid recording filename")
        path = self.root / name
        if self.root.is_symlink() or path.is_symlink():
            self._fail("recording symlink rejected")
        return path

    def _write(self, name: str, payload: dict[str, Any]) -> None:
        wrapped = _encoded({"sha256": hashlib.sha256(_encoded(payload)).hexdigest(), "payload": payload})
        descriptor, temporary = tempfile.mkstemp(prefix=".capture-", dir=self.root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(wrapped)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path(name))
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
            raise ReplayError("recording missing; live fallback forbidden") from None
        except (OSError, ValueError, KeyError, TypeError):
            self._fail("malformed recording")

    def save(self, request: dict[str, Any], *, response: tuple[int, dict[str, str], bytes, str] | None,
             outcome: str, approved_ips: tuple[str, ...] | None, elapsed_ms: float) -> None:
        key = hashlib.sha256(_encoded(request)).hexdigest()
        position = self._counts.get(key, 0)
        payload = {"request": request, "outcome": outcome, "approved_ips": approved_ips,
                   "retrieved_at": datetime.now(timezone.utc).isoformat(), "elapsed_ms": elapsed_ms,
                   "response": None if response is None else
                   {"status": response[0], "headers": response[1],
                    "body": base64.b64encode(response[2]).decode(), "final_url": response[3]}}
        self._write(f"{key}-{position}.json", payload)
        self._counts[key] = position + 1

    def load(self, request: dict[str, Any]) -> dict[str, Any]:
        key = hashlib.sha256(_encoded(request)).hexdigest()
        position = self._positions.get(key, 0)
        payload = self._read(f"{key}-{position}.json")
        try:
            if (payload["request"] != request or
                    payload["outcome"] not in {"received", "timeout", "transport_error", "cancelled"} or
                    not isinstance(payload["retrieved_at"], str) or
                    not isinstance(payload["elapsed_ms"], (int, float)) or payload["elapsed_ms"] < 0):
                self._fail("recording request or outcome mismatch")
            if datetime.fromisoformat(payload["retrieved_at"]).tzinfo is None:
                self._fail("recording retrieval time requires a timezone")
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
            if payload["outcome"] == "cancelled":
                self._fail("capture contains cancelled request")
        except (KeyError, TypeError, ValueError):
            self._fail("malformed recording payload")
        self._positions[key] = position + 1
        self.hits += 1
        return payload
