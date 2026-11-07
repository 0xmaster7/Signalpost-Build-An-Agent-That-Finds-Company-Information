"""Offline output-first gate fixtures: no live research subprocess is launched."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location('outputfirst_driver', Path(__file__).resolve().parents[1] / 'scripts/run_outputfirst_acceptance.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def repository_imports(monkeypatch):
    monkeypatch.syspath_prepend(str(REPOSITORY))


def payload(number, claim_id=None):
    from signalpost.adapter import to_evaluator
    from signalpost.models import Claim, Envelope, RefreshState, Section
    observed = datetime(2026, 11, 7, tzinfo=timezone.utc)
    claims = [Claim(claim_id=claim_id, section='identity_brand', field='legal_name', value=None,
                    state='not_available')] if claim_id else []
    return to_evaluator(Envelope(input_ref=f'row:{number}', row_number=number,
        organisation_number=str(910000000 + number), terminal_state='not_available',
        claims=claims,
        sections={name: Section(state=None, attempt_outcome='NOT_ATTEMPTED',
            claims=claims if name in {'identity_brand', 'claims_evidence_states'} else []) for name in (
            'identity_brand', 'accounts_history', 'leadership_workplaces', 'website_owned_profiles',
            'hiring_activity', 'claims_evidence_states', 'refresh_changes')},
        refresh=RefreshState(), batch_id='outputfirst-200', evidence_cutoff=observed, created_at=observed))


def marker(directory, status='output_committed'):
    output = directory / 'envelopes.jsonl'
    value = {'publication_id': 'fixture', 'status': status,
        'output_path': str(output), 'output_sha256': runner.helper.digest(output)}
    if status == 'committed':
        state = directory / 'state.json'
        state.write_text('{}\n')
        value.update(state_path=str(state), state_sha256=runner.helper.digest(state))
    else:
        value.update(output_committed=True, state_incomplete=True, canonical_pair_committed=False)
    value['marker_sha256'] = hashlib.sha256(json.dumps(value, ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    runner.helper.write(directory / 'envelopes.jsonl.publication.json', value)
    return value


def output_fixture(directory, count=2, elapsed=359.9):
    directory.mkdir(exist_ok=True)
    rows = [payload(i + 1) for i in range(count)]
    (directory / 'envelopes.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    runner.helper.write(directory / 'invocation.json', {'status': 'completed', 'exit_code': 0,
        'external_timeout': False, 'elapsed_seconds': elapsed})
    marker(directory)
    return rows


def summary(directory, rows, stage='200'):
    return runner.summarize(directory, [row['organisation_number'] for row in rows], stage, {}, REPOSITORY)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    source, config = tmp_path / 'companies.jsonl', tmp_path / 'config.json'
    source.write_text(''.join(json.dumps({'organisation_number': str(910000001 + i), 'extra': i}) + '\n' for i in range(1000)))
    config.write_text('{"budget":{"physical_request_limit":8000}}\n')
    repository = tmp_path / 'repository'
    repository.mkdir()
    monkeypatch.setattr(runner.final, 'source_identity', lambda _: {'head': 'frozen', 'source_sha256': 'frozen'})
    monkeypatch.setattr(runner, 'launch', lambda *a, **k: pytest.fail('unexpected research launch'))
    args = SimpleNamespace(root=tmp_path / 'acceptance', repository=repository, source=source, config=config,
        parent_deadline_utc='2099-01-01T00:00:00Z', parent_remaining_seconds=None, stage='200')
    assert runner.prepare(args)['status'] == 'prepared'
    return args


def test_prepare_freezes_exact_cohorts_config_and_only_two_stages(prepared):
    root = prepared.root
    assert (root / '1000-selection/companies.jsonl').read_bytes() == prepared.source.read_bytes()
    assert (root / '200-selection/companies.jsonl').read_bytes() == b''.join(prepared.source.read_bytes().splitlines(keepends=True)[:200])
    assert (root / 'config.json').read_bytes() == prepared.config.read_bytes()
    manifest = runner.bounded.load(root / runner.MANIFEST)
    assert set(manifest['stages']) == {'200', '1000'}
    assert manifest['stages']['200']['budget_seconds'] == 360
    assert manifest['stages']['1000']['budget_seconds'] == 1800
    assert root.stat().st_mode & 0o077 == 0
    assert not (root / '200').exists()
    with pytest.raises(runner.OutputFirstError, match='new_root'):
        runner.prepare(prepared)


def test_output_commit_passes_without_state_recording_or_aggregate(tmp_path):
    rows = output_fixture(tmp_path)
    report = summary(tmp_path, rows)
    assert report['execution_gate_pass'] is True
    assert report['secondary']['committed_output_state_pair'] is False
    assert report['secondary']['recording_status'] == 'unknown'
    assert report['aggregate_status'] == 'unknown'
    assert report['aggregate'] is report['runtime_seconds'] is report['requests_by_purpose'] is None


def test_full_paired_commit_also_passes(tmp_path):
    rows = output_fixture(tmp_path)
    marker(tmp_path, 'committed')
    assert summary(tmp_path, rows)['gate_pass'] is True


@pytest.mark.parametrize('changes', [
    {'exit_code': 1}, {'exit_code': -15}, {'exit_code': False}, {'external_timeout': True},
    {'elapsed_seconds': 360.0001}, {'elapsed_seconds': None}, {'elapsed_seconds': True}, {'status': 'running'},
])
def test_clean_exit_and_measured_budget_are_mandatory(tmp_path, changes):
    rows = output_fixture(tmp_path)
    path = tmp_path / 'invocation.json'
    runner.helper.write(path, {**runner.bounded.load(path), **changes})
    assert summary(tmp_path, rows)['gate_pass'] is False


@pytest.mark.parametrize('stage,elapsed,passed', [('200', 360, True), ('1000', 1800, True), ('1000', 1800.001, False)])
def test_stage_budget_boundaries(tmp_path, stage, elapsed, passed):
    rows = output_fixture(tmp_path, elapsed=elapsed)
    assert summary(tmp_path, rows, stage)['gate_pass'] is passed


def test_secondary_failures_and_overbudget_aggregate_never_gate(tmp_path):
    rows = output_fixture(tmp_path)
    events = [{'event': 'batch_complete', 'runtime_seconds': 9999}, {'event': 'recording_failed'}]
    (tmp_path / 'stdout.log').write_text(''.join(json.dumps(event) + '\n' for event in events))
    report = summary(tmp_path, rows)
    assert report['gate_pass'] is True
    assert report['runtime_seconds'] == 9999
    assert report['requests_by_purpose'] is None
    assert report['secondary']['recording_status'] == 'recording_failed'


@pytest.mark.parametrize('mutation', ['invalid_json', 'nested_section', 'invalid_operation', 'missing_row', 'duplicate_company',
                                     'duplicate_input_ref', 'stale_synthesis', 'missing_top_key'])
def test_full_jsonl_validation_and_cardinality_fail_closed(tmp_path, mutation):
    rows = output_fixture(tmp_path)
    changed = json.loads(json.dumps(rows))
    if mutation == 'nested_section':
        changed[1]['sections']['identity_brand']['state'] = 'bogus'
    elif mutation == 'invalid_operation':
        changed[1]['operations'] = [{'unexpected': 'value'}]
    elif mutation == 'missing_row':
        changed.pop()
    elif mutation == 'duplicate_company':
        changed[1]['organisation_number'] = changed[0]['organisation_number']
    elif mutation == 'duplicate_input_ref':
        changed[1]['input_ref'] = changed[0]['input_ref']
    elif mutation == 'stale_synthesis':
        changed[1]['synthesis']['summary']['unexpected'] = 'value'
    elif mutation == 'missing_top_key':
        del changed[1]['operations']
    content = ''.join(json.dumps(row) + '\n' for row in changed)
    if mutation == 'invalid_json':
        content += '{broken\n'
    (tmp_path / 'envelopes.jsonl').write_text(content)
    marker(tmp_path)
    assert summary(tmp_path, rows)['gate_pass'] is False


@pytest.mark.parametrize('mutation', ['metadata', 'bytes', 'status', 'output_path', 'output_flag', 'missing_marker', 'state_bytes'])
def test_publication_integrity_required(tmp_path, mutation):
    output_fixture(tmp_path)
    value = marker(tmp_path, 'committed' if mutation == 'state_bytes' else 'output_committed')
    path = tmp_path / 'envelopes.jsonl.publication.json'
    if mutation == 'bytes':
        (tmp_path / 'envelopes.jsonl').write_text('{}\n')
    elif mutation == 'state_bytes':
        (tmp_path / 'state.json').write_text('{"tampered":true}')
    elif mutation == 'missing_marker':
        path.unlink()
    else:
        value[{'metadata': 'publication_id', 'status': 'status', 'output_path': 'output_path', 'output_flag': 'output_committed'}[mutation]] = 'tampered'
        runner.helper.write(path, value)
    assert runner.publication(tmp_path) is False


def test_1000_requires_saved_and_recomputed_200_success(prepared, monkeypatch):
    prepared.stage = '1000'
    with pytest.raises(runner.OutputFirstError, match='prerequisite_200'):
        runner.execute(prepared)
    (prepared.root / '200').mkdir()
    runner.helper.write(prepared.root / '200/report.json', {'execution_gate_pass': True})
    monkeypatch.setattr(runner, 'summarize', lambda *args: {'execution_gate_pass': False})
    with pytest.raises(runner.OutputFirstError, match='evidence_changed'):
        runner.execute(prepared)


def test_failed_stage_cannot_be_retried_or_chain(prepared, monkeypatch):
    calls = []
    def crash(*args):
        calls.append(args)
        raise RuntimeError('fixture')
    monkeypatch.setattr(runner, 'launch', crash)
    assert runner.execute(prepared)['status'] == 'failed'
    with pytest.raises(runner.OutputFirstError, match='already_attempted'):
        runner.execute(prepared)
    assert len(calls) == 1
    assert not (prepared.root / '1000').exists()


@pytest.mark.parametrize('target', ['config.json', '200-selection/companies.jsonl', '1000-selection/companies.jsonl'])
def test_frozen_tampering_blocks_launch(prepared, target):
    (prepared.root / target).write_text('{}\n')
    with pytest.raises(runner.OutputFirstError, match='changed'):
        runner.execute(prepared)


def test_parent_time_cap_blocks_launch(prepared):
    prepared.parent_remaining_seconds = 419
    with pytest.raises(runner.OutputFirstError, match='insufficient_parent_time'):
        runner.execute(prepared)
    assert not (prepared.root / '200.attempt.json').exists()


def test_launch_command_has_output_first_recording_and_existing_config(tmp_path, monkeypatch):
    source, config = tmp_path / 'companies.jsonl', tmp_path / 'config.json'
    source.write_text('{}\n')
    config.write_text('{}')
    calls = []
    class Process:
        pid = 123
        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))
        def wait(self, timeout):
            assert timeout == 400
            return 0
    monkeypatch.setattr(runner.subprocess, 'Popen', Process)
    directory = tmp_path / '200'
    runner.launch(REPOSITORY, directory, source, config, '200')
    command = calls[0][0]
    assert '--output-first' in command and '--record-http' in command
    assert '--replay-http' not in command
    assert command[command.index('--config') + 1] == str(config)
    assert command[command.index('--budget-seconds') + 1] == '360'
    assert runner.bounded.load(directory / 'invocation.json')['exit_code'] == 0


def test_cross_row_duplicate_claim_ids_fail_even_when_each_row_is_valid(tmp_path):
    output_fixture(tmp_path)
    rows = [payload(1, 'duplicate-claim'), payload(2, 'duplicate-claim')]
    (tmp_path / 'envelopes.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    marker(tmp_path)
    report = summary(tmp_path, rows)
    assert report['validation']['valid'] is True
    assert report['duplicate_count'] == 1
    assert report['gates']['zero_duplicate_ids'] is False
    assert report['gate_pass'] is False


def test_nonfinite_secondary_metric_is_unknown_and_never_vetoes(tmp_path):
    rows = output_fixture(tmp_path)
    (tmp_path / 'stdout.log').write_text('{"event":"batch_complete","runtime_seconds":NaN}\n')
    report = summary(tmp_path, rows)
    assert report['gate_pass'] is True
    assert report['runtime_seconds'] is None
    json.dumps(report, allow_nan=False)


def test_explicit_stages_use_real_validation_and_never_chain(prepared, monkeypatch):
    calls = []
    def fake_launch(repository, directory, source, config, stage):
        calls.append(stage)
        output_fixture(directory, count=runner.STAGES[stage][0], elapsed=100)
    monkeypatch.setattr(runner, 'launch', fake_launch)
    prepared.repository = REPOSITORY
    assert runner.execute(prepared)['gate_pass'] is True
    assert calls == ['200']
    assert not (prepared.root / '1000').exists()
    prepared.stage = '1000'
    assert runner.execute(prepared)['gate_pass'] is True
    assert calls == ['200', '1000']
    with pytest.raises(runner.OutputFirstError, match='already_attempted'):
        runner.execute(prepared)
    assert calls == ['200', '1000']
