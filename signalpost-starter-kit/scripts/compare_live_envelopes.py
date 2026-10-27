"""Compare independently emitted envelopes without treating claim totals as accuracy."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


FINANCIAL = set("sales_revenue operating_costs payroll_costs net_financial_items tax_expense fixed_assets current_assets receivables cash paid_in_equity retained_earnings short_term_debt long_term_debt financial_income financial_costs total_comprehensive_result revenue operating_result profit_before_tax annual_result total_assets equity total_debt".split())
ALIASES = {"net_result": "annual_result", "name": "legal_name"}
SCALES = {"NOK": Decimal(1), "TNOK": Decimal(1000), "1000 NOK": Decimal(1000), "TUSEN NOK": Decimal(1000),
          "MNOK": Decimal(1000000), "1000000 NOK": Decimal(1000000), "MILLIONER NOK": Decimal(1000000), "EUR": Decimal(1)}


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def safe_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", ""))
    except ValueError:
        return None


def period_date(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat() if value else None
    except ValueError:
        return None


def support(claim, evidence, provider):
    ids = claim.get("evidence_ids") or []
    records = [evidence.get(ref) for ref in ids]
    complete = bool(ids) and all(isinstance(item, dict) and safe_url(item.get("source_url"))
        and re.fullmatch(r"[a-f0-9]{64}", str(item.get("content_sha256", "")))
        and item.get("retrieved_at") and item.get("extraction_method")
        and (item.get("json_pointer") or item.get("page_number") or item.get("excerpt")
             or item.get("claim_span") or item.get("source_path") or item.get("page") or claim.get("source_path"))
        for item in records)
    references = [{"source_url": safe_url(item.get("source_url")), "sha256": item.get("content_sha256"),
                   "method": item.get("extraction_method"), "locator": item.get("json_pointer") or item.get("source_path") or claim.get("source_path"),
                   "page": item.get("page_number") or item.get("page")}
                  for item in records if isinstance(item, dict)]
    return bool(complete), references


def normalize(envelope, provider):
    claims = envelope.get("claims", [])
    evidence = {item.get("evidence_id" if provider == "ours" else "id"): item for item in envelope.get("evidence", [])}
    state_key = "state" if provider == "ours" else "availability"
    financial, fte, websites, references, jobs, inventory = [], [], {}, {}, {}, defaultdict(Counter)
    company_claims = 0
    for claim in claims:
        field = str(claim.get("field", ""))
        canonical_field = ALIASES.get(field, field)
        state = claim.get(state_key, "unknown")
        inventory[canonical_field][state] += 1
        if state != "available":
            continue
        company_claims += 1
        complete, evidence_refs = support(claim, evidence, provider)
        value = claim.get("value")
        period = claim.get("reporting_period") or {}
        start = claim.get("period_start") if provider == "ours" else period.get("start")
        end = claim.get("period_end") if provider == "ours" else period.get("end")
        start, end = period_date(start), period_date(end)
        scope = claim.get("scope") if provider == "ours" else {"SELSKAP": "legal_entity", "KONSERN": "group"}.get(claim.get("account_type"), "unknown")
        if canonical_field in FINANCIAL and number(value) is not None:
            unit = claim.get("unit")
            currency = claim.get("currency") if provider == "ours" else unit
            amount = number(value)
            multiplier = SCALES.get(str(unit).upper())
            journal = None
            if provider == "ours":
                match = re.search(r":filing:(?:(?:legal_entity|group):)?([^:]+):", str(claim.get("subject_id", "")))
                journal = match.group(1) if match else None
            else:
                for ref in claim.get("evidence_ids", []):
                    match = re.search(r"journalnr=([^;\s]+)", str(evidence.get(ref, {}).get("claim_span", "")))
                    if match:
                        journal = match.group(1)
            financial.append({"metric": canonical_field, "value": str(amount), "unit": unit, "currency": currency,
                "period_start": start, "period_end": end, "scope": scope,
                "filing_journal_number": journal,
                "declared_currency_value": str(amount * multiplier) if multiplier is not None else None,
                "unit_basis": ("company_pdf_calibrated_currency_assumption" if claim.get("unit_assumed_currency") else "document_or_explicit_unit") if provider == "ours" else "currency_used_as_unit_unresolved_provider_scale_contract",
                "unit_assumed_currency": bool(claim.get("unit_assumed_currency", False)),
                "unit_assumption_basis": claim.get("unit_assumption_basis"),
                "evidence_metadata_complete": complete, "evidence": evidence_refs})
        if provider == "ours" and field == "full_time_equivalents":
            fte_value = number(value)
        elif provider == "arnav" and field == "workforce" and isinstance(value, dict) and value.get("measure") == "full_time_equivalents":
            fte_value = number(value.get("value"))
            scope = "legal_entity"
        else:
            fte_value = None
        if fte_value is not None:
            fte.append({"metric": "full_time_equivalents", "value": str(fte_value), "period_start": start,
                "period_end": end, "scope": scope, "evidence_metadata_complete": complete,
                "period_basis": "filing_period" if provider == "ours" else "calendar_year_constructed_from_filing_year",
                "evidence": evidence_refs})
        if field in {"verified_website_url", "official_website", "registry_declared_website_url", "shared_website"}:
            url = safe_url(value)
            if url:
                level = claim.get("identity_level")
                strict = (provider == "ours" and field == "verified_website_url") or (
                    provider == "arnav" and field == "official_website" and level in {"exact", "strong"}
                    and not claim.get("site_relation") and not claim.get("note"))
                host = (urlsplit(url).hostname or "").removeprefix("www.")
                target = websites if strict else references
                target[host] = {"url": url, "identity_level": level or claim.get("verification_rule_id"),
                    "field": field, "scope_reasons": claim.get("scope_reasons"),
                    "evidence_metadata_complete": complete, "evidence": evidence_refs}
        if provider == "ours" and claim.get("field_family") == "jobs" and claim.get("scope") == "job":
            subject = claim.get("subject_id") or claim.get("claim_id")
            item = jobs.setdefault(subject, {"subject": subject, "fields": {}, "evidence_metadata_complete": True,
                "source": "NAV" if str(subject).startswith("nav:") else "owned_site"})
            if field == "canonical_job_url":
                item["url"] = safe_url(value)
            elif field in {"job_status", "posting_date", "application_deadline", "job_employer_organisation_number"}:
                item["fields"][field] = value
            item["evidence_metadata_complete"] &= complete
        elif provider == "arnav" and field == "job_posting" and isinstance(value, dict):
            subject = safe_url(value.get("url")) or claim.get("key")
            if subject:
                jobs[subject] = {"subject": claim.get("key"), "url": safe_url(value.get("url")),
                    "source": claim.get("source") or "owned_site", "published": claim.get("effective_date"),
                    "expires": claim.get("valid_through"), "explicit_open_status_proven": False,
                    "evidence_metadata_complete": complete, "evidence": evidence_refs}
    def distinct(items):
        found = {}
        for item in items:
            amount = number(item.get("declared_currency_value", item["value"]))
            identity = {name: item.get(name) for name in ("metric", "currency", "period_start", "period_end", "scope")}
            identity["amount"] = str(amount.normalize()) if amount is not None else None
            key = json.dumps(identity, sort_keys=True)
            if key not in found or item["evidence_metadata_complete"]:
                found[key] = item
        return list(found.values())
    financial, fte = distinct(financial), distinct(fte)
    unique_jobs = {}
    for item in jobs.values():
        uuid = re.search(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", str(item.get("subject", "")) + " " + str(item.get("url", "")))
        key = "nav:" + uuid.group().lower() if uuid else item.get("url") or item["subject"]
        if key not in unique_jobs or str(item.get("source", "")).startswith("NAV"):
            unique_jobs[key] = item
    jobs = unique_jobs
    return {"terminal_state": envelope.get("terminal_state", envelope.get("state")),
        "terminal_status": envelope.get("run", {}).get("terminal_status"),
        "available_atomic_claims": company_claims, "verified_jobs": len(jobs),
        "verified_websites": len(websites), "registry_or_shared_url_references": len(references),
        "fte_claims": len(fte), "financial_claims": len(financial),
        "financial_periods": sorted({item["period_end"] for item in financial if item["period_end"]}),
        "evidence_complete_financial_claims": sum(item["evidence_metadata_complete"] for item in financial),
        "financial": financial, "fte": fte, "websites": list(websites.values()),
        "url_references": list(references.values()), "jobs": list(jobs.values()),
        "field_inventory": {field: dict(states) for field, states in sorted(inventory.items())},
        "error_codes": sorted({str(item.get("code") or item.get("stage") or "unknown") for item in envelope.get("errors", [])}),
        "new_source_contributions": {"nav_jobs": sum(str(item.get("source", "")).startswith("NAV") for item in jobs.values()),
            "registry_url_only_or_shared": len(references)}}


def pair_observations(ours, arnav, family):
    def index(items):
        result = defaultdict(list)
        for item in items:
            key = tuple(item.get(field) for field in ("metric", "period_start", "period_end", "scope", "currency"))
            result[key].append(item)
        return result
    left, right = index(ours[family]), index(arnav[family])
    result = []
    for key in sorted(set(left) | set(right), key=str):
        own, other = left.get(key, []), right.get(key, [])
        values = [{str(number(value)) if number(value) is not None else None
            for item in side for value in [item.get("declared_currency_value", item["value"]) ]} for side in (own, other)]
        numeric_values = [{number(value) for value in side} for side in values]
        journals = [{item["filing_journal_number"] for item in side if item.get("filing_journal_number")} for side in (own, other)]
        if not own:
            status = "only_arnav"
        elif not other:
            status = "only_ours"
        elif len(numeric_values[0]) > 1 or len(numeric_values[1]) > 1:
            status = "conflicting_duplicates"
        elif key[1] is None or key[2] is None or key[3] == "unknown" or None in values[0] or None in values[1]:
            status = "not_comparable_dimensions"
        elif journals[0] and journals[1] and journals[0] != journals[1]:
            status = "different_source_filing"
        else:
            status = "equal_declared_dimensions" if numeric_values[0] == numeric_values[1] else "value_mismatch"
        result.append({"metric": key[0], "period_start": key[1], "period_end": key[2], "scope": key[3], "currency": key[4],
            "status": status, "ours_values": sorted(values[0], key=str), "arnav_values": sorted(values[1], key=str),
            "ours_journals": sorted(journals[0]), "arnav_journals": sorted(journals[1]),
            "unit_contract_caveat": family == "financial" and bool(other)})
    return result


def pipeline(envelope):
    synthesis = envelope.get("synthesis", {})
    registry = synthesis.get("brreg_observations", {})
    document = registry.get("annual_accounts_document", {})
    website = synthesis.get("website_research", {})
    records = registry.get("financial_records", 0)
    withheld = 0
    for error in envelope.get("errors", []):
        match = re.search(r"Financial metric ([A-Za-z_]+) was withheld", str(error.get("message", "")))
        withheld += bool(error.get("code") == "BRREG_FINANCIAL_UNIT_UNSUPPORTED" and match and match.group(1) in FINANCIAL)
    return {"structured_api_unit_withheld_metric_attempts": withheld, "structured_api_records": records,
        "document": {key: document.get(key) for key in ("state", "reason", "pages_processed", "ocr_seconds", "processing_seconds", "financial_claims", "workforce_claims", "cache_hit", "examined_pages", "strategy", "stopped_early", "fte_pages_examined", "financial_anchor_pages", "coverage_complete", "document_pages", "stop_reason") if key in document},
        "financial_calibration": registry.get("financial_calibration", {}),
        "website_execution_state": website.get("execution_state"),
        "website_execution_reason": website.get("reason"),
        "website_crawl_state": website.get("crawl_state"),
        "hiring_diagnostics": envelope.get("sections", {}).get("hiring_activity", {}).get("diagnostics", []),
        "website_candidates": [{key: (safe_url(row.get(key)) if key == "url" else row.get(key)) for key in (
            "url", "source", "decision", "review_reason", "publication_tier", "http_status", "robots_state") if key in row}
            for row in website.get("candidates", [])]}


def load(path):
    with path.open() as source:
        rows = [json.loads(line) for line in source if line.strip()]
    if len(rows) != 100 or len({row["organisation_number"] for row in rows}) != 100:
        raise ValueError("Expected exactly 100 unique terminal envelopes")
    return {row["organisation_number"]: row for row in rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root, destination = args.root, args.output_dir
    execution = json.loads((root / "execution.json").read_text())
    if execution["status"] != "completed" or any(run["status"] != "completed" for run in execution["runs"].values()):
        raise SystemExit("Both original executions must complete successfully before comparison")
    selection = json.loads((root / "selection" / "selection.json").read_text())
    if hashlib.sha256((root / "selection" / "companies.jsonl").read_bytes()).hexdigest() != selection["input_sha256"]:
        raise ValueError("Frozen comparison inputs changed")
    for provider, filename in (("ours", "ours/envelopes.jsonl"), ("arnav", "arnav/out/envelopes.jsonl")):
        record = execution["runs"][provider]
        if record["source_revision_after"] != execution["versions"][provider]:
            raise ValueError("Benchmark source revision changed during execution")
        if hashlib.sha256((root / filename).read_bytes()).hexdigest() != record["output_sha256"]:
            raise ValueError("Original benchmark output changed")
    ours = load(root / "ours" / "envelopes.jsonl")
    arnav = load(root / "arnav" / "out" / "envelopes.jsonl")
    if set(ours) != set(arnav) or set(ours) != {row["organisation_number"] for row in selection["rows"]}:
        raise ValueError("Comparison inputs are not identical")
    with sqlite3.connect(f"file:{root / 'ours' / 'checkpoint.sqlite'}?mode=ro", uri=True) as checkpoint:
        raw = {item["organisation_number"]: item for payload, in checkpoint.execute("SELECT payload FROM envelopes") for item in [json.loads(payload)]}
    comparisons = []
    for selected in selection["rows"]:
        org = selected["organisation_number"]
        own, other = normalize(ours[org], "ours"), normalize(arnav[org], "arnav")
        row = {**selected, "ours": own, "arnav": other, "our_pipeline": pipeline(raw[org]),
            "financial_comparison": pair_observations(own, other, "financial"),
            "fte_comparison": pair_observations(own, other, "fte"),
            "other_fields": [{"field": field, "ours": own["field_inventory"].get(field), "arnav": other["field_inventory"].get(field),
                "comparison": "field_inventory_only_value_shapes_not_assumed_equivalent"}
                for field in sorted(set(own["field_inventory"]) | set(other["field_inventory"]))]}
        comparisons.append(row)
    summary = {"versions": execution["versions"], "input_sha256": selection["input_sha256"], "companies": 100,
        "population": selection["population"], "fixed_six": selection["fixed_companies"],
        "coverage_is_published_evidence_backed_observations_not_accuracy_or_proven_absence": True,
        "financial_comparison_uses_declared_units_not_independently_proven_arnav_scale": True,
        "evidence_complete_is_metadata_check_not_semantic_audit": True, "providers": {}}
    for provider in ("ours", "arnav"):
        rows = [row[provider] for row in comparisons]
        summary["providers"][provider] = {"companies_with_jobs": sum(row["verified_jobs"] > 0 for row in rows),
            "distinct_jobs": sum(row["verified_jobs"] for row in rows),
            "companies_with_verified_website": sum(row["verified_websites"] > 0 for row in rows),
            "companies_with_url_only_or_shared_reference": sum(row["registry_or_shared_url_references"] > 0 for row in rows),
            "companies_with_fte": sum(row["fte_claims"] > 0 for row in rows),
            "companies_with_positive_fte": sum(any(number(item["value"]) > 0 for item in row["fte"]) for row in rows),
            "companies_with_financial_claims": sum(row["financial_claims"] > 0 for row in rows),
            "financial_claims_all_periods": sum(row["financial_claims"] for row in rows),
            "financial_claims_legal_entity": sum(item["scope"] == "legal_entity" for row in rows for item in row["financial"]),
            "financial_claims_group": sum(item["scope"] == "group" for row in rows for item in row["financial"]),
            "financial_claims_evidence_metadata_complete": sum(row["evidence_complete_financial_claims"] for row in rows),
            "terminal_state_counts": dict(Counter(row["terminal_state"] for row in rows)),
            "elapsed_seconds": execution["runs"][provider]["elapsed_seconds"]}
        latest_counts = 0
        for row in comparisons:
            ends = [item["period_end"] for side in ("ours", "arnav") for item in row[side]["financial"]
                    if item["scope"] == "legal_entity" and item["period_end"]]
            latest = max(ends) if ends else None
            latest_counts += sum(item["scope"] == "legal_entity" and item["period_end"] == latest for item in row[provider]["financial"])
        summary["providers"][provider]["financial_claims_latest_standalone_period"] = latest_counts
    summary["financial_comparison"] = dict(Counter(item["status"] for row in comparisons for item in row["financial_comparison"]))
    summary["fte_comparison"] = dict(Counter(item["status"] for row in comparisons for item in row["fte_comparison"]))
    summary["our_pipeline"] = {
        "website_execution_states": dict(Counter(row["our_pipeline"]["website_execution_state"] for row in comparisons)),
        "document_states": dict(Counter(row["our_pipeline"]["document"].get("state", "no_document_record") for row in comparisons)),
        "structured_api_unit_withheld_metric_attempts": sum(row["our_pipeline"]["structured_api_unit_withheld_metric_attempts"] for row in comparisons),
        "new_source_contributions": {key: sum(row["ours"]["new_source_contributions"][key] for row in comparisons)
            for key in ("nav_jobs", "registry_url_only_or_shared")}}
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "per-company.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in comparisons))
    (destination / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    with (destination / "per-company.csv").open("w", newline="") as handle:
        fields = ["organisation_number", "name", "fixed_six_company_cohort"] + [provider + "_" + metric for provider in ("ours", "arnav")
            for metric in ("verified_jobs", "verified_websites", "registry_or_shared_url_references", "fte_claims", "financial_claims")]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in comparisons:
            values = {key: row[key] if key in row else row[key.split("_", 1)[0]][key.split("_", 1)[1]] for key in fields}
            writer.writerow({key: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value
                             for key, value in values.items()})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
