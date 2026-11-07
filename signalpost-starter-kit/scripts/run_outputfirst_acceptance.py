#!/usr/bin/env python3
"""Freeze and manually gate output-first runs (200/360s, then 1000/1800s).

On the host with /home/azureuser/projects/signalpost-bounded-source-fc39bb0:
  python scripts/run_outputfirst_acceptance.py --root /private/outputfirst-new --prepare-only
  python scripts/run_outputfirst_acceptance.py --root /private/outputfirst-new --stage 200
  python scripts/run_outputfirst_acceptance.py --root /private/outputfirst-new --stage 1000

Use --repository /path/to/signalpost if necessary. Preparation freezes the existing
source companies.jsonl and config.json, without research. Each explicit stage runs
run.sh with --output-first --record-http and that frozen config. The 1000 stage
requires recomputed passing 200 evidence. No retries, replay, or chained stages.
The default parent deadline is 2026-11-07T11:29:57Z; override at preparation only.
State pairing, recording, checkpoint and aggregate metrics are secondary; absent
aggregate values are unknown, never inferred as zero. Only clean exit within the
stage budget and complete valid committed output with zero duplicate IDs gate.
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
import signal
import subprocess
import sys
import time

SPEC = importlib.util.spec_from_file_location('_outputfirst_bounded', Path(__file__).with_name('run_bounded_acceptance.py'))
bounded = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bounded)
helper, final = bounded.helper, bounded.final
STAGES = {'200': (200, 360, 400), '1000': (1000, 1800, 1830)}
MANIFEST = 'outputfirst-acceptance.json'
OutputFirstError = bounded.BoundedError


def prepare(args):
    result = bounded.prepare(args)
    root = args.root.resolve()
    manifest = bounded.load(root / 'bounded-acceptance.json')
    manifest.update(acceptance_mode='output-first', stages={name: {
        'count': count, 'budget_seconds': budget, 'external_watch_seconds': watch,
    } for name, (count, budget, watch) in STAGES.items()})
    helper.write(root / MANIFEST, manifest)
    (root / 'bounded-acceptance.json').unlink()
    return {**result, 'acceptance_mode': 'output-first', 'frozen_stages': list(STAGES)}


def publication(directory):
    """Check the metadata hash, path, bytes and either durable commit status."""
    try:
        path = directory / 'envelopes.jsonl.publication.json'
        if path.is_symlink():
            return False
        marker = bounded.load(path)
        content = {key: value for key, value in marker.items() if key != 'marker_sha256'}
        expected = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
            separators=(',', ':')).encode()).hexdigest()
        if (marker.get('marker_sha256') != expected
                or not isinstance(marker.get('publication_id'), str) or not marker['publication_id']
                or Path(marker['output_path']).resolve() != (directory / 'envelopes.jsonl').resolve()
                or marker.get('output_sha256') != helper.digest(directory / 'envelopes.jsonl')):
            return False
        if marker.get('status') == 'output_committed':
            return marker.get('output_committed') is True
        return bounded.committed_pair(directory)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def validate_output(path, repository):
    """Reconstruct every vendor row as Envelope, then run the publication adapter.

    Imports come from the frozen repository. No source values or validation error
    messages are copied to the report. Shared identical provenance IDs across rows
    use the repository's collision semantics; duplicate claims or local IDs fail.
    """
    sys.path.insert(0, str(repository))
    try:
        from signalpost.adapter import to_evaluator, validate_vendor_payload
        from signalpost.models import Envelope, validate_batch_publication_graph
        rows, envelopes, invalid = [], [], []
        with path.open(encoding='utf-8') as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line, parse_constant=reject_nonfinite)
                    if not isinstance(raw, dict):
                        raise ValueError('envelope_requires_object')
                    validate_vendor_payload(raw)
                    rows.append(raw)
                    envelope = Envelope.model_validate({
                        **{key: raw[key] for key in ('input_ref', 'organisation_number', 'terminal_state',
                            'sections', 'claims', 'evidence', 'source_snapshots', 'refresh', 'synthesis', 'errors', 'operations')},
                        'row_number': len(rows), 'batch_id': raw['batch']['batch_id'],
                        'evidence_cutoff': raw['batch']['evidence_cutoff'], 'created_at': raw['run']['created_at'],
                    })
                    to_evaluator(envelope)
                    envelopes.append(envelope)
                except (ValueError, TypeError, KeyError, AttributeError):
                    invalid.append(number)
        batch_valid = True
        try:
            validate_batch_publication_graph(envelopes)
        except ValueError:
            batch_valid = False
        # Malformed nested arrays cannot be passed to the collision helper.
        identity = helper.collision_evidence([item.model_dump(mode='json') for item in envelopes])
        return rows, {'valid': not invalid and batch_valid, 'invalid_line_numbers': invalid,
                      'batch_graph_valid': batch_valid, **identity}
    finally:
        sys.path.pop(0)


def reject_nonfinite(value):
    raise ValueError('nonfinite_json')


def secondary_events(path):
    # Log availability/format cannot veto valid output. Nonfinite log metrics
    # are unknown rather than invalid JSON in the acceptance report.
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {key: finite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [finite(item) for item in value]
        return value
    try:
        return [finite(event) for event in helper.log_events(path)]
    except OSError:
        return []


def summarize(directory, orgs, stage, manifest, repository=None):
    repository = Path(repository or final.ROOT)
    invocation = bounded.load(directory / 'invocation.json') if (directory / 'invocation.json').is_file() else {}
    try:
        rows, validation = validate_output(directory / 'envelopes.jsonl', repository)
    except (OSError, UnicodeError, ValueError, TypeError):
        rows, validation = [], {'valid': False, 'invalid_line_numbers': [], 'duplicate_count': None,
            'conflicting_identifier_count': None, 'missing_identifier_count': None}
    budget = STAGES[stage][1]
    order = [row.get('organisation_number') for row in rows if isinstance(row, dict)]
    input_refs = [row.get('input_ref') for row in rows if isinstance(row, dict)]
    gates = {
        'process_succeeded': type(invocation.get('exit_code')) is int and invocation['exit_code'] == 0
            and invocation.get('external_timeout') is False and invocation.get('status') == 'completed',
        'process_elapsed_within_budget': helper._number(invocation.get('elapsed_seconds')) and invocation['elapsed_seconds'] <= budget,
        'complete_valid_output': validation['valid'] and order == orgs,
        'zero_duplicate_ids': validation['duplicate_count'] == 0 and validation['conflicting_identifier_count'] == 0
            and validation['missing_identifier_count'] == 0
            and all(isinstance(value, str) and value for value in input_refs)
            and len(input_refs) == len(set(input_refs)),
        'committed_output': publication(directory),
    }
    events = secondary_events(directory / 'stdout.log') + secondary_events(directory / 'stderr.log')
    batches = [event for event in events if event.get('event') == 'batch_complete']
    aggregate = batches[-1] if batches else None
    recordings = [event for event in events if event.get('event') in {'recording_complete', 'recording_failed'}]
    counts = {'finance_companies': 0, 'explicit_fte_companies': 0,
        'verified_website_companies': 0, 'jobs_companies': 0}
    for row in (rows if validation['valid'] else []):
        available = [claim for claim in row.get('claims', []) if claim.get('state') == 'available']
        counts['finance_companies'] += any(claim.get('field') in helper.FINANCIAL
            and isinstance(claim.get('value'), (int, float)) and not isinstance(claim['value'], bool)
            and helper._number(abs(claim['value'])) for claim in available)
        counts['explicit_fte_companies'] += any(claim.get('field') == 'full_time_equivalents' for claim in available)
        counts['verified_website_companies'] += any(claim.get('field') == 'verified_website_url' for claim in available)
        counts['jobs_companies'] += any(claim.get('field_family') == 'jobs' and claim.get('scope') == 'job' for claim in available)
    try:
        checkpoint = helper.checkpoint_metrics(directory / 'checkpoint.sqlite', orgs,
            manifest.get('required_phases', helper.PHASES))
    except Exception:
        checkpoint = {'complete': False, 'problems': ['checkpoint_metrics_unreadable']}
    passed = all(value is True for value in gates.values())
    return {'status': 'passed' if passed else 'failed', 'acceptance_mode': 'output-first', 'stage': stage,
        'budget_seconds': budget, 'elapsed_seconds': invocation.get('elapsed_seconds'), 'exit_code': invocation.get('exit_code'),
        'gates': gates, 'gate_pass': passed, 'execution_gate_pass': passed,
        'final_envelopes': len(rows), 'validation': validation,
        'duplicate_count': validation['duplicate_count'],
        'conflicting_identifier_count': validation['conflicting_identifier_count'],
        'missing_identifier_count': validation['missing_identifier_count'],
        'counts': counts if validation['valid'] else None,
        'checkpoint': checkpoint,
        'aggregate_status': 'known' if aggregate is not None else 'unknown', 'aggregate': aggregate,
        'runtime_seconds': aggregate.get('runtime_seconds') if aggregate else None,
        'requests_by_purpose': aggregate.get('requests_by_purpose') if aggregate else None,
        'secondary': {'committed_output_state_pair': bounded.committed_pair(directory),
            'recording_status': recordings[-1].get('event') if recordings else 'unknown',
            'recording_capture_complete': recordings[-1].get('capture_complete') if recordings else None},
        'secondary_note': 'State pairing, aggregate/runtime metrics and recording never veto the operational output gate.',
        'subsequent_stages_launched': False}


def prior(root, manifest, repository):
    path = root / '200' / 'report.json'
    if not path.is_file() or bounded.load(path).get('execution_gate_pass') is not True:
        raise OutputFirstError('prerequisite_200_success_required')
    orgs = helper.read_input(root / '200-selection' / 'companies.jsonl', 200)
    if not summarize(root / '200', orgs, '200', manifest, repository)['execution_gate_pass']:
        raise OutputFirstError('prerequisite_200_evidence_changed')


def launch(repository, directory, source, config, stage):
    _, budget, watch = STAGES[stage]
    helper.private_dir(directory)
    for name in ('home', 'cache', 'ocr-cache', 'nav-cache'):
        helper.private_dir(directory / name)
    environment = {key: value for key, value in os.environ.items() if not key.startswith('SIGNALPOST_')}
    environment.update(HOME=str(directory / 'home'), XDG_CACHE_HOME=str(directory / 'cache'),
        SIGNALPOST_OCR_CACHE=str(directory / 'ocr-cache'), SIGNALPOST_NAV_CACHE=str(directory / 'nav-cache'),
        TZ='UTC', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    command = helper.command(repository, directory, source, config, 'outputfirst-' + stage) + [
        '--output-first', '--budget-seconds', str(budget)]
    record = {'status': 'running', 'started_at_utc': final.utc(), 'command': command,
        'input_sha256': helper.digest(source), 'budget_seconds': budget, 'external_timeout': False}
    helper.write(directory / 'invocation.json', record)
    started = time.monotonic()
    with (directory / 'stdout.log').open('wb') as stdout, (directory / 'stderr.log').open('wb') as stderr:
        process = subprocess.Popen(command, cwd=directory, env=environment, stdout=stdout, stderr=stderr, start_new_session=True)
        record['pid'] = process.pid
        helper.write(directory / 'invocation.json', record)
        try:
            code = process.wait(timeout=watch)
        except subprocess.TimeoutExpired:
            record['external_timeout'] = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                code = process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
    record.update(status='completed' if code == 0 else 'failed', exit_code=code,
        elapsed_seconds=time.monotonic() - started, completed_at_utc=final.utc())
    helper.write(directory / 'invocation.json', record)


def execute(args):
    root, repository = args.root.resolve(), args.repository.resolve()
    if args.root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
        raise OutputFirstError('root_requires_private_directory')
    manifest = bounded.load(root / MANIFEST)
    if manifest.get('acceptance_mode') != 'output-first':
        raise OutputFirstError('outputfirst_manifest_required')
    if final.source_identity(repository) != manifest['source'] or helper.digest(root / 'config.json') != manifest['configuration_sha256']:
        raise OutputFirstError('frozen_source_or_configuration_changed')
    for name, expected in manifest['inputs'].items():
        if helper.digest(root / (name + '-selection') / 'companies.jsonl') != expected:
            raise OutputFirstError('frozen_input_changed')
    stage = args.stage
    if stage == '1000':
        prior(root, manifest, repository)
    deadline = datetime.fromisoformat(manifest['parent_deadline_utc'].replace('Z', '+00:00'))
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
    if args.parent_remaining_seconds is not None:
        remaining = min(remaining, args.parent_remaining_seconds)
    if remaining < STAGES[stage][2] + 20:
        raise OutputFirstError('insufficient_parent_time_for_live_stage')
    directory = root / stage
    if directory.exists() or (root / (stage + '.attempt.json')).exists():
        raise OutputFirstError('stage_already_attempted_no_retry')
    with (root / (stage + '.attempt.json')).open('x') as stream:
        json.dump({'stage': stage, 'started_at_utc': final.utc()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    source = root / (stage + '-selection') / 'companies.jsonl'
    orgs = helper.read_input(source, STAGES[stage][0])
    try:
        launch(repository, directory, source, root / 'config.json', stage)
        report = summarize(directory, orgs, stage, manifest, repository)
    except BaseException as error:
        report = {'status': 'failed', 'stage': stage, 'execution_gate_pass': False, 'gate_pass': False,
            'failure_code': 'wrapper_exception', 'exception_type': type(error).__name__, 'subsequent_stages_launched': False}
    if directory.is_dir():
        helper.write(directory / 'report.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, default=bounded.DEFAULT_SOURCE / 'companies.jsonl')
    parser.add_argument('--config', type=Path, default=bounded.DEFAULT_SOURCE / 'config.json')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--repository', type=Path, default=final.ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--stage', choices=STAGES)
    parser.add_argument('--parent-deadline-utc', default='2026-11-07T11:29:57Z', help='Frozen at preparation')
    parser.add_argument('--parent-remaining-seconds', type=float)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        deadline = datetime.fromisoformat(args.parent_deadline_utc.replace('Z', '+00:00'))
        if deadline.utcoffset() is None:
            raise OutputFirstError('deadline_requires_timezone')
        if args.parent_remaining_seconds is not None and (not math.isfinite(args.parent_remaining_seconds) or args.parent_remaining_seconds <= 0):
            raise OutputFirstError('parent_remaining_requires_positive_finite_seconds')
        result = prepare(args) if args.prepare_only else execute(args)
    except Exception as error:
        result = {'status': 'failed', 'research_launched': False,
            'failure_code': str(error) if isinstance(error, OutputFirstError) else 'wrapper_exception',
            'exception_type': type(error).__name__}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['status'] in {'prepared', 'passed'} else 1


if __name__ == '__main__':
    sys.exit(main())
