"""Offline, evidence-preserving site data derived from evaluator JSONL."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from .models import ChangeEvent, Envelope, PublicState, approved_frozen_hash_exception
from .synthesis import validate_synthesis

SCHEMA_VERSION = 1
BUNDLE_LIMIT_BYTES = 3_000_000
_CONTACT_FIELD = re.compile(
    r"email|e.?post|phone|telefon|mobile|contact|kontakt|birth|føds|fods|personal.?id|private|privat", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w\d])(?:\+47[ .-]?\d{8}|(?:\+47[ .-]?)?(?:\d{3}[ .-]\d{2}[ .-]\d{3}|\d{2}[ .-]\d{2}[ .-]\d{2}[ .-]\d{2}))(?![\w\d])")
_PERSONAL_ID = re.compile(r"(?<!\d)\d{11}(?!\d)")


class SiteExportError(ValueError):
    """The input cannot safely produce an evidence-preserving export."""


def _json_bytes(value: Any) -> bytes:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for original, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
                              ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        text = text.replace(original, escaped)
    return (text + "\n").encode("utf-8")


def safe_link(source_url: str) -> str | None:
    """Return only absolute HTTP(S) URLs suitable for an escaped href."""
    try:
        parsed = urlsplit(source_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or "\\" in source_url
                or any(character.isspace() or ord(character) < 32 for character in source_url)):
            return None
        parsed.port
    except ValueError:
        return None
    return source_url


def _private_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_CONTACT_FIELD.search(key) or _private_value(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_private_value(child) for child in value)
    return isinstance(value, str) and bool(_EMAIL.search(value) or _PHONE.search(value) or _PERSONAL_ID.search(value))


def _public_claim(claim: Any) -> bool:
    return not (_CONTACT_FIELD.search(claim.field) or _private_value(claim.value)
                or claim.scope == "person_role" and "address" in claim.field.lower())


def _source_record(item: Any) -> dict[str, Any]:
    result = item.model_dump(mode="json")
    excerpt = result.pop("excerpt", None)
    snippet = excerpt
    if snippet is not None:
        for pattern in (_EMAIL, _PHONE, _PERSONAL_ID):
            snippet = pattern.sub("[contact or personal data omitted]", snippet)
    result.update({"snippet": snippet, "snippet_redacted": snippet != excerpt,
                   "snippet_truncated": False, "link_url": safe_link(item.source_url)})
    return result


def _validate_event(event: ChangeEvent, organisation_number: str) -> None:
    if event.organisation_number != organisation_number:
        raise SiteExportError("change event belongs to another company")
    snapshots: dict[str, Any] = {}
    for snapshot in [*event.previous_source_snapshots, *event.current_source_snapshots]:
        prior = snapshots.get(snapshot.source_id)
        if prior is not None and prior != snapshot:
            raise SiteExportError("conflicting change source snapshot identifier")
        snapshots[snapshot.source_id] = snapshot
    evidence: dict[str, Any] = {}
    for item in [*event.previous_evidence, *event.current_evidence]:
        if item.subject_organisation_number != organisation_number:
            raise SiteExportError("change evidence belongs to another company")
        prior = evidence.get(item.evidence_id)
        if prior is not None and prior != item:
            raise SiteExportError("conflicting change evidence identifier")
        evidence[item.evidence_id] = item
        if event.provenance_complete and (not item.source_snapshot_ids or any(
                reference not in snapshots or snapshots[reference].source_url != item.source_url
                or snapshots[reference].content_sha256 != item.content_sha256
                for reference in item.source_snapshot_ids)):
            raise SiteExportError("change evidence does not match its source snapshot")
    if event.provenance_complete and not evidence:
        raise SiteExportError("complete change event has no evidence")


def _read_envelope(raw: dict[str, Any], line_number: int) -> Envelope:
    # Evaluator aliases and wire-only availability markers are normalized at
    # the shared boundary. Canonical checkpoint/history parsing stays direct.
    from .adapter import from_evaluator
    envelope = from_evaluator(raw, row_number=line_number)
    canonical = {claim.claim_id: claim for claim in envelope.claims}
    for section_name, section in envelope.sections.items():
        for claim in section.claims:
            if canonical.get(claim.claim_id) != claim or (
                    section_name != "claims_evidence_states" and claim.section != section_name):
                raise SiteExportError("section claim differs from its canonical claim")
    snapshots = {snapshot.source_id: snapshot for snapshot in envelope.source_snapshots}
    for item in envelope.evidence:
        if item.subject_organisation_number != envelope.organisation_number:
            raise SiteExportError("evidence belongs to another company")
        if not item.source_snapshot_ids or any(reference not in snapshots for reference in item.source_snapshot_ids):
            raise SiteExportError("evidence lacks a bound source snapshot")
        for reference in item.source_snapshot_ids:
            snapshot = snapshots[reference]
            if item.source_url != snapshot.source_url or (
                    item.content_sha256 != snapshot.content_sha256 and not approved_frozen_hash_exception(item, snapshot)):
                raise SiteExportError("evidence does not match its source snapshot")
    for claim in envelope.claims:
        if claim.organisation_number not in {None, envelope.organisation_number}:
            raise SiteExportError("claim belongs to another company")
        if claim.section not in envelope.sections:
            raise SiteExportError("claim has no canonical section")
        if not set(claim.evidence_ids) <= {item.evidence_id for item in envelope.evidence}:
            raise SiteExportError("claim references missing evidence")
        if not set(claim.source_snapshot_ids) <= set(snapshots):
            raise SiteExportError("claim references missing source snapshot")
        if claim.state == PublicState.AVAILABLE and claim.field_family == "financial":
            try:
                if isinstance(claim.value, bool) or not Decimal(str(claim.value)).is_finite():
                    raise SiteExportError("financial value must be finite numeric data")
            except (InvalidOperation, ValueError) as error:
                raise SiteExportError("financial value must be finite numeric data") from error
    events: dict[str, Any] = {}
    for event in envelope.refresh.changes:
        _validate_event(event, envelope.organisation_number)
        if event.event_id in events and events[event.event_id] != event:
            raise SiteExportError("conflicting change event identifier")
        events[event.event_id] = event
    summary = envelope.synthesis.get("summary")
    if summary is not None:
        validate_synthesis(envelope, summary)
    return envelope


def _facet(claims: list[Any], fields: set[str]) -> dict[str, Any]:
    selected = [claim for claim in claims if claim.field in fields]
    available = [claim for claim in selected if claim.state == PublicState.AVAILABLE]
    unique = {_json_bytes(claim.value): claim.value for claim in available}
    values = [unique[key] for key in sorted(unique)]
    states = sorted({claim.state.value for claim in selected})
    state = "available" if len(values) == 1 else "ambiguous" if len(values) > 1 else states[0] if len(states) == 1 else None
    return {"value": values[0] if len(values) == 1 else None, "values": values,
            "state": state, "observed_states": states, "claim_ids": sorted(claim.claim_id for claim in selected)}


def _company(envelope: Envelope) -> dict[str, Any]:
    claims = [claim for claim in envelope.claims if _public_claim(claim)]
    public_ids = {claim.claim_id for claim in claims}
    event_map = {event.event_id: event for event in envelope.refresh.changes if not (
        _CONTACT_FIELD.search(event.field or "") or _private_value(event.old_value) or _private_value(event.new_value))}
    source_ids = {reference for claim in claims for reference in claim.evidence_ids}
    snapshot_ids = {reference for claim in claims for reference in claim.source_snapshot_ids}
    sources = {item.evidence_id: _source_record(item) for item in envelope.evidence if item.evidence_id in source_ids}
    for source in sources.values():
        snapshot_ids.update(source["source_snapshot_ids"])
    snapshots = {item.source_id: {**item.model_dump(mode="json"), "link_url": safe_link(item.source_url)}
                 for item in envelope.source_snapshots if item.source_id in snapshot_ids}
    history = []
    for event in sorted(event_map.values(), key=lambda item: item.event_id):
        record = event.model_dump(mode="json")
        for field_name in ("previous_evidence", "current_evidence"):
            record[field_name] = [_source_record(item) for item in getattr(event, field_name)]
        for field_name in ("previous_source_snapshots", "current_source_snapshots"):
            record[field_name] = [{**item.model_dump(mode="json"), "link_url": safe_link(item.source_url)}
                                  for item in getattr(event, field_name)]
        history.append(record)
    summary = copy.deepcopy(envelope.synthesis.get("summary"))
    omitted_sentences = 0
    if summary is not None:
        sentences = summary.get("sentences", [])
        retained = [sentence for sentence in sentences if set(sentence.get("fact_ids", [])) <= public_ids
                    and set(sentence.get("change_ids", [])) <= set(event_map) and not _private_value(sentence.get("text"))]
        omitted_sentences = len(sentences) - len(retained)
        summary["sentences"] = retained
        if "profile" in summary and (omitted_sentences or _private_value(summary["profile"])):
            summary.pop("profile")
    identity = {"orgnr": envelope.organisation_number,
                "name": _facet(claims, {"name", "legal_name"}),
                "municipality": _facet(claims, {"municipality"}),
                "industry": _facet(claims, {"industry_codes", "industry_codes.0", "industry_codes.1", "industry_codes.2", "industry"})}
    sections = {name: {"state": section.state.value if section.state is not None else None,
                       "attempt_outcome": section.attempt_outcome,
                       "claims": [claim.model_dump(mode="json") for claim in sorted(claims, key=lambda item: item.claim_id)
                                  if claim.section == name]}
                for name, section in sorted(envelope.sections.items())}
    return {"schema_version": SCHEMA_VERSION, "orgnr": envelope.organisation_number,
            "identity": identity, "terminal_state": envelope.terminal_state.value,
            "evidence_cutoff": envelope.evidence_cutoff.isoformat(), "supported_summary": summary,
            "summary_state": "provided" if summary is not None else "not_provided",
            "sections": sections, "sources": sources, "source_snapshots": snapshots,
            "change_history": history,
            "privacy": {"omitted_claims": len(envelope.claims) - len(claims),
                        "omitted_changes": len({event.event_id for event in envelope.refresh.changes}) - len(history),
                        "omitted_summary_sentences": omitted_sentences},
            "provenance_resolver": {"company_file": f"companies/{envelope.organisation_number}.json",
                                    "evidence_pointer": "/sources", "snapshot_pointer": "/source_snapshots",
                                    "change_pointer": "/change_history"}}


def _index_entry(company: dict[str, Any], payload: bytes) -> dict[str, Any]:
    identity = company["identity"]
    return {"orgnr": company["orgnr"], "name": identity["name"]["value"],
            "name_values": identity["name"]["values"], "municipality": identity["municipality"]["values"],
            "industry": identity["industry"]["values"],
            "availability": {"terminal_state": company["terminal_state"],
                             "sections": {name: {"state": section["state"], "attempt_outcome": section["attempt_outcome"]}
                                          for name, section in company["sections"].items()}},
            "company_file": company["provenance_resolver"]["company_file"],
            "company_sha256": hashlib.sha256(payload).hexdigest()}


def _compact_company(company: dict[str, Any], *, snippets: int, facts: int | None) -> dict[str, Any]:
    result = copy.deepcopy(company)
    claims_by_id = {claim["claim_id"]: claim for section in result["sections"].values() for claim in section["claims"]}
    all_claims = list(claims_by_id.values())
    retained_ids = {claim["claim_id"] for claim in all_claims[:facts]} if facts is not None else {claim["claim_id"] for claim in all_claims}
    omitted = [claim for claim in all_claims if claim["claim_id"] not in retained_ids]
    for section in result["sections"].values():
        section["omitted_facts"] = len({claim["claim_id"] for claim in section["claims"]
                                        if claim["claim_id"] not in retained_ids})
        section["claims"] = [claim for claim in section["claims"] if claim["claim_id"] in retained_ids]
    summary = result["supported_summary"]
    omitted_summary = 0
    if facts is not None and summary is not None:
        omitted_summary = len(summary.get("sentences", []))
        result["supported_summary"] = None
        result["summary_state"] = "omitted_from_bundle"
    history = result["change_history"]
    if facts is not None:
        result["change_history"] = []
    for source in result["sources"].values():
        snippet = source["snippet"]
        if snippet is not None and len(snippet) > snippets:
            source["snippet"] = snippet[:snippets]
            source["snippet_truncated"] = True
    if facts is not None:
        used_evidence = {reference for claim in all_claims if claim["claim_id"] in retained_ids for reference in claim["evidence_ids"]}
        result["sources"] = {reference: source for reference, source in result["sources"].items() if reference in used_evidence}
        used_snapshots = {reference for source in result["sources"].values() for reference in source["source_snapshot_ids"]}
        used_snapshots.update(reference for claim in all_claims if claim["claim_id"] in retained_ids for reference in claim["source_snapshot_ids"])
        result["source_snapshots"] = {reference: snapshot for reference, snapshot in result["source_snapshots"].items() if reference in used_snapshots}
    result["compaction"] = {"omitted_facts": len(omitted), "omitted_summary_sentences": omitted_summary,
                            "omitted_changes": len(history) if facts is not None else 0,
                            "snippet_character_limit": snippets,
                            "omitted_source_ids": sorted({reference for claim in omitted for reference in claim["evidence_ids"]}),
                            "omitted_snapshot_ids": sorted({reference for claim in omitted for reference in claim["source_snapshot_ids"]})}
    return result


def _bundle(index: dict[str, Any], companies: dict[str, Any], limit: int) -> bytes:
    bundle = {"schema_version": SCHEMA_VERSION, "company_count": len(companies), "index": index["companies"],
              "companies": companies, "compact": False, "index_file": "index.json"}
    payload = _json_bytes(bundle)
    if len(payload) <= limit:
        return payload
    for snippets, facts in ((360, None), (0, None), (0, 12), (0, 3), (0, 0)):
        bundle["companies"] = {organisation_number: _compact_company(company, snippets=snippets, facts=facts)
                               for organisation_number, company in companies.items()}
        bundle["compact"] = True
        payload = _json_bytes(bundle)
        if len(payload) <= limit:
            return payload
    for company in bundle["companies"].values():
        company["compaction"]["omitted_source_ids"] = []
        company["compaction"]["omitted_snapshot_ids"] = []
        company["compaction"]["source_ids_in_company_file"] = True
        company["identity"] = {"orgnr": company["orgnr"]}
    bundle["index"] = [{"orgnr": entry["orgnr"], "company_file": entry["company_file"],
                        "company_sha256": entry["company_sha256"], "availability": entry["availability"]}
                       for entry in index["companies"]]
    bundle["index_fields_omitted"] = ["name", "name_values", "municipality", "industry"]
    payload = _json_bytes(bundle)
    if len(payload) > limit:
        raise SiteExportError(f"bundle cannot fit the {limit}-byte limit; no files were written")
    return payload


def export_site_data(input_path: str | Path, output_dir: str | Path, *,
                     bundle_limit_bytes: int = BUNDLE_LIMIT_BYTES) -> dict[str, Any]:
    """Export validated company files, index and a capped UTF-8 JSON bundle."""
    if not 1 <= bundle_limit_bytes <= BUNDLE_LIMIT_BYTES:
        raise SiteExportError("bundle limit must be between 1 and 3,000,000 bytes")
    input_file = Path(input_path)
    destination = Path(output_dir)
    if destination.exists() and any(destination.iterdir()):
        raise SiteExportError("output directory must be empty to prevent mixing stale company files")
    companies: dict[str, Any] = {}
    duplicate_rows = 0
    rejected_rows = 0
    with input_file.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                organisation_number = raw.get("organisation_number")
                if not isinstance(organisation_number, str) or not re.fullmatch(r"[0-9]{9}", organisation_number):
                    if (raw.get("terminal_state") == "failed" and not raw.get("claims") and not raw.get("evidence")
                            and any(error.get("code") == "INPUT_INVALID" for error in raw.get("errors", []) if isinstance(error, dict))):
                        rejected_rows += 1
                        continue
                    raise SiteExportError("organisation number must be an exact nine-digit string")
                company = _company(_read_envelope(raw, line_number))
                previous = companies.get(organisation_number)
                if previous is not None:
                    if previous != company:
                        raise SiteExportError("conflicting rows for the same company; export one observation per company")
                    duplicate_rows += 1
                companies[organisation_number] = company
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                raise SiteExportError(f"invalid evaluator row {line_number}: {error}") from error
    companies = dict(sorted(companies.items()))
    files = {organisation_number: _json_bytes(company) for organisation_number, company in companies.items()}
    index = {"schema_version": SCHEMA_VERSION, "company_count": len(companies),
             "duplicate_rows": duplicate_rows, "rejected_input_rows": rejected_rows,
             "companies": [_index_entry(company, files[organisation_number]) for organisation_number, company in companies.items()]}
    bundle_payload = _bundle(index, companies, bundle_limit_bytes)
    index_payload = _json_bytes(index)
    destination.mkdir(parents=True, exist_ok=True)
    company_dir = destination / "companies"
    company_dir.mkdir()
    for organisation_number, payload in files.items():
        (company_dir / f"{organisation_number}.json").write_bytes(payload)
    (destination / "index.json").write_bytes(index_payload)
    (destination / "bundle.json").write_bytes(bundle_payload)
    return {"schema_version": SCHEMA_VERSION, "company_count": len(companies),
            "duplicate_rows": duplicate_rows, "rejected_input_rows": rejected_rows,
            "bundle_bytes": len(bundle_payload), "bundle_sha256": hashlib.sha256(bundle_payload).hexdigest(),
            "output_dir": str(destination)}


def resolve_source(company: dict[str, Any], source_id: str) -> dict[str, Any]:
    """Resolve an evidence ID in a full company file, including historical evidence."""
    if source_id in company.get("sources", {}):
        return company["sources"][source_id]
    for event in company.get("change_history", []):
        for source in [*event["previous_evidence"], *event["current_evidence"]]:
            if source["evidence_id"] == source_id:
                return source
    raise SiteExportError(f"source ID is absent; load {company['provenance_resolver']['company_file']}#{quote(source_id, safe='')}")
