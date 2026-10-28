"""Publish contact-free observations and predeclared gates, never relabel misses."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
from collections import Counter


SPEC = importlib.util.spec_from_file_location("comparison", Path(__file__).with_name("compare_live_envelopes.py"))
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    execution = json.loads((args.root / "experiment.json").read_text())
    if execution["status"] != "completed":
        raise ValueError("Both preregistered runs must finish before evaluation")
    baseline_rows = {row["organisation_number"]: row for row in
        (json.loads(line) for line in (args.baseline / "comparison/per-company.jsonl").read_text().splitlines())}
    selections = {"matched": json.loads((args.baseline / "selection/selection.json").read_text()),
        "holdout": json.loads((args.root / "holdout-selection/selection.json").read_text())}
    summary = {"source_sha": execution["source_sha"], "input_hashes": execution["input_hashes"],
        "criteria": execution["pass_criteria"], "coverage_is_not_independent_accuracy": True,
        "bundled_treatment_not_component_ablation": True, "cohorts": {}}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("matched", "holdout"):
        run = execution["runs"][name]
        root = args.root / name
        if run["status"] != "completed" or run["exit_code"] != 0 or run["source_sha_after"] != execution["source_sha"]:
            summary["cohorts"][name] = {"pass": False, "execution_failed": True, "run": run}
            continue
        output = root / "envelopes.jsonl"
        if hashlib.sha256(output.read_bytes()).hexdigest() != run["output_sha256"]:
            raise ValueError("Original output changed")
        envelopes = comparison.load(output)
        selected = {row["organisation_number"]: row for row in selections[name]["rows"]}
        if set(selected) != set(envelopes):
            raise ValueError("Cohort output does not match its frozen selection")
        with sqlite3.connect(f"file:{root / 'checkpoint.sqlite'}?mode=ro", uri=True) as checkpoint:
            private = {row["organisation_number"]: row for payload, in checkpoint.execute("SELECT payload FROM envelopes")
                for row in [json.loads(payload)]}
        rows = []
        for org, envelope in envelopes.items():
            current = comparison.normalize(envelope, "ours")
            row = {**selected[org], "after": current, "pipeline": comparison.pipeline(private[org])}
            if name == "matched":
                previous = baseline_rows[org]["ours"]
                row["before_counts"] = {key: previous[key] for key in
                    ("verified_jobs", "verified_websites", "fte_claims", "financial_claims")}
            rows.append(row)
        observations = [row["after"] for row in rows]
        metrics = {"companies_with_verified_website": sum(row["verified_websites"] > 0 for row in observations),
            "companies_with_jobs": sum(row["verified_jobs"] > 0 for row in observations),
            "distinct_jobs": sum(row["verified_jobs"] for row in observations),
            "companies_with_fte": sum(row["fte_claims"] > 0 for row in observations),
            "companies_with_positive_fte": sum(any(comparison.number(item["value"]) > 0 for item in row["fte"]) for row in observations),
            "companies_with_zero_fte": sum(any(comparison.number(item["value"]) == 0 for item in row["fte"]) for row in observations),
            "companies_with_financial_claims": sum(row["financial_claims"] > 0 for row in observations),
            "companies_with_direct_financial_claims": sum(any(not item["unit_assumed_currency"] for item in row["financial"]) for row in observations),
            "companies_with_assumed_financial_claims": sum(any(item["unit_assumed_currency"] for item in row["financial"]) for row in observations),
            "financial_claims": sum(row["financial_claims"] for row in observations),
            "financial_assumed_claims": sum(item["unit_assumed_currency"] for row in observations for item in row["financial"]),
            "financial_group_claims": sum(item["scope"] == "group" for row in observations for item in row["financial"]),
            "elapsed_seconds": run["elapsed_seconds"], "terminal_envelopes": len(rows),
            "terminal_states": dict(Counter(row["terminal_state"] for row in observations)),
            "document_states": dict(Counter(row["pipeline"]["document"].get("state", "no_document") for row in rows)),
            "early_stopped_documents": sum(bool(row["pipeline"]["document"].get("stopped_early")) for row in rows)}
        latest = 0
        for row in observations:
            end = max((item["period_end"] for item in row["financial"]
                if item["scope"] == "legal_entity" and item["period_end"]), default=None)
            latest += sum(item["scope"] == "legal_entity" and item["period_end"] == end for item in row["financial"])
        metrics["financial_latest_standalone_claims"] = latest
        gates = {key: metrics[key] >= execution["pass_criteria"][key] for key in
            ("companies_with_verified_website", "companies_with_financial_claims", "companies_with_fte")}
        gates["runtime"] = metrics["elapsed_seconds"] <= execution["pass_criteria"]["maximum_elapsed_seconds"]
        gates["cardinality"] = len(rows) == execution["pass_criteria"]["terminal_envelopes"]
        batch_report = json.loads((root / "stdout.log").read_text().splitlines()[-1])
        phases = batch_report.get("scheduler_passes", {})
        summary["cohorts"][name] = {"metrics": metrics, "gates": gates, "pass": all(gates.values()),
            "phase_status_counts_and_timings": phases.get("optional_phases", {}),
            "official_foundation": {key: value for key, value in phases.get("official_foundation", {}).items() if key != "companies"},
            "nav_window": phases.get("nav_jobs", {}), "wikidata": phases.get("wikidata_discovery", {})}
        encoded = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode()
        with gzip.GzipFile(filename=str(args.output_dir / (name + "-per-company.jsonl.gz")), mode="wb", mtime=0) as compressed:
            compressed.write(encoded)
        with (args.output_dir / (name + "-per-company.csv")).open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["organisation_number", "name", "verified_websites", "verified_jobs", "fte_claims",
                "financial_claims", "assumed_financial_claims", "group_financial_claims", "document_state", "pages_processed"])
            for row in rows:
                value = row["after"]
                name_value = row["name"]
                if name_value.lstrip().startswith(("=", "+", "-", "@")):
                    name_value = "'" + name_value
                writer.writerow([row["organisation_number"], name_value, value["verified_websites"], value["verified_jobs"],
                    value["fte_claims"], value["financial_claims"], sum(item["unit_assumed_currency"] for item in value["financial"]),
                    sum(item["scope"] == "group" for item in value["financial"]),
                    row["pipeline"]["document"].get("state"), row["pipeline"]["document"].get("pages_processed")])
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
