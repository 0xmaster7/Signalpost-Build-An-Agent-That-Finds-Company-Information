#!/usr/bin/env python3
"""Compare M04 registry-only and keyless runs with the committed M03 audit."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def read_run(path: Path) -> tuple[list[dict], dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    sources, decisions = Counter(), Counter()
    accepted: set[tuple[str, str]] = set()
    wrong = unproven = missing_proof = 0
    states = Counter()
    for envelope in rows:
        audit = envelope.get("synthesis", {}).get("website_research", {})
        states[audit.get("crawl_state", "not_run")] += 1
        proof_ids = {item.get("evidence_id") for item in envelope.get("evidence", [])
                     if item.get("extraction_method") == "audited_exact_site_identity_proof_v1"}
        for claim in envelope.get("claims", []):
            if claim.get("section") != "website_owned_profiles" or claim.get("state") != "available":
                continue
            if not (set(claim.get("evidence_ids", [])) & proof_ids):
                unproven += 1
        for candidate in audit.get("candidates", []):
            source = candidate.get("source", "unknown")
            sources[source] += 1
            decisions[candidate.get("decision", "unknown")] += 1
            if candidate.get("decision") == "accepted":
                if candidate.get("proof_evidence_id") not in proof_ids:
                    missing_proof += 1
                if candidate.get("proof", {}).get("organisation_number") != envelope.get("organisation_number"):
                    wrong += 1
                accepted.add((envelope.get("organisation_number", ""), candidate.get("registered_domain", "")))
    return rows, {"input_rows": len(rows), "candidate_count": sum(sources.values()),
        "candidate_sources": dict(sorted(sources.items())), "candidate_decisions": dict(sorted(decisions.items())),
        "company_states": dict(sorted(states.items())), "accepted_exact_domains": len(accepted),
        "accepted_org_domains": sorted([list(value) for value in accepted]),
        "wrong_company_promotions": wrong, "accepted_sites_missing_proof": missing_proof,
        "website_claims_without_exact_site_proof": unproven}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-only", type=Path, required=True)
    parser.add_argument("--keyless", type=Path, required=True)
    parser.add_argument("--m03-summary", type=Path, required=True)
    parser.add_argument("--m03-domains", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, help="JSON object containing per-run gateway/runtime measurements")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    registry_rows, registry = read_run(args.registry_only)
    keyless_rows, keyless = read_run(args.keyless)
    m03 = json.loads(args.m03_summary.read_text(encoding="utf-8"))
    with args.m03_domains.open(encoding="utf-8", newline="") as stream:
        m03_domains = {(row["organisation_number"], row["domain"]) for row in csv.DictReader(stream)}
    if len(registry_rows) != len(keyless_rows) or [row.get("organisation_number") for row in registry_rows] != [row.get("organisation_number") for row in keyless_rows]:
        raise SystemExit("registry-only and keyless runs must contain the same ordered company cohort")
    registry_candidates = {(row.get("organisation_number"), c.get("registered_domain"))
        for row in registry_rows for c in row.get("synthesis", {}).get("website_research", {}).get("candidates", [])}
    added_keyless_candidates = {(row.get("organisation_number"), c.get("registered_domain"))
        for row in keyless_rows for c in row.get("synthesis", {}).get("website_research", {}).get("candidates", [])
        if c.get("source") == "keyless_no"}
    added_keyless_candidates -= registry_candidates
    registry_accepted = set(map(tuple, registry["accepted_org_domains"]))
    keyless_accepted = set(map(tuple, keyless["accepted_org_domains"]))
    additive = keyless_accepted - registry_accepted
    m03_delta = keyless_accepted - m03_domains
    metrics = json.loads(args.metrics.read_text(encoding="utf-8")) if args.metrics else {}
    report = {
        "cohort_rows": len(registry_rows),
        "registry_only": registry,
        "registry_plus_keyless": keyless,
        "m03_committed_baseline": {
            "candidate_count": m03.get("candidate_count"),
            "candidate_sources": m03.get("candidate_sources"),
            "candidate_decisions": m03.get("candidate_decisions"),
            "accepted_domain_count": m03.get("accepted_domain_count"),
            "wrong_company_publications": m03.get("wrong_company_publications"),
            "website_claims_without_exact_site_proof": m03.get("website_claims_without_exact_site_proof"),
            "batch_gateway_metrics": m03.get("batch_gateway_metrics"),
        },
        "m04_delta_vs_m03_keyless_baseline": {
            "candidate_count_delta": keyless["candidate_count"] - int(m03.get("candidate_count", 0)),
            "accepted_exact_domains_delta": keyless["accepted_exact_domains"] - int(m03.get("accepted_domain_count", 0)),
            "additional_exact_company_domains": len(m03_delta),
            "additional_exact_company_org_domains": sorted([list(value) for value in m03_delta]),
            "wrong_company_promotion_delta": keyless["wrong_company_promotions"] - int(m03.get("wrong_company_publications", 0)),
            "coverage_gain_rows": len({org for org, _ in keyless_accepted} - {org for org, _ in m03_domains}),
        },
        "keyless_increment_vs_registry_only": {
            "additional_candidate_domains": len(added_keyless_candidates),
            "additional_candidate_org_domains": sorted([list(value) for value in added_keyless_candidates]),
            "additional_exact_company_domains": len(additive),
            "additional_exact_company_org_domains": sorted([list(value) for value in additive]),
        },
        "search": {"enabled": False, "provider": None, "candidate_count": 0, "accepted_domains": 0,
                   "physical_requests": 0, "logical_requests": 0, "cost_usd": "0",
                   "reason": "No reproducible provider with approved source rights is configured; provider stays disabled."},
        "run_metrics": metrics,
        "precision_claim": None,
        "hard_gates": {
            "same_ordered_cohort": True,
            "zero_wrong_company_promotions": registry["wrong_company_promotions"] == 0 and keyless["wrong_company_promotions"] == 0,
            "all_accepted_domains_have_exact_proof": registry["accepted_sites_missing_proof"] == 0 and keyless["accepted_sites_missing_proof"] == 0,
            "all_website_claims_have_exact_proof": registry["website_claims_without_exact_site_proof"] == 0 and keyless["website_claims_without_exact_site_proof"] == 0,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0 if all(report["hard_gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
