"""Read-only, server-rendered research UX over canonical Signalpost output."""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from .query import (CompanyProfile, FindFilter, QueryError, compare_companies, find_companies,
                    build_index, load_profiles, verify_proposition)
from .synthesis import synthesize


CSS = """
:root{font-family:system-ui,-apple-system,sans-serif;color:#17212b;background:#f5f7f8}body{margin:0}header,main{max-width:1120px;margin:auto;padding:1rem}header{display:flex;gap:1rem;align-items:center;flex-wrap:wrap}main{overflow-wrap:anywhere}header a{font-weight:700}.card,section,form{background:white;border:1px solid #d7dfe4;border-radius:.65rem;padding:1rem;margin:.75rem 0}a{color:#075b82}a:focus,button:focus,input:focus,select:focus{outline:3px solid #146c94;outline-offset:2px}.muted{color:#4e5b64}.state{display:inline-block;border:1px solid #73828c;border-radius:1rem;padding:.1rem .55rem;font-size:.86rem}label{display:inline-block;margin:.35rem .4rem .35rem 0}input,select,button{font:inherit;padding:.45rem}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;vertical-align:top;border:1px solid #ccd5db;padding:.55rem;overflow-wrap:anywhere}ul{padding-left:1.3rem}.domains{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.5rem}@media(max-width:650px){header,main{padding:.7rem}.domains{grid-template-columns:1fr}table{display:block;overflow-x:auto}input{max-width:100%}}
"""


def _esc(value: Any) -> str:
    if isinstance(value, (dict, list)):
        import json
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return html.escape(str(value if value is not None else ""), quote=True)


def _url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    if any(ord(ch) < 32 for ch in value):
        return None
    return value


def _link(value: str, label: str | None = None) -> str:
    safe = _url(value)
    if not safe:
        return _esc(label or value)
    return f'<a href="{_esc(safe)}" target="_blank" rel="noopener noreferrer">{_esc(label or safe)}</a>'


def _page(title: str, content: str) -> HTMLResponse:
    return HTMLResponse("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>"
        + _esc(title) + " · Signalpost</title><style>" + CSS + "</style></head><body><header><a href=\"/\">Signalpost research</a>"
        "<a href=\"/compare\">Compare</a><a href=\"/verify\">Verify</a><a href=\"/changes\">Changes</a></header><main><h1>"
        + _esc(title) + "</h1>" + content + "</main></body></html>")


def _value(claim: Any) -> str:
    return _esc(claim.value)


def _citation_html(profile: CompanyProfile, claim: Any) -> str:
    items = []
    for evidence in profile.claim_citations(claim):
        url = evidence["source_url"]
        items.append(f'<a href="/evidence/{quote(profile.organisation_number, safe="")}/{quote(evidence["evidence_id"], safe="")}">Evidence { _esc(evidence["evidence_id"]) }</a> · {_link(url, "source")} · retrieved {_esc(evidence["retrieved_at"])}')
    return "<br>".join(items) if items else "Evidence unavailable"


def _known_claims(profile: CompanyProfile, field: str) -> list[Any]:
    return [claim for claim in profile.claims if claim.state.value == "available" and claim.field == field
            and claim.organisation_number == profile.organisation_number]


def _parse_filters(field: str, operator: str, value: str, currency: str, period_end: str, scope: str, unit: str = "") -> list[FindFilter]:
    if not field and not value:
        return []
    if not field:
        raise QueryError("a filter field is required when a filter value is supplied")
    if len(field) > 80 or len(value) > 300:
        raise QueryError("filter exceeds allowed input size")
    if field in {"revenue", "operating_result", "profit_before_tax", "annual_result", "total_assets", "equity", "total_debt", "employees"}:
        try:
            if operator == "range":
                parts = value.split(",")
                if len(parts) != 2:
                    raise QueryError("numeric range format is lower,upper")
                number: Decimal | tuple[Decimal, Decimal] = (Decimal(parts[0]), Decimal(parts[1]))
            else:
                number = Decimal(value)
            vals = number if isinstance(number, tuple) else (number,)
            if any(not val.is_finite() or len(val.as_tuple().digits) > 30 or abs(val.adjusted()) > 18 for val in vals):
                raise QueryError("numeric filter is outside the supported range")
        except (InvalidOperation, ValueError) as exc:
            if isinstance(exc, QueryError):
                raise
            raise QueryError("numeric filter value is malformed") from exc
    else:
        number = value
    return [FindFilter(field, operator, number, currency or None, period_end or None, scope or None, unit or None)]


def create_app(data_path: str | Path) -> FastAPI:
    rejected_inputs = []
    profiles = load_profiles(data_path, rejected_inputs=rejected_inputs)
    index = build_index(profiles)
    app = FastAPI(title="Signalpost research", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.profiles = profiles

    @app.middleware("http")
    async def bound_request_size(request: Request, call_next):
        if len(str(request.url)) > 4096:
            return PlainTextResponse("request URL exceeds the 4096-character limit", status_code=400)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, q: str = "", field: str = "", op: str = "eq", value: str = "",
             currency: str = "", period_end: str = "", scope: str = "", unit: str = ""):
        try:
            filters = _parse_filters(field, op, value, currency, period_end, scope, unit)
            extra_values = [request.query_params.getlist(key) for key in
                            ("filter_field", "filter_op", "filter_value", "filter_currency", "filter_period_end", "filter_scope", "filter_unit")]
            if len(extra_values[0]) > 3:
                raise QueryError("at most three additional AND filters are supported in the interface")
            for filter_index, extra_field in enumerate(extra_values[0][:3]):
                extra = [values[filter_index] if len(values) > filter_index else "" for values in extra_values[1:]]
                if extra_field or extra[1]:
                    filters.extend(_parse_filters(extra_field, extra[0] or "eq", extra[1], extra[2], extra[3], extra[4], extra[5]))
            result = find_companies(profiles.values(), text=q, filters=filters, index=index)
        except QueryError as exc:
            raise HTTPException(400, str(exc)) from exc
        field_options = (("organisation_number","Exact organisation number"),("legal_form","Legal form"),("municipality","Municipality"),
                ("industry","Industry code"),("employees","Employees"),("revenue","Revenue"),("annual_result","Annual result"),
                ("website","Verified website"))
        form = ('<form method="get" action="/"><label>Company name, brand or organisation number <input name="q" maxlength="300" value="' + _esc(q) + '"></label>'
            '<label>Optional field <select name="field"><option value="">No primary filter</option>'
            + "".join(f'<option value="{name}"{" selected" if field==name else ""}>{label}</option>' for name,label in field_options) + '</select></label><label>Operator <select name="op">'
            + "".join(f'<option value="{name}"{" selected" if op==name else ""}>{name}</option>' for name in ("eq","contains","gt","gte","lt","lte","range"))
            + '</select></label><label>Value <input name="value" maxlength="300" value="' + _esc(value) + '"></label>'
            '<label>Currency <input name="currency" maxlength="3" value="' + _esc(currency) + '"></label>'
            '<label>Period end <input name="period_end" type="date" value="' + _esc(period_end) + '"></label>'
            '<label>Unit <input name="unit" maxlength="40" value="' + _esc(unit) + '"></label>'
            '<label>Scope <select name="scope"><option value="">Choose scope</option>' + "".join(f'<option{" selected" if scope==item else ""}>{item}</option>' for item in ("legal_entity","group","unknown"))
            + '</select></label>')
        for fieldset_index in range(3):
            form += (f'<fieldset><legend>Additional AND filter {fieldset_index+1}</legend><label>Field <select name="filter_field"><option value="">None</option>' + "".join(
                f'<option value="{name}">{label}</option>' for name,label in field_options) + '</select></label><label>Operator <select name="filter_op">' + "".join(
                f'<option value="{name}">{name}</option>' for name in ("eq","contains","gt","gte","lt","lte","range")) + '</select></label>' +
                '<label>Value <input name="filter_value" maxlength="300"></label><label>Currency <input name="filter_currency" maxlength="3"></label>' +
                '<label>Period end <input name="filter_period_end" type="date"></label><label>Scope <input name="filter_scope" maxlength="30"></label><label>Unit <input name="filter_unit" maxlength="40"></label></fieldset>')
        form += '<button type="submit">Find companies</button></form>'
        entries = []
        for item in result["matches"]:
            entries.append(f'<article class="card"><h2><a href="/companies/{quote(item["organisation_number"], safe="")}">{_esc(item["name"])}</a></h2>'
                f'<p>Organisation number {_esc(item["organisation_number"])}</p><p>{len(item["citations"])} supporting source record(s) for filters.</p></article>')
        unknown = "" if not result["unknown"] else '<section><h2>Unknown for these records</h2><ul>' + "".join(
            f'<li>{_esc(item["name"])} ({_esc(item["organisation_number"])}): {_esc("; ".join(item["reasons"]))}</li>' for item in result["unknown"]) + '</ul></section>'
        note = '<p class="muted">Structured filters use AND. Unknown and unavailable source states are kept separate from matches.</p>'
        rejected = ("<section><h2>Inputs that could not be researched</h2><ul>" + "".join(
            "<li>" + _esc(item["input_ref"]) + " (" + _esc(item["organisation_number"]) + "): "
            + _esc("; ".join(str(error.get("message") or error.get("code") or "Input failed")
                             for error in item["errors"] if isinstance(error, dict))) + "</li>"
            for item in rejected_inputs) + "</ul></section>") if rejected_inputs else ""
        return _page("Find companies", form + note + f'<p>{result["result_count"]} match(es)</p>' + "".join(entries) + unknown + rejected)

    @app.get("/companies/{organisation_number}", response_class=HTMLResponse)
    def company(organisation_number: str):
        profile = profiles.get(organisation_number)
        if profile is None:
            raise HTTPException(404, "company not found in loaded canonical data")
        summary = synthesize(_as_envelope_view(profile))
        summary_html = "".join(f'<li>{_esc(item["text"])} <span class="muted">Supported by: ' + " · ".join(
            f'<a href="/evidence/{quote(organisation_number, safe="")}/{quote(eid, safe="")}">{_esc(eid)}</a>'
            for eid in item["evidence_ids"]) + '</span></li>' for item in summary["sentences"])
        by_domain = {"identity_brand": "Identity and public brand", "accounts_history": "Accounts and history",
                     "leadership_workplaces": "Leadership and workplaces", "website_owned_profiles": "Website and owned profiles",
                     "hiring_activity": "Hiring and activity"}
        sections = []
        for name, label in by_domain.items():
            meta = profile.sections.get(name) or {}
            claims = [claim for claim in profile.claims if claim.section == name and claim.organisation_number == organisation_number]
            rows = "".join(f'<li><strong>{_esc(claim.field)}:</strong> {_value(claim)}'
                f'<div class="muted">currency {_esc(claim.currency or "not specified")} · period {_esc(claim.period_start.isoformat() if claim.period_start else "not specified")} – {_esc(claim.period_end.isoformat() if claim.period_end else "not specified")} · scope {_esc(claim.scope or "not specified")}</div>'
                f'<p>{_citation_html(profile, claim)}</p></li>' for claim in claims)
            sections.append(f'<section><h2>{_esc(label)} <span class="state">{_esc(meta.get("state") or meta.get("attempt_outcome") or "unknown / not checked")}</span></h2><ul>{rows or "<li>No supported claim in this section.</li>"}</ul></section>')
        refresh = profile.sections.get("refresh_changes") or {}
        events = "".join(f'<li>{_esc(event.get("type"))}: {_esc(event.get("field"))} · observed {_esc(event.get("observed_at"))} · provenance {"complete" if event.get("provenance_complete") else "incomplete"}</li>' for event in profile.changes)
        state_boxes = "".join(f'<li>{_esc(name)}: <span class="state">{_esc(meta.get("state") or meta.get("attempt_outcome") or "unknown / not checked")}</span></li>' for name,meta in sorted(profile.sections.items()))
        content = f'<p>Organisation number { _esc(organisation_number) }</p><section><h2>Evidence-bounded summary</h2><ul>{summary_html or "<li>No synthesis statements are supported by available claims. The sparse record does not establish inactivity.</li>"}</ul></section>'
        content += "".join(sections) + f'<section><h2>Evidence and availability</h2><ul>{state_boxes}</ul></section><section><h2>Refresh and changes</h2><p>Refresh mode: {_esc((refresh.get("attempt_outcome") or (profile.changes and "changes available") or "baseline / no changes recorded"))}</p><ul>{events or "<li>No verified change events recorded.</li>"}</ul><p><a href="/changes?org={quote(organisation_number)}">View history</a></p></section>'
        return _page("Company profile", content)

    @app.get("/evidence/{organisation_number}/{evidence_id}", response_class=HTMLResponse)
    def evidence_detail(organisation_number: str, evidence_id: str):
        profile = profiles.get(organisation_number)
        item = profile.evidence.get(evidence_id) if profile else None
        snapshot_override = []
        if profile and item is None:
            from .models import ChangeEvidenceRef, ChangeSnapshotRef
            for event in profile.changes:
                for raw in [*(event.get("previous_evidence") or []), *(event.get("current_evidence") or [])]:
                    if raw.get("evidence_id") == evidence_id:
                        item = ChangeEvidenceRef.model_validate(raw)
                for raw in [*(event.get("previous_source_snapshots") or []), *(event.get("current_source_snapshots") or [])]:
                    if item and raw.get("source_id") in item.source_snapshot_ids:
                        snapshot_override.append(ChangeSnapshotRef.model_validate(raw))
        if item is None:
            raise HTTPException(404, "evidence not found")
        snapshot_list = snapshot_override or [profile.snapshots[ref] for ref in item.source_snapshot_ids if ref in profile.snapshots]
        claim_list = [claim for claim in profile.claims if evidence_id in claim.evidence_ids]
        details = f'<dl><dt>Evidence</dt><dd>{_esc(item.evidence_id)}</dd><dt>Organisation</dt><dd>{_esc(organisation_number)}</dd><dt>Source</dt><dd>{_link(item.source_url)}</dd><dt>Source class</dt><dd>{_esc(item.source_class)}</dd><dt>Retrieved</dt><dd>{_esc(item.retrieved_at.isoformat())}</dd><dt>Content SHA-256</dt><dd><code>{_esc(item.content_sha256)}</code></dd><dt>Extraction</dt><dd>{_esc(item.extraction_method)} {_esc(item.json_pointer or "")}</dd><dt>Snapshot(s)</dt><dd>{_esc([snap.model_dump(mode="json") for snap in snapshot_list])}</dd><dt>Supported claim(s)</dt><dd>{_esc([claim.claim_id for claim in claim_list])}</dd></dl>'
        return _page("Evidence detail", '<section>' + details + '</section>')

    @app.get("/compare", response_class=HTMLResponse)
    def compare(request: Request):
        raw = request.query_params.get("org", "")
        orgs = request.query_params.getlist("org") or raw.split(",")
        orgs = [item.strip() for val in orgs for item in val.split(",") if item.strip()]
        fields_raw = request.query_params.get("field", "")
        fields = [item.strip() for item in fields_raw.split(",") if item.strip()] or None
        form = '<form method="get" action="/compare"><label>2–4 organisation numbers, comma separated <input name="org" maxlength="80" required></label><label>Optional canonical fields <input name="field" maxlength="300" placeholder="legal_name,revenue"></label><button>Compare</button></form>'
        if not orgs:
            return _page("Compare companies", form + '<p>Comparisons show source values and their periods/currency/scope. No ranking or derived deltas are produced.</p>')
        try:
            result = compare_companies(profiles, orgs, fields)
        except QueryError as exc:
            raise HTTPException(400, str(exc)) from exc
        rows = []
        for column in result["columns"]:
            vals = "".join(f'<td>{_esc(item["status"])}' + (f': {_esc(item.get("value"))}' if item.get("value") is not None else "") +
                f'<br>{_esc(item.get("currency") or "")} {_esc(item.get("period_end") or "")} {_esc(item.get("scope") or "")}<br>' +
                "<br>".join(_link(cit["source_url"], "evidence source") for cit in item.get("citations", [])) + '</td>' for item in column["values"])
            rows.append(f'<tr><th>{_esc(column["field"])}<br><span class="state">{_esc(column["status"])}</span></th>{vals}</tr>')
        table = '<div style="overflow-x:auto"><table><caption>Like-for-like canonical values only</caption><thead><tr><th>Field</th>' + "".join(f'<th>{_esc(org)}</th>' for org in orgs) + '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
        return _page("Compare companies", form + '<p>Missing values remain unknown/unavailable; incompatible dimensions are marked not comparable. No ranking or deltas are computed.</p>' + table)

    @app.get("/verify", response_class=HTMLResponse)
    def verify(request: Request, org: str = "", field: str = "", value: str = "", currency: str = "", period_end: str = "", scope: str = "", unit: str = ""):
        form = '<form method="get" action="/verify"><label>Organisation number <input name="org" maxlength="9" required value="' + _esc(org) + '"></label><label>Canonical field <input name="field" maxlength="80" required value="' + _esc(field) + '"></label><label>Proposed value <input name="value" maxlength="500" required value="' + _esc(value) + '"></label><label>Currency <input name="currency" maxlength="3" value="' + _esc(currency) + '"></label><label>Period end <input name="period_end" type="date" value="' + _esc(period_end) + '"></label><label>Scope <input name="scope" maxlength="30" value="' + _esc(scope) + '"></label><label>Unit <input name="unit" maxlength="40" value="' + _esc(unit) + '"></label><button>Verify proposition</button></form>'
        if not org and not field and not value:
            return _page("Verify a proposition", form + '<p>Verification compares the exact company, field and requested dimensions against canonical claims and cites the claim evidence.</p>')
        try:
            result = verify_proposition(profiles, organisation_number=org, field=field, value=value,
                currency=currency or None, period_end=period_end or None, scope=scope or None, unit=unit or None)
        except QueryError as exc:
            raise HTTPException(400, str(exc)) from exc
        citations = "".join(f'<li>{_link(item["source_url"])} · {_esc(item["retrieved_at"])} · SHA-256 {_esc(item["content_sha256"])}</li>' for item in result["citations"])
        answer = f'<section><p>Result: <span class="state">{_esc(result["status"])}</span></p><p>{_esc(result["reason"])}</p><h2>Supporting evidence</h2><ul>{citations or "<li>No comparable evidence.</li>"}</ul></section>'
        return _page("Verify a proposition", form + answer)

    @app.get("/changes", response_class=HTMLResponse)
    def changes(org: str = ""):
        chosen = ([profiles[org]] if org in profiles else []) if org else list(profiles.values())
        events = [(profile.organisation_number, event) for profile in chosen for event in profile.changes]
        events.sort(key=lambda pair: (pair[0], str(pair[1].get("observed_at", "")), str(pair[1].get("event_id", ""))))
        rows = ""
        for company_id, event in events:
            citations = []
            for version in ("previous_evidence", "current_evidence"):
                for item in event.get(version) or []:
                    citations.append(f'{_esc(version.removesuffix("_evidence"))}: {_link(str(item.get("source_url") or ""), str(item.get("evidence_id") or "source"))} · {_esc(item.get("retrieved_at"))} · SHA-256 {_esc(item.get("content_sha256"))}')
            provenance = "<br>".join(citations) or ("complete" if event.get("provenance_complete") else "incomplete")
            rows += f'<tr><td><a href="/companies/{quote(company_id, safe="")}">{_esc(company_id)}</a></td><td>{_esc(event.get("type"))}</td><td>{_esc(event.get("field"))}</td><td>{_esc(event.get("old_value"))}</td><td>{_esc(event.get("new_value"))}</td><td>{_esc(event.get("effective_at") or "effective date not established")}</td><td>{_esc(event.get("observed_at"))}</td><td>{provenance}</td></tr>'
        table = '<div style="overflow-x:auto"><table><caption>Canonical M07 refresh events; observation time is separate from effective date.</caption><thead><tr><th>Company</th><th>Type</th><th>Field</th><th>Before</th><th>After</th><th>Effective</th><th>Observed</th><th>Evidence</th></tr></thead><tbody>' + (rows or '<tr><td colspan="8">No material change events recorded.</td></tr>') + '</tbody></table></div>'
        return _page("Changes and history", '<form method="get"><label>Optional organisation number <input name="org" maxlength="9" value="' + _esc(org) + '"></label><button>Show history</button></form>' + table)

    return app


def _as_envelope_view(profile: CompanyProfile):
    """Build only the read-only shape used by the synthesis validator."""
    from types import SimpleNamespace
    from .models import RefreshState, Section
    sections = {name: Section.model_validate(value) for name, value in profile.sections.items()
                if name in {"identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles", "hiring_activity", "claims_evidence_states", "refresh_changes"}}
    required = {"identity_brand", "accounts_history", "leadership_workplaces", "website_owned_profiles", "hiring_activity", "claims_evidence_states", "refresh_changes"}
    for name in required - set(sections):
        sections[name] = Section(state=None, attempt_outcome="not_attempted")
    return SimpleNamespace(organisation_number=profile.organisation_number, claims=profile.claims,
        evidence=list(profile.evidence.values()), source_snapshots=list(profile.snapshots.values()), sections=sections,
        refresh=RefreshState.model_validate({"changes": profile.changes}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the read-only Signalpost research UI")
    parser.add_argument("--data", required=True, help="canonical evaluator JSONL output")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        import uvicorn
        app = create_app(args.data)
    except (OSError, QueryError, ValueError) as exc:
        parser.error(str(exc))
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
