"""Replay scheduling controls and raw abandoned inputs, never saved company facts."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from .network import request_company_scope, request_phase_scope
from .recording import ReplayError


def implementation_identity() -> str:
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for filename in sorted(root.glob("*.py")):
        digest.update(filename.name.encode() + b"\0" + filename.read_bytes() + b"\0")
    for name in ("pyproject.toml", "uv.lock"):
        digest.update((root.parent / "signalpost-starter-kit" / name).read_bytes())
    return digest.hexdigest()


class ExecutionTrace:
    def __init__(self, recording):
        self.recording = recording
        self.replay = bool(recording and recording.replay)
        self.outcomes = recording.replay_execution("company_phase_outcomes") if self.replay else {}
        if not isinstance(self.outcomes, dict):
            recording._fail("invalid company phase execution controls")

    def outcome(self, phase: str, company: str):
        if not self.replay:
            return None
        try:
            return self.outcomes[phase][company]["outcome"]
        except (KeyError, TypeError):
            self.recording._fail("missing company phase control: " + phase + ":" + company)

    def admitted(self, phase: str, company: str) -> bool:
        return not self.replay or self.outcome(phase, company) in {"completed", "failed"}

    def save(self, checkpoint, phases):
        if self.recording and not self.replay:
            self.recording.record_execution("company_phase_outcomes", {
                phase: checkpoint.phase_statuses(phase) for phase in phases})

    async def consume_abandoned(self, gateway, phase: str, company: str):
        """Validate raw inputs of work cancelled before it produced any facts."""
        if not self.replay or self.admitted(phase, company):
            return
        with request_phase_scope(phase), request_company_scope(company):
            while True:
                entries = [entry for entry in self.recording.diagnostics()["unconsumed_requests"]
                    if entry["request"].get("phase") == phase and entry["request"].get("company") == company]
                if not entries:
                    return
                request = entries[0]["request"]
                before = self.recording.hits
                original_retries = gateway.retries
                gateway.retries = request["retries"]
                headers = ({"If-Modified-Since": request["if_modified_since"]}
                    if request.get("if_modified_since") else None)
                try:
                    await gateway.fetch(request["url"], purpose=request["purpose"],
                        user_agent=request["user_agent"], max_bytes=request["max_bytes"],
                        use_robots=request["use_robots"],
                        allowed_hosts=set(request["allowed_hosts"]) if request["allowed_hosts"] is not None else None,
                        access_profile=request["access_profile"], api_headers=headers)
                except asyncio.CancelledError:
                    pass
                except ReplayError:
                    raise
                except Exception:
                    if self.recording.hits == before:
                        raise
                finally:
                    gateway.retries = original_retries
                if self.recording.hits == before:
                    self.recording._fail("abandoned request was not consumed: " + entries[0]["key"])

    def control(self, name: str, actual=None):
        if not self.recording:
            return actual
        if self.replay:
            return self.recording.replay_execution(name)
        self.recording.record_execution(name, actual)
        return actual
