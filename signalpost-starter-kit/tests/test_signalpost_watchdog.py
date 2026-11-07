"""Real short-lived subprocess tests; no network or live benchmark work."""

import json
import errno
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from signalpost.watchdog import Watchdog, _monitor


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX watchdog")
ROOT = Path(__file__).resolve().parents[2]


def run_parent(body, timeout=6):
    code = """
import os, signal, sys, time
from signalpost.watchdog import Watchdog
def observed(signum, frame):
    os.write(1, (signal.Signals(signum).name + "\\n").encode())
signal.signal(signal.SIGUSR1, observed)
signal.signal(signal.SIGUSR2, observed)
""" + body
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                          capture_output=True, text=True, timeout=timeout)


@pytest.mark.parametrize("committed", [False, True])
def test_busy_parent_receives_stages_then_nonzero_force_exit(committed):
    result = run_parent("\nw = Watchdog(2)\n" +
                        ("w.mark_committed()\n" if committed else "") +
                        "while True:\n    pass\n")
    assert result.returncode == -signal.SIGKILL
    assert result.stdout.splitlines() == ["SIGUSR1", "SIGUSR2"]
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert [event["reason"] for event in events] == [
        "stop_research", "begin_finalization",
        "force_exit_committed" if committed else "force_exit_uncommitted"]
    assert events[-1]["durable_pair_committed"] is committed


def test_ignored_signals_cannot_disable_independent_force_exit():
    result = run_parent("""
signal.signal(signal.SIGUSR1, signal.SIG_IGN)
signal.signal(signal.SIGUSR2, signal.SIG_IGN)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
w = Watchdog(0.8)
while True:
    pass
""")
    assert result.returncode == -signal.SIGKILL
    assert "force_exit_uncommitted" in result.stderr


def test_native_call_holding_parent_gil_cannot_delay_force_exit():
    result = run_parent("""
import ctypes
signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1, signal.SIGUSR2})
w = Watchdog(0.8)
# PyDLL deliberately retains the GIL for a native call. Python handlers cannot
# run until it returns, but the independent helper must enforce the cutoff.
ctypes.PyDLL(None).sleep(5)
raise AssertionError('watchdog failed to interrupt native wait')
""")
    assert result.returncode == -signal.SIGKILL
    assert "begin_finalization" in result.stderr
    assert "force_exit_uncommitted" in result.stderr


def test_elapsed_budget_uses_original_total_and_fires_overdue_stage():
    result = run_parent("""
w = Watchdog(10, elapsed_seconds=9.3)
while True:
    pass
""")
    assert result.returncode == -signal.SIGKILL
    # Both stages are overdue: POSIX does not promise delivery ordering.
    assert sorted(result.stdout.splitlines()) == ["SIGUSR1", "SIGUSR2"]
    assert "force_exit_uncommitted" in result.stderr


def test_stop_reaps_child_and_is_idempotent():
    watchdog = Watchdog(30)
    watchdog.mark_committed()
    watchdog.mark_committed()
    watchdog.stop()
    watchdog.stop()
    assert watchdog._process.returncode == 0
    with pytest.raises(ProcessLookupError):
        os.kill(watchdog.pid, 0)
    with pytest.raises(RuntimeError, match="no longer monitoring"):
        watchdog.mark_committed()


def test_stop_kills_unresponsive_helper_with_bounded_wait():
    watchdog = Watchdog(30)
    os.kill(watchdog.pid, signal.SIGSTOP)
    started = time.monotonic()
    watchdog.stop()
    assert time.monotonic() - started < 0.8
    assert watchdog._process.returncode == -signal.SIGKILL


def test_context_manager_stops_on_exception():
    with pytest.raises(ValueError, match="test"):
        with Watchdog(30) as watchdog:
            raise ValueError("test")
    assert watchdog._process.returncode == 0


def test_parent_death_does_not_leave_helper_waiting_for_deadline():
    # Give the helper time to initialize, then exit without Watchdog.stop().
    result = run_parent("""
w = Watchdog(30)
print(w.pid, flush=True)
time.sleep(0.15)
os._exit(7)
""")
    assert result.returncode == 7
    helper_pid = int(result.stdout.strip())
    deadline = time.monotonic() + 1
    while True:
        status = subprocess.run(["ps", "-o", "stat=", "-p", str(helper_pid)],
                                capture_output=True, text=True)
        # An orphan may briefly remain a zombie until the system reaps it.
        if not status.stdout.strip() or status.stdout.strip().startswith("Z"):
            break
        assert time.monotonic() < deadline, "helper outlived its parent"
        time.sleep(0.02)


@pytest.mark.parametrize("total,elapsed", [
    (0, 0), (-1, 0), (float("inf"), 0), (float("nan"), 0),
    (1, -1), (1, float("nan")), (1, float("inf")),
])
def test_invalid_budget_does_not_start_helper(total, elapsed):
    with pytest.raises(ValueError):
        Watchdog(total, elapsed)


def test_portable_guard_never_signals_after_reparenting(monkeypatch):
    parents = iter([12345, 1])
    monkeypatch.setattr(os, "getppid", lambda: next(parents))
    monkeypatch.delattr(os, "pidfd_open", raising=False)
    monkeypatch.setattr("signalpost.watchdog.select.select", lambda *args: ([], [], []))
    monkeypatch.setattr(os, "kill", lambda *args: pytest.fail("signaled stale parent"))
    _monitor(12345, 1, time.monotonic() - 2)


def test_unsupported_pidfd_still_uses_lifetime_pipe(monkeypatch):
    monkeypatch.setattr(os, "getppid", lambda: 12345)
    def unsupported(pid):
        raise OSError(errno.ENOSYS, "old kernel")
    monkeypatch.setattr(os, "pidfd_open", unsupported, raising=False)
    monkeypatch.setattr(signal, "pidfd_send_signal", lambda *args: None, raising=False)
    reads = []
    monkeypatch.setattr("signalpost.watchdog.select.select", lambda *args: ([0], [], []))
    def eof(fd, count):
        reads.append(fd)
        return b""
    monkeypatch.setattr(os, "read", eof)
    monkeypatch.setattr(os, "kill", lambda *args: pytest.fail("signaled after EOF"))
    _monitor(12345, 1, time.monotonic() - 2)
    assert reads == [0]
