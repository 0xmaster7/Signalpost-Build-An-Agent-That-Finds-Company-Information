"""Presentation-only components for the saved-research workspace.

No acquisition, claim promotion, query decisions or evaluator serialization lives
here. Record grouping requires a shared canonical subject or source-record path.
"""
from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from typing import Any
from urllib.parse import quote, urlsplit

CSS = """
:root{--canvas:#f5f6f8;--surface:#fff;--ink:#172b3a;--muted:#596b78;--line:#dce3e8;--soft:#edf2f5;--accent:#176457;--accent-dark:#104c42;--accent-soft:#eaf4ef;--warning:#805817;--warning-soft:#fff6e6;--error:#943b39;--error-soft:#fcf0ee;--radius:12px;--small-radius:7px;--space:24px;font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:var(--canvas);font-size:15px;line-height:1.55;font-synthesis:none}

*{box-sizing:border-box}
body{margin:0}
a{color:var(--accent);text-underline-offset:3px}
a:hover{color:var(--accent-dark)}
button,input,select,textarea{font:inherit}
button,a,input,select,summary{touch-action:manipulation}
:focus-visible{outline:3px solid #237dba;outline-offset:3px}
h1,h2,h3,p{margin:0}
h1{font-size:clamp(1.65rem,3vw,2.15rem);line-height:1.2;letter-spacing:-.035em;font-weight:680}
h2{font-size:1.17rem;letter-spacing:-.02em;line-height:1.35}
h3{font-size:1rem;line-height:1.4}
p+p{margin-top:.6rem}
small,.small{font-size:.83rem}
.muted,.helper{color:var(--muted)}
.eyebrow{font-size:.72rem;font-weight:750;letter-spacing:.11em;text-transform:uppercase;color:var(--muted)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0}
 .mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.83rem;overflow-wrap:anywhere}
.skip{position:absolute;left:16px;top:-80px;background:var(--surface);padding:12px;z-index:10}
.skip:focus{top:10px}
.topbar{background:var(--surface);border-bottom:1px solid var(--line)}
.shell{max-width:1224px;margin:0 auto;padding:0 36px}
.topbar-inner{min-height:76px;display:flex;align-items:center;justify-content:space-between;gap:24px}
.brand{display:inline-flex;align-items:center;gap:11px;color:var(--ink);font-size:1.2rem;font-weight:750;letter-spacing:-.035em;text-decoration:none}
.brand-mark{width:31px;height:31px;border-radius:8px;background:var(--accent);display:grid;place-items:center;color:white}
.brand-mark svg{width:21px;height:21px}
.nav{display:flex;gap:5px;align-items:center}
.nav a{min-height:44px;padding:11px 16px;border-radius:7px;text-decoration:none;color:var(--muted);font-weight:600;font-size:.9rem}
.nav a:hover{background:var(--soft);color:var(--ink)}
.nav a[aria-current=page]{background:var(--accent-soft);color:var(--accent)}
.workspace-tag{font-size:.75rem;color:var(--muted);border:1px solid var(--line);padding:5px 9px;border-radius:5px}
.workspace-bar{display:flex;align-items:center;gap:8px;padding-top:20px;font-size:.76rem;color:var(--muted)}
.workspace-bar:before{content:"";width:6px;height:6px;border-radius:50%;background:var(--accent)}
main{min-width:0;padding-top:27px!important;padding-bottom:54px!important;overflow-wrap:anywhere}
.page-heading{display:flex;gap:20px;justify-content:space-between;align-items:flex-start;margin-bottom:26px}
.page-heading .description{margin-top:9px;max-width:720px;color:var(--muted)}
.page-heading .eyebrow{margin-bottom:8px}
.page-heading .actions{flex-shrink:0}
.panel,.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);min-width:0}
.panel{padding:24px;margin-bottom:24px}
.panel-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:20px}
.panel-heading p{font-size:.88rem;color:var(--muted);margin-top:5px}
.stack>*+*{margin-top:16px}
.row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.between{justify-content:space-between}
.button,button{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;border:1px solid transparent;border-radius:var(--small-radius);padding:10px 17px;background:var(--accent);color:white;font-weight:650;font-size:.9rem;cursor:pointer;text-decoration:none;line-height:1.4}
.button:hover,button:hover{background:var(--accent-dark);color:white}
.button.secondary{color:var(--ink);background:var(--surface);border-color:var(--line)}
.button.secondary:hover{background:var(--soft)}
button:disabled{opacity:.65;cursor:wait}
.field{display:flex;flex-direction:column;gap:7px;min-width:0}
.field>span,.field>label{font-size:.82rem;font-weight:650}
.field .helper{font-size:.77rem;font-weight:400}
input,select{width:100%;min-width:0;min-height:44px;border:1px solid #b9c6ce;background:white;color:var(--ink);border-radius:var(--small-radius);padding:10px 11px}
input::placeholder{color:#76848f}
input:hover,select:hover{border-color:#8195a2}
input:focus,select:focus{border-color:var(--accent)}
.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
.form-grid.three{grid-template-columns:repeat(3,minmax(0,1fr))}
.dimensions{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;padding-top:17px}
.search-panel{padding:24px}
.search-row{display:flex;gap:12px;align-items:flex-end}
.search-row .field{flex:1}
.search-row input{min-height:49px;font-size:1rem}
.search-row button{min-height:49px;padding-left:24px;padding-right:24px}
.search-hint{font-size:.82rem;color:var(--muted);margin:10px 0 0}
.disclosure{border-top:1px solid var(--line);margin-top:20px;padding-top:16px}
.disclosure summary,details.record-details>summary{cursor:pointer;font-weight:600;font-size:.86rem;min-height:44px;align-content:center;color:var(--accent)}
details summary:hover{text-decoration:underline;text-underline-offset:3px}
.disclosure[open]>summary{margin-bottom:18px}
.filter-rule{border:1px solid var(--line);border-radius:8px;padding:16px;margin:16px 0 0;min-width:0}
.filter-rule legend{font-size:.8rem;font-weight:650;padding:0 7px;color:var(--muted)}
.filter-rule .dimensions{margin-top:12px;border-top:1px solid var(--line)}
.results-heading{display:flex;justify-content:space-between;gap:12px;align-items:center;margin:28px 0 16px}
.results-heading p{font-size:.84rem;color:var(--muted)}
.result-list{display:grid;gap:12px}
.result-card{display:flex;gap:20px;padding:22px;align-items:center;justify-content:space-between}
.company-monogram{height:44px;width:44px;flex:0 0 44px;border:1px solid var(--line);border-radius:10px;background:var(--soft);display:grid;place-items:center;font-size:.85rem;font-weight:750;color:#42616f}
.company-main{display:flex;align-items:flex-start;gap:15px;min-width:0}
.company-main h2{font-size:1rem}
.company-main h2 a{text-decoration:none;color:var(--ink)}
.company-main h2 a:hover{text-decoration:underline}
.company-meta{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:6px;font-size:.82rem;color:var(--muted)}
.result-tail{flex-shrink:0}
.result-tail a{font-size:.84rem;font-weight:650}
.match-proof{font-size:.79rem;color:var(--accent);margin-top:10px}
.state{display:inline-flex;align-items:center;gap:6px;padding:3px 8px;font-size:.73rem;line-height:1.5;font-weight:650;background:var(--soft);border:1px solid #d9e2e6;border-radius:5px;max-width:100%;white-space:normal}
.state[data-state=available],.state[data-state=supported],.state[data-state=comparable]{color:#165d48;background:var(--accent-soft);border-color:#cde4d8}
.state[data-state=ambiguous],.state[data-state=insufficient_evidence],.state[data-state=not_comparable]{color:var(--warning);background:var(--warning-soft);border-color:#eadbbb}
.state[data-state=contradicted],.state[data-state=failed],.state[data-state=blocked]{color:var(--error);background:var(--error-soft);border-color:#edcfca}
.state[data-state=not_attempted]{color:var(--muted);background:#f4f6f7}
.notice{border:1px solid var(--line);border-left:3px solid #96aeb9;background:#f6f9fb;padding:15px 18px;border-radius:8px;font-size:.86rem;margin:16px 0}
.notice.error{border-color:#e8c7c1;border-left-color:var(--error);background:var(--error-soft);color:#772d2b}
.notice strong{display:block;margin-bottom:3px}
.empty{border:1px dashed #cdd8df;border-radius:10px;padding:30px;text-align:center;color:var(--muted);background:#fafcfd}
.empty h3{color:var(--ink);margin-bottom:7px}
.empty p{max-width:560px;margin:auto;font-size:.88rem}
.empty .button{margin-top:18px}
.breadcrumb{margin-bottom:17px;font-size:.8rem}
.profile-heading{margin-bottom:20px}
.profile-heading h1{max-width:800px}
.profile-subline{display:flex;gap:9px 18px;flex-wrap:wrap;color:var(--muted);margin-top:12px;font-size:.87rem}
.overview{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;margin-bottom:23px}
.overview-item{background:var(--surface);padding:19px 22px;min-width:0}
.overview-item .value{font-weight:650;font-size:1rem;margin-top:6px}
.overview-item .evidence-action{display:block;margin-top:6px}
.evidence-action{font-size:.76rem;font-weight:600;text-decoration:none}
.evidence-action:hover{text-decoration:underline}
.section-nav{display:flex;gap:7px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding:0 0 16px;margin-bottom:24px}
.section-nav a{font-size:.8rem;padding:7px 10px;text-decoration:none;color:var(--muted);border-radius:6px;background:white;border:1px solid var(--line)}
.section-nav a:hover{background:var(--accent-soft);color:var(--accent)}
section[id]{scroll-margin-top:24px}
.profile-layout{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:24px;align-items:start}
.profile-main{min-width:0}
.profile-aside{position:sticky;top:20px}
.profile-aside .panel{padding:20px}
.status-list{list-style:none;padding:0;margin:16px 0 0}
.status-list li{display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:.8rem;padding:11px 0;border-top:1px solid var(--line)}
.status-list .state{font-size:.67rem}
.facts{display:grid;grid-template-columns:minmax(120px,.7fr) minmax(0,1.4fr);gap:0;margin:0}
.facts>dt{font-size:.81rem;color:var(--muted);padding:12px 12px 12px 0;border-bottom:1px solid var(--line)}
.facts>dd{min-width:0;margin:0;padding:12px 0;border-bottom:1px solid var(--line);font-size:.88rem}
.facts>dd .evidence-action{margin-top:4px;display:inline-block}
.facts>dt:last-of-type,.facts>dd:last-of-type{border-bottom:none}
.value-list{margin:0;padding-left:18px}
.value-list li+li{margin-top:4px}
.dimensions-note{font-size:.74rem;color:var(--muted);margin-top:5px}
.record-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.record{border:1px solid var(--line);border-radius:9px;padding:17px;min-width:0}
.record>h3{margin-bottom:5px}
.record-meta{font-size:.79rem;color:var(--muted);margin:8px 0}
.record-details{margin-top:13px;border-top:1px solid var(--line);padding-top:9px}
.record-details .facts{grid-template-columns:minmax(100px,.8fr) minmax(0,1.2fr)}
.role-group+.role-group{margin-top:25px;border-top:1px solid var(--line);padding-top:22px}
.role-group-title{display:flex;align-items:center;justify-content:space-between;gap:15px;margin-bottom:12px}
.role-list{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.role-person{border:1px solid var(--line);border-radius:9px;padding:16px;min-width:0}
.role-person .muted{font-size:.8rem;margin-top:4px}
.table-wrap{overflow:auto;max-width:100%;border:1px solid var(--line);border-radius:10px;overscroll-behavior-x:contain}
.table-wrap:focus-visible{outline-offset:4px}
.scroll-hint{color:var(--muted);font-size:.77rem;margin:0 0 10px}
table{width:100%;border-collapse:separate;border-spacing:0;background:white;font-size:.85rem}
th,td{text-align:left;vertical-align:top;padding:18px;border-bottom:1px solid var(--line)}
th{font-size:.81rem;background:#f8fafb;font-weight:650}
thead th{position:sticky;top:0;z-index:1}
tbody tr:last-child>*{border-bottom:none}
.compare-table{min-width:660px;table-layout:fixed}
.compare-table .row-label{width:180px}
.compare-table th small{display:block;margin-top:7px;font-weight:400;color:var(--muted)}
.compare-table td .cell-value{font-weight:600;margin-bottom:7px}
.compare-table td .dimensions-note{margin:7px 0}
.compare-table td details{margin-top:10px}
.compare-table td summary{color:var(--accent);font-size:.76rem;cursor:pointer}
.result-banner{padding:24px;border:1px solid var(--line);border-left:4px solid #80929d;border-radius:var(--radius);background:var(--surface);margin-top:24px}
.result-banner[data-state=supported]{border-left-color:var(--accent)}
.result-banner[data-state=contradicted]{border-left-color:var(--error)}
.result-banner h2{margin:10px 0}
.result-banner p{color:var(--muted)}
.canonical-value{margin-top:18px;padding:15px;background:var(--soft);border-radius:8px}
.canonical-value .eyebrow{margin-bottom:7px}
.source-list{list-style:none;padding:0;margin:0}
.source-list li{padding:14px 0;border-bottom:1px solid var(--line)}
.source-list li:last-child{border-bottom:0}
.source-list .mono{font-size:.74rem}
.source-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}
.source-heading a{font-size:.83rem;font-weight:600}
.timeline{list-style:none;padding:0;margin:0}
.event{margin-bottom:18px;padding:22px;border:1px solid var(--line);border-radius:10px;background:white}
.event-heading{display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:17px}
.change-values{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.change-values>div{padding:16px;background:#fafbfc;min-width:0}
.change-values>div+div{border-left:1px solid var(--line);background:#f1f7f4}
.change-values .eyebrow{margin-bottom:8px}
.event-dates{display:flex;gap:20px;flex-wrap:wrap;color:var(--muted);font-size:.78rem;margin-top:15px}
.technical{padding:14px;background:#f6f8fa;border:1px solid var(--line);border-radius:8px;overflow-wrap:anywhere}
.technical dl{margin:0}
.technical dt{font-size:.74rem;color:var(--muted);margin-top:10px}
.technical dd{margin:3px 0 0;font-size:.8rem}
.technical dt:first-child{margin-top:0}
.evidence-overview{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-bottom:23px}
.evidence-overview .card{padding:17px}
.evidence-overview .value{margin-top:6px;font-weight:650;font-size:.88rem}
.footer{border-top:1px solid var(--line);padding-top:18px;margin-top:34px;color:var(--muted);font-size:.75rem}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:1000px){.profile-layout{grid-template-columns:minmax(0,1fr)}
.profile-aside{position:static}
.status-list{display:grid;grid-template-columns:1fr 1fr;gap:0 24px}
.record-grid,.role-list{grid-template-columns:repeat(2,minmax(0,1fr))}
.dimensions{grid-template-columns:repeat(2,minmax(0,1fr))}
.workspace-tag{display:none}
}
.evidence-action{font-size:.8rem}
@media(max-width:650px){.evidence-action{display:inline-flex!important;align-items:center;min-height:44px;padding:5px 0}.section-nav a{min-height:44px;display:inline-flex;align-items:center}.result-tail a{min-height:44px;display:inline-flex;align-items:center}.compare-table summary{min-height:44px;align-content:center}.shell{padding-left:18px;padding-right:18px}
.topbar-inner{display:block;padding-top:17px;padding-bottom:12px;min-height:0}
.brand{margin-bottom:12px}
.nav{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}
.nav a{text-align:center;padding:10px 6px;font-size:.82rem}
.workspace-bar{padding-top:16px}
main{padding-top:22px!important}
.page-heading{display:block;margin-bottom:20px}
.page-heading .actions{margin-top:16px}
.panel{padding:18px;margin-bottom:18px}
.search-row{display:block}
.search-row button{margin-top:12px;width:100%}
.search-panel{padding:18px}
.form-grid,.form-grid.three,.dimensions{grid-template-columns:minmax(0,1fr)}
.form-grid{gap:15px}
.result-card{padding:17px;align-items:flex-start;gap:10px}
.company-monogram{display:none}
.company-main{gap:0}
.result-tail a{font-size:.77rem}
.company-meta{gap:5px 10px}
.result-tail .button{padding:9px;min-height:40px}
.results-heading{align-items:flex-start;flex-direction:column;gap:5px}
.overview{grid-template-columns:minmax(0,1fr)}
.overview-item{padding:15px 18px}
.profile-layout{gap:0}
.profile-subline{font-size:.8rem}
.section-nav{gap:6px}
.section-nav a{font-size:.75rem;padding:7px 8px}
.record-grid,.role-list{grid-template-columns:minmax(0,1fr)}
.facts{grid-template-columns:minmax(0,1fr)}
.facts>dt{padding:12px 0 3px;border-bottom:0;font-weight:650}
.facts>dd{padding:0 0 12px}
.record-details .facts{grid-template-columns:minmax(0,1fr)}
.status-list{display:block}
.change-values{grid-template-columns:minmax(0,1fr)}
.change-values>div+div{border-left:0;border-top:1px solid var(--line)}
.event{padding:17px}
.evidence-overview{grid-template-columns:minmax(0,1fr);gap:10px}
.evidence-overview .card{padding:14px}
.result-banner{padding:19px}
.empty{padding:24px 16px}
.panel-heading{gap:10px}
.panel-heading .state{flex-shrink:0;max-width:45%}
.compare-table{min-width:650px}
.workspace-bar{font-size:.71rem}
.footer{font-size:.71rem}
}

@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important;scroll-behavior:auto!important}
}

"""

SCRIPT = """document.addEventListener('submit',function(event){var form=event.target;if(!form.checkValidity())return;var button=form.querySelector('button[type=submit]');if(button){button.dataset.originalText=button.textContent;button.textContent=button.dataset.pending||'Checking saved records…';button.disabled=true;form.setAttribute('aria-busy','true');}});window.addEventListener('pageshow',function(){document.querySelectorAll('form[aria-busy]').forEach(function(form){form.removeAttribute('aria-busy');form.querySelectorAll('button[data-original-text]').forEach(function(button){button.textContent=button.dataset.originalText;button.disabled=false;});});});"""

LABELS = {
    "name":"Legal company name","legal_name":"Legal company name","organisation_number":"Organisation number",
    "public_brand":"Public brand","legal_form":"Legal form","legal_form_description":"Legal form description",
    "business_address":"Registered business address","postal_address":"Postal address","municipality":"Municipality",
    "municipality_number":"Municipality number","employees":"Employees","latest_submitted_accounts":"Latest submitted accounts",
    "revenue":"Revenue","operating_result":"Operating result","profit_before_tax":"Profit before tax",
    "annual_result":"Annual result","total_assets":"Total assets","equity":"Equity","total_debt":"Total debt",
    "verified_website_url":"Verified website","website_url":"Website","website":"Verified website","website_description":"Website description",
    "industry":"Industry code","role":"Role holder","job":"Job title","brand":"Public brand","org":"Organisation number",
    "role.name":"Name","role.holder_kind":"Holder type","role.holder_organisation_number":"Holder organisation number",
    "role.role_code":"Role code","role.role_description":"Registered role","role.role_group":"Role group",
    "role.role_group_code":"Role group code","role.inactive":"Inactive role","role.last_changed":"Group last changed",
    "role.from_date":"From date","role.to_date":"To date","workplace.navn":"Workplace name",
    "workplace.organisasjonsnummer":"Workplace organisation number","workplace.overordnetEnhet":"Parent organisation number",
    "workplace.beliggenhetsadresse":"Location","workplace.postadresse":"Postal address","workplace.antallAnsatte":"Employees",
    "workplace.naeringskode1":"Industry","financial_record.record_id":"Record identifier",
    "financial_record.source_version_or_filing_id":"Filing or source version","financial_record.account_type":"Account type",
    "financial_record.scope":"Accounting scope","financial_record.period_start":"Period start","financial_record.period_end":"Period end",
    "financial_record.currency":"Currency","financial_record.filing_timestamp":"Filing date","financial_record.filing_id":"Filing identifier",
    "status.konkurs":"Bankrupt","status.underAvvikling":"Under liquidation",
    "status.underTvangsavviklingEllerTvangsopplosning":"Compulsory liquidation or dissolution",
    "status.registrertIForetaksregisteret":"Registered in the Register of Business Enterprises",
    "status.registrertIMvaregisteret":"Registered for VAT","status_dates.stiftelsesdato":"Founded",
    "status_dates.registreringsdatoEnhetsregisteret":"Registered in the Central Coordinating Register",
    "historical_name":"Historical name","job_title":"Job title","job_location":"Job location",
    "job_url":"Job posting","job_date_posted":"Date posted","activity_title":"Activity title",
    "activity_date":"Publication date","activity_url":"Publication","website_heading":"Website heading",
    "kode":"Code","beskrivelse":"Description","adresse":"Street address","postnummer":"Postal code","poststed":"Postal town",
    "kommune":"Municipality","kommunenummer":"Municipality number","land":"Country","landkode":"Country code",
    "legal_entity":"Legal entity","group":"Group","person_role":"Person role","organisation_role":"Organisation role",
    "workplace":"Workplace","person":"Person","organisation":"Organisation",
}
STATE_LABELS = {"available":"Available","not_available":"Not available","blocked":"Blocked","not_applicable":"Not applicable",
    "ambiguous":"Ambiguous","failed":"Failed","not_attempted":"Not attempted","unknown":"Unknown","unavailable":"Unavailable",
    "supported":"Supported","contradicted":"Contradicted","insufficient_evidence":"Insufficient evidence",
    "comparable":"Comparable","not_comparable":"Not comparable"}
SECTION_LABELS = {"identity_brand":"Identity","accounts_history":"Financial records","leadership_workplaces":"Roles & workplaces",
    "website_owned_profiles":"Websites & profiles","hiring_activity":"Hiring & activity","claims_evidence_states":"Claims & evidence","refresh_changes":"Refresh & changes"}

def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""),quote=True)

def label(field: str) -> str:
    if field.startswith("industry_codes."):return "Industry classification"
    return LABELS.get(field,field.replace("_"," ").replace("."," · ").strip().capitalize())

def safe_url(value: str) -> str | None:
    try:parsed=urlsplit(value)
    except ValueError:return None
    if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password or any(ord(ch)<32 for ch in value):return None
    return value

def source_name(value: str) -> str:
    try:return urlsplit(value).hostname or "Source identifier"
    except ValueError:return "Source identifier"

def link(value: str, text: str | None = None) -> str:
    if not safe_url(value):return esc(text or value)
    return f'<a href="{esc(value)}" target="_blank" rel="noopener noreferrer">{esc(text or value)}</a>'

def badge(state: str | None) -> str:
    state=state or "unknown"
    return f'<span class="state" data-state="{esc(state)}">{esc(STATE_LABELS.get(state,label(state)))}</span>'

def display(value: Any) -> str:
    if value is None:return '<span class="muted">Not recorded</span>'
    if isinstance(value,bool):return "Yes" if value else "No"
    if isinstance(value,dict):
        if "adresse" in value or "poststed" in value:
            lines=value.get("adresse") or []
            if isinstance(lines,str):lines=[lines]
            postal=" ".join(str(value[k]) for k in ["postnummer","poststed"] if value.get(k))
            parts=[*lines,*([postal] if postal else []),*([str(value["kommune"])] if value.get("kommune") and value.get("kommune")!=value.get("poststed") else []),*([str(value["land"])] if value.get("land") else [])]
            return "<br>".join(esc(x) for x in parts) or esc(json.dumps(value,ensure_ascii=False,sort_keys=True))
        return '<ul class="value-list">'+"".join(f'<li><span class="muted">{esc(label(str(k)))}:</span> {display(v)}</li>' for k,v in value.items())+'</ul>'
    if isinstance(value,list):return '<ul class="value-list">'+"".join('<li>'+display(x)+'</li>' for x in value)+'</ul>'
    return esc(value)

def date_text(value: Any, *, full: bool=False) -> str:
    if not value:return "Not recorded"
    text=value.isoformat() if hasattr(value,"isoformat") else str(value)
    return text if full else text[:10]

def name(profile: Any) -> str:
    claim=next((c for c in available(profile) if c.field in {"name","legal_name"} and isinstance(c.value,str)),None)
    return str(claim.value) if claim else profile.organisation_number

def available(profile: Any, *, section: str | None=None, family: str | None=None) -> list[Any]:
    return [c for c in profile.claims if c.organisation_number==profile.organisation_number and c.state.value=="available" and (section is None or c.section==section) and (family is None or c.field_family==family)]

def field_claim(profile: Any, field: str) -> Any | None:
    return next((c for c in available(profile) if c.field==field),None)

def evidence_url(org: str,eid: str) -> str:
    return f'/evidence/{quote(org,safe="")}/{quote(eid,safe="")}'

def citation(profile: Any, claim: Any) -> str:
    items=profile.claim_citations(claim)
    if not items:return '<span class="muted">Evidence unavailable</span>'
    links=[f'<a class="evidence-action" href="{evidence_url(profile.organisation_number,item["evidence_id"])}">View evidence{(" "+str(i+1)) if len(items)>1 else ""}<span class="sr-only"> for {esc(label(claim.field))}</span></a>' for i,item in enumerate(items)]
    return ' · '.join(links)

def dimensions(claim: Any) -> str:
    bits=[]
    if claim.period_start or claim.period_end:bits.append(f'{date_text(claim.period_start)} – {date_text(claim.period_end)}')
    if claim.currency:bits.append(str(claim.currency))
    if claim.unit:bits.append('Unit: '+str(claim.unit))
    if claim.scope:bits.append(LABELS.get(claim.scope,claim.scope))
    if claim.as_of:bits.append('As of '+date_text(claim.as_of))
    return esc(' · '.join(bits))

def facts(profile: Any, claims: list[Any], *, show_dimensions: bool=False) -> str:
    return '<dl class="facts">'+''.join(f'<dt>{esc(label(c.field))}</dt><dd data-claim-id="{esc(c.claim_id)}">{display(LABELS.get(str(c.value),c.value) if c.field in {"financial_record.scope","role.holder_kind"} else c.value)}'+(f'<div class="dimensions-note">{dimensions(c)}</div>' if show_dimensions and dimensions(c) else '')+f'<div>{citation(profile,c)}</div></dd>' for c in claims)+'</dl>'

def empty(title: str, message: str) -> str:
    return f'<div class="empty"><h3>{esc(title)}</h3><p>{esc(message)}</p></div>'

def section_state(profile: Any, key: str) -> str:
    meta=profile.sections.get(key) or {}
    return str(meta.get("state") or meta.get("attempt_outcome") or "unknown")

def panel(key: str,title: str,description: str,content: str,state: str | None=None) -> str:
    return f'<section class="panel" id="{esc(key)}"><div class="panel-heading"><div><h2>{esc(title)}</h2><p>{esc(description)}</p></div>{badge(state) if state else ""}</div>{content}</section>'

def notice(message: str, title: str="", *, error: bool=False) -> str:
    return f'<div class="notice{" error" if error else ""}" role="{"alert" if error else "note"}">'+(f'<strong>{esc(title)}</strong>' if title else '')+esc(message)+'</div>'

def source_key(profile: Any,claim: Any,kind: str) -> tuple[str,...] | None:
    """One exact resource + content hash + source record, never list order."""
    keys=set()
    for ref in profile.claim_citations(claim):
        pointer=ref.get("json_pointer") or ""
        if kind=="role":match=re.match(r"^(/rollegrupper/\d+/roller/\d+)(?:/|$)",pointer)
        elif kind=="role_group":match=re.match(r"^(/rollegrupper/\d+)(?:/|$)",pointer)
        else:match=re.match(r"^((?:/_embedded/regnskap|/regnskap)?/\d+)(?:/|$)",pointer)
        if match:keys.add((ref["source_url"],ref["content_sha256"],match[1]))
        else:return None
    return next(iter(keys)) if len(keys)==1 else None

def record_groups(profile: Any,kind: str) -> tuple[list[tuple[tuple[str,...],list[Any]]],list[Any]]:
    groups=defaultdict(list);unbound=[]
    families={"financial":{"financial_record_metadata","financial"},"role":{"role"},"workplace":{"workplace"}}[kind]
    for claim in available(profile):
        if claim.field_family not in families:continue
        if kind=="workplace":
            key=(str(claim.subject_id),*sorted(claim.source_snapshot_ids)) if claim.subject_id and claim.subject_id!=profile.organisation_number else None
        else:key=source_key(profile,claim,kind)
        if key:groups[key].append(claim)
        else:unbound.append(claim)
    return sorted(groups.items()),unbound

def record_value(claims: list[Any],field: str) -> Any | None:
    values=[c.value for c in claims if c.field==field]
    unique={json.dumps(v,sort_keys=True,ensure_ascii=False,default=str) for v in values}
    return values[0] if len(unique)==1 else None

def record_evidence(profile: Any,claims: list[Any],text: str="Facts and evidence") -> str:
    return f'<details class="record-details"><summary>{esc(text)} <span class="muted">({len(claims)})</span></summary>{facts(profile,claims,show_dimensions=True)}</details>'

def _scope_label(scope: Any) -> str:
    return esc(LABELS.get(str(scope),scope))

def record_cards(profile: Any,kind: str) -> str:
    groups,unbound=record_groups(profile,kind);cards=[]
    if kind=="financial":
        groups.sort(key=lambda pair:(str(record_value(pair[1],"financial_record.period_end") or date_text(pair[1][0].period_end)),str(record_value(pair[1],"financial_record.scope") or "")),reverse=True)
    for key,claims in groups:
        if kind=="financial":
            end=record_value(claims,"financial_record.period_end") or date_text(claims[0].period_end)
            scope=record_value(claims,"financial_record.scope") or claims[0].scope or "unknown"
            currency=record_value(claims,"financial_record.currency")
            filing=record_value(claims,"financial_record.record_id")
            title=f'Period ending {date_text(end)}'
            context=f'{_scope_label(scope)}'+(f' · {esc(currency)}' if currency else '')
            body=f'<p class="record-meta">{context}</p>'+(f'<p class="small">Record {esc(filing)}</p>' if filing is not None else '')
            period_claim=next((c for c in claims if c.field=="financial_record.period_end"),claims[0])
            body+=f'<p style="margin-top:8px">{citation(profile,period_claim)}</p>'
        else:
            title=str(record_value(claims,"workplace.navn") or "Registered workplace")
            number=record_value(claims,"workplace.organisasjonsnummer")
            address=record_value(claims,"workplace.beliggenhetsadresse")
            employees=record_value(claims,"workplace.antallAnsatte")
            body=(f'<p class="record-meta">Org. {esc(number)}</p>' if number else '')+(f'<p class="small">{display(address)}</p>' if address else '')+(f'<p class="record-meta">Employees: {display(employees)}</p>' if employees is not None else '')
        cards.append(f'<article class="record"><h3>{esc(title)}</h3>{body}{record_evidence(profile,claims)}</article>')
    result='<div class="record-grid">'+''.join(cards)+'</div>' if cards else ''
    if unbound:result+=f'<details class="disclosure"><summary>Other supported {"financial" if kind=="financial" else "workplace"} facts</summary><p class="helper small">These facts have evidence but cannot be joined into a single source record safely.</p>{facts(profile,unbound,show_dimensions=True)}</details>'
    return result

def roles(profile: Any) -> str:
    groups,unbound=record_groups(profile,"role");by_group=defaultdict(list);context=defaultdict(list);other=[]
    for key,claims in groups:by_group[(key[0],key[1],key[2].split('/roller/')[0])].append(claims)
    for claim in unbound:
        key=source_key(profile,claim,"role_group")
        if key and key in by_group:context[key].append(claim)
        else:other.append(claim)
    result=[]
    for key,records in sorted(by_group.items()):
        meta=context[key];heading=record_value(meta,"role.role_group") or "Registered roles"
        rows=[]
        for claims in records:
            person=record_value(claims,"role.name") or "Holder name not recorded"
            role=record_value(claims,"role.role_description")
            inactive=record_value(claims,"role.inactive")
            subtitle=esc(role) if role else "Role details in source evidence"
            rows.append(f'<li class="role-person"><h3>{esc(person)}</h3><p class="muted">{subtitle}</p>'+('<p class="small">Recorded as inactive</p>' if inactive is True else '')+record_evidence(profile,claims)+'</li>')
        result.append(f'<div class="role-group"><div class="role-group-title"><h3>{esc(heading)}</h3><span class="muted small">Saved roles: {len(records)}</span></div><ul class="role-list">'+''.join(rows)+'</ul>'+(record_evidence(profile,meta,"Role group context and evidence") if meta else '')+'</div>')
    if other:result.append('<details class="disclosure"><summary>Other supported role facts</summary><p class="helper small">No person-to-role relationship is inferred when a shared source record is missing.</p>'+facts(profile,other)+'</details>')
    return ''.join(result)
