"""Independent POSIX wall-clock enforcement for a run, including finalization.

Install SIGUSR1 (stop dispatch/research) and SIGUSR2 (begin checkpoint
finalization) handlers BEFORE constructing Watchdog: overdue stages fire at
once. POSIX may deliver simultaneously pending signals in either order, so
handlers must never move the run back from finalization into research.
The caller owns those handlers and its exit status. Only call
mark_committed after BOTH published artifacts and their directory entries are
durable. This assertion is advisory bookkeeping, never a success exit.

At 98% the helper sends SIGKILL even without a committed pair: that is an
emergency, nonzero termination, not successful finalization. A committed run
should stop the watchdog and return normally before then. No threads, Python
timers, or parent signal handlers participate in deadline enforcement.
"""

from __future__ import annotations

import errno
import json
import math
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


class Watchdog:
    """Start a session-detached child monitoring this process's lifetime.

    ``elapsed_seconds`` is time already spent from the original total budget,
    not a reduction of the denominator used for the 85/92/98% stages.
    ``stop`` is idempotent; use a context manager or a finally block. The
    instance must be controlled by its creating process (not a forked child).
    """

    def __init__(self, total_seconds, elapsed_seconds=0):
        total = float(total_seconds)
        elapsed = float(elapsed_seconds)
        if not math.isfinite(total) or total <= 0:
            raise ValueError("total_seconds must be finite and positive")
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("elapsed_seconds must be finite and nonnegative")
        if os.name != "posix":
            raise NotImplementedError("Watchdog requires POSIX signals")
        self._owner_pid = os.getpid()
        self._stopped = False
        self._committed = False
        # Pass an absolute monotonic origin: interpreter startup counts against
        # the budget. -I avoids project imports and PYTHONPATH/site hooks.
        origin = time.monotonic() - elapsed
        self._process = subprocess.Popen(
            [sys.executable, "-I", str(Path(__file__).resolve()),
             "--helper", str(self._owner_pid), repr(total), repr(origin)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            close_fds=True, start_new_session=True,
        )

    @property
    def pid(self):
        """PID of the helper, useful for lifecycle diagnostics."""
        return self._process.pid

    def _check_owner(self):
        if os.getpid() != self._owner_pid:
            raise RuntimeError("Watchdog may only be controlled by its creator")

    def mark_committed(self):
        """Assert a complete durable pair; raises if monitoring has ended.

        This performs no artifact validation or fsync. Call only after the
        parent's durable-pair publication routine has completed successfully.
        A racing emergency cutoff may still log uncommitted; it never grants
        success or delays the cutoff.
        """
        self._check_owner()
        if self._stopped or self._process.poll() is not None:
            raise RuntimeError("Watchdog is no longer monitoring")
        if not self._committed:
            try:
                self._process.stdin.write(b"C\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise RuntimeError("Watchdog control pipe closed") from exc
            self._committed = True

    def stop(self):
        """Close the lifetime pipe; wait up to 0.2s, then kill the helper.

        No PID-based kill is used after reaping. Popen owns this unreaped
        child, so its PID cannot have been reused when kill is necessary.
        """
        self._check_owner()
        if self._stopped:
            return
        self._stopped = True
        self._process.stdin.close()
        try:
            self._process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            self._process.kill()
            try:
                self._process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                # Do not let an uninterruptible OS wait stall parent cleanup.
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def _log(reason, parent_pid, committed):
    payload = json.dumps({"event": "watchdog", "reason": reason,
                          "parent_pid": parent_pid,
                          "durable_pair_committed": committed}) + "\n"
    try:
        # Logging is best effort. A full stderr pipe must not hold up a kill.
        if select.select([], [2], [], 0)[1]:
            os.write(2, payload.encode())
    except (OSError, ValueError):
        pass


def _monitor(parent_pid, total, origin):
    # Linux pidfds bind signals to the original process, closing the PID reuse
    # race. Other POSIX systems use direct-child identity AND lifetime-pipe EOF
    # checks before every signal; there is no portable atomic pidfd equivalent.
    if os.getppid() != parent_pid:
        return
    pidfd = None
    if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
        try:
            pidfd = os.pidfd_open(parent_pid)
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return
            # Python can expose pidfd_open on kernels or sandboxes which do
            # not support it. Keep the portable lifetime/parent guards active.
    committed = False
    stages = [(0.85, signal.SIGUSR1, "stop_research"),
              (0.92, signal.SIGUSR2, "begin_finalization"),
              (0.98, signal.SIGKILL, "force_exit")]
    stage = 0
    try:
        while stage < len(stages):
            fraction, signum, reason = stages[stage]
            delay = max(0, origin + total * fraction - time.monotonic())
            ready = select.select([0], [], [], min(delay, 0.05))[0]
            if ready:
                message = os.read(0, 4096)
                if not message:
                    return
                if b"C" in message:
                    committed = True
            if os.getppid() != parent_pid:
                return
            if time.monotonic() < origin + total * fraction:
                continue
            # Drain pending commit/EOF immediately before signaling. EOF always
            # wins over a deadline, including when stop() closes the pipe.
            while select.select([0], [], [], 0)[0]:
                message = os.read(0, 4096)
                if not message:
                    return
                committed = committed or b"C" in message
            if os.getppid() != parent_pid:
                return
            try:
                if pidfd is not None:
                    signal.pidfd_send_signal(pidfd, signum)
                else:
                    os.kill(parent_pid, signum)
            except ProcessLookupError:
                return
            if reason == "force_exit":
                reason += "_committed" if committed else "_uncommitted"
            _log(reason, parent_pid, committed)
            stage += 1
    finally:
        if pidfd is not None:
            os.close(pidfd)


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--helper":
        raise SystemExit("internal watchdog helper; construct Watchdog instead")
    _monitor(int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
