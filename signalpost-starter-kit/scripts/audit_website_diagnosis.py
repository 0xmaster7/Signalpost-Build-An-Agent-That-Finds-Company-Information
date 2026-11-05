"""Read captured website evidence and emit a public-safe diagnosis without network I/O."""
from __future__ import annotations

import argparse
import ast
import base64
import collections
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
import urllib.parse
from typing import Any


class CapturedHtml(HTMLParser):
    def __init__(self):
        super().__init__()
        self.jsonld = []
        self.script_parts = None
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").casefold() == "application/ld+json":
            self.script_parts = []

    def handle_data(self, data):
        self.text_parts.append(data)
        if self.script_parts is not None:
            self.script_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script_parts is not None:
            try:
                self.jsonld.append(json.loads("".join(self.script_parts)))
            except ValueError:
                pass
            self.script_parts = None


def captured_page_diagnostics(company, attempts):
    result = collections.Counter()
    for attempt in attempts:
        response = attempt.get("response") or {}
        if attempt["request"]["purpose"] != "website_page" or response.get("status") != 200:
            continue
        parser = CapturedHtml()
        parser.feed(base64.b64decode(response["body"]).decode("utf-8", "replace"))
        text = " ".join(parser.text_parts)
        formatted_pattern = r"(?<!\d)" + r"[\s.\-]*".join(company) + r"(?!\d)"
        matches = re.findall(formatted_pattern, text)
        result["pages_with_contiguous_target"] += any(match == company for match in matches)
        result["pages_with_formatted_target"] += any(match != company for match in matches)
        roots = []
        for document in parser.jsonld:
            for record in document if isinstance(document, list) else [document]:
                if isinstance(record, dict):
                    roots.extend(record.get("@graph", [record]))
        indexed = {record["@id"]: record for record in roots if isinstance(record, dict) and isinstance(record.get("@id"), str)}
        for record in roots:
            if not isinstance(record, dict):
                continue
            kinds = record.get("@type", [])
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if "WebSite" not in kinds:
                continue
            publishers = record.get("publisher", [])
            publishers = publishers if isinstance(publishers, list) else [publishers]
            for publisher in publishers:
                if isinstance(publisher, dict) and "@id" in publisher and "@type" not in publisher:
                    result["website_publisher_id_only"] += 1
                    target = indexed.get(publisher["@id"], {})
                    target_types = target.get("@type", [])
                    target_types = target_types if isinstance(target_types, list) else [target_types]
                    result["publisher_reference_resolves_to_organization"] += bool(
                        {"Organization", "Corporation", "LocalBusiness"} & set(target_types))
    return dict(result)


def decode_record(value):
    if isinstance(value, list):
        return [decode_record(item) for item in value]
    if isinstance(value, dict):
        if "$mapping" in value:
            return {key: decode_record(item) for key, item in value["$mapping"]}
        if "$record" in value or "$model" in value:
            return decode_record(value["value"])
        return {key: decode_record(item) for key, item in value.items()}
    return value


def read_capture(path):
    wrapped = json.loads(path.read_text())
    payload = wrapped["payload"]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if hashlib.sha256(encoded).hexdigest() != wrapped["sha256"]:
        raise ValueError("Capture digest mismatch")
    return payload


def origin(url):
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def hostname(url):
    return (urllib.parse.urlsplit(url).hostname or "").removeprefix("www.")


def source_probes(source_path):
    source = ast.parse(source_path.read_text())
    functions = {"normalize_name", "_distinctive_tokens", "keyless_no_candidate", "additional_no_candidates", "_identifier_values"}
    constants = {"LEGAL_SUFFIXES", "GENERIC_KEYLESS"}
    selected = [node for node in source.body if
        isinstance(node, ast.FunctionDef) and node.name in functions or
        isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in constants for target in node.targets)]
    namespace = {"Any": Any, "re": re, "unicodedata": unicodedata, "urllib": urllib}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec"), namespace)
    extract = namespace["_identifier_values"]
    formats = ["912444899", "912 444 899", "912\u00a0444\u00a0899", "912.444.899", "912-444-899", "NO 912 444 899 MVA"]
    for value in formats:
        assert extract(value) == ["912444899"]
        assert bool(re.search(r"(?<!\d)912444899(?!\d)", value)) == (value == "912444899")
    assert extract(912444899) == []
    assert extract("912/444/899") == []
    assert extract("1912444899") == []
    assert extract({"value": "912 444 899"}) == ["912444899"]
    for name in ["OLASTUEN BYGG AS", "KNOWLEDGEGROUP AS", "LAUVVERKET AS", "TVEIT AS", "W-TEK AS"]:
        assert namespace["additional_no_candidates"](name) == []
    assert namespace["additional_no_candidates"]("M VEST WATER AS") == ["https://vest-water.no/", "https://vestwater.no/"]
    assert namespace["additional_no_candidates"]("SUGAR SHOP AS") == ["https://sugar-shop.no/", "https://sugarshop.no/"]
    return {"identifier_formats": len(formats), "boundary_and_type_cases": 4, "candidate_cases": 7, "passed": True}


def website_phases(directory):
    connection = sqlite3.connect((directory / "checkpoint.sqlite").resolve().as_uri() + "?mode=ro")
    try:
        return {company: decode_record(json.loads(payload)) for company, payload in connection.execute(
            "SELECT company, payload FROM phase_results WHERE phase = ?", ("website_verify",))}
    finally:
        connection.close()


def classify(candidate, captures, controls):
    robots_url = origin(candidate["url"]) + "/robots.txt"
    control = controls.get("dns_policy:" + hashlib.sha256(robots_url.encode()).hexdigest(), {})
    if candidate.get("robots_error") == "hostname did not resolve" or control.get("failure") == "unresolved":
        return "DNS"
    if not captures:
        return "unknown_no_captured_attempt"
    terminal = max(captures, key=lambda attempt: (attempt["started_at"], attempt["position"]))
    status = (terminal.get("response") or {}).get("status", 0)
    if terminal["outcome"] == "timeout":
        return "timeout"
    if status == 403:
        return "403"
    if status == 404:
        return "404"
    if status >= 500:
        return "5xx"
    if candidate.get("robots_state") == "disallowed":
        return "disallow"
    if terminal["outcome"] == "transport_error":
        return "unknown_transport_subtype"
    return "unknown_other"


def audit(acceptance_root, comparison_root):
    matched = acceptance_root / "matched"
    phases = website_phases(matched)
    replay_phases = website_phases(acceptance_root / "matched-replay")
    capture_root = matched / "http-capture"
    manifest = read_capture(capture_root / "manifest.json")
    controls = read_capture(capture_root / "execution.json")["controls"]
    captures_by_origin = collections.defaultdict(list)
    captures_by_company = collections.defaultdict(list)
    physical = collections.Counter()
    checked_attempts = 0
    for request_key, entry in manifest["attempts"].items():
        if entry["request"]["phase"] != "website_verify":
            continue
        for position in range(entry["count"]):
            attempt = read_capture(capture_root / f"{request_key}-{position}.json")
            if attempt["key"] != request_key or attempt["position"] != position or attempt["request"] != entry["request"]:
                raise ValueError("Capture index mismatch")
            checked_attempts += 1
            request = attempt["request"]
            captures_by_company[request["company"]].append(attempt)
            if request["purpose"] == "robots":
                captures_by_origin[origin(request["url"])].append(attempt)
                response = attempt.get("response") or {}
                physical[f"{attempt['outcome']}:{response.get('status', 0)}"] += 1
    decisions = collections.Counter()
    sources = collections.Counter()
    unreachable = collections.Counter({key: 0 for key in ["DNS", "connect", "timeout", "403", "404", "5xx", "disallow", "unknown_no_captured_attempt", "unknown_transport_subtype", "unknown_other"]})
    zero_candidates = []
    unreachable_sources = collections.Counter()
    dns_controls_confirmed = 0
    replay_equal = True
    identity_rejections = []
    for company, phase in phases.items():
        candidates = phase["audit"]["candidates"]
        if not candidates:
            zero_candidates.append(company)
        replay_equal &= phase["audit"] == replay_phases[company]["audit"]
        for candidate in candidates:
            decisions[candidate["decision"]] += 1
            sources[candidate["source"]] += 1
            if candidate["decision"] == "robots_unreachable":
                robots_origin = origin(candidate["url"])
                captures = captures_by_origin[robots_origin]
                own_captures = [attempt for attempt in captures if attempt["request"]["company"] == company]
                category = classify(candidate, own_captures or captures, controls)
                unreachable[category] += 1
                unreachable_sources[candidate["source"] + ":" + category] += 1
                control_key = "dns_policy:" + hashlib.sha256((robots_origin + "/robots.txt").encode()).hexdigest()
                dns_controls_confirmed += category == "DNS" and controls.get(control_key, {}).get("failure") == "unresolved"
            if candidate.get("identity_gate_tier") != "not_evaluated":
                identity_rejections.append({"organisation_number": company, "host": hostname(candidate["url"]),
                    "decision": candidate["decision"], "identity": candidate.get("identity"),
                    "tier": candidate.get("identity_gate_tier"), "reason": candidate.get("review_reason")})
    arnav_identity = {}
    with (comparison_root / "arnav/out/envelopes.jsonl").open() as stream:
        for line in stream:
            envelope = json.loads(line)
            identity = envelope.get("website_identity") or {}
            arnav_identity[envelope["organisation_number"]] = {
                "origin": identity.get("origin"), "identity": identity.get("identity"),
                "proof_types": sorted({proof.get("type", "unknown") for proof in identity.get("proofs", [])}),
                "page_status_counts": dict(collections.Counter(str(page.get("status")) for page in identity.get("pages", []))),
                "has_raw_page_body": any(any(key in page for key in ["body", "html", "raw_html"]) for page in identity.get("pages", []))}
    comparison_rows = []
    with (comparison_root / "comparison/per-company.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            if not row["arnav"]["verified_websites"]:
                continue
            company = row["organisation_number"]
            phase = phases.get(company)
            website_hosts = sorted({hostname(site["url"]) for site in row["arnav"]["websites"]})
            candidates = [] if phase is None else phase["audit"]["candidates"]
            comparison_rows.append({"organisation_number": company, "name": row["name"],
                "arnav_hosts": website_hosts, "arnav_evidence": arnav_identity.get(company),
                "original_ours_execution": row["our_pipeline"]["website_execution_state"],
                "matched_candidates": [{"host": hostname(candidate["url"]), "source": candidate["source"],
                    "decision": candidate["decision"], "robots": candidate.get("robots_state"),
                    "identity_tier": candidate.get("identity_gate_tier"),
                    "identity": candidate.get("identity"), "reason": candidate.get("review_reason"),
                    "unreachable_category": classify(candidate, captures_by_origin[origin(candidate["url"])], controls)
                    if candidate["decision"] == "robots_unreachable" else None} for candidate in candidates],
                "arnav_host_generated": any(hostname(candidate["url"]) in website_hosts for candidate in candidates),
                "matched_page_requests": None if phase is None else phase["audit"].get("page_requests"),
                "captured_page_diagnostics": captured_page_diagnostics(company, captures_by_company[company]),
                "matched_physical_attempts": dict(collections.Counter(
                    attempt["request"]["purpose"] + ":" + attempt["outcome"] + ":" + str((attempt.get("response") or {}).get("status", 0))
                    for attempt in captures_by_company[company]))})
    return {"manifest_complete": manifest["complete"], "website_capture_hashes_checked": checked_attempts,
        "website_phase_count": len(phases), "replay_audits_equal": replay_equal,
        "candidate_decisions": dict(decisions), "candidate_sources": dict(sources),
        "unreachable_categories": dict(unreachable), "dns_controls_confirmed": dns_controls_confirmed,
        "unreachable_source_categories": dict(unreachable_sources),
        "no_candidate_companies": sorted(zero_candidates), "robots_physical_attempts": dict(physical),
        "identity_evaluations": identity_rejections, "arnav_verified_company_count": len(comparison_rows),
        "arnav_host_generated_count": sum(row["arnav_host_generated"] for row in comparison_rows),
        "comparison_rows": comparison_rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("acceptance_root", type=Path, nargs="?")
    parser.add_argument("comparison_root", type=Path, nargs="?")
    parser.add_argument("--source-probes", type=Path)
    arguments = parser.parse_args()
    if arguments.source_probes:
        print(json.dumps(source_probes(arguments.source_probes)))
        return
    if arguments.acceptance_root is None or arguments.comparison_root is None:
        parser.error("acceptance_root and comparison_root are required for a captured audit")
    print(json.dumps(audit(arguments.acceptance_root, arguments.comparison_root), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
