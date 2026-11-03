#!/usr/bin/env python3
"""Fail-closed smoke -> matched/replay -> holdout acceptance, never retrying a run.

Only this wrapper launches run.sh. Importing the module and --prepare-only do no
research. See crashsafe_acceptance_usage.md for the durable metrics contract.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import heapq
import io
import json
import math
import os
from pathlib import Path
import random
import re
import secrets
import signal
import sqlite3
import subprocess
import traceback
import time


ROOT = Path(__file__).resolve().parents[2]
COUNTERS = ("ran", "skipped", "deadline_skipped", "failed", "ineligible", "not_attempted")
PHASES = ("official_foundation", "financial_statements", "wiki_batch", "nav_batch", "nav_apply",
          "website_verify", "website_shallow", "jobs_activity", "annual_documents", "finalization")
MEASUREMENT_GATES = {"runtime_within_1200_seconds", "finance_at_least_95", "explicit_fte_at_least_50",
    "verified_websites_at_least_20"}
DEFAULT_CONFIG = {"budget": {"hard_seconds": 2700, "soft_seconds": 2214, "completion_reserve_seconds": 486,
    "physical_request_limit": 2000, "financial_seconds": 180, "financial_requests_per_company": 1,
    "nav_seconds": 360, "wikidata_seconds": 12, "website_seconds": 480, "ocr_seconds": 900, "ocr_budget_share": 0.65}}
FINANCIAL = set("sales_revenue operating_costs payroll_costs net_financial_items tax_expense fixed_assets "
    "current_assets receivables cash paid_in_equity retained_earnings short_term_debt long_term_debt "
    "financial_income financial_costs total_comprehensive_result revenue operating_result profit_before_tax "
    "annual_result total_assets equity total_debt".split())


class GateError(RuntimeError):
    """Messages are wrapper-owned codes, never arbitrary child error text."""


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def private_dir(path):
    path.mkdir(mode=0o700)
    os.chmod(path, 0o700)


def read_input(path, count):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    orgs = [str(row["organisation_number"]) for row in rows]
    if len(orgs) != count or len(set(orgs)) != count or any(not re.fullmatch(r"\d{9}", org) for org in orgs):
        raise GateError("input_requires_expected_unique_organisations")
    return orgs


def freeze_smoke(registry, original_selection, destination, seed=None, exclude_selections=()):
    """Sample solely from the archived registry, before source outcomes exist."""
    original = json.loads(original_selection.read_text())
    fixed = {str(org) for org in original["fixed_companies"]}
    if len(fixed) != 6 or any(not re.fullmatch(r"\d{9}", org) for org in fixed):
        raise GateError("original_selection_requires_six_fixed_companies")
    registry_hash = digest(registry)
    if registry_hash != original["source_file_sha256"]:
        raise GateError("archived_registry_hash_mismatch")
    excluded, exclusion_receipts = set(), []
    for directory in exclude_selections:
        selection = json.loads((directory / "selection.json").read_text())
        source = directory / "companies.jsonl"
        if digest(source) != selection["input_sha256"]:
            raise GateError("excluded_cohort_hash_mismatch")
        excluded.update(read_input(source, 100))
        exclusion_receipts.append({"input_sha256": digest(source), "selection_sha256": digest(directory / "selection.json")})
    private_dir(destination)
    seed = seed or secrets.token_hex(32)
    if not re.fullmatch(r"[0-9a-f]{64}", seed):
        raise GateError("seed_requires_64_lowercase_hex_digits")
    write(destination / "input-receipt.json", {"status": "selecting", "seed": seed,
        "registry_sha256": registry_hash, "original_selection_sha256": digest(original_selection)})
    seen, fixed_rows, best = set(), {}, []
    population = source_rows = 0
    csv.field_size_limit(10_000_000)
    with registry.open("rb") as raw:
        compressed = raw.read(2) == b"\x1f\x8b"
        raw.seek(0)
        binary = gzip.GzipFile(fileobj=raw) if compressed else raw
        with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"organisasjonsnummer", "navn", "organisasjonsform.kode", "antallAnsatte",
                        "konkurs", "underAvvikling"}
            if not required <= set(reader.fieldnames or []):
                raise GateError("archived_registry_columns_missing")
            for row in reader:
                source_rows += 1
                org = str(row["organisasjonsnummer"]).strip()
                if not re.fullmatch(r"\d{9}", org) or org in seen:
                    continue
                seen.add(org)
                employees = str(row["antallAnsatte"]).strip()
                inactive = any(str(row.get(key, "")).strip().casefold() in {"ja", "true", "1"}
                    for key in ("konkurs", "underAvvikling", "underTvangsavviklingEllerTvangsopplosning"))
                inactive = inactive or bool(str(row.get("slettedato", "")).strip())
                eligible = row["organisasjonsform.kode"] == "AS" and employees.isdigit() and int(employees) > 0 and not inactive
                public = {"organisation_number": org, "legal_form": row["organisasjonsform.kode"],
                    "registered_employees": int(employees) if employees.isdigit() else None,
                    "eligible_in_selection_frame": bool(eligible), "fixed_six_company_cohort": org in fixed}
                if org in fixed:
                    fixed_rows[org] = public
                if not eligible:
                    continue
                population += 1
                if org in fixed or org in excluded:
                    continue
                rank = int(sha((seed + ":" + org).encode()), 16)
                entry = (-rank, org, public)
                if len(best) < 4:
                    heapq.heappush(best, entry)
                elif entry > best[0]:
                    heapq.heapreplace(best, entry)
    if set(fixed_rows) != fixed or len(best) != 4:
        raise GateError("insufficient_registry_population_or_missing_fixed_company")
    rows = [row for _, _, row in sorted(best, key=lambda entry: -entry[0])] + [fixed_rows[org] for org in sorted(fixed)]
    random.Random(int(seed, 16)).shuffle(rows)
    payload = "".join(json.dumps({"organisation_number": row["organisation_number"]}) + "\n" for row in rows).encode()
    source = destination / "companies.jsonl"
    source.write_bytes(payload)
    os.chmod(source, 0o600)
    receipt = {"status": "frozen", "selected_at_utc": utc(), "seed": seed,
        "method": "four smallest seeded SHA256 ranks without replacement excluding fixed six; shuffle all ten",
        "population": "active AS employers with registered employees >= 1; no optional-data outcome filters",
        "registry_sha256": registry_hash, "registry_bytes": registry.stat().st_size,
        "original_selection_sha256": digest(original_selection), "source_rows": source_rows,
        "eligible_population": population, "fixed_companies": sorted(fixed), "sample_size": 10,
        "excluded_cohorts": exclusion_receipts, "excluded_organisation_numbers": sorted(excluded),
        "random_additions": 4, "input_sha256": sha(payload), "rows": rows}
    write(destination / "input-receipt.json", receipt)
    return receipt


def source_identity(repository):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
    names = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=repository)
    value = hashlib.sha256()
    for name in sorted(set(names.split(b"\0")) - {b""}):
        path = repository / os.fsdecode(name)
        if path.suffix not in {".py", ".sh", ".toml", ".lock", ".json", ".yaml", ".yml"}:
            continue
        value.update(name + b"\0")
        value.update((digest(path) if path.is_file() else "MISSING").encode() + b"\0")
    return {"head": head, "source_sha256": value.hexdigest()}


def require_frozen(root, repository, manifest):
    if source_identity(repository) != manifest["source"] or digest(root / "config.json") != manifest["configuration_sha256"]:
        raise GateError("frozen_head_source_or_configuration_changed")
    if digest(root / "smoke-selection" / "companies.jsonl") != manifest["smoke_input_sha256"]:
        raise GateError("frozen_smoke_input_changed")


def _number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def checkpoint_metrics(path, orgs, required_phases=PHASES):
    """Read durable counters, never infer success from logs or phase_results.

    Supported adapters: native phase_status payloads; company_phase_metrics/phase_metrics table, with
    company (or organisation_number), phase, and numeric columns or JSON payload;
    or run_meta.company_phase_metrics JSON list of the same records. No writes.
    """
    report = {"complete": False, "shell_states": {}, "final_envelopes": 0,
              "company_phase_rows": 0, "phase_counters": {}, "failed": 0, "problems": []}
    if not path.exists():
        report["problems"].append("checkpoint_missing")
        return report
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "shells" in tables:
            shells = list(connection.execute("SELECT organisation_number,execution_state FROM shells"))
            report["shell_states"] = dict(Counter(str(row["execution_state"]) if row["execution_state"] in
                {"pending", "baseline_done", "terminalized", "aborted"} else "unrecognized" for row in shells))
            if (len(shells) != len(orgs) or Counter(str(row["organisation_number"]) for row in shells) != Counter(orgs)
                    or any(row["execution_state"] != "terminalized" for row in shells)):
                report["problems"].append("shells_not_all_terminalized")
        else:
            report["problems"].append("shells_missing")
        if "envelopes" in tables:
            report["final_envelopes"] = connection.execute("SELECT COUNT(*) FROM envelopes").fetchone()[0]
        if report["final_envelopes"] != len(orgs):
            report["problems"].append("checkpoint_envelope_count_mismatch")
        records = []
        native_status = False
        for table in ("phase_status", "company_phase_metrics", "phase_metrics"):
            if table not in tables:
                continue
            native_status = table == "phase_status"
            for row in connection.execute(f'SELECT * FROM "{table}"'):
                record = dict(row)
                if "payload" in record:
                    record.update(json.loads(record.pop("payload")))
                records.append(record)
            break
        else:
            if "run_meta" in tables:
                row = connection.execute("SELECT value FROM run_meta WHERE key='company_phase_metrics'").fetchone()
                if row:
                    records = json.loads(row[0])
        if not isinstance(records, list):
            report["problems"].append("metrics_require_record_list")
            return report
        seen = set()
        aggregates = {}
        fingerprints = []
        for record in records:
            if native_status:
                required = {"status", "outcome", "seconds", "ran", "skipped", "deadline_skipped", "failed"}
                if (not required <= record.keys() or not _number(record.get("seconds"))
                        or any(not isinstance(record.get(key), bool) for key in ("ran", "skipped", "deadline_skipped", "failed"))
                        or record["status"] not in {"ran", "skipped", "deadline_skipped", "failed"}
                        or record["outcome"] not in {"completed", "failed", "deadline_skipped", "ineligible", "not_attempted", "budget_skipped", "skipped"}):
                    report["problems"].append("incomplete_native_phase_status")
                    continue
                state = record["outcome"]
                status = state if state in {"failed", "deadline_skipped"} else "ran" if state == "completed" else "skipped"
                if (record["status"] != status or record["ran"] != (state in {"completed", "failed"})
                        or record["skipped"] != (status == "skipped")
                        or record["deadline_skipped"] != (state == "deadline_skipped")
                        or record["failed"] != (state == "failed")):
                    report["problems"].append("inconsistent_native_phase_status")
                    continue
                record = {**record, "ran": int(record["ran"]),
                    "skipped": int(record["skipped"] or record["deadline_skipped"]),
                    "deadline_skipped": int(record["deadline_skipped"]), "failed": int(record["failed"]),
                    "ineligible": int(record["outcome"] == "ineligible"),
                    "not_attempted": int(record["outcome"] == "not_attempted"),
                    "worker_seconds": record["seconds"], "wall_seconds": None}
            company = str(record.get("company", record.get("organisation_number", "")))
            phase = record.get("phase")
            phase = "official_foundation" if phase == "official" else phase
            pair = (company, phase)
            if (company not in orgs or not isinstance(phase, str) or not re.fullmatch(r"[a-z_]{1,64}", phase)
                    or pair in seen):
                report["problems"].append("invalid_or_duplicate_company_phase")
                continue
            seen.add(pair)
            fingerprint = record.get("traceback_sha256")
            if isinstance(fingerprint, str) and re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                fingerprints.append({"phase": phase, "traceback_sha256": fingerprint})
            if (any(not isinstance(record.get(key), int) or isinstance(record.get(key), bool) or record[key] < 0 for key in COUNTERS)
                    or not _number(record.get("worker_seconds"))
                    or (not native_status and not _number(record.get("wall_seconds")))):
                report["problems"].append("incomplete_company_phase_counters_or_timings")
                continue
            if (record["ran"] + record["skipped"] != 1 or record["failed"] > record["ran"]
                    or sum(record[key] for key in ("deadline_skipped", "ineligible", "not_attempted")) > record["skipped"]):
                report["problems"].append("inconsistent_company_phase_counters")
            aggregate = aggregates.setdefault(phase, {key: 0 for key in (*COUNTERS, "worker_seconds", "wall_seconds")})
            for key in aggregate:
                if record[key] is None:
                    aggregate[key] = None
                else:
                    aggregate[key] += record[key]
        expected = {(org, phase) for org in orgs for phase in required_phases}
        if not expected <= seen:
            report["problems"].append("required_company_phase_metrics_missing")
        report["company_phase_rows"] = len(seen)
        report["phase_counters"] = aggregates
        report["phase_failure_fingerprints"] = fingerprints
        report["failed"] = sum(row["failed"] for row in aggregates.values())
        report["problems"] = sorted(set(report["problems"]))
        report["complete"] = not report["problems"]
    return report


def collision_evidence(rows):
    """Hash identifiers and claim bodies; never copy claim values into a report."""
    duplicates, collisions, missing = 0, [], 0
    global_seen = {}
    for envelope in rows:
        for array, key in (("claims", "claim_id"), ("evidence", "evidence_id"), ("source_snapshots", "source_id")):
            local = {}
            for item in envelope.get(array, []):
                identifier = item.get(key)
                if not isinstance(identifier, str) or not identifier:
                    missing += 1
                    continue
                stable = dict(item)
                if array == "source_snapshots":
                    stable.pop("retrieved_at", None)
                fingerprint = sha(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode())
                previous = local.get(identifier)
                global_previous = global_seen.get((array, identifier))
                if previous is not None or (array == "claims" and global_previous is not None):
                    duplicates += 1
                conflict = global_previous is not None and global_previous != fingerprint
                if previous is not None or conflict or (array == "claims" and global_previous is not None):
                    collisions.append({"kind": array, "identifier_sha256": sha(identifier.encode()),
                        "first_content_sha256": previous or global_previous, "second_content_sha256": fingerprint,
                        "conflicting_content": conflict or (previous is not None and previous != fingerprint)})
                local[identifier] = fingerprint
                global_seen[(array, identifier)] = fingerprint
    return {"duplicate_count": duplicates, "conflicting_identifier_count": sum(collision["conflicting_content"] for collision in collisions),
            "missing_identifier_count": missing, "colliding_claims_and_provenance": collisions}


def log_events(path):
    if path.exists():
        with path.open(errors="replace") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    yield value


def failure_evidence(path):
    """Return traceback structure, excluding source text, paths and messages."""
    frames, exceptions = [], []
    if path.exists():
        with path.open(errors="replace") as stream:
            for line in stream:
                match = re.match(r'\s*File "[^"\n]+", line (\d+), in ([\w<>]+)\s*$', line)
                if match:
                    frames.append({"line": int(match[1]), "function": match[2]})
                match = re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception))(?::|$)", line)
                if match:
                    exceptions.append(match[1])
    return {"traceback_frames": frames[-40:], "exception_types": sorted(set(exceptions))}


def sanitized_exception(error):
    return {"failure_code": str(error) if isinstance(error, GateError) else "wrapper_exception",
        "exception_type": type(error).__name__, "sanitized_traceback": [
            {"function": frame.name, "line": frame.lineno} for frame in traceback.extract_tb(error.__traceback__)[-30:]]}


def summarize(directory, orgs, required_phases, replay=False, live_directory=None):
    output = directory / "envelopes.jsonl"
    rows = [json.loads(line) for line in output.read_text().splitlines() if line.strip()] if output.exists() else []
    states = Counter(row.get("terminal_state") if row.get("terminal_state") in
        {"available", "not_available", "not_attempted", "failed", "partial", "aborted"} else "unrecognized" for row in rows)
    allowed_statuses = {"absent", "completed", "partial", "failed", "aborted"}
    run_statuses = Counter(key if key in allowed_statuses else "unrecognized" for row in rows
                          for key in [row.get("run", {}).get("terminal_status", "absent")])
    errors = Counter()
    counts = Counter({"finance_companies": 0, "explicit_fte_companies": 0, "verified_website_companies": 0,
                      "jobs_companies": 0, "companies_with_available_claims": 0})
    for row in rows:
        available = [claim for claim in row.get("claims", []) if claim.get("state") == "available"]
        counts["companies_with_available_claims"] += bool(available)
        counts["finance_companies"] += any(claim.get("field") in FINANCIAL and _number(abs(claim["value"]))
            for claim in available if isinstance(claim.get("value"), (int, float)) and not isinstance(claim["value"], bool))
        counts["explicit_fte_companies"] += any(claim.get("field") == "full_time_equivalents" for claim in available)
        counts["verified_website_companies"] += any(claim.get("field") == "verified_website_url" for claim in available)
        counts["jobs_companies"] += any(claim.get("field_family") == "jobs" and claim.get("scope") == "job" for claim in available)
        for error in row.get("errors", []):
            code = error.get("code", "")
            errors[code if re.fullmatch(r"[A-Z][A-Z0-9_]{1,99}", code) else "UNRECOGNIZED"] += 1
    events = list(log_events(directory / "stdout.log")) + list(log_events(directory / "stderr.log"))
    batches = [event for event in events if event.get("event") == "batch_complete"]
    batch = batches[-1] if batches else {}
    checkpoint = checkpoint_metrics(directory / "checkpoint.sqlite", orgs, required_phases)
    collision_rows = rows
    if not rows and (directory / "checkpoint.sqlite").exists():
        with sqlite3.connect((directory / "checkpoint.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as connection:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='envelopes'").fetchone():
                collision_rows = [json.loads(row[0]) for row in connection.execute("SELECT payload FROM envelopes")]
    identity = collision_evidence(collision_rows)
    record = json.loads((directory / "invocation.json").read_text())
    required_keys = {"input_ref", "organisation_number", "terminal_state", "sections", "claims", "evidence",
                     "source_snapshots", "refresh", "synthesis", "errors", "operations", "run", "batch"}
    required_sections = {"identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles",
                         "hiring_activity", "claims_evidence_states", "refresh_changes"}
    gates = {"process_succeeded": record.get("exit_code") == 0 and not record.get("external_timeout", False),
        "exact_final_cardinality_and_order": [str(row.get("organisation_number")) for row in rows] == orgs,
        "complete_final_envelope_shape": bool(rows) and all(required_keys <= row.keys()
            and isinstance(row["sections"], dict) and set(row["sections"]) == required_sections for row in rows),
        "zero_aborted_inputs": states["aborted"] == 0 and run_statuses["aborted"] == 0
            and checkpoint["shell_states"].get("aborted", 0) == 0,
        "recognized_final_statuses": states["unrecognized"] == 0 and run_statuses["unrecognized"] == 0,
        "zero_failed_finals": states["failed"] == 0 and run_statuses["failed"] == 0,
        "paired_state_present": (directory / "state.json").is_file(),
        "zero_duplicate_ids": identity["duplicate_count"] == identity["conflicting_identifier_count"] == identity["missing_identifier_count"] == 0,
        "durable_company_phase_metrics_complete": checkpoint["complete"],
        "zero_phase_failures": checkpoint["failed"] == 0 and not any("FAILURE" in code or "PHASE_FAILED" in code for code in errors),
        "completion_aggregate_present": len(batches) == 1 and batch.get("output_cardinality") == len(orgs)
            and _number(batch.get("runtime_seconds")) and _number(batch.get("finalization_seconds")),
        "runtime_within_1200_seconds": _number(record.get("elapsed_seconds")) and record["elapsed_seconds"] <= 1200}
    quality = {name: gates.pop(name) for name in ("zero_failed_finals", "zero_phase_failures")}
    if len(orgs) != 100 or replay:
        quality["runtime_within_1200_seconds"] = gates.pop("runtime_within_1200_seconds")
    if len(orgs) == 100 and not replay:
        gates.update(finance_at_least_95=counts["finance_companies"] >= 95,
                     explicit_fte_at_least_50=counts["explicit_fte_companies"] >= 50,
                     verified_websites_at_least_20=counts["verified_website_companies"] >= 20)
    report = {"status": "failed", "gate_pass": False, "gates": gates,
        "final_envelopes": len(rows), "terminal_states": dict(states), "run_statuses": dict(run_statuses),
        "aborted_inputs": sum(row.get("terminal_state") == "aborted" or row.get("run", {}).get("terminal_status") == "aborted" for row in rows),
        "failed_finals": sum(row.get("terminal_state") == "failed" or row.get("run", {}).get("terminal_status") == "failed" for row in rows),
        "partial_finals": sum(row.get("terminal_state") == "partial" or row.get("run", {}).get("terminal_status") == "partial" for row in rows),
        "unfinalized_inputs": max(0, len(orgs) - checkpoint["shell_states"].get("terminalized", 0)),
        "phase_failed": checkpoint["failed"], "company_counts": dict(counts), "error_codes": dict(errors),
        "elapsed_seconds": record["elapsed_seconds"], "exit_code": record["exit_code"],
        "runtime_seconds": batch.get("runtime_seconds") if _number(batch.get("runtime_seconds")) else None,
        "checkpoint": checkpoint, "quality_observations": quality, **identity,
        "failure_evidence": failure_evidence(directory / "stderr.log")}
    report["phase_wall_seconds"] = {phase: values["wall_seconds"] for phase, values in
        batch.get("scheduler_passes", {}).get("optional_phases", {}).items()
        if phase in (*PHASES, "official") and isinstance(values, dict) and _number(values.get("wall_seconds"))}
    report["finalization_seconds"] = batch.get("finalization_seconds") if _number(batch.get("finalization_seconds")) else None
    if replay:
        totals = [event for event in events if event.get("event") in {"replay_complete", "replay_failed"}]
        if totals:
            summary = totals[-1]
            misses = {key: summary.get(key) for key in ("http_misses", "http_failures", "ocr_misses")}
            complete = all(_number(value) for value in misses.values())
        else:
            summary = batch
            misses = {key: batch.get(key) for key in ("http_misses", "http_failures", "ocr_misses")}
            complete = all(_number(value) for value in misses.values())
        complete = complete and all(key in summary for key in ("missing_requests", "unconsumed_requests", "capture_complete"))
        gates["replay_aggregate_keys_present"] = complete and "research_mode" in batch and "actual_network_requests" in batch
        gates["replay_zero_misses_and_network"] = (complete and all(value == 0 for value in misses.values())
            and batch.get("research_mode") == "replay" and batch.get("actual_network_requests") == 0)
        gates["replay_capture_sealed_and_fully_consumed"] = (summary.get("capture_complete") is True
            and summary.get("missing_requests") == [] and summary.get("unconsumed_requests") == [])
        gates["exact_output_bytes_equal"] = bool(live_directory and output.exists()
            and (live_directory / "envelopes.jsonl").exists()
            and output.read_bytes() == (live_directory / "envelopes.jsonl").read_bytes())
        gates["exact_state_bytes_equal"] = bool(live_directory and (directory / "state.json").exists()
            and (live_directory / "state.json").exists()
            and (directory / "state.json").read_bytes() == (live_directory / "state.json").read_bytes())
        report["replay_misses"] = misses
        report["replay_missing_request_keys"] = len(summary["missing_requests"]) if isinstance(summary.get("missing_requests"), list) else None
        report["replay_unconsumed_request_keys"] = len(summary["unconsumed_requests"]) if isinstance(summary.get("unconsumed_requests"), list) else None
    report["artifacts"] = {name: digest(directory / name) for name in
        ("envelopes.jsonl", "state.json", "checkpoint.sqlite", "stdout.log", "stderr.log", "invocation.json") if (directory / name).exists()}
    report["gate_pass"] = all(gates.values())
    report["execution_gate_pass"] = all(value for name, value in gates.items() if name not in MEASUREMENT_GATES)
    report["status"] = "passed" if report["gate_pass"] else "failed"
    return report


def command(repository, directory, source, config, batch_id, capture=None):
    return [str(repository / "run.sh"), "--input", str(source), "--format", "jsonl",
        "--output", str(directory / "envelopes.jsonl"), "--state-output", str(directory / "state.json"),
        "--checkpoint", str(directory / "checkpoint.sqlite"), "--config", str(config),
        "--batch-id", batch_id, "--replay-http" if capture else "--record-http",
        str(capture if capture else directory / "http-capture")]


def launch(repository, directory, source, config, batch_id, timeout, capture=None):
    private_dir(directory)
    for name in ("home", "cache", "ocr-cache"):
        private_dir(directory / name)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("SIGNALPOST_")}
    environment.update(HOME=str(directory / "home"), XDG_CACHE_HOME=str(directory / "cache"),
        SIGNALPOST_OCR_CACHE=str(capture.parent / "ocr-cache" if capture else directory / "ocr-cache"),
        TZ="UTC", PYTHONNOUSERSITE="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    invocation = {"status": "running", "started_at_utc": utc(),
        "command": command(repository, directory, source, config, batch_id, capture),
        "input_sha256": digest(source), "external_timeout": False}
    write(directory / "invocation.json", invocation)
    started = time.monotonic()
    with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        os.chmod(directory / "stdout.log", 0o600)
        os.chmod(directory / "stderr.log", 0o600)
        process = subprocess.Popen(invocation["command"], cwd=directory, env=environment,
                                   stdout=stdout, stderr=stderr, start_new_session=True)
        invocation["pid"] = process.pid
        write(directory / "invocation.json", invocation)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            invocation["external_timeout"] = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                code = process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
        except BaseException:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    invocation.update(status="completed" if code == 0 else "failed", exit_code=code,
                      elapsed_seconds=round(time.monotonic() - started, 3), completed_at_utc=utc())
    write(directory / "invocation.json", invocation)


def require_gate(root, name):
    directory = root / name
    report = json.loads((directory / "report.json").read_text())
    prerequisites = {name: value for name, value in report.get("gates", {}).items() if name not in MEASUREMENT_GATES}
    if (report.get("execution_gate_pass", report.get("gate_pass")) is not True
            or not prerequisites or not all(prerequisites.values())):
        raise GateError("prerequisite_gate_not_passed")
    expected_artifacts = {"envelopes.jsonl", "state.json", "checkpoint.sqlite", "stdout.log", "stderr.log", "invocation.json"}
    if not expected_artifacts <= report.get("artifacts", {}).keys():
        raise GateError("prerequisite_artifact_hashes_missing")
    for name, expected in report["artifacts"].items():
        if name not in expected_artifacts or digest(directory / name) != expected:
            raise GateError("prerequisite_artifact_changed")
    return report


def frozen_cohort(root, name, selection_path, expected_hash=None):
    selection = json.loads((selection_path / "selection.json").read_text())
    source = selection_path / "companies.jsonl"
    actual = digest(source)
    if actual != selection["input_sha256"] or (expected_hash and actual != expected_hash):
        raise GateError("cohort_selection_hash_mismatch")
    orgs = read_input(source, 100)
    destination = root / (name + "-selection")
    private_dir(destination)
    (destination / "companies.jsonl").write_bytes(source.read_bytes())
    os.chmod(destination / "companies.jsonl", 0o600)
    write(destination / "input-receipt.json", {"input_sha256": actual,
        "original_selection_sha256": digest(selection_path / "selection.json"), "sample_size": 100,
        "frozen_at_utc": utc(), "seed": selection.get("seed")})
    return destination / "companies.jsonl", orgs


def execute(args):
    root, repository = args.root.resolve(), args.repository.resolve()
    if root.is_relative_to(repository):
        raise GateError("acceptance_artifacts_must_be_outside_repository")
    if args.stage != "smoke" and not args.allow_100:
        raise GateError("hundred_company_stage_requires_explicit_allow_100")
    if args.prepare_only and args.stage != "smoke":
        raise GateError("prepare_only_is_smoke_only")
    if not root.exists():
        private_dir(root)
    if root.is_symlink() or root.stat().st_mode & 0o077:
        raise GateError("acceptance_root_requires_private_directory")
    manifest_path = root / "acceptance.json"
    if not manifest_path.exists():
        if args.stage != "smoke" or not args.registry or not args.original_selection:
            raise GateError("initial_smoke_requires_registry_and_original_selection")
        exclusions = list(args.exclude_selection)
        for cohort in (args.matched_selection, args.holdout_selection):
            if cohort is not None and cohort not in exclusions:
                exclusions.append(cohort)
        receipt = freeze_smoke(args.registry, args.original_selection, root / "smoke-selection", args.seed, exclusions)
        config = args.config.read_bytes() if args.config else (json.dumps(DEFAULT_CONFIG, indent=2) + "\n").encode()
        if not isinstance(json.loads(config), dict):
            raise GateError("configuration_requires_object")
        (root / "config.json").write_bytes(config)
        os.chmod(root / "config.json", 0o600)
        manifest = {"schema_version": 1, "created_at_utc": utc(), "source": source_identity(repository),
            "configuration_sha256": sha(config), "smoke_input_sha256": receipt["input_sha256"],
            "matched_input_sha256": json.loads(args.original_selection.read_text())["input_sha256"],
            "required_phases": list(PHASES), "external_timeout_seconds": args.timeout,
            "automatic_retry": False, "order": ["smoke", "smoke-replay", "matched", "matched-replay", "holdout", "holdout-replay"]}
        write(manifest_path, manifest)
    manifest = json.loads(manifest_path.read_text())
    require_frozen(root, repository, manifest)
    if args.config and digest(args.config) != manifest["configuration_sha256"]:
        raise GateError("supplied_configuration_differs_from_frozen_configuration")
    if args.prepare_only:
        return {"status": "prepared", "research_launched": False, "smoke_input_sha256": manifest["smoke_input_sha256"]}
    if args.stage == "smoke":
        source = root / "smoke-selection" / "companies.jsonl"
        orgs = read_input(source, 10)
    elif args.stage == "matched":
        require_gate(root, "smoke")
        require_gate(root, "smoke-replay")
        if not args.matched_selection:
            raise GateError("matched_selection_required")
        source, orgs = frozen_cohort(root, "matched", args.matched_selection, manifest["matched_input_sha256"])
    else:
        for name in ("smoke", "smoke-replay", "matched", "matched-replay"):
            require_gate(root, name)
        if not args.holdout_selection or not args.confirm_unobserved_holdout:
            raise GateError("holdout_requires_selection_and_explicit_unobserved_confirmation")
        if digest(root / "matched-selection" / "companies.jsonl") != manifest["matched_input_sha256"]:
            raise GateError("frozen_matched_input_changed")
        candidate = read_input(args.holdout_selection / "companies.jsonl", 100)
        if set(candidate) & set(read_input(root / "matched-selection" / "companies.jsonl", 100)):
            raise GateError("holdout_overlaps_matched")
        if set(candidate) & set(read_input(root / "smoke-selection" / "companies.jsonl", 10)):
            raise GateError("holdout_overlaps_observed_smoke")
        source, orgs = frozen_cohort(root, "holdout", args.holdout_selection)
    live_directory = root / args.stage
    replay_directory = root / (args.stage + "-replay")
    if live_directory.exists() or replay_directory.exists():
        raise GateError("stage_already_attempted_no_automatic_retry")
    batch_id = "crashsafe-" + args.stage
    for directory, capture in ((live_directory, None), (replay_directory, live_directory / "http-capture")):
        require_frozen(root, repository, manifest)
        try:
            launch(repository, directory, source, root / "config.json", batch_id,
                   manifest["external_timeout_seconds"], capture)
            report = summarize(directory, orgs, manifest["required_phases"], bool(capture), live_directory)
        except BaseException as error:
            report = {"status": "failed", "gate_pass": False, "gates": {"wrapper_completed": False},
                **sanitized_exception(error), "failure_evidence": failure_evidence(directory / "stderr.log")}
        try:
            require_frozen(root, repository, manifest)
            if digest(source) != json.loads((source.parent / "input-receipt.json").read_text())["input_sha256"]:
                raise GateError("frozen_cohort_input_changed")
        except GateError:
            report["gates"]["frozen_source_config_input"] = False
            report.update(status="failed", gate_pass=False, execution_gate_pass=False)
        write(directory / "report.json", report)
        if not report.get("execution_gate_pass", report["gate_pass"]):
            return {"status": "failed", "failed_stage": directory.name, "gate_pass": False,
                    "report": report, "subsequent_stages_launched": False}
    live_report = json.loads((live_directory / "report.json").read_text())
    return {"status": "passed" if live_report["gate_pass"] else "acceptance_failed", "stage": args.stage,
            "gate_pass": live_report["gate_pass"], "execution_gate_pass": True,
            "live_complete_and_replay_identical": True, "subsequent_stages_launched": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="New private artifact root outside the checkout")
    parser.add_argument("--repository", type=Path, default=ROOT)
    parser.add_argument("--stage", choices=("smoke", "matched", "holdout"), default="smoke")
    parser.add_argument("--registry", type=Path, help="Archived original registry CSV or gzip; never downloaded here")
    parser.add_argument("--original-selection", type=Path, help="Original livecomparison selection.json with fixed_companies")
    parser.add_argument("--config", type=Path, help="Frozen verbatim once; reuse across every cohort and replay")
    parser.add_argument("--seed", help="Optional predeclared 64-character hex sampling seed")
    parser.add_argument("--exclude-selection", type=Path, action="append", default=[],
                        help="Frozen 100-company selection directory to exclude from smoke additions; repeatable")
    parser.add_argument("--prepare-only", action="store_true", help="Freeze selection/config; launch no research")
    parser.add_argument("--timeout", type=float, default=3000, help="External process cap, frozen at preparation")
    parser.add_argument("--allow-100", action="store_true", help="Explicitly authorize only the selected 100-company stage")
    parser.add_argument("--matched-selection", type=Path)
    parser.add_argument("--holdout-selection", type=Path)
    parser.add_argument("--confirm-unobserved-holdout", action="store_true",
                        help="Parent attests this frozen holdout has never had optional-data outcomes observed")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise GateError("timeout_requires_positive_finite_seconds")
        report = execute(args)
    except BaseException as error:
        report = {"status": "failed", "gate_pass": False, "subsequent_stages_launched": False,
            **sanitized_exception(error)}
        if args.root.is_dir() and not args.root.is_symlink() and not args.root.stat().st_mode & 0o077:
            write(args.root / ("failure-" + secrets.token_hex(8) + ".json"), report)
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0 if report["status"] in {"passed", "prepared"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
