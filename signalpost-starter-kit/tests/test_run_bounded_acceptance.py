"""Offline driver fixtures: research subprocesses are forbidden or mocked."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location('bounded_driver', Path(__file__).resolve().parents[1] / 'scripts/run_bounded_acceptance.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    source, config = tmp_path / 'companies.jsonl', tmp_path / 'config.json'
    source.write_bytes(b''.join(json.dumps({'organisation_number': str(910000000 + i), 'extra': i}).encode() + b'\n' for i in range(1000)))
    config.write_text('{"budget":{"physical_request_limit":8000}}\n')
    repo = tmp_path / 'repository'
    repo.mkdir()
    monkeypatch.setattr(runner.final, 'source_identity', lambda _: {'head': 'frozen', 'source_sha256': 'frozen'})
    monkeypatch.setattr(runner.final, 'launch', lambda *a, **k: pytest.fail('unexpected research launch'))
    args = SimpleNamespace(root=tmp_path / 'acceptance', repository=repo, source=source, config=config,
        parent_deadline_utc='2099-01-01T00:00:00Z', parent_remaining_seconds=None, stage='200')
    assert runner.prepare(args)['status'] == 'prepared'
    return args


def fake_summary(directory, orgs, phases, replay=False, live_directory=None):
    gates = {'process_succeeded': True, 'exact_final_cardinality_and_order': True,
        'durable_company_phase_metrics_complete': True, 'runtime_within_1200_seconds': False,
        'finance_at_least_95': False, 'explicit_fte_at_least_50': False,
        'verified_websites_at_least_20': False}
    if replay:
        gates.update(exact_output_bytes_equal=True, exact_state_bytes_equal=True,
                     replay_capture_sealed_and_fully_consumed=True)
    return {'gates': gates, 'checkpoint': {'shell_states': {'terminalized': len(orgs)}},
            'company_counts': {'finance_companies': 3}}


def report_fixture(monkeypatch, *, runtime=350, recording=True):
    def summary(*args, **kwargs):
        return {**fake_summary(*args, **kwargs), 'elapsed_seconds': runtime + 0.1}
    monkeypatch.setattr(runner.helper, 'summarize', summary)
    events = [{'event': 'batch_complete', 'runtime_seconds': runtime,
        'requests_by_purpose': {'financial': 17},
        'scheduler_passes': {'optional_phases': {'financial_statements': {
            'ran': 5, 'worker_seconds': 13, 'wall_seconds': 4, 'requests': 17}}}}]
    if recording:
        events.append({'event': 'recording_complete', 'capture_complete': True})
    monkeypatch.setattr(runner.helper, 'log_events', lambda path: events if path.name == 'stdout.log' else [])
    monkeypatch.setattr(runner, 'committed_pair', lambda _: True)


def test_prepare_frozen_bytes_order_receipts_no_launch(prepared):
    args = prepared
    root = args.root
    assert (root / '1000-selection/companies.jsonl').read_bytes() == args.source.read_bytes()
    assert (root / '200-selection/companies.jsonl').read_bytes() == b''.join(args.source.read_bytes().splitlines(keepends=True)[:200])
    assert (root / 'config.json').read_bytes() == args.config.read_bytes()
    for stage in ('200', '1000'):
        directory = root / (stage + '-selection')
        assert runner.load(directory / 'input-receipt.json')['input_sha256'] == runner.helper.digest(directory / 'companies.jsonl')
    assert root.stat().st_mode & 0o077 == 0
    with pytest.raises(runner.BoundedError, match='new_root'):
        runner.prepare(args)


def test_measurements_never_gate_operational_success(prepared, monkeypatch):
    report_fixture(monkeypatch)
    report = runner.summarize(prepared.root / '200', ['x'] * 200, '200', runner.load(prepared.root / 'bounded-acceptance.json'))
    assert report['execution_gate_pass'] is True
    assert not any(report['ignored_measurement_gates'].values())
    assert report['company_counts']['finance_companies'] == 3
    assert report['phase_aggregate_metrics']['financial_statements']['requests'] == 17
    assert report['phase_aggregate_metrics']['financial_statements']['worker_seconds'] == 13


@pytest.mark.parametrize('runtime,recording', [(361, True), (350, False)])
def test_runtime_and_recording_fail_closed(prepared, monkeypatch, runtime, recording):
    report_fixture(monkeypatch, runtime=runtime, recording=recording)
    report = runner.summarize(prepared.root / '200', ['x'] * 200, '200', runner.load(prepared.root / 'bounded-acceptance.json'))
    assert report['execution_gate_pass'] is False


@pytest.mark.parametrize('stage,prior', [('1000', '200'), ('replay', '1000')])
def test_large_stages_require_persisted_success(prepared, stage, prior):
    prepared.stage = stage
    with pytest.raises(runner.BoundedError, match='prerequisite_' + prior):
        runner.execute(prepared)
    (prepared.root / prior).mkdir()
    runner.helper.write(prepared.root / prior / 'report.json', {'execution_gate_pass': False})
    with pytest.raises(runner.BoundedError, match='failed'):
        runner.execute(prepared)


def test_failed_launch_is_never_retried(prepared, monkeypatch):
    calls = []
    def crash(*args):
        calls.append(args)
        raise RuntimeError('fixture failure')
    monkeypatch.setattr(runner.final, 'launch', crash)
    assert runner.execute(prepared)['status'] == 'failed'
    assert (prepared.root / '200.attempt.json').exists()
    with pytest.raises(runner.BoundedError, match='stage_already_attempted_no_retry'):
        runner.execute(prepared)
    assert len(calls) == 1
    assert calls[0][5:7] == (400, 360)


def test_replay_watch_capped_by_parent_time_and_same_batch_id(prepared, monkeypatch):
    prepared.stage = 'replay'
    prepared.parent_remaining_seconds = 100
    monkeypatch.setattr(runner, 'prior', lambda *args: None)
    calls = []
    def launch(*args):
        calls.append(args)
        args[1].mkdir()
    monkeypatch.setattr(runner.final, 'launch', launch)
    monkeypatch.setattr(runner, 'summarize', lambda *args: {'status': 'passed', 'execution_gate_pass': True})
    assert runner.execute(prepared)['status'] == 'passed'
    assert calls[0][4:7] == ('bounded-1000', 80, 1800)
    assert calls[0][7] == prepared.root / '1000/http-capture'
    assert not (prepared.root / '200').exists()


def test_frozen_input_tamper_blocks_launch(prepared):
    (prepared.root / '200-selection/companies.jsonl').write_text('{}\n')
    with pytest.raises(runner.BoundedError, match='frozen_input_changed'):
        runner.execute(prepared)


def test_committed_pair_checks_marker_and_bytes(tmp_path):
    output, state = tmp_path / 'envelopes.jsonl', tmp_path / 'state.json'
    output.write_bytes(b'{}\n')
    state.write_bytes(b'{}\n')
    marker = {'status': 'committed', 'publication_id': 'fixture', 'output_path': str(output),
        'state_path': str(state), 'output_sha256': runner.helper.digest(output), 'state_sha256': runner.helper.digest(state)}
    marker['marker_sha256'] = runner.hashlib.sha256(json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    runner.helper.write(tmp_path / 'envelopes.jsonl.publication.json', marker)
    assert runner.committed_pair(tmp_path)
    state.write_bytes(b'{"changed":true}\n')
    assert not runner.committed_pair(tmp_path)


@pytest.mark.parametrize('gate', ['exact_output_bytes_equal', 'exact_state_bytes_equal',
                                 'replay_capture_sealed_and_fully_consumed'])
def test_replay_rejects_mismatch_or_unconsumed_capture(prepared, monkeypatch, gate):
    report_fixture(monkeypatch)
    def summary(*args, **kwargs):
        result = fake_summary(*args, **kwargs)
        result['gates'][gate] = False
        return result
    monkeypatch.setattr(runner.helper, 'summarize', summary)
    report = runner.summarize(prepared.root / 'replay', ['x'] * 1000, 'replay',
                             runner.load(prepared.root / 'bounded-acceptance.json'))
    assert report['execution_gate_pass'] is False
