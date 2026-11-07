"""Independent POSIX watchdog with an opt-in durable-output contract.

Legacy default: USR1 at 85%, USR2 at 92%, KILL at 98%.
With output_first=True: USR2 requests output publication at 92% and again at
98% if unacknowledged. TERM requests graceful exit at/after 98% ONLY after
mark_output_committed(). KILL at/after 100% is gated on that same assertion.
Without it emergency USR2 requests continue beyond the budget. A blocked
parent cannot be guaranteed both a hard deadline and output completion;
output safety wins, and the helper never claims success.

Parent API: install handlers BEFORE construction. USR1 stops dispatch; USR2
idempotently promotes/publishes complete output, fsyncs the file AND directory,
then calls mark_output_committed(); TERM checks output_committed, flushes
required diagnostics, and calls os._exit(0). Signals may arrive out of order.
The parent creates/validates Envelopes. The child only tracks acknowledgements.
A prepublished baseline can be acknowledged if it meets the complete output
contract, including legal unknown/not_started rows for EVERY input. Staged
candidates are insufficient: atomic publication and directory fsync must finish.
State/pair completion is independent; mark_committed acknowledges both in
output-first mode. Neither method validates artifacts. Only the parent's TERM
handler can supply exit code zero; KILL remains nonzero even after output ack.
A late acknowledgement grants a bounded 100 ms TERM grace beyond the budget.
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

    def __init__(self, total_seconds, elapsed_seconds=0, *, output_first=False):
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
        self._output_committed = False
        self._output_first = bool(output_first)
        # Pass an absolute monotonic origin: interpreter startup counts against
        # the budget. -I avoids project imports and PYTHONPATH/site hooks.
        origin = time.monotonic() - elapsed
        self._process = subprocess.Popen(
            [sys.executable, "-I", str(Path(__file__).resolve()),
             "--helper", str(self._owner_pid), repr(total), repr(origin),
             "output-first" if self._output_first else "legacy"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, bufsize=0,
            close_fds=True, start_new_session=True,
        )

    @property
    def pid(self):
        """PID of the helper, useful for lifecycle diagnostics."""
        return self._process.pid

    def _check_owner(self):
        if os.getpid() != self._owner_pid:
            raise RuntimeError("Watchdog may only be controlled by its creator")

    @property
    def output_committed(self):
        """Parent assertion of durable complete output, independent of state."""
        return self._output_committed

    def _acknowledge(self, message):
        self._check_owner()
        if self._stopped or self._process.poll() is not None:
            raise RuntimeError("Watchdog is no longer monitoring")
        try:
            # Unbuffered single-byte writes avoid flush locks in signal handlers.
            if os.write(self._process.stdin.fileno(), message) != len(message):
                raise RuntimeError("Watchdog acknowledgement incomplete")
        except OSError as exc:
            raise RuntimeError("Watchdog control pipe closed") from exc

    def mark_output_committed(self):
        """Assert published, fsynced, complete output; does not assert a pair.

        The parent owns validation and publication. This enables graceful exit
        and the hard cutoff. Acknowledging a partial candidate is invalid.
        """
        if not self._output_first:
            raise RuntimeError("requires output_first=True")
        self._check_owner()
        if self._stopped or self._process.poll() is not None:
            raise RuntimeError("Watchdog is no longer monitoring")
        if not self._output_committed:
            # TERM may arrive immediately after the helper receives the byte.
            self._output_committed = True
            try:
                self._acknowledge(b"O")
            except BaseException:
                self._output_committed = False
                raise

    def mark_committed(self):
        """Assert BOTH published artifacts and directory entries are durable."""
        self._check_owner()
        if self._stopped or self._process.poll() is not None:
            raise RuntimeError("Watchdog is no longer monitoring")
        if not self._committed:
            previous = self._output_committed
            self._output_committed = True
            try:
                self._acknowledge(b"C")
            except BaseException:
                self._output_committed = previous
                raise
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


def _log(reason, parent_pid, committed, output_committed=None):
    record = {"event": "watchdog", "reason": reason,
              "parent_pid": parent_pid, "durable_pair_committed": committed}
    if output_committed is not None:
        record["durable_output_committed"] = output_committed
    payload = json.dumps(record) + "\n"
    try:
        # Logging is best effort. A full stderr pipe must not hold up a kill.
        if select.select([], [2], [], 0)[1]:
            os.write(2, payload.encode())
    except (OSError, ValueError):
        pass


def _monitor(parent_pid, total, origin, output_first=False):
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
    output_committed = False
    graceful_requested = False
    exit_deadline = origin + total
    retry_at = origin + total * 0.98
    stages = [(0.85, signal.SIGUSR1, "stop_research"),
              (0.92, signal.SIGUSR2, "begin_finalization"),
              (0.98, signal.SIGKILL, "force_exit")]
    if output_first:
        stages[2] = (0.98, signal.SIGUSR2, "emergency_output_commit")
    stage = 0
    try:
        while output_first or stage < len(stages):
            if stage < len(stages):
                fraction, signum, reason = stages[stage]
                deadline = origin + total * fraction
            elif output_committed:
                deadline = time.monotonic() if not graceful_requested else exit_deadline
                signum = signal.SIGTERM if not graceful_requested else signal.SIGKILL
                reason = "output_committed_exit" if not graceful_requested else "force_exit"
            else:
                deadline = retry_at
                signum, reason = signal.SIGUSR2, "emergency_output_commit"
            delay = max(0, deadline - time.monotonic())
            ready = select.select([0], [], [], min(delay, 0.05))[0]
            if ready:
                message = os.read(0, 4096)
                if not message:
                    return
                if b"C" in message:
                    committed = True
                output_committed = output_committed or b"O" in message or committed
            if os.getppid() != parent_pid:
                return
            if time.monotonic() < deadline:
                continue
            # Drain pending commit/EOF immediately before signaling. EOF always
            # wins over a deadline, including when stop() closes the pipe.
            while select.select([0], [], [], 0)[0]:
                message = os.read(0, 4096)
                if not message:
                    return
                committed = committed or b"C" in message
                output_committed = output_committed or b"O" in message or committed
            if os.getppid() != parent_pid:
                return
            if output_first and stage >= 2 and output_committed and not graceful_requested:
                signum, reason = signal.SIGTERM, "output_committed_exit"
            try:
                if pidfd is not None:
                    signal.pidfd_send_signal(pidfd, signum)
                else:
                    os.kill(parent_pid, signum)
            except ProcessLookupError:
                return
            if reason == "force_exit":
                if output_first:
                    reason += "_output_committed"
                else:
                    reason += "_committed" if committed else "_uncommitted"
            _log(reason, parent_pid, committed,
                 output_committed if output_first else None)
            if signum == signal.SIGKILL:
                return
            if output_first and signum == signal.SIGTERM:
                graceful_requested = True
                # A late ack still needs a bounded chance to run TERM before
                # a nonzero cutoff; the original deadline may already be past.
                exit_deadline = max(origin + total, time.monotonic() + 0.1)
            retry_at = time.monotonic() + min(1.0, max(0.05, total * 0.01))
            stage += 1
    finally:
        if pidfd is not None:
            os.close(pidfd)


if __name__ == "__main__":
    if len(sys.argv) not in (5, 6) or sys.argv[1] != "--helper":
        raise SystemExit("internal watchdog helper; construct Watchdog instead")
    _monitor(int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]),
             len(sys.argv) == 6 and sys.argv[5] == "output-first")
