#!/usr/bin/env python3
"""Summarize a canonical M03 run without retaining page bodies or snippets."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import median


def summarize(path: Path, batch_metrics_path: Path | None = None, *, run_id: str | None = None,
              cohort: str | None = None, snapshot_sha256: str | None = None,
              source_url: str | None = None) -> tuple[dict, list[dict]]:
    envelopes = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    candidates: list[dict] = []
    sources = Counter()
    decisions = Counter()
    families = Counter()
    states = Counter()
    pages: list[int] = []
    content_requests: list[int] = []
    durations: list[float] = []
    accepted: list[dict] = []
    proof_failures = 0
    wrong_company = 0
    unproven_website_claims = 0
    for envelope in envelopes:
        audit = envelope.get("synthesis", {}).get("website_research", {})
        org = envelope.get("organisation_number")
        states[audit.get("crawl_state", "not_run")] += 1
        pages.append(int(audit.get("page_count", 0)))
        content_requests.append(int(audit.get("page_requests", 0)))
        durations.append(float(audit.get("elapsed_ms", 0)))
        proof_evidence = {item.get("evidence_id") for item in envelope.get("evidence", [])
                          if item.get("extraction_method") == "audited_exact_site_identity_proof_v1"}
        for claim in envelope.get("claims", []):
            if claim.get("section") == "website_owned_profiles" and claim.get("state") == "available":
                if not (set(claim.get("evidence_ids", [])) & proof_evidence):
                    unproven_website_claims += 1
        for candidate in audit.get("candidates", []):
            row = {"organisation_number": org, **candidate}
            candidates.append(row)
            sources[candidate.get("source", "unknown")] += 1
            decisions[candidate.get("decision", "unknown")] += 1
            if candidate.get("decision") == "accepted":
                proof_id = candidate.get("proof_evidence_id")
                if not proof_id or proof_id not in proof_evidence:
                    proof_failures += 1
                if candidate.get("proof", {}).get("organisation_number") != org:
                    wrong_company += 1
                accepted.append({"organisation_number": org, "domain": (candidate.get("registered_domain") or ""),
                    "url": candidate.get("target_url") or candidate.get("final_url") or candidate.get("url"),
                    "source": candidate.get("source"), "method": candidate.get("proof", {}).get("method"),
                    "proof_record_id": candidate.get("proof_record_id"), "proof_evidence_id": proof_id})
        for claim in envelope.get("claims", []):
            if claim.get("section") == "website_owned_profiles":
                families[claim.get("field", "unknown")] += 1
    summary = {
        "input_rows": len(envelopes), "candidate_count": len(candidates),
        "candidate_sources": dict(sorted(sources.items())), "candidate_decisions": dict(sorted(decisions.items())),
        "company_states": dict(sorted(states.items())), "accepted_domain_count": len(accepted),
        "website_claims_by_field": dict(sorted(families.items())),
        "proof_evidence_failures": proof_failures, "wrong_company_publications": wrong_company,
        "website_claims_without_exact_site_proof": unproven_website_claims,
        "pages_per_company": {"total": sum(pages), "median": median(pages) if pages else 0, "max": max(pages, default=0)},
        "content_requests_per_company": {"total": sum(content_requests), "median": median(content_requests) if content_requests else 0, "max": max(content_requests, default=0)},
        "elapsed_ms_per_company": {"median": median(durations) if durations else 0, "max": max(durations, default=0)},
        "precision_claim": None,
    }
    if batch_metrics_path:
        summary["batch_gateway_metrics"] = json.loads(batch_metrics_path.read_text(encoding="utf-8"))
    summary["audit_run_id"] = run_id
    summary["cohort"] = cohort
    summary["cohort_sha256"] = snapshot_sha256
    summary["candidate_source_url"] = source_url
    return summary, accepted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--domains", type=Path, required=True)
    parser.add_argument("--batch-metrics", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--cohort")
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--source-url")
    args = parser.parse_args()
    summary, accepted = summarize(args.input, args.batch_metrics, run_id=args.run_id,
        cohort=args.cohort, snapshot_sha256=args.snapshot_sha256, source_url=args.source_url)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    args.domains.parent.mkdir(parents=True, exist_ok=True)
    with args.domains.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["organisation_number", "domain", "url", "source", "method", "proof_record_id", "proof_evidence_id"],
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(accepted)
    if summary["proof_evidence_failures"] or summary["wrong_company_publications"] or summary["website_claims_without_exact_site_proof"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
