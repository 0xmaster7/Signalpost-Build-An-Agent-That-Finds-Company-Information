"""BRREG public API adapters. Every response is fetched by NetworkGateway."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

from .inputs import normalize_org_number
from .models import Claim, Evidence, PublicState, RunError, SourceSnapshot, SUPPORTED_FINANCIAL_UNITS, financial_dimensions_compatible
from .identifiers import stable_claim_id
from .network import NetworkGateway

BASE = "https://data.brreg.no/enhetsregisteret/api"
ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap"
UA = "Signalpost/0.2 (public BRREG foundation; contact pending)"
RIGHTS = "NLOD-2.0"


def _get(data: Any, *path: str) -> Any:
    for part in path:
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


@dataclass
class BrregResult:
    claims: list[Claim]
    evidence: list[Evidence]
    snapshots: list[SourceSnapshot]
    errors: list[RunError]
    section_states: dict[str, PublicState]
    terminal_state: PublicState
    observations: dict[str, Any]
    account_records: list[dict[str, Any]] = field(default_factory=list)
    account_source: dict[str, Any] = field(default_factory=dict)


def normalize_entity(body: dict[str, Any]) -> dict[str, Any]:
    """Keep public legal identity fields and exclude personal identifiers."""
    legal_form = _get(body, "organisasjonsform", "kode")
    address = body.get("forretningsadresse") or {}
    if not isinstance(address, dict):
        address = {}
    postal = body.get("postadresse") or {}
    def address_value(value: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(value, dict) or not value:
            return None
        return {key: value.get(key) for key in ("adresse", "postnummer", "poststed", "kommunenummer", "kommune", "land", "landkode") if value.get(key) is not None}
    hist = body.get("historiskeNavn") or []
    history = [{"name": h.get("navn"), "from": h.get("fraDato"), "to": h.get("tilDato")} for h in hist if isinstance(h, dict)]
    return {
        "organisation_number": body.get("organisasjonsnummer"), "name": body.get("navn"),
        "legal_form": legal_form, "legal_form_description": _get(body, "organisasjonsform", "beskrivelse"),
        "status": {key: body.get(key) for key in ("konkurs", "underAvvikling", "underTvangsavviklingEllerTvangsopplosning", "registrertIMvaregisteret", "registrertIForetaksregisteret") if body.get(key) is not None},
        "status_dates": {key: body.get(key) for key in ("konkursdato", "avviklingsdato", "tvangsavviklingsdato", "registreringsdatoEnhetsregisteret", "stiftelsesdato") if body.get(key) is not None},
        "historical_names": history,
        # ENK registration addresses can be an owner's home address; keep them out.
        "business_address": None if legal_form == "ENK" else address_value(address),
        "postal_address": None if legal_form == "ENK" else address_value(postal),
        "registered_workplace_address": None if legal_form == "ENK" else address_value(body.get("beliggenhetsadresse") or {}),
        "industry_codes": [body.get(f"naeringskode{i}") for i in range(1, 4) if body.get(f"naeringskode{i}")],
        "municipality_number": body.get("kommunenummer") or address.get("kommunenummer"),
        "municipality": body.get("kommune") or address.get("kommune"),
        "website": body.get("hjemmeside"), "employees": body.get("antallAnsatte"),
        "latest_submitted_accounts": body.get("sisteInnsendteAarsregnskap"),
        "parent_organisation_number": body.get("overordnetEnhet"),
    }


METRICS = {
    "sales_revenue": "resultatregnskapResultat/driftsresultat/driftsinntekter/salgsinntekter",
    "operating_costs": "resultatregnskapResultat/driftsresultat/driftskostnad/sumDriftskostnad",
    "payroll_costs": "resultatregnskapResultat/driftsresultat/driftskostnad/loennskostnad",
    "net_financial_items": "resultatregnskapResultat/finansresultat/nettoFinans",
    "tax_expense": "resultatregnskapResultat/ordinaertResultatSkattekostnad",
    "fixed_assets": "eiendeler/anleggsmidler/sumAnleggsmidler",
    "current_assets": "eiendeler/omloepsmidler/sumOmloepsmidler",
    "receivables": "eiendeler/sumFordringer",
    "cash": "eiendeler/sumBankinnskuddOgKontanter",
    "paid_in_equity": "egenkapitalGjeld/egenkapital/innskuttEgenkapital/sumInnskuttEgenkaptial",
    "retained_earnings": "egenkapitalGjeld/egenkapital/opptjentEgenkapital/sumOpptjentEgenkapital",
    "short_term_debt": "egenkapitalGjeld/gjeldOversikt/kortsiktigGjeld/sumKortsiktigGjeld",
    "long_term_debt": "egenkapitalGjeld/gjeldOversikt/langsiktigGjeld/sumLangsiktigGjeld",
    "financial_income": "resultatregnskapResultat/finansresultat/finansinntekt/sumFinansinntekter",
    "financial_costs": "resultatregnskapResultat/finansresultat/finanskostnad/sumFinanskostnad",
    "total_comprehensive_result": "resultatregnskapResultat/totalresultat",

    "revenue": "resultatregnskapResultat/driftsresultat/driftsinntekter/sumDriftsinntekter",
    "operating_result": "resultatregnskapResultat/driftsresultat/driftsresultat",
    "profit_before_tax": "resultatregnskapResultat/ordinaertResultatFoerSkattekostnad",
    "annual_result": "resultatregnskapResultat/aarsresultat",
    "total_assets": "eiendeler/sumEiendeler",
    "equity": "egenkapitalGjeld/egenkapital/sumEgenkapital",
    "total_debt": "egenkapitalGjeld/gjeldOversikt/sumGjeld",
}

# Active ISO 4217 alpha codes accepted from BRREG account records. A
# three-letter shape alone does not establish a supported currency.
SUPPORTED_CURRENCY_CODES = frozenset("""
AED AFN ALL AMD AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD
CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP
GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW
KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN
NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK
SGD SHP SLE SOS SRD SSP STN SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS
VES VND VUV WST XAF XCD XCG XOF XPF YER ZAR ZMW ZWG
""".split())


def supported_currency(value: Any) -> bool:
    return isinstance(value, str) and value in SUPPORTED_CURRENCY_CODES


def financial_records(body: Any) -> list[dict[str, Any]]:
    """Normalize every returned record; preserve raw source fields and periods."""
    if isinstance(body, dict):
        embedded = body.get("_embedded") if isinstance(body.get("_embedded"), dict) else {}
        records = embedded.get("regnskap") or body.get("regnskap") or []
        if not records and any(k in body for k in ("regnskapsperiode", "id")):
            records = [body]
    elif isinstance(body, list):
        records = body
    else:
        records = []
    result = []
    for source_index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        period = record.get("regnskapsperiode") or {}
        if not isinstance(period, dict):
            period = {}
        account_type = str(record.get("regnskapstype") or "").casefold()
        scope = "group" if account_type in {"konsern", "konsernregnskap"} else "legal_entity" if account_type in {"selskap", "selskapsregnskap"} else "unknown"
        values = {}
        record_unit = record.get("enhet")
        record_unit_present = "enhet" in record
        record_unit_state = _unit_state(record_unit, present=record_unit_present)
        for field, path in METRICS.items():
            val = _get(record, *path.split("/"))
            # Numeric field labels are intentionally exact: an unlabelled or mistyped
            # value is never guessed from a nearby account name.
            if isinstance(val, dict):
                raw = val.get("sum") if isinstance(val.get("sum"), (int, float)) else None
                # Currency is a separate dimension. Never use it as a scale.
                metric_unit_present = "enhet" in val
                metric_unit = val.get("enhet")
                metric_unit_state = _unit_state(metric_unit, present=metric_unit_present)
                if metric_unit_state == "absent":
                    unit = record_unit if record_unit_state == "supported" else None
                    unit_state = record_unit_state
                elif metric_unit_state == "supported":
                    unit = metric_unit
                    unit_state = "supported"
                else:
                    unit = None
                    unit_state = metric_unit_state
                if (metric_unit_state == "supported" and record_unit_state == "supported"
                        and str(metric_unit).strip().upper() != str(record_unit).strip().upper()):
                    unit, unit_state = "__conflict__", "conflict"
                unit_conflict = unit_state == "conflict"
            else:
                raw, unit = val, (record_unit if record_unit_state == "supported" else None)
                unit_state = record_unit_state
                unit_conflict = False
            values[field] = raw if (isinstance(raw, (int, float)) and not isinstance(raw, bool)
                                    and math.isfinite(float(raw))) else None
            if values[field] is not None:
                values[field + "_unit"] = unit
                values[field + "_unit_conflict"] = unit_conflict
                values[field + "_unit_state"] = unit_state
        result.append({
            "record_id": record.get("id"), "filing_id": record.get("innsendingsId"), "record_version": record.get("versjon"),
            "source_version_or_filing_id": record.get("versjon") or record.get("innsendingsId") or record.get("id"),
            "account_type": record.get("regnskapstype"), "scope": scope,
            "_source_index": source_index,
            "_source_prefix": (f"/{source_index}" if isinstance(body, list) else
                               f"/_embedded/regnskap/{source_index}" if isinstance(body.get("_embedded"), dict) else
                               f"/regnskap/{source_index}" if isinstance(body.get("regnskap"), list) else ""),
            "period_start": period.get("fraDato"), "period_end": period.get("tilDato"),
            "filing_timestamp": record.get("innsendingsdato") or record.get("registreringsdato"),
            "currency": record.get("valuta"), "raw_unit": record.get("enhet"), "metrics": values,
            "raw": record,
        })
    # Exact duplicate payloads may be removed. Different versions/corrections remain.
    unique: dict[str, dict[str, Any]] = {}
    for record in result:
        digest = hashlib.sha256(json.dumps(record["raw"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        unique.setdefault(digest, record)
    return list(unique.values())


def _unit_state(value: Any, *, present: bool) -> str:
    """Classify source unit metadata without truthiness-based fallback."""
    if not present:
        return "absent"
    if value is None:
        return "explicit_null"
    if not isinstance(value, str):
        return "malformed"
    normalized = value.strip().upper()
    if not normalized:
        return "malformed"
    return "supported" if normalized in SUPPORTED_FINANCIAL_UNITS else "unsupported"


def financial_record_subject(org: str, record: dict[str, Any]) -> str:
    identity = {key: record.get(key) for key in ("record_id", "filing_id", "record_version",
        "period_start", "period_end", "scope")}
    identity["journalnr"] = record.get("raw", {}).get("journalnr")
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode()).hexdigest()[:20]
    return f"{org}:accounts:{record.get('scope')}:{record.get('period_start')}:{record.get('period_end')}:{digest}"


def role_records(body: Any) -> list[dict[str, Any]]:
    result = []
    for gi, group in enumerate(body.get("rollegrupper", []) if isinstance(body, dict) else []):
        for ri, item in enumerate(group.get("roller", []) if isinstance(group, dict) else []):
            if not isinstance(item, dict):
                continue
            person, entity = item.get("person") or {}, item.get("enhet") or {}
            name = person.get("navn") or {}
            display = " ".join(str(name.get(k)) for k in ("fornavn", "mellomnavn", "etternavn") if name.get(k))
            # Birth date and identifier fields are never copied into normalized output.
            result.append({"name": display or entity.get("navn"), "holder_organisation_number": entity.get("organisasjonsnummer"),
                           "role_code": _get(item, "type", "kode"), "role_description": _get(item, "type", "beskrivelse"),
                           "role_group_code": _get(group, "type", "kode"), "role_group": _get(group, "type", "beskrivelse"),
                           "from_date": item.get("fraDato"), "to_date": item.get("tilDato"),
                           "last_changed": group.get("sistEndret"), "inactive": bool(item.get("avregistrert") or item.get("fratraadt")),
                           "holder_kind": "organisation" if entity.get("organisasjonsnummer") else "person",
                           "_source_path": f"/rollegrupper/{gi}/roller/{ri}",
                           "_source_group_path": f"/rollegrupper/{gi}"})
    return result


def subunit_page(body: Any) -> tuple[list[dict[str, Any]], str | None, bool]:
    if not isinstance(body, dict):
        return [], None, False
    rows = _get(body, "_embedded", "underenheter") or []
    if not isinstance(rows, list):
        return [], None, False
    links = body.get("_links") or {}
    next_url = _get(links, "next", "href")
    page = body.get("page") or {}
    try:
        complete = not next_url and (not page or int(page.get("number", 0)) + 1 >= int(page.get("totalPages", 1)))
    except (AttributeError, TypeError, ValueError):
        complete = False
    return [row for row in rows if isinstance(row, dict)], next_url, complete


def _account_collection_shape(body: Any) -> bool:
    if isinstance(body, list):
        return all(isinstance(item, dict) for item in body)
    if not isinstance(body, dict):
        return False
    embedded = body.get("_embedded")
    if isinstance(embedded, dict) and "regnskap" in embedded:
        rows = embedded["regnskap"]
        return isinstance(rows, list) and all(isinstance(item, dict) for item in rows)
    if "regnskap" in body:
        rows = body["regnskap"]
        return isinstance(rows, list) and all(isinstance(item, dict) for item in rows)
    return "id" in body and isinstance(body.get("regnskapsperiode"), dict)


def _role_collection_shape(body: Any) -> bool:
    if not isinstance(body, dict) or not isinstance(body.get("rollegrupper"), list):
        return False
    return all(isinstance(group, dict) and "roller" in group and isinstance(group.get("roller"), list)
               and isinstance(group.get("type"), dict) and bool(group["type"].get("kode"))
               and all(isinstance(role, dict) and isinstance(role.get("type"), dict)
                       and bool(role["type"].get("kode")) for role in group.get("roller", []))
               for group in body["rollegrupper"])


def _empty_hal_subunit_page(body: Any) -> bool:
    """BRREG may omit _embedded for an explicitly empty first HAL page."""
    if not isinstance(body, dict) or "_embedded" in body:
        return False
    page, links = body.get("page"), body.get("_links")
    return (isinstance(page, dict) and isinstance(links, dict) and "next" not in links
            and all(type(page.get(key)) is int and page[key] == 0
                    for key in ("number", "totalElements", "totalPages")))


def _subunit_collection_shape(body: Any) -> bool:
    return (_empty_hal_subunit_page(body) or
            (isinstance(body, dict) and isinstance(body.get("_embedded"), dict)
             and isinstance(body["_embedded"].get("underenheter"), list)
             and all(isinstance(item, dict) for item in body["_embedded"]["underenheter"])))


def group_relationships(body: Any, target_org: str) -> list[dict[str, Any]]:
    """Flatten relationship nodes without changing the anchored target entity."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    def walk(node: Any, parent_org: str | None = None, parent_name: str | None = None, path: str = "") -> None:
        if not isinstance(node, dict):
            return
        org = node.get("organisasjonsnummer")
        if isinstance(org, str) and org and org != target_org:
            relation = str(node.get("knytningsform") or "unknown")
            key = (org, parent_org or "", relation)
            if key not in seen:
                result.append({"organisation_number": org, "name": node.get("navn"), "parent_organisation_number": parent_org,
                               "parent_name": parent_name, "relationship": relation, "level": node.get("nivaa"),
                               "legal_form": _get(node, "organisasjonsform", "kode"), "source_path": path})
                seen.add(key)
            next_parent, next_name = org, node.get("navn")
        else:
            next_parent, next_name = (org, node.get("navn")) if org == target_org else (parent_org, parent_name)
        children = node.get("children") or node.get("barn") or []
        for index, child in enumerate(children):
            walk(child, next_parent, next_name, f"{path}/children/{index}")
    root = body.get("enhet") if isinstance(body, dict) and isinstance(body.get("enhet"), dict) else body
    walk(root)
    return result


def cutoff_identity(frozen: dict[str, Any] | None, live: dict[str, Any] | None, cutoff: datetime) -> dict[str, Any] | None:
    """Select the latest dated exact-entity identity observation allowed by cutoff."""
    choices = []
    for source, item in (("frozen", frozen), ("live", live)):
        if not isinstance(item, dict):
            continue
        observed = _date(item.get("as_of") or item.get("retrieved_at"))
        if observed is not None and observed <= cutoff:
            choices.append((observed, 1 if source == "live" else 0, {**item, "source": source}))
    return max(choices, key=lambda row: (row[0], row[1]))[2] if choices else None


def _source_id(org: str, section: str, digest: str, url: str) -> str:
    """Bind a BRREG snapshot identity to its target and exact endpoint context."""
    url_key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"brreg:{org}:{section}:{url_key}:{digest[:16]}"


def _add_endpoint_evidence(evidence: list[Evidence], snapshots: list[SourceSnapshot], *, org: str, name: str,
                           url: str, retrieved_at: datetime, status: int, digest: str | None,
                           pointer: str, method: str, rights: str = RIGHTS) -> str | None:
    if not digest:
        return None
    source_id = _source_id(org, name, digest, url)
    evidence_id = f"{org}:{name}:state:{digest[:12]}"
    evidence.append(Evidence(evidence_id=evidence_id, source_url=url, retrieved_at=retrieved_at,
                             content_sha256=digest, extraction_method=method, json_pointer=pointer,
                             source_class="official", subject_organisation_number=org,
                             source_snapshot_ids=[source_id]))
    if not any(item.source_id == source_id for item in snapshots):
        snapshots.append(SourceSnapshot(source_id=source_id, source_url=url, retrieved_at=retrieved_at,
            content_sha256=digest, http_status=status if 100 <= status <= 599 else None,
            cache_mode="transient", rights_status=rights))
    return evidence_id


async def fetch_company(org: str, gateway: NetworkGateway, cutoff: datetime, *,
                        allow_current_identity_after_run_start: bool = False) -> BrregResult:
    claims: list[Claim] = []
    evidence: list[Evidence] = []
    snapshots: list[SourceSnapshot] = []
    errors: list[RunError] = []
    states: dict[str, PublicState] = {"identity_brand": PublicState.NOT_AVAILABLE, "accounts_history": PublicState.NOT_AVAILABLE,
                                     "leadership_workplaces": PublicState.NOT_AVAILABLE}
    observations: dict[str, Any] = {"workplace_count": 0, "workplaces_complete": False, "financial_records": 0,
                                   "roles_count": 0, "entity_http_status": None, "group_checked": False}
    target_legal_form: str | None = None
    records: list[dict[str, Any]] = []

    def contact_leads(row: dict[str, Any], url: str, digest: str | None, retrieved: datetime,
                      status: int, source_name: str, prefix: str = "", *, workplace: bool = False) -> None:
        # Exact linked registry rows supply leads only; no mailbox or website fact is published.
        from .websites import registry_contact_leads
        if not digest:
            return
        sid = _source_id(org, source_name, digest, url)
        for raw, source_field in registry_contact_leads(row):
            if source_field == "hjemmeside" and not workplace:
                continue
            pointer = prefix + "/" + source_field
            eid = f"{org}:contact-lead:" + hashlib.sha256((url + pointer + raw).encode()).hexdigest()[:20]
            if any(e.evidence_id == eid for e in evidence):
                continue
            evidence.append(Evidence(evidence_id=eid, source_url=url, retrieved_at=retrieved,
                content_sha256=digest, json_pointer=pointer, extraction_method="brreg_contact_domain_lead_v1",
                subject_organisation_number=org, source_snapshot_ids=[sid]))
            if not any(item.source_id == sid for item in snapshots):
                snapshots.append(SourceSnapshot(source_id=sid, source_url=url, retrieved_at=retrieved,
                    content_sha256=digest, http_status=status, cache_mode="transient", rights_status=RIGHTS))
            observations.setdefault("website_candidates", []).append({"raw": raw,
                "source": "workplace_contact" if workplace else "registry_email", "json_pointer": pointer,
                "rights_status": RIGHTS, "source_url": url, "content_sha256": digest,
                "evidence_id": eid, "source_snapshot_id": sid})

    async def request(url: str, purpose: str, section: str) -> tuple[Any, str | None, int, datetime, str | None]:
        retrieved = datetime.now(timezone.utc)
        try:
            status, headers, payload, final_url, outcome = await gateway.fetch(url, purpose=purpose, user_agent=UA,
                                                                                max_bytes=4 * 1024 * 1024,
                                                                                allowed_hosts={"data.brreg.no"},
                                                                                access_profile="brreg_structured_api")
        except Exception as exc:
            detail = str(exc).replace("\n", " ")[:160]
            errors.append(RunError(code=f"BRREG_{purpose.upper()}_TRANSPORT", message=f"{type(exc).__name__}: {detail}", retryable=True, source_id=section))
            return None, None, 0, retrieved, None
        response_digest = hashlib.sha256(payload).hexdigest()
        if final_url and urlsplit(final_url).hostname != "data.brreg.no":
            errors.append(RunError(code="BRREG_REDIRECT_HOST_REJECTED", message="BRREG endpoint redirected outside its official API host."))
            return {"_http_status": status, "_outcome": "redirect_host_rejected"}, final_url, 0, retrieved, response_digest
        if status == 200 and outcome == "ok":
            try:
                return json.loads(payload), final_url, status, retrieved, response_digest
            except (ValueError, UnicodeDecodeError):
                errors.append(RunError(code=f"BRREG_{purpose.upper()}_INVALID_JSON", message="Official endpoint returned invalid JSON.", source_id=section))
                return None, final_url, status, retrieved, response_digest
        code = f"BRREG_{purpose.upper()}_{status or outcome.upper()}"
        errors.append(RunError(code=code, message=f"Official source outcome: {outcome}.", retryable=status >= 500 or status == 0, source_id=section))
        return {"_http_status": status, "_outcome": outcome}, final_url or url, status, retrieved, response_digest

    def add_claim(field: str, value: Any, section: str, family: str, subject: str, scope: str,
                  url: str, retrieved: datetime, raw_document: Any, pointer: str, source_name: str,
                  *, unit: str | None = None, currency: str | None = None, start: Any = None, end: Any = None,
                  as_of: Any = None, source_hash: str | None = None,
                  extraction_method: str = "brreg_json_pointer_v1") -> None:
        if value is None:
            return
        raw_bytes = json.dumps(raw_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        digest = source_hash or hashlib.sha256(raw_bytes).hexdigest()
        sid = _source_id(org, source_name, digest, url)
        eid = f"{org}:{section}:{len(evidence)}:{digest[:12]}"
        evidence.append(Evidence(evidence_id=eid, source_url=url, retrieved_at=retrieved,
                                 content_sha256=digest, extraction_method=extraction_method, json_pointer=pointer,
                                 source_class="official", subject_organisation_number=org,
                                 source_snapshot_ids=[sid]))
        if not any(s.source_id == sid for s in snapshots):
            snapshots.append(SourceSnapshot(source_id=sid, source_url=url, retrieved_at=retrieved, content_sha256=digest,
                                            http_status=200, cache_mode="transient", rights_status=RIGHTS))
        identity = stable_claim_id(org, field, value, source=url + "#" + pointer, content_sha256=digest,
            subject=subject, period_start=_date(start), period_end=_date(end), scope=scope,
            unit=unit, currency=currency, as_of=_date(as_of))
        claims.append(Claim(claim_id=identity, organisation_number=org, section=section,
                            field_family=family, subject_id=subject, field=field, value=value, state=PublicState.AVAILABLE,
                            unit=unit, currency=currency, period_start=_date(start), period_end=_date(end), as_of=_date(as_of),
                            scope=scope, verification_rule_id="brreg_exact_org_pointer_v1", verification_score="1.0",
                            evidence_ids=[eid], source_snapshot_ids=[sid]))

    entity_url = f"{BASE}/enheter/{org}"
    entity, entity_final, entity_status, entity_time, entity_hash = await request(entity_url, "entity", "identity_brand")
    observations["entity_http_status"] = entity_status
    if entity_status in {404, 410}:
        observations["identity_state_evidence_id"] = _add_endpoint_evidence(evidence, snapshots, org=org, name="entity_state",
            url=entity_final or entity_url, retrieved_at=entity_time, status=entity_status, digest=entity_hash,
            pointer="/", method="brreg_entity_status_v1")
    entity_is_target = isinstance(entity, dict) and entity.get("organisasjonsnummer") == org
    if entity_is_target and entity_final:
        identity = normalize_entity(entity)
        observations["identity_profile"] = identity
        target_legal_form = identity.get("legal_form")
        if identity.get("website"):
            candidate_source_id = _source_id(org, "entity", entity_hash or hashlib.sha256(b"").hexdigest(), entity_final)
            candidate_evidence_id = f"{org}:website-candidate:{(entity_hash or '')[:12]}"
            if entity_hash:
                evidence.append(Evidence(evidence_id=candidate_evidence_id, source_url=entity_final,
                    retrieved_at=entity_time, content_sha256=entity_hash, extraction_method="brreg_website_candidate_v1",
                    json_pointer="/hjemmeside", source_class="official", subject_organisation_number=org,
                    source_snapshot_ids=[candidate_source_id]))
                if not any(item.source_id == candidate_source_id for item in snapshots):
                    snapshots.append(SourceSnapshot(source_id=candidate_source_id, source_url=entity_final,
                        retrieved_at=entity_time, content_sha256=entity_hash, http_status=entity_status,
                        cache_mode="transient", rights_status=RIGHTS))
            observations["website_candidates"] = [{"raw": identity["website"], "source": "registry_live", "rights_status": "NLOD-2.0",
                "source_url": entity_final, "content_sha256": entity_hash, "evidence_id": candidate_evidence_id,
                "source_snapshot_id": candidate_source_id, "retrieved_at": entity_time.isoformat()}]
        contact_leads(entity, entity_final, entity_hash, entity_time, entity_status, "entity")
        identity_source_paths = {
            "organisation_number": "/organisasjonsnummer", "name": "/navn", "legal_form": "/organisasjonsform/kode",
            "legal_form_description": "/organisasjonsform/beskrivelse", "website": "/hjemmeside", "employees": "/antallAnsatte",
            "latest_submitted_accounts": "/sisteInnsendteAarsregnskap", "parent_organisation_number": "/overordnetEnhet",
            "municipality_number": "/kommunenummer" if entity.get("kommunenummer") else "/forretningsadresse/kommunenummer",
            "municipality": "/kommune" if entity.get("kommune") else "/forretningsadresse/kommune",
            "business_address": "/forretningsadresse", "postal_address": "/postadresse", "registered_workplace_address": "/beliggenhetsadresse", "status": "/",
            "status_dates": "/", "industry_codes": "/",
        }
        fields = [(k, v) for k, v in identity.items() if v is not None and k not in {"status", "status_dates", "historical_names", "industry_codes", "business_address", "postal_address", "registered_workplace_address", "website"}]
        fields.extend((f"status.{k}", v) for k, v in identity["status"].items())
        fields.extend((f"status_dates.{k}", v) for k, v in identity["status_dates"].items())
        fields.extend((f"industry_codes.{i}", v) for i, v in enumerate(identity["industry_codes"]))
        for key in ("business_address", "postal_address", "registered_workplace_address"):
            if identity[key]: fields.append((key, identity[key]))
        for key, value in fields:
            pointer = identity_source_paths.get(key, "/")
            if key.startswith("status.") or key.startswith("status_dates."):
                pointer = "/" + key.split(".", 1)[1]
            elif key.startswith("industry_codes."):
                pointer = f"/naeringskode{int(key.rsplit('.', 1)[1]) + 1}"
            add_claim(key, value, "identity_brand", "identity", org, "legal_entity", entity_final, entity_time,
                      entity, pointer, "entity", source_hash=entity_hash,
                      extraction_method="brreg_json_pointer_projection_v1" if key in {"business_address", "postal_address", "registered_workplace_address"} else "brreg_json_pointer_v1")
        # These are registered statements, not observed dated events or an
        # inferred industry description. Preserve the complete source arrays:
        # their elements can be line wraps rather than independent activities.
        for source_field, field in (("aktivitet", "registered_business_activity"),
                                    ("vedtektsfestetFormaal", "registered_purpose")):
            value = entity.get(source_field)
            if (not isinstance(value, list) or not value or
                    not all(isinstance(line, str) for line in value) or
                    not any(line.strip() for line in value)):
                continue
            text = " ".join(value)
            if re.search(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b|(?<!\d)(?:\+47\s?)?\d{8}(?!\d)|(?<!\d)\d{11}(?!\d)", text):
                continue
            add_claim(field, value, "identity_brand", "business_description", org, "legal_entity",
                      entity_final, entity_time, entity, "/" + source_field, "entity", source_hash=entity_hash)
        for i, item in enumerate(identity["historical_names"]):
            add_claim("historical_name", item["name"], "identity_brand", "identity_history", org, "legal_entity",
                      entity_final, entity_time, entity, f"/historiskeNavn/{i}/navn", "entity", start=item["from"], end=item["to"], source_hash=entity_hash)
        states["identity_brand"] = PublicState.AVAILABLE if claims else PublicState.NOT_AVAILABLE
    elif entity_status == 410:
        states["identity_brand"] = PublicState.BLOCKED
        observations["entity_removed_from_disclosure"] = True
    elif entity_status >= 500 or entity_status == 0:
        states["identity_brand"] = PublicState.FAILED
    elif entity_status in {401, 403, 429, 451}:
        states["identity_brand"] = PublicState.BLOCKED
    else:
        states["identity_brand"] = PublicState.NOT_AVAILABLE
    if isinstance(entity, dict) and entity.get("organisasjonsnummer") and entity.get("organisasjonsnummer") != org:
        errors.append(RunError(code="BRREG_IDENTITY_ANCHOR_MISMATCH", message="Live registry returned a different organisation number."))
        states["identity_brand"] = PublicState.AMBIGUOUS

    # Subunit input is atomic. Do not use its parent to fill its legal identity.
    target_is_subunit = bool(isinstance(entity, dict) and entity.get("overordnetEnhet"))
    observations["target_is_subunit"] = target_is_subunit
    accounts_url = f"{ACCOUNTS}/{org}"
    account_body, account_final, account_status, account_time, account_hash = await request(accounts_url, "accounts", "accounts_history")
    if account_status != 200:
        observations["accounts_state_evidence_id"] = _add_endpoint_evidence(evidence, snapshots, org=org, name="accounts_state",
            url=account_final or accounts_url, retrieved_at=account_time, status=account_status, digest=account_hash,
            pointer="/", method="brreg_accounts_endpoint_state_v1")
    accounts_malformed = account_status == 200 and not _account_collection_shape(account_body)
    if accounts_malformed:
        errors.append(RunError(code="BRREG_ACCOUNTS_MALFORMED", message="Official accounts endpoint returned an invalid collection shape.", source_id="accounts_history"))
    if account_status == 200 and _account_collection_shape(account_body):
        records = financial_records(account_body)
        observations["financial_records"] = len(records)
        if not records:
            observations["accounts_state_evidence_id"] = _add_endpoint_evidence(evidence, snapshots, org=org, name="accounts_empty",
                url=account_final or accounts_url, retrieved_at=account_time, status=account_status, digest=account_hash,
                pointer="/", method="brreg_empty_account_collection_v1")
        for ri, record in enumerate(records):
            raw = account_body
            record_path = record["_source_prefix"]
            period_start = _date(record.get("period_start"))
            period_end = _date(record.get("period_end"))
            currency_valid = supported_currency(record.get("currency"))
            metadata_valid = (period_start is not None and period_end is not None and period_start <= period_end
                              and currency_valid and record.get("scope") in {"legal_entity", "group"})
            if any(record["metrics"].get(metric) is not None for metric in METRICS) and not metadata_valid:
                missing = []
                if period_start is None or period_end is None or period_start > period_end: missing.append("period")
                if not currency_valid: missing.append("currency")
                if record.get("scope") not in {"legal_entity", "group"}: missing.append("scope")
                errors.append(RunError(code="BRREG_FINANCIAL_METADATA_INCOMPLETE",
                    message="Financial metrics were withheld because source metadata is missing or invalid: " + ",".join(missing),
                    source_id="accounts_history"))
            subject = financial_record_subject(org, record)
            for metric in METRICS:
                value = record["metrics"].get(metric)
                if value is None:
                    continue
                if not metadata_valid:
                    continue
                unit = record["metrics"].get(metric + "_unit")
                if not isinstance(unit, str) or not financial_dimensions_compatible(unit.strip().upper(), record["currency"]):
                    errors.append(RunError(code="BRREG_FINANCIAL_UNIT_UNSUPPORTED",
                        message=f"Financial metric {metric} was withheld because its source unit is missing or unsupported.",
                        source_id="accounts_history"))
                    continue
                # The record's own labels determine scope and periods. No calendar-year inference.
                raw_metric = _get(record["raw"], *METRICS[metric].split("/"))
                metric_pointer = record_path + "/" + METRICS[metric]
                if isinstance(raw_metric, dict) and isinstance(raw_metric.get("sum"), (int, float)):
                    metric_pointer += "/sum"
                add_claim(metric, value, "accounts_history", "financial", subject, record["scope"], account_final or accounts_url,
                          account_time, raw, metric_pointer, "accounts", unit=unit.strip().upper(),
                          currency=record["currency"], start=record["period_start"], end=record["period_end"],
                          as_of=record["filing_timestamp"], source_hash=account_hash,
                          extraction_method="brreg_financial_projection_v1" if isinstance(raw_metric, dict) else "brreg_json_pointer_v1")
            for meta in ("record_id", "filing_id", "record_version", "source_version_or_filing_id", "account_type", "scope",
                         "period_start", "period_end", "filing_timestamp", "currency", "raw_unit"):
                if record.get(meta) is not None:
                    source_pointers = {"record_id": "/id", "filing_id": "/innsendingsId", "record_version": "/versjon",
                                       "account_type": "/regnskapstype", "scope": "/regnskapstype",
                                       "period_start": "/regnskapsperiode/fraDato", "period_end": "/regnskapsperiode/tilDato",
                                       "filing_timestamp": "/innsendingsdato" if record["raw"].get("innsendingsdato") else "/registreringsdato",
                                       "currency": "/valuta", "raw_unit": "/enhet"}
                    if meta == "source_version_or_filing_id":
                        pointer = "/versjon" if record["raw"].get("versjon") else "/innsendingsId" if record["raw"].get("innsendingsId") else "/id"
                    else:
                        pointer = source_pointers[meta]
                    add_claim(f"financial_record.{meta}", record[meta], "accounts_history", "financial_record_metadata", subject,
                              record["scope"], account_final or accounts_url, account_time, raw, record_path + pointer, "accounts",
                              start=record["period_start"], end=record["period_end"], as_of=record["filing_timestamp"],
                              currency=record["currency"], source_hash=account_hash,
                              extraction_method="brreg_scope_normalization_v1" if meta == "scope" else "brreg_json_pointer_v1")
        states["accounts_history"] = (PublicState.AVAILABLE if any(c.section == "accounts_history" for c in claims)
            else PublicState.AMBIGUOUS if records else PublicState.NOT_AVAILABLE)
    elif accounts_malformed or account_status >= 500 or account_status == 0:
        states["accounts_history"] = PublicState.FAILED
    elif account_status in {401, 403, 429, 451}:
        states["accounts_history"] = PublicState.BLOCKED
    else:
        states["accounts_history"] = PublicState.NOT_AVAILABLE

    roles_url = f"{BASE}/enheter/{org}/roller"
    roles_body, roles_final, roles_status, roles_time, roles_hash = await request(roles_url, "roles", "leadership_workplaces")
    if roles_status != 200:
        observations["roles_state_evidence_id"] = _add_endpoint_evidence(evidence, snapshots, org=org, name="roles_state",
            url=roles_final or roles_url, retrieved_at=roles_time, status=roles_status, digest=roles_hash,
            pointer="/", method="brreg_roles_endpoint_state_v1")
    subunits_url = f"{BASE}/underenheter?overordnetEnhet={org}&size=1000"
    subunit_body, subunit_final, subunit_status, subunit_time, subunit_hash = await request(subunits_url, "subunits", "leadership_workplaces")
    if subunit_status != 200:
        observations["subunits_state_evidence_id"] = _add_endpoint_evidence(evidence, snapshots, org=org, name="subunits_state",
            url=subunit_final or subunits_url, retrieved_at=subunit_time, status=subunit_status, digest=subunit_hash,
            pointer="/", method="brreg_subunits_endpoint_state_v1")
    roles_malformed = roles_status == 200 and not _role_collection_shape(roles_body)
    if roles_malformed:
        errors.append(RunError(code="BRREG_ROLES_MALFORMED", message="Official roles endpoint returned an invalid collection shape.", source_id="leadership_workplaces"))
    roles = role_records(roles_body) if roles_status == 200 and not roles_malformed else []
    observations["roles_count"] = len(roles)
    observations["role_family_state"] = (
        PublicState.AVAILABLE.value if roles else PublicState.FAILED.value if roles_malformed else PublicState.NOT_AVAILABLE.value if roles_status == 200 else
        PublicState.BLOCKED.value if roles_status in {401, 403, 429, 451} else PublicState.FAILED.value)
    ceo_rows = [role for role in roles if str(role.get("role_code") or "").casefold() in {"dagl", "ceo"}
                or "daglig leder" in str(role.get("role_description") or "").casefold()
                or "managing director" in str(role.get("role_description") or "").casefold()]
    observations["ceo_state"] = (PublicState.AVAILABLE.value if ceo_rows else
                                 PublicState.FAILED.value if roles_malformed else PublicState.NOT_AVAILABLE.value if roles_status == 200 else
                                 PublicState.BLOCKED.value if roles_status in {401, 403, 429, 451} else PublicState.FAILED.value)
    if roles_status == 200 and not roles_malformed:
        roles_digest = roles_hash or hashlib.sha256(json.dumps(roles_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        completion_snapshot_id = _source_id(org, "roles", roles_digest, roles_final or roles_url)
        observations["roles_completeness_evidence_id"] = f"{org}:roles-complete:{roles_digest[:12]}"
        if not roles:
            observations["roles_state_evidence_id"] = observations["roles_completeness_evidence_id"]
        evidence.append(Evidence(evidence_id=observations["roles_completeness_evidence_id"], source_url=roles_final or roles_url,
                                retrieved_at=roles_time, content_sha256=roles_digest,
                                extraction_method="brreg_complete_role_collection_v1", json_pointer="/rollegrupper",
                                subject_organisation_number=org, source_snapshot_ids=[completion_snapshot_id]))
        if not any(item.source_id == completion_snapshot_id for item in snapshots):
            snapshots.append(SourceSnapshot(source_id=completion_snapshot_id, source_url=roles_final or roles_url,
                retrieved_at=roles_time, content_sha256=roles_digest, http_status=200, rights_status=RIGHTS))
    for i, role in enumerate(roles):
        holder = role.get("holder_organisation_number")
        if holder:
            normalized, valid = normalize_org_number(holder)
            if not valid:
                errors.append(RunError(code="BRREG_ROLE_HOLDER_INVALID_ORG", message="Role holder organisation number failed checksum."))
                continue
            role["holder_organisation_number"] = normalized
        for key, value in role.items():
            if value is None or key in {"_source_path", "_source_group_path"}: continue
            role_source_paths = {"name": "/enhet/navn" if role.get("holder_kind") == "organisation" else "/person/navn", "holder_organisation_number": "/enhet/organisasjonsnummer",
                                 "role_code": "/type/kode", "role_description": "/type/beskrivelse",
                                 "role_group_code": "/type/kode", "role_group": "/type/beskrivelse",
                                 "from_date": "/fraDato", "to_date": "/tilDato", "last_changed": "/sistEndret",
                                 "inactive": "/", "holder_kind": "/"}
            source_root = role["_source_group_path"] if key.startswith("role_group") or key == "last_changed" else role["_source_path"]
            relative_pointer = role_source_paths.get(key, "/" + key)
            role_path = source_root + (relative_pointer if relative_pointer != "/" else "")
            method = "brreg_role_name_join_v1" if key == "name" and role.get("holder_kind") == "person" else "brreg_role_status_normalization_v1" if key in {"inactive", "holder_kind"} else "brreg_json_pointer_v1"
            add_claim(f"role.{key}", value, "leadership_workplaces", "role", org, "person_role",
                      roles_final or roles_url, roles_time, roles_body, role_path, "roles", source_hash=roles_hash,
                      as_of=role.get("last_changed"),
                      extraction_method=method)
    locations: list[tuple[dict[str, Any], Any, str, str | None, datetime, int]] = []
    subunits_malformed = subunit_status == 200 and not _subunit_collection_shape(subunit_body)
    if subunits_malformed:
        errors.append(RunError(code="BRREG_SUBUNITS_MALFORMED", message="Official subunit endpoint returned an invalid collection shape.", source_id="leadership_workplaces"))
    complete = subunit_status == 200 and not subunits_malformed
    subunit_pages: list[dict[str, Any]] = []
    subunit_page_pointers: dict[str, str] = {}
    current = subunit_body
    current_url = subunit_final or subunits_url
    current_hash = subunit_hash
    current_time = subunit_time
    page_index = 0
    while subunit_status == 200 and isinstance(current, dict) and _subunit_collection_shape(current):
        if current_hash:
            subunit_pages.append({"url": current_url, "content_sha256": current_hash,
                                  "retrieved_at": current_time.isoformat(), "page_index": page_index})
        collection_pointer = "/page/totalElements" if _empty_hal_subunit_page(current) else "/_embedded/underenheter"
        subunit_page_pointers[current_url] = collection_pointer
        rows, next_path, page_complete = subunit_page(current)
        locations.extend((item, current, current_url, current_hash, current_time, i) for i, item in enumerate(rows))
        if not rows:
            observations["subunits_state_evidence_id"] = _add_endpoint_evidence(evidence, snapshots, org=org, name=f"subunits_page_{page_index}",
                url=current_url, retrieved_at=current_time, status=200, digest=current_hash,
                pointer=collection_pointer, method="brreg_subunit_page_collection_v1")
        complete = page_complete
        if not next_path: break
        next_url = urljoin(current_url, next_path)
        current, subunit_final, subunit_status, subunit_time, current_hash = await request(next_url, "subunits_page", "leadership_workplaces")
        current_time = subunit_time
        current_url = subunit_final or next_url
        page_index += 1
        if page_index >= 100:
            complete = False
            errors.append(RunError(code="BRREG_SUBUNITS_PAGE_LIMIT", message="Subunit pagination exceeded 100 pages."))
            break
    observations["workplace_rows_returned"] = len(locations)
    observations["workplaces_complete"] = complete
    candidates_by_child: dict[str, list[tuple[dict[str, Any], Any, str, str | None, datetime, int, str | None]]] = {}
    for item, page_body, page_url, page_hash, page_time, page_row_index in locations:
        child_org, child_valid = normalize_org_number(item.get("organisasjonsnummer"))
        parent_org, parent_valid = normalize_org_number(item.get("overordnetEnhet"))
        if not child_valid:
            observations["workplaces_complete"] = False
            errors.append(RunError(code="BRREG_SUBUNIT_RELATION_INVALID",
                message="A returned workplace had an invalid child organisation number."))
            continue
        canonical_row = dict(item)
        canonical_row["organisasjonsnummer"] = child_org
        if parent_valid:
            canonical_row["overordnetEnhet"] = parent_org
        fingerprint = hashlib.sha256(json.dumps(canonical_row, sort_keys=True, ensure_ascii=False,
            separators=(",", ":")).encode()).hexdigest()
        candidates_by_child.setdefault(child_org, []).append(
            (item, page_body, page_url, page_hash, page_time, page_row_index,
             fingerprint if parent_valid else None))

    publishable: list[tuple[dict[str, Any], Any, str, str | None, datetime, int]] = []
    for child_org, rows in sorted(candidates_by_child.items()):
        relation_valid = all(normalize_org_number(row[0].get("overordnetEnhet"))[1]
            and normalize_org_number(row[0].get("overordnetEnhet"))[0] == org
            and child_org != org for row in rows)
        fingerprints = {row[6] for row in rows}
        if not relation_valid:
            observations["workplaces_complete"] = False
            errors.append(RunError(code="BRREG_SUBUNIT_RELATION_INVALID",
                message="A returned workplace had an invalid parent or represented the target as its own child."))
            continue
        if len(fingerprints) != 1:
            observations["workplaces_complete"] = False
            errors.append(RunError(code="BRREG_SUBUNIT_DUPLICATE_CONFLICT",
                message="Conflicting duplicate records were returned for one workplace; its facts were withheld."))
            continue
        # Identical duplicate rows are one deterministic source-backed workplace.
        publishable.append(min(rows, key=lambda row: row[5])[:6])

    observations["workplace_count"] = len(publishable)
    if observations["workplaces_complete"]:
        completeness_ids = []
        for page in subunit_pages:
            digest = page["content_sha256"]
            source_id = _source_id(org, "subunits", digest, page["url"])
            evidence_id = f"{org}:workplaces-page-complete:{page['page_index']}:{digest[:12]}"
            completeness_ids.append(evidence_id)
            if not any(item.source_id == source_id for item in snapshots):
                snapshots.append(SourceSnapshot(source_id=source_id, source_url=page["url"],
                    retrieved_at=datetime.fromisoformat(page["retrieved_at"]), content_sha256=digest,
                    http_status=200, rights_status=RIGHTS))
            evidence.append(Evidence(evidence_id=evidence_id, source_url=page["url"],
                retrieved_at=datetime.fromisoformat(page["retrieved_at"]), content_sha256=digest,
                extraction_method="brreg_complete_workplace_page_v1", json_pointer=subunit_page_pointers[page["url"]],
                subject_organisation_number=org, source_snapshot_ids=[source_id]))
        observations["workplaces_completeness_evidence_ids"] = completeness_ids
        observations["workplaces_completeness_evidence_id"] = completeness_ids[0] if completeness_ids else None
    for item, page_body, page_url, page_hash, page_time, page_row_index in publishable:
        child_org = normalize_org_number(item.get("organisasjonsnummer"))[0]
        parent_org = normalize_org_number(item.get("overordnetEnhet"))[0]
        item["organisasjonsnummer"] = child_org
        contact_leads(item, page_url, page_hash, page_time, 200, "subunits",
            f"/_embedded/underenheter/{page_row_index}", workplace=True)
        for key in ("organisasjonsnummer", "navn", "beliggenhetsadresse", "postadresse", "naeringskode1", "antallAnsatte", "overordnetEnhet"):
            if target_legal_form == "ENK" and key in {"beliggenhetsadresse", "postadresse"}:
                continue
            val = item.get(key)
            if val is not None:
                add_claim(f"workplace.{key}", val, "leadership_workplaces", "workplace", child_org, "workplace",
                          page_url, page_time, page_body, f"/_embedded/underenheter/{page_row_index}/{key}", "subunits",
                          source_hash=page_hash)
    role_claims = any(c.field_family == "role" for c in claims)
    workplace_claims = any(c.field_family == "workplace" for c in claims)
    observations["workplaces_state"] = (PublicState.AVAILABLE.value if observations["workplaces_complete"] else
        PublicState.FAILED.value if subunits_malformed or subunit_status >= 500 or subunit_status == 0 else
        PublicState.BLOCKED.value if subunit_status in {401, 403, 429, 451} else
        PublicState.AMBIGUOUS.value)
    states["leadership_workplaces"] = PublicState.AVAILABLE if role_claims or workplace_claims else (
        PublicState.FAILED if roles_malformed or subunits_malformed or roles_status >= 500 or subunit_status >= 500 or roles_status == 0 or subunit_status == 0 else
        PublicState.BLOCKED if roles_status in {401, 403, 429, 451} or subunit_status in {401, 403, 429, 451} else
        PublicState.AMBIGUOUS if not observations["workplaces_complete"] else PublicState.NOT_AVAILABLE)

    for section in states:
        if states[section] == PublicState.NOT_AVAILABLE:
            errors.append(RunError(code=f"BRREG_{section.upper()}_NO_DATA", message="Official lookup completed without a source record for this section."))
    evidence_by_id = {item.evidence_id: item for item in evidence}
    eligible_claims = []
    excluded_sections: set[str] = set()
    for claim in claims:
        observed_at = claim.as_of or claim.period_end
        if observed_at is None and claim.evidence_ids:
            observed_at = evidence_by_id[claim.evidence_ids[0]].retrieved_at
        # In default live mode these are current registry observations, not historical
        # events. Explicit evaluator cutoffs keep the original strict date gate.
        current_live_identity = (
            allow_current_identity_after_run_start
            and (claim.section == "identity_brand" or (
                claim.section == "leadership_workplaces" and claim.field_family == "workplace"
                and claim.scope == "workplace"))
            and claim.as_of is None
            and claim.period_end is None
            and claim.evidence_ids
            and evidence_by_id[claim.evidence_ids[0]].retrieved_at >= cutoff
        )
        if (observed_at is not None and observed_at <= cutoff) or current_live_identity:
            eligible_claims.append(claim)
        else:
            excluded_sections.add(claim.section or "unknown")
    claims = eligible_claims
    for section_name in excluded_sections:
        if not any(c.section == section_name for c in claims) and section_name in states:
            states[section_name] = PublicState.NOT_AVAILABLE
            errors.append(RunError(code="BRREG_POST_CUTOFF_EXCLUDED", message=f"Undated or post-cutoff {section_name} claims were excluded."))
    terminal = PublicState.AVAILABLE if any(c.section in states and c.state == PublicState.AVAILABLE for c in claims) else (
        PublicState.BLOCKED if any(s == PublicState.BLOCKED for s in states.values()) else
        PublicState.FAILED if any(s == PublicState.FAILED for s in states.values()) else PublicState.NOT_AVAILABLE)
    return BrregResult(claims, evidence, snapshots, errors, states, terminal, observations,
        account_records=records, account_source={"url": account_final or accounts_url,
            "retrieved_at": account_time, "content_sha256": account_hash, "status": account_status})
