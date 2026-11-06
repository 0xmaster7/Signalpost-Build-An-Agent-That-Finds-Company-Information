"""Synchronous research interruption on POSIX main threads.

Wrap only research in ``signal_deadline``. Catch ``ResearchDeadline`` outside
that context, then use ``with exc.finalizing():`` around checkpoint recovery.
Signal exceptions can interrupt Python CPU loops as well as blocking waits;
extension code that does not return to Python can still delay delivery.
"""

from contextlib import contextmanager
import math
import os
import signal
import threading
import time


def _signals_available():
    return (
        os.name == "posix"
        and threading.current_thread() is threading.main_thread()
        and all(hasattr(signal, name) for name in (
            "SIGALRM", "SIGTERM", "ITIMER_REAL", "setitimer", "getitimer"
        ))
    )


class ResearchDeadline(BaseException):
    """Escape ordinary exception handlers when research must stop."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)

    @contextmanager
    def finalizing(self):
        """Ignore repeated SIGTERM while recovering from a checkpoint."""
        if not _signals_available():
            yield
            return
        previous = signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            yield
        finally:
            signal.signal(signal.SIGTERM, previous)


@contextmanager
def signal_deadline(seconds, enabled=True):
    """Interrupt research with reason ``deadline`` or ``sigterm``.

    Disabled contexts, worker threads, and non-POSIX platforms are no-ops.
    Nonpositive durations expire immediately. Previous signal handlers and
    the real-time timer are restored on every exit, accounting for elapsed
    time. An overdue previous timer is delivered promptly after restoration.
    This context owns the process-wide real-time timer while it is active.
    """
    if not enabled or not _signals_available():
        yield
        return
    seconds = float(seconds)
    if not math.isfinite(seconds):
        raise ValueError("deadline seconds must be finite")

    previous_alarm = signal.getsignal(signal.SIGALRM)
    previous_term = signal.getsignal(signal.SIGTERM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    interrupted = False

    def interrupt(signum, frame):
        nonlocal interrupted
        if interrupted:
            return
        interrupted = True
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.setitimer(signal.ITIMER_REAL, 0)
        raise ResearchDeadline("sigterm" if signum == signal.SIGTERM else "deadline")

    try:
        signal.signal(signal.SIGALRM, interrupt)
        signal.signal(signal.SIGTERM, interrupt)
        signal.setitimer(signal.ITIMER_REAL, max(seconds, 0.000001))
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_alarm)
        signal.signal(signal.SIGTERM, previous_term)
        delay, interval = previous_timer
        if delay > 0:
            delay = max(0.000001, delay - (time.monotonic() - started))
        signal.setitimer(signal.ITIMER_REAL, delay, interval)
