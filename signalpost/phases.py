"""Private exception fingerprints and public, bounded phase failure messages."""
from __future__ import annotations

import hashlib
import re
import traceback

from .models import RunError


def failure_error(code: str, phase: str, exc: Exception) -> RunError:
    digest = hashlib.sha256("".join(traceback.format_exception(exc)).encode()).hexdigest()
    reason = re.sub(r"[^A-Za-z0-9_]", "_", type(exc).__name__)[:80]
    return RunError(code=code, message=f"{phase} failed: {reason}; traceback_sha256={digest}", retryable=True)


def error_fingerprint(errors):
    for error in reversed(errors):
        match = re.search(r"traceback_sha256=([0-9a-f]{64})", error.message)
        if match:
            return error.message.split(";", 1)[0], match.group(1)
    return None, None
