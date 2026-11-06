import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from signalpost.deadlines import ResearchDeadline, signal_deadline


POSIX_SIGNALS = os.name == "posix" and hasattr(signal, "setitimer")


def test_deadline_is_not_swallowed_by_exception_handlers():
    assert issubclass(ResearchDeadline, BaseException)
    assert not issubclass(ResearchDeadline, Exception)
    error = ResearchDeadline("sigterm")
    assert error.reason == str(error) == "sigterm"


def test_disabled_deadline_and_worker_thread_are_noops():
    with signal_deadline(0, enabled=False):
        time.sleep(0.01)
    errors = []

    def worker():
        try:
            with signal_deadline(0):
                time.sleep(0.01)
            with ResearchDeadline("sigterm").finalizing():
                pass
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert errors == []


def test_unsupported_platform_falls_back(monkeypatch):
    monkeypatch.setattr("signalpost.deadlines._signals_available", lambda: False)
    with signal_deadline(0):
        time.sleep(0.01)
    with ResearchDeadline("sigterm").finalizing():
        pass


@pytest.mark.skipif(not POSIX_SIGNALS, reason="requires POSIX interval timers")
@pytest.mark.parametrize("exit_kind", ["normal", "exception", "deadline", "sigterm"])
def test_handlers_and_existing_periodic_timer_restored(exit_kind):
    old_alarm = signal.getsignal(signal.SIGALRM)
    old_term = signal.getsignal(signal.SIGTERM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)

    def original_handler(signum, frame):
        pass

    try:
        signal.signal(signal.SIGALRM, original_handler)
        signal.signal(signal.SIGTERM, original_handler)
        signal.setitimer(signal.ITIMER_REAL, 10, 2)
        started = time.monotonic()
        try:
            with signal_deadline(0.03 if exit_kind == "deadline" else 5):
                if exit_kind == "exception":
                    raise ValueError("ordinary failure")
                if exit_kind == "sigterm":
                    os.kill(os.getpid(), signal.SIGTERM)
                if exit_kind == "deadline":
                    while True:
                        pass
                time.sleep(0.02)
        except ResearchDeadline as error:
            assert error.reason == exit_kind
        except ValueError:
            assert exit_kind == "exception"
        else:
            assert exit_kind == "normal"
        delay, interval = signal.getitimer(signal.ITIMER_REAL)
        assert signal.getsignal(signal.SIGALRM) is original_handler
        assert signal.getsignal(signal.SIGTERM) is original_handler
        assert delay == pytest.approx(10 - (time.monotonic() - started), abs=0.1)
        assert interval == pytest.approx(2)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_alarm)
        signal.signal(signal.SIGTERM, old_term)
        signal.setitimer(signal.ITIMER_REAL, *old_timer)


@pytest.mark.skipif(not POSIX_SIGNALS, reason="requires POSIX interval timers")
def test_nested_context_restores_outer_deadline():
    with pytest.raises(ResearchDeadline, match="deadline"):
        with signal_deadline(0.08):
            with signal_deadline(5):
                time.sleep(0.02)
            while True:
                pass


@pytest.mark.skipif(not POSIX_SIGNALS, reason="requires POSIX signals")
def test_failed_finalization_restores_sigterm_handler():
    previous = signal.getsignal(signal.SIGTERM)
    with pytest.raises(ValueError, match="checkpoint failure"):
        with ResearchDeadline("sigterm").finalizing():
            assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
            os.kill(os.getpid(), signal.SIGTERM)
            raise ValueError("checkpoint failure")
    assert signal.getsignal(signal.SIGTERM) == previous


@pytest.mark.skipif(not POSIX_SIGNALS, reason="requires POSIX signals")
@pytest.mark.parametrize("trigger", ["sigterm", "deadline"])
def test_subprocess_interrupts_cpu_loop_and_finalizes_despite_repeated_sigterm(trigger):
    root = Path(__file__).resolve().parents[2]
    program = r'''
import os, signal, sys, threading, time
from signalpost.deadlines import ResearchDeadline, signal_deadline

trigger = sys.argv[1]
def terminate():
    time.sleep(0.05)
    os.kill(os.getpid(), signal.SIGTERM)

try:
    with signal_deadline(0.05 if trigger == "deadline" else 20):
        if trigger == "sigterm":
            threading.Thread(target=terminate, daemon=True).start()
        try:
            while True:
                pass
        except Exception:
            raise AssertionError("ordinary handler swallowed deadline")
        finally:
            # Repeated termination during stack unwinding must be ignored.
            os.kill(os.getpid(), signal.SIGTERM)
except ResearchDeadline as error:
    assert error.reason == trigger
    with error.finalizing():
        os.kill(os.getpid(), signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(0.02)
        print("checkpoint finalized", flush=True)
assert signal.getsignal(signal.SIGTERM) == signal.SIG_DFL
assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
'''
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-c", program, trigger], cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "checkpoint finalized"
    assert time.monotonic() - started < 5
