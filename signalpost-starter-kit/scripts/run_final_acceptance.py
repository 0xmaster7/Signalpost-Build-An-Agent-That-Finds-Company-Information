#!/usr/bin/env python3
"""Prepare or run one frozen final-measurement cohort; never retries a stage."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import heapq
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import random
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = ROOT / "signalpost-starter-kit" / "scripts" / "run_crashsafe_acceptance.py"
SPEC = importlib.util.spec_from_file_location("_final_crashsafe_helper", HELPER_PATH)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
helper.PHASES = (*helper.PHASES[:2], "official_details", *helper.PHASES[2:])
EXPECTED_MATCHED = "acd65b35b1a87ef35c77fa673e4a44b63bd3718b339bc69adddc152889692076"
EXPECTED_REGISTRY = "f2c8f55b47c0a203f91444b1280da00573a44067939da6f06900d559cbde1ece"
STAGES = ("smoke", "matched", "fresh", "scale")


class FinalGateError(RuntimeError):
    pass


def digest(path):
    return helper.digest(path)


def utc():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    helper.write(path, value)


def private_dir(path):
    helper.private_dir(path)


def selection_input(directory, count):
    source = Path(directory) / "companies.jsonl"
    selection = Path(directory) / "selection.json"
    receipt = Path(directory) / "input-receipt.json"
    if not source.is_file() or not (selection.is_file() or receipt.is_file()):
        raise FinalGateError("selection_artifacts_missing")
    info = json.loads((selection if selection.is_file() else receipt).read_text())
    actual = digest(source)
    if info.get("input_sha256") != actual:
        raise FinalGateError("selection_input_hash_mismatch")
    return source, helper.read_input(source, count), info


def freeze_sample(registry, original_selection, destination, *, count, seed, exclusions, fixed_six=False):
    """Select only from the archived eligibility frame, before research outcomes."""
    registry, original_selection, destination = map(Path, (registry, original_selection, destination))
    original = json.loads(original_selection.read_text())
    fixed = set(map(str, original.get("fixed_companies", []))) if fixed_six else set()
    if fixed_six and (len(fixed) != 6 or any(not re.fullmatch(r"\d{9}", company) for company in fixed)):
        raise FinalGateError("original_selection_requires_six_fixed_companies")
    if digest(registry) != original.get("source_file_sha256"):
        raise FinalGateError("archived_registry_hash_mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", seed):
        raise FinalGateError("seed_requires_64_lowercase_hex_digits")
    excluded = set()
    receipts = []
    for directory in exclusions:
        _, orgs, info = selection_input(directory, int(info_count(directory)))
        excluded.update(orgs)
        metadata = Path(directory) / ("selection.json" if (Path(directory) / "selection.json").is_file() else "input-receipt.json")
        receipts.append({"input_sha256": info["input_sha256"], "selection_sha256": digest(metadata)})
    private_dir(destination)
    write(destination / "input-receipt.json", {"status": "selecting", "seed": seed,
        "registry_sha256": digest(registry), "original_selection_sha256": digest(original_selection)})
    wanted_random = count - len(fixed)
    best = []
    fixed_rows = {}
    seen = set()
    eligible_population = source_rows = 0
    csv.field_size_limit(10_000_000)
    with registry.open("rb") as raw:
        compressed = raw.read(2) == b"\x1f\x8b"
        raw.seek(0)
        binary = gzip.GzipFile(fileobj=raw) if compressed else raw
        with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            needed = {"organisasjonsnummer", "navn", "organisasjonsform.kode", "antallAnsatte", "konkurs", "underAvvikling"}
            if not needed <= set(reader.fieldnames or []):
                raise FinalGateError("archived_registry_columns_missing")
            for row in reader:
                source_rows += 1
                org = str(row.get("organisasjonsnummer", "")).strip()
                if not re.fullmatch(r"\d{9}", org) or org in seen:
                    continue
                seen.add(org)
                employees = str(row.get("antallAnsatte", "")).strip()
                inactive = any(str(row.get(key, "")).strip().casefold() in {"ja", "true", "1"}
                    for key in ("konkurs", "underAvvikling", "underTvangsavviklingEllerTvangsopplosning"))
                inactive = inactive or bool(str(row.get("slettedato", "")).strip())
                eligible = row.get("organisasjonsform.kode") == "AS" and employees.isdigit() and int(employees) > 0 and not inactive
                if org in fixed:
                    fixed_rows[org] = {"organisation_number": org, "legal_form": "AS",
                        "registered_employees": int(employees) if employees.isdigit() else None,
                        "eligible_in_selection_frame": bool(eligible), "fixed_six_company_cohort": True}
                if not eligible:
                    continue
                eligible_population += 1
                if org in excluded or org in fixed:
                    continue
                public = {"organisation_number": org, "legal_form": row["organisasjonsform.kode"],
                    "registered_employees": int(employees), "eligible_in_selection_frame": True,
                    "fixed_six_company_cohort": False}
                rank = int(hashlib.sha256((seed + ":" + org).encode()).hexdigest(), 16)
                entry = (-rank, org, public)
                if len(best) < wanted_random:
                    heapq.heappush(best, entry)
                elif wanted_random and entry > best[0]:
                    heapq.heapreplace(best, entry)
    if len(best) != wanted_random or set(fixed_rows) != fixed:
        raise FinalGateError("insufficient_registry_population_or_missing_fixed_company")
    rows = [row for _, _, row in sorted(best, key=lambda entry: -entry[0])] + [fixed_rows[key] for key in sorted(fixed)]
    random.Random(int(seed, 16)).shuffle(rows)
    payload = "".join(json.dumps({"organisation_number": row["organisation_number"]}) + "\n" for row in rows).encode()
    source = destination / "companies.jsonl"
    source.write_bytes(payload)
    os.chmod(source, 0o600)
    receipt = {"status": "frozen", "selected_at_utc": utc(), "seed": seed,
        "method": f"smallest seeded SHA256 ranks without replacement; {count} rows shuffled",
        "population": "active AS employers with registered employees >= 1; no optional-data outcome filters",
        "generalization": "The archived frame defines this selection population; generalization beyond active AS employers is unproven.",
        "registry_sha256": digest(registry), "registry_bytes": registry.stat().st_size,
        "original_selection_sha256": digest(original_selection), "source_rows": source_rows,
        "eligible_population": eligible_population, "fixed_companies": sorted(fixed), "sample_size": count,
        "excluded_cohorts": receipts, "excluded_organisation_numbers": sorted(excluded),
        "random_additions": wanted_random, "input_sha256": hashlib.sha256(payload).hexdigest(),
        "rows": rows}
    write(destination / "input-receipt.json", receipt)
    return receipt


def info_count(directory):
    selection = Path(directory) / "selection.json"
    info = json.loads((selection if selection.is_file() else Path(directory) / "input-receipt.json").read_text())
    return int(info.get("sample_size", 100))


def source_identity(repository):
    return helper.source_identity(Path(repository))


def config_default(budget_seconds):
    reserve = min(300.0, budget_seconds * 0.2)
    return {"budget": {"hard_seconds": budget_seconds, "soft_seconds": budget_seconds - reserve,
        "completion_reserve_seconds": reserve, "physical_request_limit": 8000,
        "financial_seconds": 180, "financial_requests_per_company": 1, "nav_seconds": 360,
        "wikidata_seconds": 12, "website_seconds": 480, "ocr_seconds": 900, "ocr_budget_share": 0.65}}


def stage_seed(base, stage):
    return hashlib.sha256((base + ":" + stage).encode()).hexdigest()


def prepare(args):
    root, repository = args.root.resolve(), args.repository.resolve()
    if root.is_relative_to(repository):
        raise FinalGateError("acceptance_artifacts_must_be_outside_repository")
    if root.exists():
        raise FinalGateError("prepare_root_must_be_new_never_overwrite_attempts")
    if not args.registry or not args.original_selection or not args.matched_selection:
        raise FinalGateError("prepare_requires_registry_original_and_matched_selections")
    if digest(args.registry) != EXPECTED_REGISTRY:
        raise FinalGateError("archived_registry_hash_mismatch")
    matched_path, matched_orgs, _ = selection_input(args.matched_selection, 100)
    if digest(matched_path) != EXPECTED_MATCHED:
        raise FinalGateError("matched_input_hash_mismatch")
    private_dir(root)
    base_seed = args.seed or secrets.token_hex(32)
    if not re.fullmatch(r"[0-9a-f]{64}", base_seed):
        raise FinalGateError("seed_requires_64_lowercase_hex_digits")
    exclusions = list(args.exclude_selection)
    for directory in (args.matched_selection,):
        if Path(directory) not in [Path(exclusion) for exclusion in exclusions]:
            exclusions.append(directory)
    smoke_receipt = freeze_sample(args.registry, args.original_selection, root / "smoke-selection",
        count=10, seed=stage_seed(base_seed, "smoke"), exclusions=exclusions, fixed_six=True)
    frozen_matched = root / "matched-selection"
    private_dir(frozen_matched)
    shutil.copyfile(matched_path, frozen_matched / "companies.jsonl")
    os.chmod(frozen_matched / "companies.jsonl", 0o600)
    write(frozen_matched / "input-receipt.json", {"input_sha256": EXPECTED_MATCHED,
        "selection_sha256": digest(Path(args.matched_selection) / "selection.json"), "sample_size": 100})
    used = set(matched_orgs) | set(helper.read_input(root / "smoke-selection" / "companies.jsonl", 10))
    for directory in exclusions:
        _, orgs, _ = selection_input(directory, info_count(directory))
        used.update(orgs)
    fresh_receipt = freeze_sample(args.registry, args.original_selection, root / "fresh-selection",
        count=100, seed=stage_seed(base_seed, "fresh"), exclusions=exclusions + [root / "smoke-selection"], fixed_six=False)
    fresh_orgs = set(helper.read_input(root / "fresh-selection" / "companies.jsonl", 100))
    if fresh_orgs & used:
        raise FinalGateError("fresh_cohort_overlap")
    used.update(fresh_orgs)
    scale_receipt = freeze_sample(args.registry, args.original_selection, root / "scale-selection",
        count=1000, seed=stage_seed(base_seed, "scale"), exclusions=exclusions + [root / "smoke-selection", root / "fresh-selection"], fixed_six=False)
    scale_orgs = set(helper.read_input(root / "scale-selection" / "companies.jsonl", 1000))
    if scale_orgs & used:
        raise FinalGateError("scale_cohort_overlap")
    config_bytes = (json.dumps(config_default(args.budget_seconds), indent=2) + "\n").encode() if not args.config else args.config.read_bytes()
    config = json.loads(config_bytes)
    if not isinstance(config, dict):
        raise FinalGateError("configuration_requires_object")
    (root / "config.json").write_bytes(config_bytes)
    os.chmod(root / "config.json", 0o600)
    manifest = {"schema_version": 1, "created_at_utc": utc(), "source": source_identity(repository),
        "configuration_sha256": hashlib.sha256(config_bytes).hexdigest(), "budget_seconds": args.budget_seconds,
        "smoke_input_sha256": smoke_receipt["input_sha256"], "matched_input_sha256": EXPECTED_MATCHED,
        "fresh_input_sha256": fresh_receipt["input_sha256"], "scale_input_sha256": scale_receipt["input_sha256"],
        "base_seed": base_seed, "required_phases": list(helper.PHASES), "external_timeout_seconds": args.timeout,
        "cohorts_frozen_before_outcomes": True, "automatic_retry": False,
        "order": ["smoke", "smoke-replay", "matched", "matched-replay", "fresh", "fresh-replay", "scale", "scale-replay"]}
    write(root / "acceptance.json", manifest)
    return {"status": "prepared", "research_launched": False, "frozen_stages": list(STAGES),
        "input_sha256": {key: manifest[key + "_input_sha256"] for key in ("smoke", "matched", "fresh", "scale")}}


def launch(repository, directory, source, config, batch_id, timeout, budget_seconds, capture=None):
    private_dir(directory)
    for name in ("home", "cache", "ocr-cache", "nav-cache"):
        private_dir(directory / name)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("SIGNALPOST_")}
    environment.update(HOME=str(directory / "home"), XDG_CACHE_HOME=str(directory / "cache"),
        SIGNALPOST_OCR_CACHE=str(capture.parent / "ocr-cache" if capture else directory / "ocr-cache"),
        SIGNALPOST_NAV_CACHE=str(capture.parent / "nav-cache" if capture else directory / "nav-cache"),
        TZ="UTC", PYTHONNOUSERSITE="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    command = helper.command(repository, directory, source, config, batch_id, capture) + ["--budget-seconds", str(budget_seconds)]
    record = {"status": "running", "started_at_utc": utc(), "command": command,
        "input_sha256": digest(source), "budget_seconds": budget_seconds, "external_timeout": False}
    write(directory / "invocation.json", record)
    started = time.monotonic()
    with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        os.chmod(directory / "stdout.log", 0o600)
        os.chmod(directory / "stderr.log", 0o600)
        process = subprocess.Popen(command, cwd=directory, env=environment, stdout=stdout, stderr=stderr, start_new_session=True)
        record["pid"] = process.pid
        write(directory / "invocation.json", record)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            record["external_timeout"] = True
            os.killpg(process.pid, 15)
            try:
                code = process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, 9)
                code = process.wait()
    record.update(status="completed" if code == 0 else "failed", exit_code=code,
        elapsed_seconds=round(time.monotonic() - started, 3), completed_at_utc=utc())
    write(directory / "invocation.json", record)


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(len(values) - 1, low + 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def document_audit(checkpoint, orgs):
    """Read only aggregate document audit values and content hashes from checkpoint artifacts."""
    rows = []
    if not checkpoint.is_file():
        return rows
    with sqlite3.connect(checkpoint.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"phase_results", "envelopes"} <= tables:
            return rows
        payloads = {}
        for row in db.execute("SELECT payload FROM envelopes"):
            envelope = json.loads(row[0])
            company = str(envelope.get("organisation_number", ""))
            if company in orgs:
                payloads[company] = envelope
        sys.path.insert(0, str(ROOT))
        try:
            from signalpost.operations import _checkpoint_decode
            for company, payload in db.execute("SELECT company,payload FROM phase_results WHERE phase='annual_documents'"):
                if company not in orgs:
                    continue
                decoded = _checkpoint_decode(json.loads(payload))
                obs = getattr(decoded, "observations", {}) or {}
                audit = obs.get("annual_accounts_document", {}) if isinstance(obs, dict) else {}
                envelope = payloads.get(company, {})
                hashes = sorted({str(item.get("content_sha256")) for item in envelope.get("source_snapshots", [])
                    if isinstance(item, dict) and re.fullmatch(r"[0-9a-f]{64}", str(item.get("content_sha256", "")))
                    and "annual-document" in str(item.get("source_id", ""))})
                for doc_hash in hashes or [None]:
                    rows.append({"organisation_number": company, "document_sha256": doc_hash,
                        "seconds": audit.get("worker_seconds"), "text_layer_pages": audit.get("text_layer_pages"),
                        "processing_seconds": audit.get("processing_seconds"),
                        "download_seconds": audit.get("download_seconds"),
                        "text_layer_seconds": audit.get("text_layer_seconds"),
                        "ocr_engine_seconds": audit.get("ocr_engine_seconds"),
                        "ocr_pages": audit.get("ocr_pages"), "resolution_method": audit.get("resolved_method") or audit.get("extraction_method")})
        finally:
            if sys.path and sys.path[0] == str(ROOT):
                sys.path.pop(0)
    return rows


def scale_summary(directory, orgs, replay=False, live_directory=None):
    """Operational-only summary: never reads claim values or calculates coverage."""
    output = directory / "envelopes.jsonl"
    rows = [json.loads(line) for line in output.read_text().splitlines() if line.strip()] if output.exists() else []
    identity = helper.collision_evidence(rows)
    checkpoint = helper.checkpoint_metrics(directory / "checkpoint.sqlite", orgs, helper.PHASES)
    events = list(helper.log_events(directory / "stdout.log")) + list(helper.log_events(directory / "stderr.log"))
    batches = [event for event in events if event.get("event") == "batch_complete"]
    batch = batches[-1] if batches else {}
    invocation_path = directory / "invocation.json"
    invocation = json.loads(invocation_path.read_text()) if invocation_path.exists() else {}
    order = [str(row.get("organisation_number", "")) for row in rows]
    statuses = Counter(str(row.get("run", {}).get("terminal_status", "absent")) for row in rows)
    terminal_states = Counter(str(row.get("terminal_state", "absent")) for row in rows)
    gates = {"process_succeeded": invocation.get("exit_code") == 0 and not invocation.get("external_timeout", False),
        "exact_final_cardinality_and_order": order == orgs,
        "zero_aborted_inputs": statuses["aborted"] == terminal_states["aborted"] == 0
            and checkpoint.get("shell_states", {}).get("aborted", 0) == 0,
        "zero_duplicate_ids": identity["duplicate_count"] == identity["conflicting_identifier_count"] == identity["missing_identifier_count"] == 0,
        "durable_company_phase_metrics_complete": checkpoint.get("complete") is True,
        "completion_aggregate_present": len(batches) == 1 and batch.get("output_cardinality") == len(orgs)
            and helper._number(batch.get("runtime_seconds")) and helper._number(batch.get("finalization_seconds"))}
    budget = invocation.get("budget_seconds")
    gates["runtime_within_budget"] = helper._number(batch.get("runtime_seconds")) and helper._number(budget) \
        and batch["runtime_seconds"] <= budget
    report = {"status": "failed", "gate_pass": False, "execution_gate_pass": False, "gates": gates,
        "final_envelopes": len(rows), "run_statuses": dict(statuses), "terminal_states": dict(terminal_states),
        "phase_failed": checkpoint.get("failed", 0),
        "elapsed_seconds": invocation.get("elapsed_seconds"), "exit_code": invocation.get("exit_code"),
        "budget_seconds": budget,
        "runtime_seconds": batch.get("runtime_seconds") if helper._number(batch.get("runtime_seconds")) else None,
        "phase_wall_seconds": {phase: values.get("wall_seconds") for phase, values in
            batch.get("scheduler_passes", {}).get("optional_phases", {}).items()
            if phase in helper.PHASES and isinstance(values, dict) and helper._number(values.get("wall_seconds"))},
        "finalization_seconds": batch.get("finalization_seconds"), "checkpoint": checkpoint,
        "duplicate_count": identity["duplicate_count"], "conflicting_identifier_count": identity["conflicting_identifier_count"],
        "missing_identifier_count": identity["missing_identifier_count"],
        "artifacts": {name: digest(directory / name) for name in
            ("envelopes.jsonl", "state.json", "checkpoint.sqlite", "stdout.log", "stderr.log", "invocation.json")
            if (directory / name).is_file()}}
    if replay:
        totals = [event for event in events if event.get("event") in {"replay_complete", "replay_failed"}]
        summary = totals[-1] if totals else batch
        miss_keys = ("http_misses", "http_failures", "ocr_misses")
        misses = {key: summary.get(key) for key in miss_keys}
        complete = all(helper._number(value) for value in misses.values()) and all(key in summary for key in
            ("capture_complete", "missing_requests", "unconsumed_requests"))
        gates["replay_aggregate_keys_present"] = complete and "research_mode" in batch and "actual_network_requests" in batch
        gates["replay_zero_misses_and_network"] = complete and all(value == 0 for value in misses.values()) \
            and batch.get("research_mode") == "replay" and batch.get("actual_network_requests") == 0
        gates["replay_capture_sealed_and_fully_consumed"] = summary.get("capture_complete") is True \
            and summary.get("missing_requests") == [] and summary.get("unconsumed_requests") == []
        gates["exact_output_bytes_equal"] = bool(live_directory and output.is_file()
            and (live_directory / "envelopes.jsonl").is_file()
            and output.read_bytes() == (live_directory / "envelopes.jsonl").read_bytes())
        gates["exact_state_bytes_equal"] = bool(live_directory and (directory / "state.json").is_file()
            and (live_directory / "state.json").is_file()
            and (directory / "state.json").read_bytes() == (live_directory / "state.json").read_bytes())
        report["replay_misses"] = misses
        report["replay_missing_request_keys"] = len(summary["missing_requests"]) if isinstance(summary.get("missing_requests"), list) else None
        report["replay_unconsumed_request_keys"] = len(summary["unconsumed_requests"]) if isinstance(summary.get("unconsumed_requests"), list) else None
    report["gate_pass"] = all(gates.values())
    report["execution_gate_pass"] = report["gate_pass"]
    report["status"] = "passed" if report["gate_pass"] else "failed"
    return report


def sanitized_report(directory, orgs, stage, replay, live_directory=None):
    base = scale_summary(directory, orgs, replay, live_directory) if stage == "scale" \
        else helper.summarize(directory, orgs, helper.PHASES, replay, live_directory)
    keys = ("gate_pass", "execution_gate_pass", "gates", "final_envelopes", "terminal_states", "run_statuses",
        "aborted_inputs", "failed_finals", "partial_finals", "unfinalized_inputs", "phase_failed", "elapsed_seconds",
        "exit_code", "budget_seconds", "runtime_seconds", "phase_wall_seconds", "finalization_seconds", "checkpoint", "quality_observations",
        "duplicate_count", "conflicting_identifier_count", "missing_identifier_count", "replay_misses",
        "replay_missing_request_keys", "replay_unconsumed_request_keys", "artifacts")
    report = {key: base.get(key) for key in keys if key in base}
    report.update(status=base.get("status"), stage=stage, replay=bool(replay),
        wrong_company_audit="UNKNOWN: parent manual review required",
        population="active AS employers with registered employees >= 1; generalization beyond this frame is unproven")
    report["phase_status_counts"] = {phase: {
        "ran": counters["ran"] - counters["failed"],
        "skipped": counters["skipped"] - counters["deadline_skipped"],
        "deadline_skipped": counters["deadline_skipped"], "failed": counters["failed"],
        "company_seconds": counters["worker_seconds"],
        "wall_seconds": base.get("phase_wall_seconds", {}).get(phase),
    } for phase, counters in base.get("checkpoint", {}).get("phase_counters", {}).items()}
    if len(orgs) == 100:
        report["company_counts"] = base.get("company_counts")
    if stage == "scale":
        report.pop("company_counts", None)
        report.pop("quality_observations", None)
        report["scale_rows"] = base.get("final_envelopes")
        report["scale_order_and_duplicates"] = {"exact_final_cardinality_and_order": base.get("gates", {}).get("exact_final_cardinality_and_order"),
            "duplicate_count": base.get("duplicate_count"), "missing_identifier_count": base.get("missing_identifier_count")}
    if len(orgs) in (100, 1000) and not replay:
        company_seconds = []
        company_totals = Counter()
        phase_company = {}
        with sqlite3.connect((directory / "checkpoint.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='phase_status'").fetchone():
                for row in db.execute("SELECT phase,company,payload FROM phase_status"):
                    payload = json.loads(row["payload"])
                    phase = "official_foundation" if row["phase"] == "official" else row["phase"]
                    if isinstance(payload.get("seconds"), (int, float)) and math.isfinite(payload["seconds"]):
                        if phase not in {"nav_batch", "wiki_batch"}:
                            company_seconds.append(float(payload["seconds"]))
                            company_totals[row["company"]] += float(payload["seconds"])
                            phase_company.setdefault(phase, []).append(float(payload["seconds"]))
        report["timing_percentiles"] = {"definition": "linear-interpolated percentiles over company-phase seconds; excludes shared nav_batch and wiki_batch; foundation is queue-inclusive when recorded",
            "company_phase_worker_time_p50_seconds": percentile(company_seconds, .5),
            "company_phase_worker_time_p95_seconds": percentile(company_seconds, .95),
            "company_total_recorded_seconds_p50": percentile(list(company_totals.values()), .5),
            "company_total_recorded_seconds_p95": percentile(list(company_totals.values()), .95),
            "phase_p50_p95_seconds": {name: {"p50": percentile(vals, .5), "p95": percentile(vals, .95)} for name, vals in sorted(phase_company.items())}}
        if len(orgs) == 100:
            report["document_table"] = document_audit(directory / "checkpoint.sqlite", set(orgs))
    return report


def require_prior(root, name):
    directory = root / name
    report_path = directory / "report.json"
    if not report_path.is_file():
        raise FinalGateError("prerequisite_stage_missing")
    report = json.loads(report_path.read_text())
    gates = report.get("gates", {})
    if report.get("execution_gate_pass") is not True or not gates or not all(
            value for key, value in gates.items() if key not in helper.MEASUREMENT_GATES):
        raise FinalGateError("prerequisite_execution_or_replay_failed")
    return report


def execute_stage(args):
    root, repository = args.root.resolve(), args.repository.resolve()
    if root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
        raise FinalGateError("acceptance_root_requires_private_directory")
    manifest = json.loads((root / "acceptance.json").read_text())
    if source_identity(repository) != manifest["source"] or digest(root / "config.json") != manifest["configuration_sha256"]:
        raise FinalGateError("frozen_head_source_or_configuration_changed")
    stage = args.stage
    if stage == "smoke":
        if args.allow_stage:
            raise FinalGateError("smoke_does_not_use_large_stage_allow_flag")
    elif not args.allow_stage:
        raise FinalGateError("stage_requires_explicit_allow_stage")
    if stage in {"fresh", "scale"}:
        require_prior(root, "matched")
        require_prior(root, "matched-replay")
    if stage == "scale" and (args.include_scale_coverage or args.scale_worker_metrics):
        raise FinalGateError("scale_is_operational_measurement_only")
    for preceding in {"matched": ("smoke", "smoke-replay"), "fresh": ("matched", "matched-replay"),
                      "scale": ("matched", "matched-replay")}.get(stage, ()):
        require_prior(root, preceding)
    source = root / (stage + "-selection") / "companies.jsonl"
    count = {"smoke": 10, "matched": 100, "fresh": 100, "scale": 1000}[stage]
    orgs = helper.read_input(source, count)
    if digest(source) != manifest[stage + "_input_sha256"]:
        raise FinalGateError("frozen_cohort_input_changed")
    live, replay = root / stage, root / (stage + "-replay")
    if live.exists() or replay.exists():
        raise FinalGateError("stage_already_attempted_no_automatic_retry")
    for directory, capture in ((live, None), (replay, live / "http-capture")):
        if source_identity(repository) != manifest["source"] or digest(root / "config.json") != manifest["configuration_sha256"]:
            raise FinalGateError("frozen_head_source_or_configuration_changed")
        try:
            launch(repository, directory, source, root / "config.json", "final-" + stage,
                manifest["external_timeout_seconds"], manifest["budget_seconds"], capture)
            report = sanitized_report(directory, orgs, stage, bool(capture), live)
        except BaseException as error:
            report = {"status": "failed", "stage": stage, "replay": bool(capture), "gate_pass": False,
                "execution_gate_pass": False, "gates": {"wrapper_completed": False},
                "failure_code": "wrapper_exception", "exception_type": type(error).__name__,
                "traceback_frames": [{"function": frame.name, "line": frame.lineno} for frame in traceback.extract_tb(error.__traceback__)[-20:]]}
        write(directory / "report.json", report)
        if not report.get("execution_gate_pass", False):
            return {"status": "failed", "failed_stage": directory.name, "gate_pass": False,
                "subsequent_stages_launched": False}
    return {"status": "passed" if json.loads((live / "report.json").read_text()).get("gate_pass") else "measurement_failed",
        "stage": stage, "subsequent_stages_launched": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--original-selection", type=Path)
    parser.add_argument("--matched-selection", type=Path)
    parser.add_argument("--exclude-selection", type=Path, action="append", default=[])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--seed", help="Predeclared base seed; 64 lowercase hexadecimal digits")
    parser.add_argument("--budget-seconds", type=float, default=1800.0)
    parser.add_argument("--timeout", type=float, default=2100.0)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--stage", choices=STAGES, default="smoke")
    parser.add_argument("--allow-stage", action="store_true", help="Explicitly allow the selected cohort stage")
    parser.add_argument("--include-scale-coverage", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scale-worker-metrics", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0 or not math.isfinite(args.budget_seconds) or args.budget_seconds <= 0:
            raise FinalGateError("budget_and_timeout_require_positive_finite_seconds")
        result = prepare(args) if args.prepare_only else execute_stage(args)
    except BaseException as error:
        result = {"status": "failed", "research_launched": False, "failure_code": str(error) if isinstance(error, FinalGateError) else "wrapper_exception",
            "exception_type": type(error).__name__, "traceback_frames": [{"function": frame.name, "line": frame.lineno}
                for frame in traceback.extract_tb(error.__traceback__)[-20:]]}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["status"] in {"prepared", "passed", "measurement_failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
