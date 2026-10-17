"""Server-rendered, read-only product UI over canonical saved research."""
from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .query import (CompanyProfile, FindFilter, QueryError, compare_companies, find_companies,
                    build_index, load_profiles, verify_proposition, FIELD_ALIASES)
from .web_ui import (CSS, SCRIPT, LABELS, SECTION_LABELS, available, badge, citation, date_text, dimensions,
    display, empty, esc as _esc, evidence_url, facts, field_claim, label, link as _link,
    name, notice, panel, record_cards, record_groups, roles, safe_url as _url, section_state, source_name)


def _page(title: str,content: str,*,active: str="find",description: str="",eyebrow: str="Research workspace",status_code: int=200,actions: str="") -> HTMLResponse:
    navigation=''.join(f'<a href="{path}"'+(' aria-current="page"' if active==key else '')+f'>{text}</a>' for key,path,text in [('find','/','Find'),('compare','/compare','Compare'),('verify','/verify','Verify'),('changes','/changes','Changes')])
    mark='<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 5h5v14H5zM14 5h5v5h-5zM14 14h5v5h-5z" stroke="currentColor" stroke-width="1.8"/></svg>'
    body=f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{_esc(title)} · Signalpost</title><style>{CSS}</style></head><body><a class="skip" href="#main">Skip to content</a><header class="topbar"><div class="shell topbar-inner"><a class="brand" href="/" aria-label="Signalpost home"><span class="brand-mark">{mark}</span>Signalpost</a><nav class="nav" aria-label="Main navigation">{navigation}</nav><span class="workspace-tag">Company research</span></div></header><div class="shell workspace-bar">Saved research workspace · No live lookups</div><main id="main" class="shell"><div class="page-heading"><div><p class="eyebrow">{_esc(eyebrow)}</p><h1>{_esc(title)}</h1>'+(f'<p class="description">{_esc(description)}</p>' if description else '')+'</div>'+(f'<div class="actions">{actions}</div>' if actions else '')+f'</div>{content}<footer class="footer">Signalpost · Evidence-backed company research. Missing information is not evidence of inactivity.</footer></main><script>{SCRIPT}</script></body></html>'
    return HTMLResponse(body,status_code=status_code)


def _input(name_: str,title: str,value: str="",*,hint: str="",placeholder: str="",required: bool=False,limit: int=300,type_: str="text",list_: str="") -> str:
    attrs=f' name="{_esc(name_)}" value="{_esc(value)}" maxlength="{limit}" type="{type_}"'+(' required' if required else '')+(f' list="{_esc(list_)}"' if list_ else '')
    return f'<label class="field"><span>{_esc(title)}</span><input{attrs} placeholder="{_esc(placeholder)}">'+(f'<span class="helper">{_esc(hint)}</span>' if hint else '')+'</label>'


def _select(name_: str,title: str,options: list[tuple[str,str]],value: str="") -> str:
    if value not in {key for key,_ in options}:options=[(value,'Current input: '+value),*options]
    return f'<label class="field"><span>{_esc(title)}</span><select name="{_esc(name_)}">'+''.join(f'<option value="{_esc(key)}"'+(' selected' if value==key else '')+f'>{_esc(text)}</option>' for key,text in options)+'</select></label>'


def _dimensions_form(values: dict[str,str],prefix: str="") -> str:
    return '<div class="dimensions">'+_input(prefix+'currency','Currency',values.get('currency',''),placeholder='NOK',limit=3)+_input(prefix+'period_end','Period end',values.get('period_end',''),type_='date')+_select(prefix+'scope','Scope',[('','Choose scope'),('legal_entity','Legal entity'),('group','Group'),('unknown','Unknown')],values.get('scope',''))+_input(prefix+'unit','Unit',values.get('unit',''),placeholder='Exact source unit',limit=40)+'</div>'


def _company_options(profiles: dict[str,CompanyProfile]) -> str:
    return '<datalist id="saved-companies">'+''.join(f'<option value="{_esc(org)}">{_esc(name(profile))}</option>' for org,profile in sorted(profiles.items()))+'</datalist>'


def _error(message: str) -> str:
    return notice(message,'Check your input',error=True)


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



FIELD_OPTIONS=[('','No filter'),('organisation_number','Organisation number'),('legal_form','Legal form'),('municipality','Municipality'),('industry','Industry code'),('employees','Employees'),('revenue','Revenue'),('annual_result','Annual result'),('website','Verified website')]
OPERATORS=[('eq','Equals'),('contains','Contains'),('gt','Greater than'),('gte','At least'),('lt','Less than'),('lte','At most'),('range','Between (lower,upper)')]


def _find_form(request: Request) -> str:
    params=request.query_params
    def rule(values: dict[str,str],prefix: str="") -> str:
        return '<div class="form-grid three">'+_select(prefix+'field','Field',FIELD_OPTIONS,values.get('field',''))+_select(prefix+'op','Condition',OPERATORS,values.get('op') or 'eq')+_input(prefix+'value','Value',values.get('value',''),placeholder='Value to match')+'</div>'+_dimensions_form(values,prefix)
    primary={key:params.get(key,'') for key in ['field','op','value','currency','period_end','scope','unit']}
    extra_keys=['field','op','value','currency','period_end','scope','unit']
    extras=[{key:(params.getlist('filter_'+key)[i] if len(params.getlist('filter_'+key))>i else '') for key in extra_keys} for i in range(3)]
    opened=bool(primary['field'] or primary['value'] or any(v['field'] or v['value'] for v in extras))
    additional=''.join(f'<fieldset class="filter-rule"><legend>Additional AND filter {i+1}</legend>{rule(values,"filter_")}</fieldset>' for i,values in enumerate(extras))
    return '<form class="panel search-panel" method="get" action="/#results" aria-label="Find saved companies"><div class="search-row">'+_input('q','Company name, brand or organisation number',params.get('q',''),placeholder='Search saved companies, e.g. Equinor or 923609016')+'<button type="submit" data-pending="Searching saved records…">Find companies <span aria-hidden="true">→</span></button></div><p class="search-hint">Search the records already loaded into this workspace. This does not start new research.</p><details class="disclosure"'+(' open' if opened else '')+'><summary>Advanced filters</summary><p class="helper small">All conditions use AND. Financial filters require matching currency, period, scope and unit; missing facts stay unknown.</p><fieldset class="filter-rule"><legend>Primary condition</legend>'+rule(primary)+'</fieldset><details class="disclosure"'+(' open' if any(v['field'] or v['value'] for v in extras) else '')+'><summary>Additional AND conditions</summary>'+additional+'</details></details></form>'


def _overview(profile: CompanyProfile) -> str:
    tiles=[]
    for title,fields in [('Legal form',['legal_form_description','legal_form']),('Employees in saved record',['employees']),('Registered address',['business_address'])]:
        claim=next((field_claim(profile,key) for key in fields if field_claim(profile,key)),None)
        tiles.append(f'<div class="overview-item"><p class="eyebrow">{_esc(title)}</p><div class="value">{display(claim.value) if claim else "Not recorded"}</div>'+(citation(profile,claim) if claim else '<p class="muted small">No supported fact loaded</p>')+'</div>')
    return '<div class="overview">'+''.join(tiles)+'</div>'


def _source_list(profile: CompanyProfile) -> str:
    entries=[]
    for snapshot in sorted(profile.snapshots.values(),key=lambda s:(s.source_url,s.source_id)):
        refs=[e for e in profile.evidence.values() if snapshot.source_id in e.source_snapshot_ids]
        hostname=source_name(snapshot.source_url)
        action=f'<a class="evidence-action" href="{evidence_url(profile.organisation_number,refs[0].evidence_id)}">Source details</a>' if refs else '<span class="muted small">No claim evidence for this observation</span>'
        entries.append(f'<li><div class="source-heading"><strong class="small">{_esc(hostname)}</strong>{action}</div><p class="muted small">Observed {date_text(snapshot.retrieved_at)} · {_esc(snapshot.rights_status)}</p><details class="record-details"><summary>Observation metadata</summary><div class="technical"><dl><dt>Source URL</dt><dd>{_link(snapshot.source_url)}</dd><dt>Snapshot identifier</dt><dd class="mono">{_esc(snapshot.source_id)}</dd><dt>Content SHA-256</dt><dd class="mono">{_esc(snapshot.content_sha256)}</dd><dt>Retrieved</dt><dd>{_esc(date_text(snapshot.retrieved_at,full=True))}</dd><dt>HTTP status</dt><dd>{_esc(snapshot.http_status)}</dd></dl></div></details></li>')
    return '<ul class="source-list">'+''.join(entries)+'</ul>' if entries else empty('No source observations loaded','There are no source snapshots available for this saved company.')


def _profile_content(profile: CompanyProfile) -> str:
    org=profile.organisation_number
    identity=available(profile,section='identity_brand')
    financial=available(profile,section='accounts_history')
    numeric=[c for c in financial if c.field_family=='financial']
    financial_body=record_cards(profile,'financial')
    other_financial=[c for c in financial if c.field_family not in {'financial','financial_record_metadata'}]
    if other_financial:financial_body+=facts(profile,other_financial,show_dimensions=True)
    if not numeric:financial_body=notice('No verified numeric financial metrics are available in this saved record. Filing metadata does not establish revenue or profit. Missing values are not zero.','Financial coverage')+financial_body
    if not financial:financial_body+=empty('No supported financial records','Check the source state for this section; the absence of figures does not establish that the company has no accounts.')
    leadership=roles(profile) or empty('No supported role records','The saved evidence does not establish leadership or role holders.')
    workplace=record_cards(profile,'workplace') or empty('No supported workplaces','No workplace records could be established from the loaded evidence.')
    websites=available(profile,section='website_owned_profiles')
    hiring=available(profile,section='hiring_activity')
    nav='<nav class="section-nav" aria-label="Company sections">'+''.join(f'<a href="#{key}">{text}</a>' for key,text in [('identity','Identity'),('financials','Financials'),('leadership','Leadership'),('workplaces','Workplaces'),('websites','Websites'),('activity','Hiring & activity'),('history','Changes'),('sources','Sources')])+'</nav>'
    body=panel('identity','Company identity','Source-backed identity and registration details.',facts(profile,identity) if identity else empty('Identity not established','No supported identity facts were loaded.'),section_state(profile,'identity_brand'))
    body+=panel('financials','Financial records','Filing metadata grouped by its exact source record, accounting period and scope.',financial_body,section_state(profile,'accounts_history'))
    body+=panel('leadership','Leadership and roles','Holders are joined to roles only when their evidence points to the same source record.',leadership)
    body+=panel('workplaces','Registered workplaces','Locations reported for this company in the saved evidence.',workplace)
    other_lead=[c for c in available(profile,section='leadership_workplaces') if c.field_family not in {'role','workplace'}]
    if other_lead:body+=panel('other-roles','Other supported registration facts','These facts are not joined to a person or workplace.',facts(profile,other_lead))
    body+=panel('websites','Verified websites and profiles','A website is published only when the canonical evidence establishes the company relationship.',facts(profile,websites) if websites else empty('No verified website or profile','The saved evidence does not establish an owned website. This does not mean the company has no website.'),section_state(profile,'website_owned_profiles'))
    body+=panel('activity','Hiring and public activity','Only supported postings and dated activity appear here.',facts(profile,hiring,show_dimensions=True) if hiring else empty('No supported hiring or activity claims','This section may not have been attempted or its evidence may be unavailable. It is not a claim that the company is inactive.'),section_state(profile,'hiring_activity'))
    changes=f'<p class="muted small">Refresh mode: {_esc((profile.sections.get("refresh_changes") or {}).get("attempt_outcome") or "Not recorded")}</p>'
    changes+=(f'<p style="margin-top:12px">{len(profile.changes)} supported material change event(s) in this saved record.</p>' if profile.changes else '<p style="margin-top:12px">No verified change events recorded. An unchanged refresh is a valid result.</p>')
    changes+=f'<p style="margin-top:16px"><a class="button secondary" href="/changes?org={quote(org)}">View history</a></p>'
    body+=panel('history','Changes and history','Previous evidence is retained when supported material changes are recorded.',changes)
    body+=panel('sources','Sources and evidence','Source links and snapshot observations. Technical provenance is available on demand.',_source_list(profile))
    if profile.errors:
        body+='<details class="panel"><summary>Research notes and diagnostics</summary><ul>'+''.join(f'<li class="small">{_esc(e.get("message") or e.get("code"))}</li>' for e in profile.errors)+'</ul></details>'
    dates=[e.retrieved_at for e in profile.evidence.values()]
    observation=date_text(max(dates)) if dates else 'Not recorded'
    status='<ul class="status-list">'+''.join(f'<li><span>{_esc(SECTION_LABELS.get(key,label(key)))}</span>{badge(section_state(profile,key))}</li>' for key in ['identity_brand','accounts_history','leadership_workplaces','website_owned_profiles','hiring_activity','refresh_changes'])+'</ul>'
    coverage_details='<details class="disclosure"><summary>Coverage details</summary><dl class="facts">'+''.join(f'<dt>{_esc(SECTION_LABELS.get(key,label(key)))}</dt><dd>State: {_esc(meta.get("state") or "Not recorded")}<br>Attempt: {_esc(meta.get("attempt_outcome") or "Not recorded")}</dd>' for key,meta in sorted(profile.sections.items()))+'</dl></details>'
    aside='<aside class="profile-aside" aria-label="Research coverage"><section class="panel"><p class="eyebrow">Research coverage</p><h2 style="margin-top:7px">What the evidence supports</h2>'+status+'<p class="helper small" style="margin-top:16px">Availability applies to each section. It does not guarantee that every requested fact was found.</p>'+coverage_details+'</section><section class="panel"><p class="eyebrow">Source observation</p><p style="margin-top:8px">'+_esc(observation)+'</p><p class="helper small" style="margin-top:8px">Latest evidence retrieval in the loaded record. This page does not refresh sources.</p></section></aside>'
    freshness=f'<p class="profile-subline" style="margin-bottom:18px"><span>Latest source observation: <time>{_esc(observation)}</time></span><span>Evidence retrieved, not a live status check</span></p>'
    return freshness+_overview(profile)+nav+'<div class="profile-layout"><div class="profile-main">'+body+'</div>'+aside+'</div>'


def create_app(data_path: str | Path) -> FastAPI:
    rejected_inputs=[]
    profiles=load_profiles(data_path,rejected_inputs=rejected_inputs)
    index=build_index(profiles)
    app=FastAPI(title='Signalpost research',docs_url=None,redoc_url=None,openapi_url=None)
    app.state.profiles=profiles

    @app.exception_handler(StarletteHTTPException)
    async def display_http_error(request: Request,exc: StarletteHTTPException):
        return _page('Page unavailable' if exc.status_code==404 else 'Request could not be completed',notice(str(exc.detail),'Unable to open this view',error=True)+'<a class="button secondary" href="/">Return to saved companies</a>',description='Your saved company data has not changed.',status_code=exc.status_code)

    @app.middleware('http')
    async def bound_request_size(request: Request,call_next):
        if len(str(request.url))>4096:return _page('Request too long',_error('request URL exceeds the 4096-character limit'),status_code=400)
        return await call_next(request)

    @app.get('/',response_class=HTMLResponse)
    def home(request: Request,q: str='',field: str='',op: str='eq',value: str='',currency: str='',period_end: str='',scope: str='',unit: str=''):
        error=None;result=None;filters=[]
        try:
            filters=_parse_filters(field,op,value,currency,period_end,scope,unit)
            extra_values=[request.query_params.getlist(key) for key in ('filter_field','filter_op','filter_value','filter_currency','filter_period_end','filter_scope','filter_unit')]
            if len(extra_values[0])>3:raise QueryError('at most three additional AND filters are supported in the interface')
            for i,extra_field in enumerate(extra_values[0][:3]):
                extra=[values[i] if len(values)>i else '' for values in extra_values[1:]]
                if extra_field or extra[1]:filters.extend(_parse_filters(extra_field,extra[0] or 'eq',extra[1],extra[2],extra[3],extra[4],extra[5]))
            result=find_companies(profiles.values(),text=q,filters=filters,index=index)
        except QueryError as exc:error=str(exc)
        content=(_error(error) if error else '')+_find_form(request)
        if result is not None:
            count=result['result_count'];heading=f'{count} '+('match' if count==1 else 'matches')
            content+=f'<div class="results-heading" id="results" tabindex="-1"><h2>{heading}</h2><p>{len(profiles)} saved companies · '+('Advanced conditions applied' if filters else 'Evidence available inside each profile')+'</p></div>'
            entries=[]
            for item in result['matches']:
                profile=profiles[item['organisation_number']];meta=[]
                for key in ['legal_form','municipality']:
                    claim=field_claim(profile,key)
                    if claim:meta.append(str(claim.value))
                meta_html=''.join(f'<span>{_esc(v)}</span>' for v in meta)
                proof=''
                if filters:
                    refs=item['citations']
                    proof=(f'<details class="match-proof"><summary>Why this matches · {len(refs)} supporting source record(s)</summary><ul>'+''.join(f'<li><a href="{evidence_url(profile.organisation_number,c["evidence_id"])}">View matching evidence</a></li>' for c in refs)+'</ul></details>') if refs else '<p class="match-proof">Exact company filter matched.</p>'
                initials=''.join(word[0] for word in name(profile).split()[:2])
                entries.append(f'<article class="card result-card"><div class="company-main"><span class="company-monogram" aria-hidden="true">{_esc(initials)}</span><div><h2><a href="/companies/{profile.organisation_number}">{_esc(name(profile))}</a></h2><div class="company-meta"><span>Org. {profile.organisation_number}</span>{meta_html}</div>{proof}</div></div><div class="result-tail"><a href="/companies/{profile.organisation_number}">View profile <span aria-hidden="true">→</span></a></div></article>')
            content+='<div class="result-list">'+''.join(entries)+'</div>' if entries else empty('No verified matches','Try a saved company name or organisation number, or review the advanced filters. Unknown information is not treated as a negative fact.')
            if result['unknown']:
                unknown=''.join(f'<li><a href="/companies/{_esc(item["organisation_number"])}">{_esc(item["name"])}</a><p class="helper small">{_esc("; ".join(item["reasons"]))}</p></li>' for item in result['unknown'])
                content+=panel('unknown','Not established by saved evidence','These records may meet the conditions, but the available facts cannot establish that.',f'<ul class="source-list">{unknown}</ul>')
        if rejected_inputs:
            content+='<details class="panel disclosure"><summary>Inputs that could not be researched</summary><ul>'+''.join('<li>'+_esc(item['input_ref'])+' ('+_esc(item['organisation_number'])+'): '+_esc('; '.join(str(e.get('message') or e.get('code') or 'Input failed') for e in item['errors'] if isinstance(e,dict)))+'</li>' for item in rejected_inputs)+'</ul></details>'
        return _page('Find companies',content,description='Explore saved company research, follow the sources and see what remains unknown.',status_code=400 if error else 200)

    @app.get('/companies/{organisation_number}',response_class=HTMLResponse)
    def company(organisation_number: str):
        profile=profiles.get(organisation_number)
        if profile is None:raise HTTPException(404,'company not found in loaded canonical data')
        form=field_claim(profile,'legal_form')
        description=f'Organisation number {organisation_number}'+(' · '+str(form.value) if form else '')+' · Saved research'
        return _page(name(profile),'<p class="breadcrumb"><a href="/">← All saved companies</a></p>'+_profile_content(profile),description=description,eyebrow='Company profile',actions=f'<a class="button secondary" href="/verify?org={organisation_number}">Verify a fact</a>')

    @app.get('/evidence/{organisation_number}/{evidence_id}',response_class=HTMLResponse)
    def evidence_detail(organisation_number: str,evidence_id: str):
        profile=profiles.get(organisation_number);item=profile.evidence.get(evidence_id) if profile else None;snapshot_override=[]
        if profile and item is None:
            from .models import ChangeEvidenceRef,ChangeSnapshotRef
            for event in profile.changes:
                candidate=next((raw for raw in [*(event.get('previous_evidence') or []),*(event.get('current_evidence') or [])] if raw.get('evidence_id')==evidence_id),None)
                if candidate:
                    item=ChangeEvidenceRef.model_validate(candidate)
                    snapshot_override=[ChangeSnapshotRef.model_validate(raw) for raw in [*(event.get('previous_source_snapshots') or []),*(event.get('current_source_snapshots') or [])] if raw.get('source_id') in item.source_snapshot_ids]
                    break
        if item is None:raise HTTPException(404,'evidence not found')
        snapshots=snapshot_override or [profile.snapshots[ref] for ref in item.source_snapshot_ids if ref in profile.snapshots]
        supported=[c for c in profile.claims if evidence_id in c.evidence_ids]
        host=source_name(item.source_url)
        content=f'<p class="breadcrumb"><a href="/companies/{organisation_number}">← {_esc(name(profile))}</a></p><div class="evidence-overview"><div class="card"><p class="eyebrow">Source</p><div class="value">{_esc(host)}</div><p class="muted small">{_esc(item.source_class)}</p></div><div class="card"><p class="eyebrow">Retrieved</p><div class="value">{date_text(item.retrieved_at)}</div></div><div class="card"><p class="eyebrow">Company</p><div class="value">{_esc(name(profile))}</div><p class="muted small">{organisation_number}</p></div></div>'
        content+=panel('source','Source reference','The source associated with this evidence record.',f'<p>{_link(item.source_url)}</p>')
        if supported:content+=panel('supported-facts','Supported facts','Each value below points to this exact evidence record.',facts(profile,supported,show_dimensions=True))
        else:content+=notice('This evidence is retained for a historical event or source observation. It is not presented as a current company fact.')
        technical=f'<div class="technical"><dl><dt>Evidence identifier</dt><dd class="mono">{_esc(item.evidence_id)}</dd><dt>Content SHA-256</dt><dd class="mono">{_esc(item.content_sha256)}</dd><dt>Extraction method</dt><dd class="mono">{_esc(item.extraction_method)}</dd><dt>Extraction locator</dt><dd class="mono">{_esc(item.json_pointer or "Not recorded")}</dd><dt>Retrieved timestamp</dt><dd>{_esc(date_text(item.retrieved_at,full=True))}</dd></dl></div>'
        canonical_details='<details class="disclosure"><summary>Canonical claim details</summary><div class="technical"><pre class="mono">'+_esc(json.dumps([c.model_dump(mode="json") for c in supported],ensure_ascii=False,sort_keys=True,indent=2))+'</pre></div></details>' if supported else ''
        snapshot_html=''.join(f'<article class="record"><h3>Snapshot observation</h3><dl class="facts">'+''.join(f'<dt>{_esc(label(k))}</dt><dd class="mono">{_esc(v)}</dd>' for k,v in snap.model_dump(mode='json').items())+'</dl></article>' for snap in snapshots)
        content+='<section class="panel"><h2>Technical provenance</h2><p class="helper small" style="margin-top:7px">Exact hashes, locators and source snapshots are preserved for inspection.</p><details class="disclosure"><summary>Evidence identifiers, hash and extraction</summary>'+technical+'</details><details class="disclosure"><summary>Snapshot(s) and permissions</summary><div class="record-grid">'+snapshot_html+'</div></details>'+canonical_details+'</section>'
        return _page('Evidence detail',content,description='Inspect the source behind a fact, including its retrieval and provenance.')

    @app.get('/compare',response_class=HTMLResponse)
    def compare(request: Request):
        raw=request.query_params.get('org','');orgs=request.query_params.getlist('org') or raw.split(',');orgs=[item.strip() for val in orgs for item in val.split(',') if item.strip()]
        fields_raw=request.query_params.get('field','');fields=[item.strip() for item in fields_raw.split(',') if item.strip()] or None
        selections=orgs[:4] if len(orgs)<=4 else [','.join(orgs)]
        company_inputs=[_input('org',f'Company {i+1}'+(' (optional)' if i>1 else ''),selections[i] if len(selections)>i else '',placeholder='Choose or enter an organisation number',list_='saved-companies',required=i==0,limit=80) for i in range(4)]
        inputs=''.join(company_inputs[:2])
        additional='<details class="disclosure"'+(' open' if len(orgs)>2 else '')+'><summary>Add more companies (up to four)</summary><div class="form-grid">'+''.join(company_inputs[2:])+'</div></details>'
        form='<form class="panel" method="get" action="/compare#comparison" aria-label="Compare saved companies"><div class="form-grid">'+inputs+'</div>'+additional+_company_options(profiles)+'<p class="helper small" style="margin-top:14px">Choose two to four saved companies. You can also paste comma-separated organisation numbers into a field.</p><details class="disclosure"'+(' open' if fields_raw else '')+'><summary>Choose specific comparison fields</summary>'+_input('field','Canonical fields, comma separated',fields_raw,placeholder='legal_name,revenue',hint='Leave empty for the standard comparison.')+'</details><button type="submit" style="margin-top:20px" data-pending="Comparing saved records…">Compare companies</button></form>'
        error=None;result=None
        if orgs:
            try:result=compare_companies(profiles,orgs,fields)
            except QueryError as exc:error=str(exc)
        content=(_error(error) if error else '')+form
        if result:
            headers=''.join(f'<th scope="col"><a href="/companies/{org}">{_esc(name(profiles[org]))}</a><small>Org. {org}</small></th>' for org in orgs)
            rows=[]
            for column in result['columns']:
                cells=[]
                for org in orgs:
                    values=[v for v in column['values'] if v['organisation_number']==org]
                    blocks=[]
                    for item in values:
                        dimension_text=' · '.join(str(v) for v in [item.get('currency'),(' – '.join(date_text(item.get(k)) for k in ['period_start','period_end'])) if item.get('period_start') or item.get('period_end') else None,LABELS.get(item.get('scope'),item.get('scope')),item.get('unit')] if v)
                        refs=item.get('citations',[])
                        proof='<details><summary>View evidence</summary><ul class="source-list">'+''.join(f'<li><a href="{evidence_url(org,c["evidence_id"])}">Source details</a><p class="muted small">Observed {date_text(c["retrieved_at"])}</p></li>' for c in refs)+'</ul></details>' if refs else ''
                        blocks.append((f'<div class="cell-value">{display(item["value"])}</div>' if item.get('value') is not None else '')+badge(item['status'])+(f'<p class="dimensions-note">{_esc(dimension_text)}</p>' if dimension_text else '')+proof)
                    cells.append('<td>'+('<hr>'.join(blocks))+'</td>')
                rows.append(f'<tr><th scope="row">{_esc(label(column["field"]))}<div style="margin-top:9px">{badge(column["status"])}</div></th>'+''.join(cells)+'</tr>')
            content+='<section id="comparison" tabindex="-1"><div class="results-heading"><h2>Comparison results</h2></div>'+notice('Only like-for-like values are comparable. Unknown values stay unknown; not comparable means a fact is missing, has multiple values, or its dimensions differ. No rankings or derived deltas are calculated.')
            content+='<p class="scroll-hint">Scroll horizontally to inspect all companies on smaller screens.</p><div class="table-wrap" role="region" aria-label="Company comparison" tabindex="0"><table class="compare-table"><caption class="sr-only">Like-for-like canonical values only</caption><thead><tr><th class="row-label" scope="col">Company facts</th>'+headers+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></section>'
        elif not error:content+=empty('Compare the facts side by side','Select saved companies above to compare their supported facts, availability and sources.')
        return _page('Compare companies',content,active='compare',description='Compare existing research with the reporting period, scope and source context intact.',status_code=400 if error else 200)

    @app.get('/verify',response_class=HTMLResponse)
    def verify(request: Request,org: str='',field: str='',value: str='',currency: str='',period_end: str='',scope: str='',unit: str=''):
        chosen=field or 'legal_name'
        options=[('legal_name','Legal company name'),('legal_form','Legal form'),('organisation_number','Organisation number'),('brand','Public brand'),('municipality','Municipality'),('industry','Industry code'),('employees','Employees'),('website','Verified website'),('role','Role holder'),('job','Job title')]+[(key,label(key)) for key in ['revenue','operating_result','profit_before_tax','annual_result','total_assets','equity','total_debt']]
        advanced=any([currency,period_end,scope,unit])
        form='<form class="panel" method="get" action="/verify#decision" aria-label="Verify a saved fact"><div class="form-grid">'+_input('org','Company organisation number',org,placeholder='923609016',required=True,limit=9,list_='saved-companies')+_select('field','Fact to check',options,chosen)+'</div><div style="margin-top:18px">'+_input('value','Proposed value',value,placeholder='For example, EQUINOR ASA',required=True,limit=500)+'</div>'+_company_options(profiles)+'<details class="disclosure"'+(' open' if advanced else '')+'><summary>Advanced fact dimensions</summary><p class="helper small">Financial facts require exact currency, period end, scope and unit. Dimensions must match the saved claim.</p>'+_dimensions_form({'currency':currency,'period_end':period_end,'scope':scope,'unit':unit})+'</details><button type="submit" style="margin-top:20px" data-pending="Checking saved evidence…">Verify proposition</button></form>'
        error=None;result=None
        if field or value:
            try:result=verify_proposition(profiles,organisation_number=org,field=field,value=value,currency=currency or None,period_end=period_end or None,scope=scope or None,unit=unit or None)
            except QueryError as exc:error=str(exc)
        content=(_error(error) if error else '')+form
        if result:
            explanations={'supported':'The saved evidence supports this proposed value.','contradicted':'A comparable saved fact records a different value.','insufficient_evidence':'The saved evidence cannot establish this proposition. This does not mean it is false.','unavailable':'No comparable fact is available in the loaded research.'}
            content+=f'<section id="decision" tabindex="-1" class="result-banner" data-state="{_esc(result["status"])}" role="status">{badge(result["status"])}<h2>{_esc(explanations.get(result["status"],result["reason"]))}</h2><p>{_esc(result["reason"])}</p>'
            profile=profiles.get(org);selected=[c for c in available(profile) if c.claim_id in result.get('claim_ids',[])] if profile else []
            if selected:content+='<div class="canonical-value"><p class="eyebrow">Saved canonical value</p>'+facts(profile,selected,show_dimensions=True)+'</div>'
            refs=result.get('citations',[])
            if refs:
                content+='<details class="disclosure"><summary>Supporting evidence and source details</summary><ul class="source-list">'+''.join(f'<li><div class="source-heading">{_link(c["source_url"],source_name(c["source_url"]))}<a href="{evidence_url(org,c["evidence_id"])}">View evidence</a></div><p class="muted small">Retrieved {date_text(c["retrieved_at"])}</p><div class="technical" style="margin-top:12px"><dl><dt>Content SHA-256</dt><dd class="mono">{_esc(c["content_sha256"])}</dd><dt>Evidence identifier</dt><dd class="mono">{_esc(c["evidence_id"])}</dd></dl></div></li>' for c in refs)+'</ul></details>'
            content+='</section>'
        elif not error:content+=notice('Verification checks an existing saved claim. It does not browse the web or acquire new evidence.','A decision you can inspect')
        return _page('Verify a fact',content,active='verify',description='Test a proposition against the exact company and its saved evidence.',status_code=400 if error else 200)

    @app.get('/changes',response_class=HTMLResponse)
    def changes(org: str=''):
        chosen=([profiles[org]] if org in profiles else []) if org else list(profiles.values())
        events=sorted([(profile.organisation_number,event) for profile in chosen for event in profile.changes],key=lambda pair:(pair[0],str(pair[1].get('observed_at','')),str(pair[1].get('event_id',''))))
        content='<form class="panel" method="get" action="/changes" aria-label="Filter change history"><div class="search-row">'+_input('org','Company organisation number (optional)',org,placeholder='Choose a company, or leave empty for all',limit=9,list_='saved-companies')+'<button type="submit" data-pending="Loading saved history…">Show history</button></div>'+_company_options(profiles)+'</form>'+notice('Observation time is when a change was detected. An effective date is shown only when established by evidence; it may be earlier or remain unknown.')
        if org and org not in profiles:content+=notice('This organisation number is not in the loaded research. No other company’s history is substituted.','Company not loaded')
        if not events:content+=empty('No material change events recorded','No supported material changes are stored for this selection. An unchanged refresh is valid, and an empty history does not imply that the company never changes.')
        else:
            entries=[]
            for company_id,event in events:
                refs=[]
                for version in ['previous_evidence','current_evidence']:
                    for item in event.get(version) or []:
                        refs.append(f'<li><strong>{"Before" if version.startswith("previous") else "After"}</strong> · <a href="{evidence_url(company_id,item["evidence_id"])}">View evidence</a><p class="muted small">Observed {date_text(item.get("retrieved_at"))}</p><details class="record-details"><summary>Source reference</summary><p>{_link(str(item.get("source_url") or ""))}</p><p class="mono">{_esc(item.get("evidence_id"))}</p><p class="mono">SHA-256 {_esc(item.get("content_sha256"))}</p></details></li>')
                title=label(event.get('field') or 'Change')
                entries.append(f'<li class="event"><div class="event-heading"><div><p class="eyebrow">{_esc(label(event.get("type") or "Change"))}</p><h2 style="margin-top:7px">{_esc(title)}</h2></div><a href="/companies/{company_id}">{_esc(name(profiles[company_id]))}</a></div><div class="change-values"><div><p class="eyebrow">Before</p>{display(event.get("old_value"))}</div><div><p class="eyebrow">After</p>{display(event.get("new_value"))}</div></div><div class="event-dates"><span>Observed {date_text(event.get("observed_at"))}</span><span>Effective: {_esc(event.get("effective_at") or "effective date not established")}</span></div><details class="disclosure"><summary>Change evidence · {"complete provenance" if event.get("provenance_complete") else "incomplete provenance"}</summary><ul class="source-list">'+''.join(refs)+'</ul><p class="mono">Event '+_esc(event.get('event_id'))+'</p></details></li>')
            content+='<ol class="timeline">'+''.join(entries)+'</ol>'
        return _page('Changes and history',content,active='changes',description='Review supported before-and-after changes without losing their earlier evidence.')

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
