#!/usr/bin/env python3
"""Independent-gold evaluation of canonical M08 find/compare/verify/synthesis."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import statistics
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "signalpost-starter-kit" / "tests"
sys.path[:0] = [str(ROOT), str(TESTS)]

from signalpost.query import FindFilter, QueryError, build_index, compare_companies, find_companies, load_profiles, verify_proposition  # noqa: E402
from signalpost.synthesis import synthesize, validate_synthesis  # noqa: E402
from signalpost.web import _as_envelope_view  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default=str(TESTS / "fixtures/m08/research-gold.json"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    def p95(values: list[float]) -> float:
        return sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)]
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    canonical_path = TESTS / "fixtures/m08/canonical.jsonl"
    profiles = load_profiles(canonical_path)
    index = build_index(profiles)
    find_results = []
    find_correct = 0
    find_times = []
    for case in gold["find"]:
        filters = list(case.get("filters", []))
        if case.get("field"):
            filters.append({key: case[key] for key in ("field", "operator", "value", "currency", "period_end", "scope", "unit") if key in case})
        typed = [FindFilter(item["field"], item["operator"],
            Decimal(str(item["value"])) if item["field"] in {"revenue", "employees", "annual_result"} else item["value"],
            item.get("currency"), item.get("period_end"), item.get("scope"), item.get("unit")) for item in filters]
        start = time.perf_counter()
        result = find_companies(profiles, text=case.get("text", ""), filters=typed, index=index)
        find_times.append((time.perf_counter() - start) * 1000)
        actual, unknown = ([row["organisation_number"] for row in result["matches"]],
                           [row["organisation_number"] for row in result["unknown"]])
        correct = actual == case["matches"] and unknown == case["unknown"]
        find_correct += int(correct)
        find_results.append({"id": case["id"], "expected": case["matches"], "actual": actual,
                             "expected_unknown": case["unknown"], "actual_unknown": unknown, "correct": correct})
    compare_results = []
    compare_correct = 0
    compare_times = []
    for case in gold["compare"]:
        orgs = case["organisations"]
        start = time.perf_counter()
        result = compare_companies(profiles, orgs, case["fields"])
        compare_times.append((time.perf_counter() - start) * 1000)
        actual = [column["status"] for column in result["columns"]]
        no_foreign_citations = all(citation.get("source_url") and
            citation.get("evidence_id") in profiles[value["organisation_number"]].evidence
            for column in result["columns"] for value in column["values"]
            for citation in value.get("citations", []))
        correct = actual == case["expected"] and no_foreign_citations and result["ranking"] is None
        compare_correct += int(correct)
        compare_results.append({"id": case["id"], "expected": case["expected"], "actual": actual,
                                "no_cross_company_citations": no_foreign_citations, "correct": correct})
    verify_results = []
    verify_correct = 0
    for case in gold["verify"]:
        actual = verify_proposition(profiles, **{key: case[key] for key in
            ("organisation_number", "field", "value", "currency", "period_end", "scope", "unit") if key in case})
        correct = actual["status"] == case["expected"] and all(
            citation["evidence_id"] in profiles[case["organisation_number"]].evidence for citation in actual["citations"])
        verify_correct += int(correct)
        verify_results.append({"id": case["id"], "expected": case["expected"], "actual": actual["status"],
                               "citation_count": len(actual["citations"]), "correct": correct})
    abstention_correct = False
    try:
        verify_proposition(profiles, organisation_number=gold["abstention"]["organisation_number"],
            field=gold["abstention"]["field"], value=gold["abstention"]["value"])
    except QueryError:
        abstention_correct = gold["abstention"]["expected"] == "abstain"
    summaries = []
    assertions = 0
    unsupported = 0
    fully_cited = 0
    for org, profile in sorted(profiles.items()):
        envelope = _as_envelope_view(profile)
        summary = synthesize(envelope)
        for sentence in summary["sentences"]:
            assertions += 1
            try:
                validate_synthesis(envelope, {"sentences": [sentence]})
                fully_cited += 1
            except ValueError:
                unsupported += 1
        summaries.append({"organisation_number": org, "assertions": len(summary["sentences"]),
                          "unknown_sections": summary["unknown_sections"]})
    overall_correct = (find_correct == len(gold["find"]) and compare_correct == len(gold["compare"])
        and verify_correct == len(gold["verify"]) and abstention_correct and unsupported == 0
        and fully_cited == assertions)
    source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip())
    report = {"measurement_kind": "offline_independent_gold_ux_regression",
        "source_commit": source_sha, "source_tree_dirty": dirty,
        "gold_sha256": hashlib.sha256(Path(args.gold).read_bytes()).hexdigest(),
        "canonical_corpus_sha256": hashlib.sha256(canonical_path.read_bytes()).hexdigest(),
        "corpus": gold["corpus"], "company_count": len(profiles),
        "find": {"correct_cases": find_correct, "cases": len(gold["find"]), "accuracy": find_correct / len(gold["find"]), "results": find_results,
                 "latency_ms": {"median": statistics.median(find_times), "p95": p95(find_times)}},
        "compare": {"correct_cases": compare_correct, "cases": len(gold["compare"]), "accuracy": compare_correct / len(gold["compare"]), "results": compare_results,
                    "latency_ms": {"median": statistics.median(compare_times), "p95": p95(compare_times)}},
        "verify": {"correct_cases": verify_correct, "cases": len(gold["verify"]), "accuracy": verify_correct / len(gold["verify"]), "results": verify_results},
        "unsupported_question_abstention_correct": abstention_correct,
        "synthesis": {"assertions": assertions, "unsupported_assertions": unsupported,
                      "unsupported_assertion_rate": unsupported / assertions if assertions else 0,
                      "provenance_complete_assertions": fully_cited,
                      "provenance_completeness": fully_cited / assertions if assertions else 1,
                      "profiles": summaries},
        "evaluation_passed": overall_correct}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"find", "compare", "verify", "synthesis"}}, indent=2))
    print(json.dumps({"find_accuracy": report["find"]["accuracy"], "compare_accuracy": report["compare"]["accuracy"],
        "verify_accuracy": report["verify"]["accuracy"], "unsupported_assertions": unsupported,
        "citation_completeness": report["synthesis"]["provenance_completeness"], "evaluation_passed": overall_correct}, indent=2))
    return 0 if overall_correct else 1


if __name__ == "__main__":
    raise SystemExit(main())
