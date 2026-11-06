#!/usr/bin/env python3
"""Frozen 200 -> 1000 -> exact replay acceptance, one manually invoked stage at a time.

Preparation only reads local files. No stage is retried, including wrapper failures.
Examples (run on the host containing the frozen source):
  python scripts/run_bounded_acceptance.py --root /private/new-root --prepare-only
  python scripts/run_bounded_acceptance.py --root /private/new-root --stage 200
  python scripts/run_bounded_acceptance.py --root /private/new-root --stage 1000
  python scripts/run_bounded_acceptance.py --root /private/new-root --stage replay
The latter two commands are separate manual gates; no command chains stages.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

SPEC = importlib.util.spec_from_file_location("_bounded_final", Path(__file__).with_name("run_final_acceptance.py"))
final = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(final)
helper = final.helper
DEFAULT_SOURCE = Path('/home/azureuser/projects/signalpost-bounded-source-fc39bb0')
STAGES = {'200': (200, 360, 400), '1000': (1000, 1800, 1830), 'replay': (1000, 1800, 600)}


class BoundedError(RuntimeError):
    pass


def load(path):
    return json.loads(path.read_text())


def prepare(args):
    root, repository = args.root.resolve(), args.repository.resolve()
    if root.is_relative_to(repository):
        raise BoundedError('artifacts_must_be_outside_repository')
    if args.root.is_symlink() or root.exists():
        raise BoundedError('prepare_requires_new_root')
    orgs = helper.read_input(args.source, 1000)
    raw = args.source.read_bytes()
    lines = [line for line in raw.splitlines(keepends=True) if line.strip()]
    config = args.config.read_bytes()
    if not isinstance(json.loads(config), dict):
        raise BoundedError('config_requires_object')
    helper.private_dir(root)
    inputs = {}
    for stage, payload in (('200', b''.join(lines[:200])), ('1000', raw)):
        directory = root / (stage + '-selection')
        helper.private_dir(directory)
        source = directory / 'companies.jsonl'
        source.write_bytes(payload)
        source.chmod(0o600)
        helper.read_input(source, int(stage))
        inputs[stage] = helper.digest(source)
        helper.write(directory / 'input-receipt.json', {
            'sample_size': int(stage), 'input_sha256': inputs[stage],
            'source_path': str(args.source.resolve()), 'source_sha256': hashlib.sha256(raw).hexdigest(),
            'selection': 'first 200 in original order' if stage == '200' else 'all 1000 in original order',
            'organisation_numbers': orgs[:int(stage)], 'research_launched': False})
    (root / 'config.json').write_bytes(config)
    (root / 'config.json').chmod(0o600)
    manifest = {'schema_version': 1, 'source': final.source_identity(repository),
        'source_path': str(args.source.resolve()), 'source_sha256': hashlib.sha256(raw).hexdigest(),
        'configuration_sha256': hashlib.sha256(config).hexdigest(), 'inputs': inputs,
        'required_phases': list(helper.PHASES), 'automatic_retry': False,
        'parent_deadline_utc': args.parent_deadline_utc,
        'stages': {name: {'count': n, 'budget_seconds': b, 'external_watch_seconds': w}
                   for name, (n, b, w) in STAGES.items()}}
    helper.write(root / 'bounded-acceptance.json', manifest)
    return {'status': 'prepared', 'research_launched': False, 'input_sha256': inputs,
            'configuration_sha256': manifest['configuration_sha256']}


def committed_pair(directory):
    try:
        marker = load(directory / 'envelopes.jsonl.publication.json')
        content = {k: v for k, v in marker.items() if k != 'marker_sha256'}
        expected = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
            separators=(',', ':')).encode()).hexdigest()
        return (marker.get('status') == 'committed' and marker.get('marker_sha256') == expected
            and all(Path(marker.get(role + '_path', '')).resolve() == (directory / name).resolve()
                    and marker.get(role + '_sha256') == helper.digest(directory / name)
                    for role, name in (('output', 'envelopes.jsonl'), ('state', 'state.json'))))
    except (OSError, ValueError, TypeError):
        return False


def summarize(directory, orgs, stage, manifest):
    replay = stage == 'replay'
    report = helper.summarize(directory, orgs, manifest['required_phases'], replay,
                              directory.parent / '1000' if replay else None)
    events = list(helper.log_events(directory / 'stdout.log')) + list(helper.log_events(directory / 'stderr.log'))
    batches = [event for event in events if event.get('event') == 'batch_complete']
    batch = batches[-1] if batches else {}
    gates = {key: value for key, value in report['gates'].items() if key not in helper.MEASUREMENT_GATES}
    budget = STAGES[stage][1]
    gates['runtime_within_budget'] = helper._number(batch.get('runtime_seconds')) and batch['runtime_seconds'] <= budget
    gates['process_elapsed_within_budget'] = helper._number(report.get('elapsed_seconds')) and report['elapsed_seconds'] <= budget
    gates['all_shells_terminalized'] = report['checkpoint']['shell_states'] == {'terminalized': len(orgs)}
    gates['committed_output_state_pair'] = committed_pair(directory)
    if not replay:
        recordings = [event for event in events if event.get('event') in {'recording_complete', 'recording_failed'}]
        gates['recording_complete'] = len(recordings) == 1 and recordings[0].get('event') == 'recording_complete' \
            and recordings[0].get('capture_complete') is True
    # Keep coverage as integer counts; it cannot veto operational safety.
    report.update(stage=stage, budget_seconds=budget, gates=gates,
                  gate_pass=all(value is True for value in gates.values()),
                  ignored_measurement_gates={k: v for k, v in report['gates'].items() if k in helper.MEASUREMENT_GATES})
    report['execution_gate_pass'] = report['gate_pass']
    report['status'] = 'passed' if report['gate_pass'] else 'failed'
    report['aggregate'] = batch
    phases = batch.get('scheduler_passes', {}).get('optional_phases', {})
    report['phase_aggregate_metrics'] = {phase: {
        **{key: metrics.get(key) for key in (*helper.COUNTERS, 'worker_seconds', 'wall_seconds')},
        'requests': metrics.get('requests', metrics.get('physical_requests')),
    } for phase, metrics in phases.items() if isinstance(metrics, dict)}
    report['requests_by_purpose'] = batch.get('requests_by_purpose', {})
    report['request_metrics_note'] = 'Null phase requests mean absent in aggregate; requests_by_purpose preserves recorded counts without inferring phase attribution.'
    return report


def prior(root, stage, manifest):
    path = root / stage / 'report.json'
    if not path.is_file():
        raise BoundedError('prerequisite_' + stage + '_success_required')
    saved = load(path)
    if saved.get('execution_gate_pass') is not True:
        raise BoundedError('prerequisite_' + stage + '_failed')
    # Recompute from durable evidence rather than trusting a stale boolean.
    orgs = helper.read_input(root / (stage + '-selection') / 'companies.jsonl', int(stage))
    if not summarize(root / stage, orgs, stage, manifest)['execution_gate_pass']:
        raise BoundedError('prerequisite_' + stage + '_evidence_changed')


def execute(args):
    root, repository = args.root.resolve(), args.repository.resolve()
    if args.root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
        raise BoundedError('root_requires_private_directory')
    manifest = load(root / 'bounded-acceptance.json')
    if final.source_identity(repository) != manifest['source'] or helper.digest(root / 'config.json') != manifest['configuration_sha256']:
        raise BoundedError('frozen_source_or_configuration_changed')
    for name, expected in manifest['inputs'].items():
        if helper.digest(root / (name + '-selection') / 'companies.jsonl') != expected:
            raise BoundedError('frozen_input_changed')
    stage = args.stage
    if stage in ('1000', 'replay'):
        prior(root, '200' if stage == '1000' else '1000', manifest)
    count, budget, watch = STAGES[stage]
    deadline = datetime.fromisoformat(manifest['parent_deadline_utc'].replace('Z', '+00:00'))
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
    if args.parent_remaining_seconds is not None:
        remaining = min(remaining, args.parent_remaining_seconds)
    # Helper gives a timed-out process at most 20 seconds to stop.
    if stage == 'replay':
        watch = min(watch, remaining - 20)
    elif remaining < watch + 20:
        raise BoundedError('insufficient_parent_time_for_live_stage')
    if watch <= 0:
        raise BoundedError('parent_time_exhausted')
    directory = root / stage
    if directory.exists() or (root / (stage + '.attempt.json')).exists():
        raise BoundedError('stage_already_attempted_no_retry')
    # Exclusive persistent reservation survives crashes and concurrent invocations.
    with (root / (stage + '.attempt.json')).open('x') as stream:
        json.dump({'stage': stage, 'started_at_utc': final.utc(), 'external_watch_seconds': watch}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    source = root / (('1000' if stage == 'replay' else stage) + '-selection') / 'companies.jsonl'
    orgs = helper.read_input(source, count)
    try:
        final.launch(repository, directory, source, root / 'config.json', 'bounded-' + ('1000' if stage == 'replay' else stage),
                     watch, budget, root / '1000' / 'http-capture' if stage == 'replay' else None)
        report = summarize(directory, orgs, stage, manifest)
    except BaseException as error:
        report = {'status': 'failed', 'stage': stage, 'execution_gate_pass': False,
                  'gate_pass': False, 'failure_code': 'wrapper_exception', 'exception_type': type(error).__name__}
    if directory.is_dir():
        helper.write(directory / 'report.json', report)
    report['subsequent_stages_launched'] = False
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE / 'companies.jsonl')
    parser.add_argument('--config', type=Path, default=DEFAULT_SOURCE / 'config.json')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--repository', type=Path, default=final.ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--stage', choices=STAGES)
    parser.add_argument('--parent-deadline-utc', default='2026-11-06T23:12:55+00:00',
                        help='Frozen parent deadline (UTC), stored at preparation')
    parser.add_argument('--parent-remaining-seconds', type=float, help='Additional parent time cap for this invocation')
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        deadline = datetime.fromisoformat(args.parent_deadline_utc.replace('Z', '+00:00'))
        if deadline.utcoffset() is None:
            raise BoundedError('deadline_requires_timezone')
        if args.parent_remaining_seconds is not None and (not math.isfinite(args.parent_remaining_seconds) or args.parent_remaining_seconds <= 0):
            raise BoundedError('parent_remaining_requires_positive_finite_seconds')
        result = prepare(args) if args.prepare_only else execute(args)
    except Exception as error:
        result = {'status': 'failed', 'research_launched': False,
                  'failure_code': str(error) if isinstance(error, BoundedError) else 'wrapper_exception',
                  'exception_type': type(error).__name__}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['status'] in {'prepared', 'passed'} else 1


if __name__ == '__main__':
    sys.exit(main())
