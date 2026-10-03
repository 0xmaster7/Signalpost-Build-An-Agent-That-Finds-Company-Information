#!/usr/bin/env python3
"""Summarize exact-site M05 jobs/activity coverage and publication safety."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path


def wilson(errors: int, sample: int) -> dict[str, float | int] | None:
    if sample == 0:
        return None
    z = 1.959963984540054
    p = errors / sample
    den = 1 + z * z / sample
    center = (p + z * z / (2 * sample)) / den
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * sample)) / sample) / den
    return {"errors": errors, "sample_size": sample, "observed_error_rate": p,
            "wilson_95_lower": max(0.0, center - radius), "wilson_95_upper": min(1.0, center + radius)}


def summarize(rows: list[dict], metrics: dict) -> dict:
    family = Counter()
    company_family = {"jobs": set(), "public_activity": set()}
    subjects = {"jobs": set(), "public_activity": set()}
    states = Counter()
    wrong_company = missing_proof = missing_evidence = missing_snapshot = undated = no_rights = 0
    proof_ids_by_row: list[set[str]] = []
    for row in rows:
        evidence = row.get("evidence", [])
        evidence_ids = {item.get("evidence_id") for item in evidence}
        proof_ids = {item.get("evidence_id") for item in evidence
                     if item.get("extraction_method") == "audited_exact_site_identity_proof_v1"}
        snapshot_ids = {item.get("source_id") for item in row.get("source_snapshots", [])}
        proof_ids_by_row.append(proof_ids)
        audit = row.get("synthesis", {}).get("website_research", {})
        states[audit.get("crawl_state", "not_run")] += 1
        for claim in row.get("claims", []):
            if claim.get("section") != "hiring_activity" or claim.get("state") != "available":
                continue
            family_name = claim.get("field_family", "unknown")
            family[family_name] += 1
            subject = claim.get("subject_id")
            if family_name in company_family:
                company_family[family_name].add(row.get("organisation_number"))
                subjects[family_name].add((row.get("organisation_number"), subject))
            if claim.get("organisation_number") != row.get("organisation_number"):
                wrong_company += 1
            claim_evidence = set(claim.get("evidence_ids", []))
            if not claim_evidence or not claim_evidence <= evidence_ids:
                missing_evidence += 1
            if not claim_evidence & proof_ids:
                missing_proof += 1
            if not set(claim.get("source_snapshot_ids", [])) <= snapshot_ids:
                missing_snapshot += 1
            if family_name == "public_activity" and claim.get("field") == "source_published_at" and not claim.get("as_of"):
                undated += 1
        if audit.get("jobs", {}).get("state"):
            states[f"jobs:{audit['jobs']['state']}"] += 1
        if audit.get("hiring_activity_state"):
            states[f"hiring_activity:{audit['hiring_activity_state']}"] += 1
        for entry in row.get("errors", []):
            if entry.get("code", "").startswith("SOURCE_RIGHTS"):
                no_rights += 1
    claim_sample = family["jobs"] + family["public_activity"]
    return {
        "cohort_rows": len(rows), "company_states": dict(sorted(states.items())),
        "atomic_claims_by_family": dict(sorted(family.items())),
        "company_coverage_by_family": {name: len(companies) for name, companies in company_family.items()},
        "unique_subjects_by_family": {name: len(values) for name, values in subjects.items()},
        "wrong_company_claims": wrong_company, "missing_exact_site_proof_claims": missing_proof,
        "claims_missing_evidence": missing_evidence, "claims_missing_source_snapshots": missing_snapshot,
        "activity_date_claims_missing_as_of": undated, "source_rights_errors": no_rights,
        "claim_error_sample": wilson(wrong_company + missing_proof + missing_evidence + missing_snapshot + undated, claim_sample),
        "gateway_and_runtime_metrics": metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="Canonical M05 JSONL output")
    parser.add_argument("--metrics", type=Path, help="Gateway/runtime JSON captured from batch_complete")
    parser.add_argument("--baseline", type=Path, help="M04 benchmark JSON for M04-to-M05 delta")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.output.read_text(encoding="utf-8").splitlines() if line.strip()]
    metrics = json.loads(args.metrics.read_text(encoding="utf-8")) if args.metrics else {}
    report = summarize(rows, metrics)
    report["cohort"] = {"path": "docs/audit/m00-company-sample-200.jsonl",
        "sha256": "cee97e17af7e8b2d9dc9f5ee60548b9e186a11a2e485469446219ea10a1e38ed",
        "baseline_commit": "0e681ab8fee2d36f41fb8ceb47af4f5fcc0fb96f"}
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else {}
    previous = baseline.get("registry_plus_keyless", {})
    report["m04_delta"] = {
        "m04_accepted_domains": previous.get("accepted_exact_domains", 0),
        "m05_accepted_domains": sum(len(row.get("synthesis", {}).get("website_research", {}).get("accepted_domains", [])) for row in rows),
        "m05_jobs_companies": report["company_coverage_by_family"]["jobs"],
        "m05_activity_companies": report["company_coverage_by_family"]["public_activity"],
        "new_companies_with_hiring_or_activity_claims": len({row.get("organisation_number") for row in rows
            if any(claim.get("section") == "hiring_activity" and claim.get("state") == "available" for claim in row.get("claims", []))}),
    }
    root = Path(__file__).resolve().parents[2]
    website_policy = (root / "config/source_policy.yaml").read_text(encoding="utf-8")
    job_policy = json.loads((root / "config/jobs_source_policy.json").read_text(encoding="utf-8"))
    report["source_rights"] = {"active_source_classes": ["exact_company_owned_website"],
        "external_ats_or_activity_sources_enabled": False,
        "policy_configured": "company_owned_website:" in website_policy and bool(job_policy),
        "site_terms_license_status": "site_specific_terms_unreviewed",
        "site_terms_rule": "site-specific; skip when prohibitive; no third-party acquisition"}
    report["hard_gates"] = {
        "expected_200_company_cohort": len(rows) == 200,
        "one_output_per_input": len(rows) == len({row.get("row_number") for row in rows}),
        "zero_wrong_company_publications": report["wrong_company_claims"] == 0,
        "all_claims_have_exact_site_proof": report["missing_exact_site_proof_claims"] == 0,
        "all_claims_have_evidence_and_snapshot": report["claims_missing_evidence"] == 0 and report["claims_missing_source_snapshots"] == 0,
        "activity_dates_have_explicit_as_of": report["activity_date_claims_missing_as_of"] == 0,
        "source_policy_configured_for_enabled_source_classes": report["source_rights"]["policy_configured"],
        "no_rights_policy_errors_for_published_claims": report["source_rights_errors"] == 0,
        "external_sources_disabled_until_rights_approved": not report["source_rights"]["external_ats_or_activity_sources_enabled"],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0 if all(report["hard_gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
