"""Output-first handshake tests; isolated parents, no network or CLI changes."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from signalpost.watchdog import Watchdog

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='POSIX signals')
ROOT = Path(__file__).resolve().parents[2]


def parent(code, *args):
    return subprocess.run([sys.executable, '-c', code, *map(str, args)],
                          cwd=ROOT, capture_output=True, text=True, timeout=5)


@pytest.mark.parametrize('late', [False, True])
def test_forced_stop_commits_output_before_exit_zero_without_pair(tmp_path, late):
    output = tmp_path / 'output.jsonl'
    result = parent('''
import json, os, signal, sys, time
from pathlib import Path
from signalpost.watchdog import Watchdog
path = Path(sys.argv[1])
started = time.monotonic()
def stop(sig, frame):
    pass
def commit(sig, frame):
    # Late publication proves an emergency request can cross the hard budget.
    if sys.argv[2] == 'True' and time.monotonic() - started < 1.12:
        return
    if w.output_committed:
        return
    candidate = path.with_suffix('.staged')
    with candidate.open('w') as f:
        for i in range(200):
            f.write(json.dumps({'input': i, 'status': 'unknown:not_started'}) + '\\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(candidate, path)
    fd = os.open(path.parent, os.O_RDONLY)
    os.fsync(fd)
    os.close(fd)
    w.mark_output_committed()
def finish(sig, frame):
    assert w.output_committed and not w._committed
    print('durable-output-exit', flush=True)
    os._exit(0)
signal.signal(signal.SIGUSR1, stop)
signal.signal(signal.SIGUSR2, commit)
signal.signal(signal.SIGTERM, finish)
w = Watchdog(1, output_first=True)
while True:
    time.sleep(.01)
''', output, late)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'durable-output-exit'
    assert len([json.loads(row) for row in output.read_text().splitlines()]) == 200
    assert 'output_committed_exit' in result.stderr
    assert 'force_exit' not in result.stderr


def test_no_ack_survives_hard_budget_without_success_or_kill():
    result = parent('''
import os, signal, time
from signalpost.watchdog import Watchdog
for sig in (signal.SIGUSR1, signal.SIGUSR2, signal.SIGTERM):
    signal.signal(sig, signal.SIG_IGN)
w = Watchdog(.3, output_first=True)
time.sleep(.65)
print('alive without ack', flush=True)
w.stop()
''')
    assert result.returncode == 0, result.stderr
    assert 'alive without ack' in result.stdout
    assert 'emergency_output_commit' in result.stderr
    assert 'output_committed_exit' not in result.stderr
    assert 'force_exit' not in result.stderr


@pytest.mark.parametrize('pair', [False, True])
def test_durable_ack_allows_nonzero_fallback_if_exit_handler_ignored(pair):
    result = parent('''
import signal, time
from signalpost.watchdog import Watchdog
for sig in (signal.SIGUSR1, signal.SIGUSR2, signal.SIGTERM):
    signal.signal(sig, signal.SIG_IGN)
w = Watchdog(.5, output_first=True)
''' + ('w.mark_committed()\n' if pair else 'w.mark_output_committed()\n') + '''
while True:
    time.sleep(.01)
''')
    assert result.returncode == -signal.SIGKILL
    assert 'output_committed_exit' in result.stderr
    events = [json.loads(row) for row in result.stderr.splitlines()]
    assert events[-1]['durable_pair_committed'] is pair
    assert events[-1]['durable_output_committed'] is True
    assert events[-1]['reason'] == 'force_exit_output_committed'


@pytest.mark.parametrize('stderr_mode', ['closed', 'full'])
def test_helper_exits_on_parent_exit_with_unusable_stderr(stderr_mode):
    result = parent('''
import os, signal, time, sys
from signalpost.watchdog import Watchdog
for sig in (signal.SIGUSR1, signal.SIGUSR2):
    signal.signal(sig, signal.SIG_IGN)
if sys.argv[1] == 'closed':
    os.close(2)
else:
    r, fd = os.pipe()
    os.set_blocking(fd, False)
    try:
        while True:
            os.write(fd, b'x' * 4096)
    except BlockingIOError:
        pass
    os.set_blocking(fd, True)
    os.dup2(fd, 2)
w = Watchdog(.2, output_first=True)
time.sleep(.35)
w.stop()
assert w._process.returncode == 0
os._exit(0)
''', stderr_mode)
    assert result.returncode == 0, result.stderr


def test_output_ack_is_idempotent_and_checks_lifetime():
    with Watchdog(30, output_first=True) as watchdog:
        watchdog.mark_output_committed()
        watchdog.mark_output_committed()
        assert watchdog.output_committed
        assert not watchdog._committed
    with pytest.raises(RuntimeError, match='no longer monitoring'):
        watchdog.mark_output_committed()
    with Watchdog(30) as legacy:
        with pytest.raises(RuntimeError, match='output_first'):
            legacy.mark_output_committed()
