"""Conservative website candidate verification and bounded shallow research.

Discovery returns candidates. Only ``verify_site_pages`` can create an accepted
site, and only accepted pages can create website claims.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any

from bs4 import BeautifulSoup
import extruct
import trafilatura

from .models import Claim, Evidence, PublicState, RunError, SourceSnapshot
from .network import NetworkGateway, NetworkPolicyError, registered_domain, robots_directives
from .identifiers import canonical_product_heading, website_claim_value_digest

UA = "SignalpostResearchBot/1.0 (contact pending)"
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_SITE_BYTES = 8 * 1024 * 1024
MAX_INITIAL_PAGES = 6
MAX_DEFAULT_PAGES = 10
MAX_ABSOLUTE_PAGES = 25
MAX_DEPTH = 2
MAX_SITEMAP_INDEXES = 5
MAX_SITEMAP_URLS = 100
MAX_FEEDS = 5
APPROVED_WEBSITE_REQUEST_PURPOSES = frozenset({"robots", "sitemap", "website_page", "feed"})
APPROVED_EXTERNAL_CLAIM_FAMILIES = frozenset({"owned_web", "owned_profile", "jobs", "public_activity"})

SOCIAL_HOSTS = {
    "linkedin.com": "linkedin", "facebook.com": "facebook", "instagram.com": "instagram",
    "x.com": "x", "twitter.com": "x", "youtube.com": "youtube", "tiktok.com": "tiktok",
}
SOCIAL_ROOTS = {"linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com", "youtu.be", "tiktok.com"}
THIRD_PARTY_DIRECTORY_ROOTS = {
    "1881.no", "proff.no", "purehelp.no", "gulesider.no", "kompass.com", "creditsafe.com",
    "zoominfo.com", "crunchbase.com", "yellowpages.com", "firmainfo.no", "allabolag.se",
}
THIRD_PARTY_DIRECTORY_PATHS = {"company", "companies", "business", "listing", "listings", "directory", "profile", "profiles", "search", "reviews"}
LEGAL_SUFFIXES = {"as", "asa", "enk", "ans", "da", "sa", "nuf", "iks", "sti", "ab", "ltd", "inc", "plc", "limited"}
GENERIC_KEYLESS = {
    "sameie", "sameiet", "borettslag", "kommune", "fylkeskommune", "forening", "lag", "holding", "holdings",
    "eiendom", "property", "capital", "partners", "partnership", "group", "gruppen", "invest", "investering",
    "company", "selskap", "norge", "norway", "norsk", "norske", "international", "global", "service", "services",
    "consulting", "solutions", "management", "drift", "utleie", "bygg", "bygging", "handel", "butikk",
}
NEGATIVE_PATHS = ("privacy", "personvern", "cookie", "terms", "vilkar", "login", "logg-inn", "cart", "checkout", "search", "sok")
POSITIVE_PATHS = {
    "legal": ("legal", "imprint", "company-information", "bedriftsinformasjon", "organisasjonsnummer", "orgnr"),
    "about": ("about", "om-oss", "om_oss", "company", "bedriften", "who-we-are"),
    "contact": ("contact", "kontakt", "contact-us"),
    "careers": ("career", "careers", "jobb", "ledige-stillinger", "stillinger", "work-with-us"),
    "news": ("news", "nyheter", "press", "aktuelt", "blog", "rss", "feed"),
    "products": ("product", "products", "services", "tjenester", "produkter", "what-we-do"),
    "locations": ("locations", "avdelinger", "lokasjoner", "contact", "besoksadresse"),
}
IDENTITY_KINDS = {"legal", "about", "contact", "locations"}


def normalize_name(value: Any) -> str:
    """NFC/casefold/punctuation normalization that preserves Norwegian letters."""
    text = unicodedata.normalize("NFC", str(value or "")).casefold()
    text = re.sub(r"\b(?:a\s*[./-]\s*s(?:\s*[./-]\s*a)?|as|asa)\s*[.,]?\s*$", "", text).strip()
    text = "".join(char if char.isalnum() else " " for char in text)
    words = [word for word in text.split() if word not in LEGAL_SUFFIXES]
    return " ".join(words)


def _canonical_heading_key(value: str) -> str:
    """Canonicalize presentation-only whitespace/Unicode/case for heading identity."""
    return canonical_product_heading(value)


def _dedupe_product_headings(rows: list[tuple[str, "PageRecord"]]) -> list[tuple[str, "PageRecord"]]:
    """Keep one deterministic representative for equivalent headings on a page."""
    selected: dict[tuple[str, str], tuple[str, PageRecord]] = {}
    for raw_heading, page in rows:
        heading = " ".join(unicodedata.normalize("NFKC", raw_heading).split())
        semantic_key = _canonical_heading_key(heading)
        if not semantic_key:
            continue
        key = (_page_key(page), semantic_key)
        previous = selected.get(key)
        if previous is None or (heading.casefold(), heading) < (previous[0].casefold(), previous[0]):
            selected[key] = (heading, page)
    return [selected[key] for key in sorted(selected)]


def _distinctive_tokens(value: Any) -> list[str]:
    return [token for token in normalize_name(value).split() if len(token) >= 3]


def _host_social(host: str) -> str | None:
    normalized = host.casefold().removeprefix("www.")
    return next((name for domain, name in SOCIAL_HOSTS.items() if normalized == domain or normalized.endswith("." + domain)), None)


def _clean_url(value: str) -> str | None:
    raw = value.strip().strip("<>()[]{}\"'").rstrip(".,;:")
    if not raw or "@" in raw and "://" not in raw:
        return None
    if not re.match(r"^https?://", raw, re.I):
        if not re.fullmatch(r"(?:www\.)?[A-Za-z0-9\u00c0-\u024f](?:[A-Za-z0-9\u00c0-\u024f-]*[A-Za-z0-9\u00c0-\u024f])?(?:\.[A-Za-z0-9\u00c0-\u024f-]+)+(?:/[^\s]*)?", raw):
            return None
        raw = "https://" + raw
    try:
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        host = parsed.hostname.encode("idna").decode("ascii").casefold().rstrip(".")
        if not registered_domain(host) or host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal", ".test")):
            return None
        port = parsed.port
        if port and not ((parsed.scheme.casefold() == "https" and port == 443) or (parsed.scheme.casefold() == "http" and port == 80)):
            return None
        path = urllib.parse.quote(urllib.parse.unquote(parsed.path or "/"), safe="/%:@!$&'()*+,;=-._~")
        return urllib.parse.urlunsplit((parsed.scheme.casefold(), host, path, parsed.query, ""))
    except (ValueError, UnicodeError):
        return None


def sanitize_registry_websites(value: Any) -> list[dict[str, str]]:
    """Turn a registry field into candidates; never treat it as ownership proof."""
    raw = str(value or "").strip()
    if not raw or re.fullmatch(r"[^\s@]+@[^\s@]+", raw):
        return []
    matches = re.findall(r"(?:https?://[^\s,;]+|(?:www\.)?[A-Za-z0-9\u00c0-\u024f][A-Za-z0-9\u00c0-\u024f.-]*\.[A-Za-z\u00c0-\u024f]{2,}(?:/[^\s,;]*)?)", raw, re.I)
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in matches:
        url = _clean_url(item)
        if not url or url in seen:
            continue
        seen.add(url)
        host = urllib.parse.urlsplit(url).hostname or ""
        profile = _host_social(host)
        if profile:
            results.append({"url": url, "kind": "profile", "platform": profile})
        else:
            results.append({"url": url, "kind": "website"})
    return results


def keyless_no_candidate(legal_name: str) -> str | None:
    """Generate one conservative .no candidate, without searching or network access."""
    tokens = _distinctive_tokens(legal_name)
    meaningful = [token for token in tokens if token not in GENERIC_KEYLESS]
    if len(meaningful) < 2 or len(set(meaningful)) < 2:
        return None
    slug = "-".join(meaningful[:5])
    slug = slug.replace("æ", "ae").replace("ø", "o").replace("å", "a")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        return None
    return f"https://{slug}.no/"


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_as_text(item) for item in value)
    return ""


def _walk_schema(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        kind = value.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if any(isinstance(item, str) and any(token in item.casefold() for token in ("organization", "corporation", "localbusiness")) for item in kinds):
            found.append(value)
        for child in value.values():
            found.extend(_walk_schema(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_schema(child))
    return found


def _identifier_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [re.sub(r"\D", "", match.group(0)) for match in
                re.finditer(r"(?<!\d)\d(?:[\s.\-]*\d){8}(?!\d)", value)]
    if isinstance(value, dict):
        return _identifier_values(value.get("value")) + _identifier_values(value.get("identifier"))
    if isinstance(value, list):
        return [item for child in value for item in _identifier_values(child)]
    return []


@dataclass
class PageRecord:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    digest: str
    retrieved_at: datetime
    title: str = ""
    description: str = ""
    visible_text: str = ""
    identity_text: str = ""
    identity_blocks: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    structured: dict[str, Any] = field(default_factory=dict)
    schema_organizations: list[dict[str, Any]] = field(default_factory=list)
    canonical: str | None = None
    directives: set[str] = field(default_factory=set)
    soft_error: str | None = None
    locator: str = "/html/body"
    rights_status: str = "unknown_not_reviewed"
    footer_blocks: list[str] = field(default_factory=list)


@dataclass
class WebsiteResearchResult:
    claims: list[Claim] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    snapshots: list[SourceSnapshot] = field(default_factory=list)
    errors: list[RunError] = field(default_factory=list)
    state: PublicState | None = PublicState.NOT_AVAILABLE
    hiring_activity_state: PublicState | None = PublicState.AMBIGUOUS
    attempt_outcome: str | None = None
    hiring_attempt_outcome: str | None = None
    audit: dict[str, Any] = field(default_factory=dict)
    phase_state: dict[str, Any] = field(default_factory=dict, repr=False)


def _parse_page(requested_url: str, status: int, headers: dict[str, str], body: bytes, final_url: str) -> PageRecord | None:
    content_type = next((value for key, value in headers.items() if key.casefold() == "content-type"), "")
    if status < 200 or status >= 300 or "html" not in content_type.casefold() or len(body) > MAX_PAGE_BYTES:
        return None
    html = body.decode("utf-8", "replace")
    soup = BeautifulSoup(html, "lxml")
    title_node = soup.title
    title = title_node.get_text(" ", strip=True)[:500] if title_node else ""
    description_node = soup.select_one('meta[name="description"],meta[property="og:description"]')
    description = str(description_node.get("content") or "").strip()[:1000] if description_node else ""
    try:
        structured = extruct.extract(html, base_url=final_url, syntaxes=["json-ld", "microdata", "rdfa", "opengraph"])
    except Exception:
        structured = {}
    jsonld = structured.get("json-ld", []) if isinstance(structured, dict) else []
    schemas = _walk_schema(jsonld)
    # Microdata/RDFa organizations are retained as structured observations too.
    schemas.extend(_walk_schema(structured.get("microdata", []) if isinstance(structured, dict) else []))
    schemas.extend(_walk_schema(structured.get("rdfa", []) if isinstance(structured, dict) else []))
    text = trafilatura.extract(html, url=final_url, include_links=False, include_tables=True, favor_precision=True) or soup.get_text(" ", strip=True)
    text = " ".join(unescape(text).split())[:50_000]
    identity_nodes = soup.select("footer, address, [itemprop='legalName'], [itemprop='address'], [itemprop='identifier'], .legal, #legal, .contact, #contact, .about, #about")
    footer_blocks = [" ".join(node.get_text(" ", strip=True).split())[:3000]
                     for node in identity_nodes if node.name == "footer" or node.find_parent("footer")]
    identity_blocks = [" ".join(node.get_text(" ", strip=True).split())[:3000]
                       for node in identity_nodes if not (node.name == "footer" or node.find_parent("footer"))]
    identity_text = " ".join([*identity_blocks, *footer_blocks])[:12_000]
    links: list[dict[str, str]] = []
    for anchor in soup.select("a[href]"):
        href = urllib.parse.urljoin(final_url, str(anchor.get("href") or ""))
        parsed = urllib.parse.urlsplit(href)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        clean = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
        links.append({"url": clean, "text": " ".join(anchor.get_text(" ", strip=True).split())[:180],
                      "rel": " ".join(anchor.get("rel", [])) if isinstance(anchor.get("rel"), list) else str(anchor.get("rel") or "")})
    canonical_node = soup.select_one('link[rel~="canonical"][href]')
    canonical = urllib.parse.urljoin(final_url, str(canonical_node.get("href"))) if canonical_node else None
    directives = robots_directives(headers, html)
    body_text = (title + " " + description + " " + text[:2000]).casefold()
    soft_error = None
    if any(marker in body_text for marker in ("domain is for sale", "domain for sale", "this domain may be for sale", "parked free", "buy this domain", "coming soon")):
        soft_error = "parked_or_placeholder"
    elif len(text) < 40 and any(marker in (title + " " + body_text) for marker in ("not found", "page not found", "404", "access denied")):
        soft_error = "soft_404_or_access_wall"
    elif any(marker in body_text for marker in ("verify you are human", "just a moment...", "captcha")):
        soft_error = "waf_or_cookie_challenge"
    headings = [" ".join(node.get_text(" ", strip=True).split())[:220] for node in soup.select("h1,h2,h3")]
    page = PageRecord(requested_url, final_url, status, content_type, body, hashlib.sha256(body).hexdigest(),
                      datetime.now(timezone.utc), title, description, text, identity_text, identity_blocks, headings, links,
                      structured if isinstance(structured, dict) else {}, schemas, canonical, directives, soft_error)
    page.footer_blocks = footer_blocks
    return page


def _exact_name(legal_names: list[str], text: str) -> str | None:
    normalized = normalize_name(text)
    suffix_re = re.compile(r"(?i)\s*(?:a\s*[./-]?\s*s(?:\s*[./-]?\s*a)?|as|asa|enk|nuf|da|ans|ba|ab|oy|ltd|limited|inc|gmbh|plc)\s*[.,]?\s*$")
    suffix_forms = r"(?:a\s*[./-]?\s*s(?:\s*[./-]?\s*a)?|as|asa|enk|nuf|da|ans|ba|ab|oy|ltd|limited|inc|gmbh|plc)"
    for legal in legal_names:
        name = normalize_name(legal)
        if not name:
            continue
        if suffix_re.search(str(legal)):
            base = suffix_re.sub("", str(legal)).strip()
            base_words = normalize_name(base).split()
            if not base_words:
                continue
            base_pattern = r"[\W_]+".join(re.escape(word) for word in base_words)
            entity_pattern = r"(?<!\w)" + base_pattern + r"[\W_]+" + suffix_forms + r"(?!\w)"
            if re.search(entity_pattern, unicodedata.normalize("NFC", str(text)), re.IGNORECASE):
                return legal
            continue
        match = re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", normalized)
        if match:
            following = normalized[match.end():].split()
            sentence_continuations = {"announces", "announced", "opens", "opened", "reports", "reported",
                "update", "updates", "today", "now", "is", "has", "was", "will", "with", "for", "and",
                "partners", "launches", "launched", "welcomes", "published", "public", "website", "official"}
            if not following or following[0] in sentence_continuations:
                return legal
        if name == normalized:
            return legal
    return None


def _same_legal_name(left: Any, right: Any) -> bool:
    """Compare two entity names without accepting a longer, distinct legal name."""
    normalized_left, normalized_right = normalize_name(left), normalize_name(right)
    return bool(normalized_left and normalized_left == normalized_right)


_LEGAL_NAME_MENTION = re.compile(
    r"\b([A-ZÆØÅ][\wÆØÅæøå .&'’\-]{0,90}?\s+(?:AS|ASA|AB|Oy|Ltd|Limited|Inc|GmbH|PLC))\b",
    re.IGNORECASE)


def _mentions_exact_entity(names: set[str] | list[str], text: str) -> bool:
    """Find a named entity mention without matching a longer company name."""
    expected = [name for name in names if normalize_name(name)]
    mentions = [match.group(1).strip(" ,.;:") for match in _LEGAL_NAME_MENTION.finditer(text)]
    if mentions:
        return bool(mentions) and all(any(_same_legal_name(name, mention) for name in expected) for mention in mentions)
    folded = normalize_name(text)
    return any(re.search(r"(?<!\w)" + re.escape(normalize_name(name)) + r"(?!\w)", folded)
               for name in expected)


def _walk_schema_subjects(value: Any, path: tuple[str, ...] = ()) -> list[tuple[dict[str, Any], tuple[str, ...]]]:
    """Keep structured organization nodes with their relationship path."""
    found: list[tuple[dict[str, Any], tuple[str, ...]]] = []
    if isinstance(value, dict):
        kind = value.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if any(isinstance(item, str) and any(token in item.casefold() for token in
                ("organization", "corporation", "localbusiness")) for item in kinds):
            found.append((value, path))
        for key, child in value.items():
            found.extend(_walk_schema_subjects(child, (*path, str(key).casefold())))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_schema_subjects(child, path))
    return found


def _address_match(profile: dict[str, Any], text: str) -> dict[str, Any] | None:
    folded = normalize_name(text)
    address = profile.get("registered_address") or profile.get("business_address") or {}
    postal = profile.get("postal_address") or {}
    for item in (address, postal):
        if not isinstance(item, dict):
            continue
        postcode = str(item.get("postnummer") or item.get("postal_code") or "").strip()
        municipality = str(item.get("kommune") or item.get("poststed") or item.get("municipality") or "").strip()
        street_values = item.get("adresse") or item.get("address") or []
        if isinstance(street_values, str):
            street_values = [street_values]
        postcode_present = bool(postcode and re.search(rf"(?<!\d){re.escape(postcode)}(?!\d)", text))
        municipality_present = bool(municipality and normalize_name(municipality) in folded.split())
        street_present = any(normalize_name(street) and normalize_name(street) in folded for street in street_values if street)
        if postcode_present and municipality_present:
            return {"method": "exact_postcode_and_municipality", "postcode": postcode, "municipality": municipality}
        if street_present and postcode_present:
            return {"method": "exact_street_and_postcode", "postcode": postcode, "street": next(street for street in street_values if street and normalize_name(street) in folded)}
    return None


def _negative_subject_context(text: str, org: str) -> bool:
    lowered = unicodedata.normalize("NFC", text).casefold()
    # Interpret the identifier's local clause as a role reference. This is
    # combined with same-block name/id pairing and structured subject scope.
    negative_labels = ("customer", "client", "kunde", "partner", "supplier", "leverandør", "designer", "webmaster",
        "auditor", "revisor", "board member", "styremedlem", "procurement", "anskaffelse",
        "designed by", "design by", "website by", "site by", "web by", "developed by",
        "provided by", "powered by", "hosted by", "web developer", "web agency", "webbyrå",
        "webbureau", "website development", "website design", "leverandør av nettside")
    for match in re.finditer(r"(?<!\d)" + re.escape(org) + r"(?!\d)", text):
        context = lowered[max(0, match.start() - 90):match.end() + 50]
        if any(label in context for label in negative_labels):
            return True
    return False


def verify_site_pages(profile: dict[str, Any], pages: list[PageRecord], *, shared_domain: bool = False,
                      candidate_source: str = "registry_live") -> dict[str, Any]:
    """Apply the audited exact-site table; name-only and self-derived brand never pass."""
    org = str(profile.get("organisation_number") or "")
    legal_names = [str(profile.get("name") or ""), *[str(item.get("name") or "") for item in profile.get("historical_names", []) if isinstance(item, dict)]]
    legal_names = [name for name in legal_names if name]
    registered = {org}
    related = {str(item) for item in profile.get("related_organisation_numbers", []) if str(item).isdigit()}
    identity_pages: list[dict[str, Any]] = []
    for page in pages:
        if page.soft_error:
            continue
        subject_names: list[str] = []
        subject_ids: list[str] = []
        target_schema_names: list[str] = []
        conflict_schema: list[dict[str, str]] = []
        non_owner_relationships = {"customer", "client", "supplier", "partner", "about", "mentions",
            "author", "employee", "member", "sponsor", "designer", "provider", "founder",
            "parentorganization", "suborganization", "department", "affiliate", "employer",
            "hiringorganization"}
        schema_subjects = _walk_schema_subjects(page.structured.get("json-ld", []))
        known_nodes = {id(node) for node, _path in schema_subjects}
        schema_subjects.extend((node, ()) for node in page.schema_organizations if id(node) not in known_nodes)
        owner_subjects: list[dict[str, Any]] = []
        for node, path in schema_subjects:
            name = _as_text(node.get("legalName") or node.get("name"))
            ids = _identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID")) + _identifier_values(node.get("vatID"))
            ids = sorted(set(ids))
            nested_non_owner = any(key in non_owner_relationships for key in path)
            if name:
                subject_names.append(name)
            subject_ids.extend(ids)
            if not nested_non_owner:
                owner_subjects.append(node)
            if org in ids and name and not nested_non_owner:
                conflicting_ids = [identifier for identifier in ids if identifier != org]
                if conflicting_ids or not any(_same_legal_name(expected, name) for expected in legal_names):
                    conflict_schema.append({"name": name, "organisation_numbers": ids})
                    continue
                target_schema_names.append(name)
            elif ids and any(identifier not in related and identifier != org for identifier in ids) and name and not nested_non_owner:
                conflict_schema.append({"name": name, "organisation_numbers": ids})
        # A visible organization number and a name are a text proof only when
        # they occur in the same identity block. JSON-LD proof is handled above
        # with exact node scope; values from separate graph nodes never combine.
        paired_identity_blocks = [block for block in page.identity_blocks
            if re.search(r"(?<!\d)" + re.escape(org) + r"(?!\d)", block)
            and _exact_name(legal_names, block) and not _negative_subject_context(block, org)]
        target_context = bool(paired_identity_blocks)
        exact_name = next((_exact_name(legal_names, block) for block in paired_identity_blocks), None)
        safe_identity_text = " ".join([page.title, *(block for block in page.identity_blocks
            if not _negative_subject_context(block, org))])
        page_identity_name = _exact_name(legal_names, safe_identity_text)
        relevant_text = page.title + " " + page.identity_text + " " + page.visible_text[:15_000]
        address = _address_match(profile, relevant_text)
        role_match = next((str(role) for role in profile.get("registered_roles", []) if len(normalize_name(role)) > 5 and normalize_name(role) in normalize_name(relevant_text)), None)
        has_contact_endpoint = bool(re.search(rb"(?i)(?:mailto:|tel:)", page.body))
        contact_page = _kind(page.final_url, page.title) == "contact"
        contact_signal = has_contact_endpoint and contact_page
        material_conflict = bool(conflict_schema)
        if material_conflict:
            continue
        final_parts = urllib.parse.urlsplit(page.final_url)
        homepage = final_parts.path in {"", "/"} and not final_parts.query
        # Footer mentions do not establish ownership when a page represents
        # another entity or lists several entities. Target-specific pages may
        # still pass when title/headings and paired legal identity identify it.
        visible_identity = " ".join([page.title, *page.headings, *page.identity_blocks, *page.footer_blocks])
        visible_orgs = set(re.findall(r"(?<!\d)\d{9}(?!\d)", visible_identity))
        foreign_orgs = visible_orgs - {org} - related
        target_named_in_heading = bool(_exact_name(legal_names, " ".join([page.title, *page.headings])))
        if target_context and (foreign_orgs and (homepage or not target_named_in_heading)
                               or homepage and visible_orgs - {org}):
            continue
        incompatible_legal_subjects = [node for node in owner_subjects
            if _as_text(node.get("legalName") or node.get("name"))
            and not any(_same_legal_name(expected, _as_text(node.get("legalName") or node.get("name"))) for expected in legal_names)
            and org not in (_identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID")) + _identifier_values(node.get("vatID")))]
        legal_form_marker = re.compile(r"(?i)\b(?:AS|ASA|NUF|ENK|DA|ANS|BA)\b")
        visible_identity_blocks = [page.title, *page.headings, *page.identity_blocks]
        conflicting_visible_identity = any(legal_form_marker.search(block)
            and not _exact_name(legal_names, block) for block in visible_identity_blocks if block)
        if target_context and conflicting_visible_identity:
            continue
        if homepage and conflicting_visible_identity:
            continue
        if homepage and incompatible_legal_subjects:
            # A group/brand root with another structured legal subject cannot
            # be adopted from an incidental footer mention of the subsidiary.
            continue
        compatible_target_subject = next((name for name in target_schema_names
            if any(_same_legal_name(expected, name) for expected in legal_names)), None)
        if compatible_target_subject:
            identity_pages.append({"page": page, "method": "subject_scoped_structured_org_number", "name": compatible_target_subject, "address": address, "subject_ids": sorted(set(subject_ids))})
        elif target_context and exact_name:
            identity_pages.append({"page": page, "method": "subject_scoped_legal_org_number", "name": exact_name, "address": address, "subject_ids": sorted(set(subject_ids))})
        elif page_identity_name and address and candidate_source != "keyless_no":
            identity_pages.append({"page": page, "method": "exact_legal_name_and_registered_address", "name": page_identity_name, "address": address, "subject_ids": sorted(set(subject_ids))})
        elif page_identity_name and address and (role_match or (candidate_source == "keyless_no" and contact_signal)):
            method = "legal_name_address_registered_role" if role_match else "legal_name_address_official_contact"
            proof_row = {"page": page, "method": method, "name": page_identity_name, "address": address,
                         "subject_ids": sorted(set(subject_ids))}
            if role_match:
                proof_row["registered_role"] = role_match
            else:
                proof_row["additional_signal"] = "official_contact_endpoint"
            identity_pages.append(proof_row)
        if conflict_schema and not target_context and not any(item["page"] is page for item in identity_pages):
            continue
    if not identity_pages:
        # Distinguish a conflicting site identity from a merely weak/no-name candidate.
        for page in pages:
            if page.soft_error:
                continue
            blocks = [page.identity_text, page.title]
            other = [node for node in page.schema_organizations if _as_text(node.get("legalName") or node.get("name"))]
            if other and not any(org in (_identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID")) + _identifier_values(node.get("vatID"))) for node in other):
                names = [_as_text(node.get("legalName") or node.get("name")) for node in other]
                competing_ids = [identifier for node in other for identifier in (_identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID")) + _identifier_values(node.get("vatID")))]
                if names and competing_ids and all(identifier not in related and identifier != org for identifier in competing_ids):
                    return {"decision": "rejected", "reason": "conflicting_structured_company_identity", "proof": None, "target_page": None}
            text = " ".join(blocks)
            if text and any(re.search(r"\b" + re.escape(name) + r"\b", text, re.I) for name in legal_names if len(name) > 4):
                return {"decision": "ambiguous", "reason": "name_only_or_missing_address_and_subject_scoped_id", "proof": None, "target_page": None}
        return {"decision": "ambiguous", "reason": "insufficient_exact_company_identity_evidence", "proof": None, "target_page": None}
    selected = sorted(identity_pages, key=lambda row: (0 if row["method"].startswith("subject_scoped") else 1, row["page"].requested_url))[0]
    page = selected["page"]
    parsed_target = urllib.parse.urlsplit(page.final_url)
    is_homepage = parsed_target.path in {"", "/"} and not parsed_target.query
    if shared_domain and is_homepage:
        # A group homepage never becomes a subsidiary homepage solely from a brand or name mention.
        if selected["method"] not in {"subject_scoped_structured_org_number", "subject_scoped_legal_org_number"}:
            return {"decision": "ambiguous", "reason": "shared_group_homepage_without_target_subject_proof", "proof": None, "target_page": None}
    proof = {
        "rule_id": "audited_exact_site_identity_v1", "method": selected["method"],
        "organisation_number": org, "compatible_legal_name": selected["name"],
        "page_url": page.final_url, "page_sha256": page.digest,
        "json_ld_subject_match": selected["method"] == "subject_scoped_structured_org_number",
        "registered_address_match": selected.get("address"), "shared_domain": shared_domain,
        "conflicting_subject_ids": sorted(identifier for identifier in selected.get("subject_ids", []) if identifier != org and identifier not in related),
    }
    return {"decision": "accepted", "reason": None, "proof": proof, "target_page": page.final_url, "proof_page": page}


def _kind(url: str, text: str = "") -> str:
    value = (urllib.parse.urlsplit(url).path + " " + text).casefold()
    for kind, tokens in POSITIVE_PATHS.items():
        if any(token in value for token in tokens):
            return kind
    return "other"


def _link_rank(item: dict[str, str]) -> tuple[int, int, str]:
    path = urllib.parse.urlsplit(item["url"]).path.casefold()
    if any(token in path for token in NEGATIVE_PATHS):
        return (9, 9, item["url"])
    kind = _kind(item["url"], item.get("text", ""))
    rank = {"legal": 0, "about": 1, "contact": 2, "locations": 3, "careers": 4,
            "news": 5, "products": 6, "other": 8}.get(kind, 8)
    return rank, 0, item["url"]


def _internal_hosts(candidate_url: str) -> set[str]:
    host = urllib.parse.urlsplit(candidate_url).hostname or ""
    result = {host.casefold()}
    if host.casefold().startswith("www."):
        result.add(host[4:].casefold())
    else:
        result.add("www." + host.casefold())
    return result


def _internal_url(url: str, allowed_hosts: set[str]) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme in {"http", "https"} and (parsed.hostname or "").casefold() in allowed_hosts


def _profile_links(page: PageRecord, target_org: str | None = None) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}
    for link in page.links:
        parsed = urllib.parse.urlsplit(link["url"])
        host = (parsed.hostname or "").casefold().removeprefix("www.")
        platform = _host_social(host)
        if not platform:
            continue
        path = [part for part in parsed.path.split("/") if part]
        if not path or path[0].casefold() in {"share", "sharer", "intent", "search", "explore", "privacy", "events", "plugins"}:
            continue
        if platform == "linkedin" and (path[0].casefold() != "company" or len(path) < 2):
            continue
        if platform == "youtube" and path[0].casefold() not in {"channel", "user", "c"} and not path[0].startswith("@"):
            continue
        canonical_host = {"linkedin": "linkedin.com", "facebook": "facebook.com", "instagram": "instagram.com",
                          "x": "x.com", "youtube": "youtube.com", "tiktok": "tiktok.com"}.get(platform, "")
        normalized = f"https://{canonical_host}/{'/'.join(path[:2] if platform in { 'linkedin', 'youtube'} else path[:1])}"
        if normalized:
            found[(platform, normalized)] = {"platform": platform, "url": normalized}
    for node in page.schema_organizations:
        ids = _identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID")) + _identifier_values(node.get("vatID"))
        if target_org and target_org not in ids:
            continue
        same_as = node.get("sameAs")
        for url in same_as if isinstance(same_as, list) else [same_as]:
            if not isinstance(url, str):
                continue
            parsed = urllib.parse.urlsplit(url)
            platform = _host_social(parsed.hostname or "")
            if platform:
                found[(platform, url)] = {"platform": platform, "url": url}
    return sorted(found.values(), key=lambda item: (item["platform"], item["url"]))


def _page_key(page: PageRecord) -> str:
    return hashlib.sha256((page.final_url + "\0" + page.digest).encode()).hexdigest()[:16]


def _proof_key(assessment: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(assessment["proof"], sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode()).hexdigest()


def _public_evidence(page: PageRecord, snapshots: list[SourceSnapshot], evidence: list[Evidence], *,
                     org: str, excerpt: str | None = None, locator: str | None = None) -> str:
    page_key = _page_key(page)
    source_id = f"website:{page_key}"
    observation_excerpt = (_canonical_heading_key(excerpt) if excerpt is not None
        and locator == "/html/body//h1|h2|h3" else excerpt)
    observation_identity = json.dumps({"locator": locator or page.locator, "excerpt": observation_excerpt},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    observation_key = hashlib.sha256(observation_identity.encode()).hexdigest()[:24]
    # Content identity may be shared; subject-bound evidence identity may not.
    evidence_id = f"website-page:{org}:{page_key}:{observation_key}"
    if not any(item.source_id == source_id for item in snapshots):
        snapshots.append(SourceSnapshot(source_id=source_id, source_url=page.final_url, retrieved_at=page.retrieved_at,
            content_sha256=page.digest, http_status=page.status, cache_mode="transient", rights_status=page.rights_status))
    if not any(item.evidence_id == evidence_id for item in evidence):
        evidence.append(Evidence(evidence_id=evidence_id, source_url=page.final_url, retrieved_at=page.retrieved_at,
            content_sha256=page.digest, extraction_method=("website_feed_extract_v1" if "xml" in page.content_type.casefold() or "rss" in page.content_type.casefold() or "atom" in page.content_type.casefold() else "website_html_extract_v1"), json_pointer=locator or page.locator,
            excerpt=(excerpt[:500] if excerpt else None), source_class="public_web",
            subject_organisation_number=org, source_snapshot_ids=[source_id]))
    return evidence_id


def _make_claim(org: str, field: str, value: Any, page: PageRecord, evidence_id: str, scope: str = "legal_entity", *,
                evidence_ids: list[str] | None = None, proof_source: str | None = None,
                proof_evidence: str | None = None,
                evidence_source_snapshot_ids: list[str] | None = None) -> Claim:
    eids = list(evidence_ids or [evidence_id])
    if proof_evidence and proof_evidence not in eids:
        eids.append(proof_evidence)
    page_key = _page_key(page)
    value_key = website_claim_value_digest(field, value)
    return Claim(claim_id=f"{org}:web:{field}:{page_key[:12]}:{value_key}", organisation_number=org,
        section="website_owned_profiles", field_family="owned_web", subject_id=org, field=field,
        value=value, state=PublicState.AVAILABLE, scope=scope,
        verification_rule_id="audited_exact_site_identity_v1", verification_score="1.0",
        evidence_ids=eids, source_snapshot_ids=list(dict.fromkeys(
            [f"website:{page_key}"] + ([proof_source] if proof_source else [])
            + list(evidence_source_snapshot_ids or []))))


async def _fetch(gateway: NetworkGateway, url: str, *, purpose: str, allowed_hosts: set[str], cap: int) -> tuple[int, dict[str, str], bytes, str, str]:
    return await gateway.fetch(url, purpose=purpose, user_agent=UA, max_bytes=cap, allowed_hosts=allowed_hosts)


def _parse_sitemap(body: bytes) -> tuple[list[str], list[str]]:
    try:
        root = ET.fromstring(body[:MAX_PAGE_BYTES])
    except (ET.ParseError, ValueError):
        return [], []
    urls: list[str] = []
    indexes: list[str] = []
    kind = root.tag.rsplit("}", 1)[-1].casefold()
    for node in list(root)[:MAX_SITEMAP_URLS]:
        loc = next((child.text for child in list(node) if child.tag.rsplit("}", 1)[-1].casefold() == "loc"), None)
        if not loc:
            continue
        (indexes if kind == "sitemapindex" else urls).append(loc.strip())
    return urls, indexes


def _parse_feed(body: bytes) -> list[dict[str, str]]:
    """Parse bounded RSS/Atom entries retaining only explicit source fields."""
    try:
        root = ET.fromstring(body[:MAX_PAGE_BYTES])
    except (ET.ParseError, ValueError):
        return []
    entries: list[dict[str, str]] = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1].casefold() not in {"item", "entry"}:
            continue
        row: dict[str, str] = {}
        for node in list(item):
            tag = node.tag.rsplit("}", 1)[-1].casefold()
            value = (node.text or "").strip()
            if tag == "link":
                value = node.attrib.get("href") or value
                if node.attrib.get("rel", "alternate").casefold() not in {"alternate", ""}:
                    continue
                row.setdefault("url", value)
            elif tag in {"guid", "id"} and value.startswith(("http://", "https://")):
                row.setdefault("url", value)
            elif tag in {"title", "published", "updated", "pubdate", "date", "summary", "description", "category"} and value:
                row.setdefault({"pubdate": "published", "date": "published"}.get(tag, tag), value)
        if row.get("url"):
            entries.append(row)
    unique: dict[str, dict[str, str]] = {}
    for row in entries:
        unique.setdefault(row["url"], row)
    return list(unique.values())[:MAX_SITEMAP_URLS]


def _date_value(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw.strip())
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_date_value(parsed: datetime, raw: str) -> dict[str, str]:
    precision = "second" if re.search(r"[T ]\d{2}:\d{2}:\d{2}", raw) else ("minute" if re.search(r"[T ]\d{2}:\d{2}", raw) else "day")
    return {"source_value": raw, "normalized_utc": parsed.isoformat(), "precision": precision}


def _contains_direct_contact_or_identifier(value: str) -> bool:
    return bool(re.search(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b|(?<!\d)(?:\+47\s?)?\d{8}(?!\d)|(?<!\d)\d{11}(?!\d)", value))


def _schema_nodes(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        kind = value.get("@type")
        kinds = [kind] if isinstance(kind, str) else (kind if isinstance(kind, list) else [])
        if any(str(item).casefold() in {"jobposting", "newsarticle", "article", "blogposting"} for item in kinds):
            found.append(value)
        for child in value.values():
            found.extend(_schema_nodes(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_schema_nodes(child))
    return found


def _schema_text(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("name") or value.get("@id")
    if isinstance(value, list):
        value = next((_schema_text(item) for item in value if _schema_text(item)), None)
    if isinstance(value, str):
        cleaned = " ".join(value.split())
        return cleaned[:500] if cleaned else None
    return None


def _same_host_url(value: Any, page_url: str) -> str | None:
    raw = _schema_text(value)
    if not raw:
        return None
    url = urllib.parse.urljoin(page_url, raw)
    return url if _internal_url(url, _internal_hosts(page_url)) else None


def _employer_matches(value: Any, org: str, verified_names: set[str]) -> bool:
    """Require explicit target-employer evidence on each JobPosting."""
    if not isinstance(value, dict):
        return False
    identifiers = (_identifier_values(value.get("identifier"))
                   + _identifier_values(value.get("taxID")))
    name = _schema_text(value.get("legalName") or value.get("name"))
    name_matches = bool(name and any(_same_legal_name(expected, name) for expected in verified_names if expected))
    if identifiers:
        return org in identifiers and all(item == org for item in identifiers) and (not name or name_matches)
    return name_matches


def _article_subject_matches(node: dict[str, Any], title: str, org: str,
                             verified_names: set[str]) -> bool:
    """Do not infer an article's subject from the host site's ownership."""
    subjects = node.get("about") or node.get("mainEntity")
    if subjects is not None:
        rows = subjects if isinstance(subjects, list) else [subjects]
        target_found = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            identifiers = (_identifier_values(row.get("identifier"))
                           + _identifier_values(row.get("taxID")))
            name = _schema_text(row.get("legalName") or row.get("name"))
            if identifiers:
                if org in identifiers and (not name or _employer_matches({"identifier": org, "name": name}, org, verified_names)):
                    target_found = True
                else:
                    # A second identified organisation makes the article multi-entity.
                    return False
            elif name:
                if any(_same_legal_name(expected, name) for expected in verified_names if expected):
                    target_found = True
                elif re.search(r"(?i)\b(?:AS|ASA|AB|Oy|Ltd|Limited|Inc|GmbH|PLC)\b", name):
                    return False
        return target_found
    # Older company newsroom markup often omits about/mainEntity. Retain only
    # headlines that explicitly name the exact legal entity or verified brand.
    if not _mentions_exact_entity(verified_names, title):
        return False
    # Headline-only evidence cannot disambiguate a second legal entity.
    company_mentions = re.findall(r"\b([A-ZÆØÅ][\wÆØÅæøå .&'’-]{1,80}?\s(?:AS|ASA|AB|Oy|Ltd|Limited|Inc|GmbH|PLC))\b", title)
    return all(any(normalize_name(expected) == normalize_name(mention) for expected in verified_names if expected)
               for mention in company_mentions)


def _approved_ats_hosts() -> set[str]:
    policy_path = Path(__file__).resolve().parent.parent / "config" / "jobs_source_policy.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(host).casefold().strip(".") for host in policy.get("approved_ats_hosts", []) if host}


def _make_footprint_claim(org: str, field: str, value: Any, subject: str, scope: str,
                          page: PageRecord, evidence_id: str, proof_source: str, proof_evidence: str,
                          as_of: datetime | None = None) -> Claim:
    key = hashlib.sha256((subject + "\0" + field).encode()).hexdigest()[:16]
    return Claim(claim_id=f"{org}:footprint:{key}", organisation_number=org, section="hiring_activity",
        field_family="jobs" if scope == "job" else "public_activity", subject_id=subject, field=field,
        value=value, state=PublicState.AVAILABLE, scope=scope, as_of=as_of,
        verification_rule_id="exact_company_owned_site_source_v1", verification_score="1.0",
        evidence_ids=[evidence_id, proof_evidence], source_snapshot_ids=[f"website:{_page_key(page)}", proof_source])


def _job_location(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, dict):
        return _schema_text(value)
    address = value.get("address") if isinstance(value.get("address"), dict) else value
    parts = [address.get(key) for key in ("addressLocality", "addressRegion", "addressCountry")]
    parts = [str(part.get("name") if isinstance(part, dict) else part).strip() for part in parts if part]
    return ", ".join(dict.fromkeys(part for part in parts if part))[:300] or None


def _page_footprints(page: PageRecord, *, org: str, legal_name: str, verified_names: set[str],
                     cutoff: datetime, lookback_days: int = 365) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Extract conservative same-site job and dated activity observations."""
    jobs: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []
    counts = {"job_candidates": 0, "job_identity_rejected": 0, "job_future": 0, "activity_candidates": 0,
              "activity_undated": 0, "activity_future": 0, "activity_outside_window": 0}
    for node in _schema_nodes(page.structured):
        kinds = node.get("@type")
        kinds = [kinds] if isinstance(kinds, str) else (kinds or [])
        if any(str(kind).casefold() == "jobposting" for kind in kinds):
            counts["job_candidates"] += 1
            employer = node.get("hiringOrganization")
            employer_rows = employer if isinstance(employer, list) else [employer]
            if not employer_rows or not all(_employer_matches(row, org, verified_names) for row in employer_rows):
                counts["job_identity_rejected"] += 1
                continue
            title = _schema_text(node.get("title"))
            url = _same_host_url(node.get("url") or node.get("sameAs") or page.final_url, page.final_url)
            if not title or not url:
                continue
            posted = _date_value(node.get("datePosted"))
            deadline = _date_value(node.get("validThrough"))
            if _contains_direct_contact_or_identifier(title) or (posted and posted > cutoff):
                counts["job_future"] += int(bool(posted and posted > cutoff))
                continue
            status_raw = _schema_text(node.get("jobStatus") or node.get("employmentStatus"))
            status = status_raw
            if deadline and deadline < cutoff:
                status = "closed"
            elif deadline and deadline >= cutoff:
                status = "open"
            elif status_raw:
                status = status_raw
            job = {"title": title, "url": url, "location": _job_location(node.get("jobLocation")),
                   "employment_type": _schema_text(node.get("employmentType")), "posting_date": posted,
                   "posting_date_raw": node.get("datePosted"), "deadline": deadline,
                   "deadline_raw": node.get("validThrough"), "status": status}
            fingerprint = hashlib.sha256(json.dumps([org, title.casefold(), job["location"], url],
                ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:24]
            job["subject"] = f"{org}:job:{fingerprint}"
            job["locator"] = "/structured_data/JobPosting"
            jobs.append(job)
        if any(str(kind).casefold() in {"newsarticle", "article", "blogposting"} for kind in kinds):
            counts["activity_candidates"] += 1
            title = _schema_text(node.get("headline") or node.get("name"))
            url = _same_host_url(node.get("url") or node.get("mainEntityOfPage") or page.final_url, page.final_url)
            raw_date = node.get("datePublished")
            published = _date_value(raw_date)
            if not title or not url:
                continue
            if not _article_subject_matches(node, title, org, verified_names):
                counts["activity_subject_rejected"] = counts.get("activity_subject_rejected", 0) + 1
                continue
            activity = _activity_record(org, title, url, published, _schema_text(node.get("description")),
                                        _schema_text(node.get("articleSection")), cutoff, lookback_days, counts, raw_date)
            if activity:
                activity["locator"] = "/structured_data/NewsArticle"
                activities.append(activity)
    # Visible fallback is limited to explicitly marked JobPosting containers on this verified origin.
    soup = BeautifulSoup(page.body.decode("utf-8", "replace"), "lxml")
    for index, card in enumerate(soup.select('[itemtype*="JobPosting"], article[data-job-posting]')):
        title_node = card.select_one('[itemprop="title"],h1,h2,h3')
        link = card.select_one('a[href]')
        title = " ".join(title_node.get_text(" ", strip=True).split())[:300] if title_node else ""
        url = _same_host_url(link.get("href") if link else None, page.final_url)
        if not title or not url or _contains_direct_contact_or_identifier(title):
            continue
        employer_node = card.select_one('[itemprop="hiringOrganization"]')
        employer_name_node = (employer_node.select_one('[itemprop="legalName"], [itemprop="name"]')
                              if employer_node else None)
        employer_name = (employer_name_node.get("content") or employer_name_node.get_text(" ", strip=True)
                         if employer_name_node else employer_node.get("content") if employer_node else None)
        employer_id_node = employer_node.select_one('[itemprop="identifier"], [itemprop="taxID"]') if employer_node else None
        employer_id = (employer_id_node.get("content") or employer_id_node.get_text(" ", strip=True)
                       if employer_id_node else None)
        employer_row = {"name": employer_name, "identifier": employer_id}
        if not employer_node or not _employer_matches(employer_row, org, verified_names):
            counts["job_identity_rejected"] += 1
            continue
        def itemprop(*names: str) -> str | None:
            node = next((card.select_one(f'[itemprop="{name}"]') for name in names if card.select_one(f'[itemprop="{name}"]')), None)
            return str(node.get("content") or node.get("datetime") or node.get("data-value") or node.get_text(" ", strip=True)).strip() if node else None
        posted = _date_value(itemprop("datePosted"))
        deadline = _date_value(itemprop("validThrough"))
        if posted and posted > cutoff:
            counts["job_future"] += 1
            continue
        location_node = card.select_one('[itemprop="jobLocation"]')
        location = None
        if location_node:
            location_parts = []
            for prop in ("addressLocality", "addressRegion", "addressCountry"):
                prop_node = location_node.select_one(f'[itemprop="{prop}"]')
                if prop_node:
                    location_parts.append(str(prop_node.get("content") or prop_node.get_text(" ", strip=True)))
            location = ", ".join(dict.fromkeys(part.strip() for part in location_parts if part.strip()))[:300] or None
        employment = itemprop("employmentType")
        status = itemprop("jobStatus") or ("closed" if deadline and deadline < cutoff else None)
        fingerprint = hashlib.sha256(json.dumps([org, title.casefold(), location, url],
            ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:24]
        jobs.append({"subject": f"{org}:job:{fingerprint}", "title": title, "url": url, "location": location,
            "employment_type": employment, "posting_date": posted,
            "posting_date_raw": itemprop("datePosted"), "deadline": deadline,
            "deadline_raw": itemprop("validThrough"), "status": status,
            "locator": f"/html/body//JobPosting[{index + 1}]"})
    # Explicit article publication time only; no retrieval or sitemap date fallback.
    article_nodes = soup.select('article, [itemprop="articleBody"]')
    for index, article in enumerate(article_nodes):
        title_node = article.select_one("h1,h2,h3")
        title = " ".join(title_node.get_text(" ", strip=True).split())[:300] if title_node else ""
        date_node = article.select_one('time[datetime], [itemprop="datePublished"]')
        raw_date = (date_node.get("datetime") or date_node.get("content") or date_node.get_text(" ", strip=True)) if date_node else None
        published = _date_value(raw_date)
        if not title or not published or _contains_direct_contact_or_identifier(title):
            if title:
                counts["activity_undated"] += 1
            continue
        if not _mentions_exact_entity(verified_names, title):
            counts["activity_subject_rejected"] = counts.get("activity_subject_rejected", 0) + 1
            continue
        summary = " ".join(article.get_text(" ", strip=True).split())[:1200]
        activity = _activity_record(org, title, page.final_url, published, summary, None, cutoff, lookback_days, counts, raw_date)
        if activity:
            activity["locator"] = f"/html/body//article[{index + 1}]"
            activities.append(activity)
    return _dedupe_jobs(jobs), _dedupe_activities(activities), counts


def _activity_record(org: str, title: str, url: str, published: datetime | None, summary: str | None,
                     event_type: str | None, cutoff: datetime, lookback_days: int, counts: dict[str, int],
                     source_date: str | None = None) -> dict[str, Any] | None:
    if not published:
        counts["activity_undated"] += 1
        return None
    if published > cutoff:
        counts["activity_future"] += 1
        return None
    if published < cutoff - timedelta(days=lookback_days):
        counts["activity_outside_window"] += 1
        return None
    # Summaries are extractive and omit email addresses, phone numbers, and national identifiers.
    safe_summary = " ".join((summary or "").split())[:500]
    if _contains_direct_contact_or_identifier(safe_summary):
        safe_summary = ""
    fingerprint = hashlib.sha256(json.dumps([org, title.casefold(), published.date().isoformat()],
        ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:24]
    return {"subject": f"{org}:event:{fingerprint}", "title": title, "url": url,
            "published": published, "published_raw": source_date or published.date().isoformat(),
            "summary": safe_summary or None, "event_type": event_type or "company_announcement"}


def _dedupe_jobs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        unique.setdefault(row["subject"], row)
    return list(unique.values())


def _dedupe_activities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        unique.setdefault(row["subject"], row)
    return list(unique.values())


def _source_evidence(candidate: dict[str, Any], evidence: list[Evidence], snapshots: list[SourceSnapshot], org: str) -> str | None:
    digest = candidate.get("content_sha256")
    url = candidate.get("source_url")
    rights_status = candidate.get("rights_status") or ("NLOD-2.0" if candidate.get("source") == "registry_live" else None)
    if not digest or not url or not rights_status:
        return None
    evidence_id = candidate.get("evidence_id") or f"registry-site-candidate:{digest[:16]}"
    source_id = candidate.get("source_snapshot_id") or f"brreg:entity:{digest[:16]}"
    extraction_method = ("frozen_registry_jsonl_v1" if candidate.get("source") == "registry_frozen"
                         else "brreg_website_candidate_v1")
    if not any(item.evidence_id == evidence_id for item in evidence):
        evidence.append(Evidence(evidence_id=evidence_id, source_url=url, retrieved_at=datetime.now(timezone.utc),
            content_sha256=digest, extraction_method=extraction_method, json_pointer="/hjemmeside", source_class="official",
            subject_organisation_number=org, source_snapshot_ids=[source_id]))
    if not any(item.source_id == source_id for item in snapshots):
        snapshots.append(SourceSnapshot(source_id=source_id, source_url=url, retrieved_at=datetime.now(timezone.utc),
            content_sha256=candidate.get("source_snapshot_sha256") or digest, cache_mode="transient", rights_status=rights_status))
    return evidence_id


def _additional_evidence_snapshot_ids(evidence: list[Evidence], evidence_ids: list[str]) -> list[str]:
    """Return ordered, unique snapshot IDs required by extra claim evidence."""
    wanted = set(evidence_ids)
    return list(dict.fromkeys(snapshot_id for item in evidence if item.evidence_id in wanted
                              for snapshot_id in item.source_snapshot_ids))


def _assess_candidate(profile: dict[str, Any], pages: list[PageRecord], candidate: dict[str, Any],
                      *, shared_domain: bool) -> dict[str, Any]:
    assessment = verify_site_pages(profile, pages, shared_domain=shared_domain,
                                   candidate_source=str(candidate.get("source") or "registry_live"))
    if candidate.get("source") == "search_provider" and assessment.get("decision") == "accepted":
        proof_page = assessment["proof_page"]
        parsed = urllib.parse.urlsplit(proof_page.final_url)
        host = registered_domain(parsed.hostname or "") or (parsed.hostname or "")
        path_segments = {part.casefold() for part in parsed.path.split("/") if part}
        page_markers = (proof_page.title + " " + proof_page.description).casefold()
        directory_page = (
            host in THIRD_PARTY_DIRECTORY_ROOTS
            or bool(path_segments & THIRD_PARTY_DIRECTORY_PATHS)
            or any(marker in page_markers for marker in ("business directory", "company directory", "business listing", "company listing", "company profile", "customer reviews"))
        )
        if directory_page:
            return {"decision": "ambiguous", "reason": "search_candidate_is_directory_or_third_party_profile"}
        if assessment.get("proof", {}).get("method") != "subject_scoped_structured_org_number":
            return {"decision": "ambiguous", "reason": "search_candidate_requires_subject_scoped_org_proof"}
    return assessment


async def research_company(profile: dict[str, Any], gateway: NetworkGateway, *, shared_domains: set[str] | None = None,
                           enable_keyless: bool = True, evidence_cutoff: datetime | None = None,
                           phase: str = "all", previous: WebsiteResearchResult | None = None,
                           rights_decisions: dict[str, str] | None = None) -> WebsiteResearchResult:
    """Fetch, verify, then shallowly research one target using the central gateway."""
    org = str(profile.get("organisation_number") or "")
    output = previous if previous is not None else WebsiteResearchResult()
    cutoff = evidence_cutoff or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    if previous is None:
        source_candidates = list(profile.get("website_candidates") or [])
        # Search adapters may add URL candidates here. Their titles/snippets are
        # never accepted by this path, and their provenance stays in the audit.
        source_candidates.extend(profile.get("discovery_candidates") or [])
        candidates: list[dict[str, Any]] = []
        for item in source_candidates:
            raw = item.get("raw") if isinstance(item, dict) else item
            source = item.get("source", "registry_frozen") if isinstance(item, dict) else "registry_frozen"
            source_ref = item if isinstance(item, dict) else {"raw": raw, "source": source}
            for sanitized in sanitize_registry_websites(raw):
                candidates.append({**sanitized, "source": source, "source_ref": source_ref,
                    "discovery": source_ref.get("discovery") if isinstance(source_ref, dict) else None})
        if not any(item["kind"] == "website" for item in candidates) and enable_keyless:
            guessed = keyless_no_candidate(str(profile.get("name") or ""))
            if guessed:
                candidates.append({"url": guessed, "kind": "website", "source": "keyless_no", "source_ref": {}})
        output.audit = {"organisation_number": org, "candidate_count": len(candidates), "candidates": [],
            "accepted_domains": [], "page_count": 0, "page_requests": 0, "pages": [], "request_count_scope": "batch_gateway_metrics", "request_outcomes": {},
            "crawl_state": "not_started", "website_claim_families": [], "high_risk_review": [],
            "jobs": {"candidates": 0, "published": 0, "explicit_zero": False},
            "activity": {"candidates": 0, "published": 0, "undated": 0, "future": 0, "outside_window": 0, "deduplicated": 0},
            "ats_origins": []}
        started = time.monotonic()
        page_total_bytes = 0
        page_limit = 0
        website_page_requests = 0
        accepted_pages: list[tuple[dict[str, Any], list[PageRecord], dict[str, Any], float | None]] = []
        feed_observations: list[tuple[str, PageRecord, list[dict[str, str]]]] = []
        unresolved = False
        saw_blocked = False
        saw_failure = False
        saw_candidate = False
        saw_robots_disallowed = False
        saw_robots_unreachable = False
        saw_policy_skip = False
        saw_budget_skip = False
        profiles = [item for item in candidates if item["kind"] == "profile"]
        for candidate in profiles:
            # Registry social URLs are candidates only. M03 promotes profiles solely
            # when linked from a page on a domain that passed exact-site verification.
            output.audit["candidates"].append({"url": candidate["url"], "source": candidate["source"], "kind": "profile", "decision": "candidate_only"})
        for candidate in (item for item in candidates if item["kind"] == "website"):
            saw_candidate = True
            if page_limit >= MAX_ABSOLUTE_PAGES:
                output.audit["candidates"].append({"url": candidate["url"], "source": candidate["source"], "decision": "budget_skipped"})
                saw_budget_skip = True
                continue
            page_limit += 1
            url = candidate["url"]
            parsed = urllib.parse.urlsplit(url)
            host = parsed.hostname or ""
            root_domain = registered_domain(host) or host
            configured_values = [(rights_decisions or {}).get(host), (rights_decisions or {}).get(root_domain)]
            configured_rights = next((value for value in configured_values if value is not None), None)
            source_rights = candidate.get("source_rights_status", "unknown_not_reviewed")
            if source_rights not in {"allowed", "blocked", "unknown_not_reviewed"}:
                source_rights = "unknown_not_reviewed"
            rights_status = ("blocked" if "blocked" in set(configured_values + [source_rights])
                else configured_rights or source_rights)
            if rights_status not in {"allowed", "blocked", "unknown_not_reviewed"}:
                raise ValueError("website rights decisions must be allowed, blocked, or unknown_not_reviewed")
            candidate["rights_status"] = rights_status
            if rights_status == "blocked":
                output.audit["candidates"].append({"url": candidate["url"], "source": candidate["source"],
                    "kind": "website", "rights_status": rights_status, "decision": "blocked_source_rights"})
                saw_blocked = True
                continue
            shared = root_domain in (shared_domains or set())
            allowed_hosts = _internal_hosts(url)
            gateway.set_rate_limit(host, 1.0)
            robots_error = None
            try:
                state, delay = await gateway.robots_decision(url, UA, allowed_hosts=allowed_hosts)
            except NetworkPolicyError as exc:
                # DNS failure is an unreachable candidate, not a robots disallow.
                # Other preflight rejections stay distinct as policy failures.
                robots_error = str(exc)[:180]
                state, delay = ("unreachable" if "did not resolve" in robots_error else "policy_skip"), None
            candidate_row: dict[str, Any] = {"url": url, "source": candidate["source"], "kind": "website", "registered_domain": root_domain,
                "robots_state": state, "crawl_delay_seconds": delay, "rights_status": rights_status, "decision": "candidate"}
            if candidate.get("discovery"):
                candidate_row["discovery"] = {key: candidate["discovery"].get(key) for key in
                    ("provider_id", "provider_version", "query_id", "result_id", "rank", "response_sha256")}
            if robots_error:
                candidate_row["robots_error"] = robots_error
            output.audit["candidates"].append(candidate_row)
            source_ref = candidate["source_ref"]
            source_id = _source_evidence(source_ref, output.evidence, output.snapshots, org) if source_ref.get("source") else None
            if state == "disallowed":
                candidate_row["decision"] = "blocked_robots"
                saw_robots_disallowed = True
                continue
            if state == "budget_skipped":
                candidate_row["decision"] = "budget_skipped"
                saw_budget_skip = True
                continue
            if state != "allowed":
                candidate_row["decision"] = "robots_unreachable" if state == "unreachable" else "robots_unusable" if state == "unusable" else "candidate_policy_rejected"
                error_code = "ROBOTS_UNREACHABLE" if state == "unreachable" else "ROBOTS_UNUSABLE" if state == "unusable" else "WEBSITE_POLICY_REJECTED"
                message = ("Website origin was skipped because robots.txt could not be retrieved." if state == "unreachable"
                           else "Website origin was skipped because its robots response could not be used." if state == "unusable"
                           else "Website candidate was rejected by gateway host policy.")
                output.errors.append(RunError(code=error_code, message=message))
                if state == "unreachable":
                    saw_robots_unreachable = True
                else:
                    saw_policy_skip = True
                continue
            pages: list[PageRecord] = []
            page_queue = [(url, 0, "homepage")]
            seen_urls: set[str] = set()
            seen_hashes: set[str] = set()
            discovery_links: list[dict[str, str]] = []
            site_start_bytes = page_total_bytes
            # The candidate homepage and up to three identity pages can establish proof.
            while page_queue and website_page_requests < MAX_DEFAULT_PAGES and page_limit < MAX_ABSOLUTE_PAGES:
                page_url, depth, purpose = page_queue.pop(0)
                normalized = _clean_url(page_url)
                if not normalized or normalized in seen_urls or not _internal_url(normalized, allowed_hosts):
                    continue
                if any(token in urllib.parse.urlsplit(normalized).path.casefold() for token in NEGATIVE_PATHS):
                    continue
                if delay is not None and delay > 60 and depth > 0:
                    continue
                if delay is not None and 10 < delay <= 60 and purpose != "homepage" and _kind(normalized) not in IDENTITY_KINDS | {"careers", "news"}:
                    continue
                if page_total_bytes >= MAX_SITE_BYTES:
                    candidate_row["decision"] = "budget_skipped_bytes"
                    saw_budget_skip = True
                    break
                seen_urls.add(normalized)
                if page_limit >= MAX_ABSOLUTE_PAGES or website_page_requests >= MAX_DEFAULT_PAGES:
                    candidate_row["decision"] = "budget_skipped_pages"
                    saw_budget_skip = True
                    break
                page_limit += 1
                output.audit["page_requests"] += 1
                website_page_requests += 1
                try:
                    status, headers, body, final_url, outcome = await _fetch(gateway, normalized, purpose="website_page",
                        allowed_hosts=allowed_hosts, cap=min(MAX_PAGE_BYTES, MAX_SITE_BYTES - page_total_bytes))
                except NetworkPolicyError as exc:
                    candidate_row["decision"] = "redirect_or_url_policy_rejected"
                    candidate_row["error"] = str(exc)[:180]
                    saw_blocked = True
                    location = next((entry.redirect_location for entry in gateway.ledger.entries
                        if entry.url == normalized and getattr(entry, "redirect_location", None)), None)
                    if location:
                        candidate_row["redirect_target"] = location
                    break
                except Exception as exc:
                    output.errors.append(RunError(code="WEBSITE_FETCH_ERROR", message=f"{type(exc).__name__}: {str(exc)[:140]}"))
                    candidate_row["decision"] = "unreachable"
                    saw_failure = True
                    break
                page_total_bytes += len(body)
                if status < 200 or status >= 300:
                    if outcome == "robots_unreachable":
                        candidate_row["decision"] = "robots_unreachable"
                        output.errors.append(RunError(code="ROBOTS_UNREACHABLE", message="Website origin was skipped because robots.txt could not be retrieved."))
                    else:
                        candidate_row["decision"] = "blocked" if status in {401, 403, 451} else "unreachable" if status == 0 or status >= 500 else "rejected_http"
                    candidate_row["http_status"] = status
                    saw_blocked |= status in {401, 403, 451}
                    saw_failure |= status == 0 or status >= 500 or outcome == "robots_unreachable"
                    break
                page = _parse_page(normalized, status, headers, body, final_url)
                if page is None:
                    candidate_row["decision"] = "rejected_non_html_or_oversized"
                    break
                page.rights_status = rights_status
                output.audit["page_count"] += 1
                output.audit["pages"].append({"url": page.final_url, "kind": _kind(page.final_url, page.title), "sha256": page.digest, "bytes": len(page.body)})
                if page.soft_error:
                    candidate_row["decision"] = "rejected_" + page.soft_error
                    break
                if page.digest in seen_hashes:
                    candidate_row["decision"] = "duplicate_page"
                    continue
                seen_hashes.add(page.digest)
                pages.append(page)
                discovery_links.extend(page.links)
                candidate_row["final_url"] = page.final_url
                candidate_row["content_sha256"] = page.digest
                candidate_row["http_status"] = status
                candidate_row["page_count"] = len(pages)
                # Continue only with likely legal/about/contact identity pages until the gate decides.
                assessment = _assess_candidate(profile, pages, candidate, shared_domain=shared)
                if assessment["decision"] == "accepted":
                    break
                if assessment["decision"] == "rejected":
                    candidate_row["decision"] = "rejected_conflicting_identity"
                    break
                eligible_links = [link for link in page.links if (delay is None or delay <= 60) and "nofollow" not in page.directives
                                  and "nofollow" not in link.get("rel", "").casefold().split()
                                  and depth < MAX_DEPTH and _internal_url(link["url"], allowed_hosts)
                                  and _kind(link["url"], link.get("text", "")) in IDENTITY_KINDS]
                eligible_links.sort(key=_link_rank)
                for link in eligible_links:
                    if link["url"] not in seen_urls:
                        page_queue.append((link["url"], depth + 1, _kind(link["url"], link.get("text", ""))))
                if len(page_queue) > MAX_INITIAL_PAGES - 1:
                    page_queue = page_queue[:MAX_INITIAL_PAGES - 1]
                if len(pages) >= MAX_INITIAL_PAGES or website_page_requests >= MAX_DEFAULT_PAGES or page_limit >= MAX_ABSOLUTE_PAGES:
                    break
            assessment = _assess_candidate(profile, pages, candidate, shared_domain=shared)
            candidate_row["decision"] = assessment["decision"] if candidate_row["decision"] == "candidate" else candidate_row["decision"]
            if assessment["decision"] == "accepted":
                candidate_row["proof"] = assessment["proof"]
                candidate_row["target_url"] = assessment["target_page"]
                proof_key = _proof_key(assessment)
                if any(_proof_key(existing[2]) == proof_key for existing in accepted_pages):
                    output.audit["duplicate_accepted_proofs_deduplicated"] = (
                        output.audit.get("duplicate_accepted_proofs_deduplicated", 0) + 1)
                else:
                    accepted_pages.append((candidate, pages, assessment, delay))
            elif assessment["decision"] == "ambiguous" and candidate_row["decision"] == "ambiguous":
                candidate_row["review_reason"] = assessment["reason"]
                output.audit["high_risk_review"].append({"url": url, "reason": assessment["reason"], "source": candidate["source"]})
                unresolved = True
            elif assessment["decision"] == "rejected":
                candidate_row["decision"] = "rejected_conflicting_identity"
    else:
        saved = previous.phase_state
        candidates = saved["candidates"]
        accepted_pages = saved["accepted_pages"]
        feed_observations = saved["feed_observations"]
        page_total_bytes = saved["page_total_bytes"]
        page_limit = saved["page_limit"]
        website_page_requests = saved["website_page_requests"]
        started = saved["started"]
        unresolved = saved["unresolved"]
        saw_blocked = saved["saw_blocked"]
        saw_failure = saved["saw_failure"]
        saw_candidate = saved["saw_candidate"]
        saw_robots_disallowed = saved.get("saw_robots_disallowed", False)
        saw_robots_unreachable = saved.get("saw_robots_unreachable", False)
        saw_policy_skip = saved.get("saw_policy_skip", False)
        saw_budget_skip = saved.get("saw_budget_skip", False)

    def save_phase_state() -> None:
        output.phase_state = {"candidates": candidates, "accepted_pages": accepted_pages,
            "feed_observations": feed_observations, "page_total_bytes": page_total_bytes,
            "page_limit": page_limit, "website_page_requests": website_page_requests,
            "started": started, "unresolved": unresolved, "saw_blocked": saw_blocked,
            "saw_failure": saw_failure, "saw_candidate": saw_candidate,
            "saw_robots_disallowed": saw_robots_disallowed,
            "saw_robots_unreachable": saw_robots_unreachable,
            "saw_policy_skip": saw_policy_skip, "saw_budget_skip": saw_budget_skip}

    if phase == "verify":
        save_phase_state()
        # Verification has established a candidate, but extraction/publication
        # still belongs to later global passes. Do not expose the untouched
        # default NOT_AVAILABLE state as if those passes had completed.
        if unresolved:
            output.state = PublicState.AMBIGUOUS
        elif saw_blocked:
            output.state = PublicState.BLOCKED
        elif saw_failure:
            output.state = PublicState.FAILED
        elif accepted_pages:
            output.state = None
            output.attempt_outcome = "identity_verified_extraction_pending"
        elif saw_robots_disallowed or saw_robots_unreachable or saw_policy_skip or saw_budget_skip or not saw_candidate:
            output.state = None
            output.attempt_outcome = ("robots_disallowed" if saw_robots_disallowed else
                "robots_unreachable" if saw_robots_unreachable else "policy_skipped" if saw_policy_skip else
                "budget_skipped" if saw_budget_skip else "not_attempted")
        else:
            output.state = PublicState.NOT_AVAILABLE
        output.audit["crawl_state"] = output.state.value if output.state else output.attempt_outcome
        # This scheduler phase establishes site identity only. The later jobs
        # phase owns hiring/activity availability, so do not expose its default.
        output.hiring_activity_state = None
        output.hiring_attempt_outcome = "not_attempted"
        output.audit["hiring_activity_state"] = output.hiring_attempt_outcome
        return output
    if phase not in {"all", "shallow", "jobs"}:
        raise ValueError(f"unsupported website research phase: {phase}")
    if phase == "verify":
        save_phase_state()
        return output

    if phase != "jobs":
        # A website/brand claim is made only for an exact verified page and its proof record.
        for candidate, pages, assessment, delay in accepted_pages:
            proof_page = assessment["proof_page"]
            domain = registered_domain(urllib.parse.urlsplit(proof_page.final_url).hostname or "")
            proof = assessment["proof"]
            proof_digest = hashlib.sha256(json.dumps(proof, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            proof_source = f"website-proof:{proof_digest[:16]}"
            proof_evidence = f"website-proof-evidence:{proof_digest[:16]}"
            if not any(item.source_id == proof_source for item in output.snapshots):
                output.snapshots.append(SourceSnapshot(source_id=proof_source, source_url=proof_page.final_url,
                    retrieved_at=proof_page.retrieved_at, content_sha256=proof_digest, cache_mode="transient", rights_status="deterministic_identity_proof"))
            output.evidence.append(Evidence(evidence_id=proof_evidence, source_url=proof_page.final_url,
                retrieved_at=proof_page.retrieved_at, content_sha256=proof_digest, extraction_method="audited_exact_site_identity_proof_v1",
                json_pointer="/identity_proof", excerpt=json.dumps(proof, ensure_ascii=False, sort_keys=True)[:500], source_class="public_web",
                subject_organisation_number=org, source_snapshot_ids=[proof_source]))
            candidate_row = next(row for row in output.audit["candidates"] if row.get("url") == candidate["url"])
            source_candidate_id = _source_evidence(candidate["source_ref"], output.evidence, output.snapshots, org) if candidate["source_ref"].get("source") else None
            all_eids = [_public_evidence(proof_page, output.snapshots, output.evidence, org=org), proof_evidence]
            if source_candidate_id:
                all_eids.append(source_candidate_id)
            candidate_snapshot_ids = _additional_evidence_snapshot_ids(output.evidence, [source_candidate_id] if source_candidate_id else [])
            claim_provenance = {"evidence_ids": all_eids, "proof_source": proof_source,
                "evidence_source_snapshot_ids": candidate_snapshot_ids}
            output.claims.append(_make_claim(org, "verified_website_url", proof_page.final_url, proof_page,
                all_eids[0], **claim_provenance))
            output.claims.append(_make_claim(org, "verified_website_domain", domain, proof_page,
                all_eids[0], **claim_provenance))
            candidate_row["proof_record_id"] = proof_digest
            candidate_row["proof_evidence_id"] = proof_evidence
            candidate_row["source_candidate_evidence_id"] = source_candidate_id
            output.audit["accepted_domains"].append({"domain": domain, "url": proof_page.final_url, "source": candidate["source"],
                "proof_record_id": proof_digest, "proof_method": proof["method"], "organisation_number": org})
            output.audit["website_claim_families"].extend(["verified_website_url", "verified_website_domain"])
            # Brand is derived only after exact-site acceptance; the site cannot verify itself with this value.
            brand = next((_as_text(node.get("name")) for node in proof_page.schema_organizations
                          if org in (_identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID")) + _identifier_values(node.get("vatID")))
                          and _same_legal_name(str(profile.get("name") or ""), _as_text(node.get("legalName")))
                          and _as_text(node.get("name"))
                          and normalize_name(_as_text(node.get("name"))) != normalize_name(profile.get("name"))), None)
            if brand:
                eid = _public_evidence(proof_page, output.snapshots, output.evidence, org=org, excerpt=brand, locator="/structured_data/Organization/name")
                corroborating_headings = [heading for heading in proof_page.headings
                    if canonical_product_heading(heading) == canonical_product_heading(brand)]
                brand_evidence = [eid]
                if corroborating_headings:
                    brand_evidence.append(_public_evidence(proof_page, output.snapshots, output.evidence,
                        org=org, excerpt=brand, locator="/html/body//h1|h2|h3"))
                output.claims.append(_make_claim(org, "public_brand", brand, proof_page, eid,
                    evidence_ids=brand_evidence, proof_source=proof_source, proof_evidence=proof_evidence))
                output.audit["website_claim_families"].append("public_brand")
            claim_pages = pages if not proof.get("shared_domain") else [proof_page]
            description = next((page.description for page in claim_pages if page.description and len(page.description.strip()) >= 30
                and not re.search(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b|(?<!\d)(?:\+47\s?)?\d{8}(?!\d)|(?<!\d)\d{11}(?!\d)", page.description)), None)
            if description:
                source_page = next(page for page in claim_pages if page.description == description)
                eid = _public_evidence(source_page, output.snapshots, output.evidence, org=org, excerpt=description, locator="/html/head/meta[name=description]/@content")
                output.claims.append(_make_claim(org, "website_description", description[:500], source_page, eid, proof_source=proof_source, proof_evidence=proof_evidence))
                output.audit["website_claim_families"].append("website_description")
            product_headings: list[tuple[str, PageRecord]] = []
            for page in claim_pages:
                if _kind(page.final_url, page.title) != "products":
                    continue
                for heading in page.headings:
                    if len(heading) >= 4 and normalize_name(heading) not in {normalize_name(str(profile.get("name") or "")), "home", "homepage"}:
                        product_headings.append((heading, page))
            product_headings = _dedupe_product_headings(product_headings)
            for heading, page in product_headings[:20]:
                eid = _public_evidence(page, output.snapshots, output.evidence, org=org, excerpt=heading, locator="/html/body//h1|h2|h3")
                output.claims.append(_make_claim(org, "product_or_service_heading", heading[:180], page, eid, proof_source=proof_source, proof_evidence=proof_evidence))
                output.audit["website_claim_families"].append("product_or_service_heading")
            seen_profiles: set[str] = set()
            for page in claim_pages:
                if page.soft_error:
                    continue
                for social in _profile_links(page, org):
                    if social["url"] in seen_profiles:
                        continue
                    seen_profiles.add(social["url"])
                    eid = _public_evidence(page, output.snapshots, output.evidence, org=org, excerpt=social["url"], locator="/html/body//a[@href]")
                    output.claims.append(Claim(claim_id=f"{org}:web-profile:{hashlib.sha256(social['url'].encode()).hexdigest()[:12]}",
                        organisation_number=org, section="website_owned_profiles", field_family="owned_profile", subject_id=org,
                        field="company_owned_profile", value=social, state=PublicState.AVAILABLE, scope="legal_entity",
                        verification_rule_id="outbound_link_from_exact_verified_site_v1", verification_score="1.0",
                        evidence_ids=[eid, proof_evidence], source_snapshot_ids=[f"website:{_page_key(page)}", proof_source]))
                    output.audit["website_claim_families"].append("company_owned_profile")
            candidate_row["claim_count"] = sum(claim.field in {"verified_website_url", "verified_website_domain", "public_brand", "website_description", "product_or_service_heading", "company_owned_profile"} for claim in output.claims)
        # After verification only, discover one bounded shallow set: sitemap, feeds and ranked pages.
        for candidate, pages, assessment, delay in accepted_pages:
            if not pages:
                continue
            if delay is not None and delay > 60:
                continue
            proof_page = assessment["proof_page"]
            allowed_hosts = _internal_hosts(candidate["url"])
            root = urllib.parse.urlsplit(proof_page.final_url)
            origin = f"{root.scheme}://{root.netloc}"
            sitemap_urls: list[str] = []
            sitemap_candidates = [urllib.parse.urljoin(origin, "/sitemap.xml")]
            # Rel=sitemap from robots may be in the cached file; sitemap.xml is the bounded fallback.
            visited_sitemaps: set[str] = set()
            sitemap_count = 0
            feed_candidates: list[str] = []
            for page in pages:
                for node in BeautifulSoup(page.body.decode("utf-8", "replace"), "lxml").select('link[rel~="alternate"][href]'):
                    kind = str(node.get("type") or "").casefold()
                    if "rss" in kind or "atom" in kind:
                        feed_candidates.append(urllib.parse.urljoin(page.final_url, str(node.get("href"))))
            queue = [(url, 0) for url in sitemap_candidates]
            while queue and sitemap_count < MAX_SITEMAP_INDEXES and page_limit < MAX_ABSOLUTE_PAGES and page_total_bytes < MAX_SITE_BYTES:
                sitemap_url, level = queue.pop(0)
                if sitemap_url in visited_sitemaps or not _internal_url(sitemap_url, allowed_hosts):
                    continue
                visited_sitemaps.add(sitemap_url)
                sitemap_count += 1
                try:
                    status, headers, body, final_url, outcome = await _fetch(gateway, sitemap_url, purpose="sitemap", allowed_hosts=allowed_hosts, cap=min(256 * 1024, MAX_SITE_BYTES - page_total_bytes))
                except Exception as exc:
                    output.audit["request_outcomes"]["sitemap_error"] = output.audit["request_outcomes"].get("sitemap_error", 0) + 1
                    continue
                page_total_bytes += len(body)
                page_limit += 1
                output.audit["page_requests"] += 1
                if status != 200 or len(body) > 256 * 1024:
                    continue
                urls, indexes = _parse_sitemap(body)
                if indexes and level < 1:
                    queue.extend((url, level + 1) for url in indexes[:MAX_SITEMAP_INDEXES - sitemap_count])
                sitemap_urls.extend(urls[:MAX_SITEMAP_URLS - len(sitemap_urls)])
            for item in sitemap_urls:
                if not _internal_url(item, allowed_hosts):
                    continue
                kind = _kind(item)
                if kind == "news" and item not in feed_candidates:
                    feed_candidates.append(item)
            feed_candidates = list(dict.fromkeys(url for url in feed_candidates if _internal_url(url, allowed_hosts)))[:MAX_FEEDS]
            feed_entries: list[dict[str, str]] = []
            for feed_url in feed_candidates:
                if len(feed_entries) >= MAX_SITEMAP_URLS or page_limit >= MAX_ABSOLUTE_PAGES or page_total_bytes >= MAX_SITE_BYTES:
                    break
                try:
                    status, headers, body, final_url, outcome = await _fetch(gateway, feed_url, purpose="feed", allowed_hosts=allowed_hosts, cap=min(256 * 1024, MAX_SITE_BYTES - page_total_bytes))
                except Exception:
                    continue
                page_total_bytes += len(body)
                page_limit += 1
                output.audit["page_requests"] += 1
                if status == 200 and len(body) <= 256 * 1024:
                    parsed_entries = _parse_feed(body)
                    feed_page = PageRecord(requested_url=feed_url, final_url=final_url, status=status,
                        content_type=next((v for k, v in headers.items() if k.casefold() == "content-type"), "application/xml"),
                        body=body, digest=hashlib.sha256(body).hexdigest(), retrieved_at=datetime.now(timezone.utc))
                    feed_observations.append((candidate["url"], feed_page, parsed_entries))
                    feed_entries.extend(row for row in parsed_entries if _same_host_url(row.get("url"), final_url))
            seen_page_urls = {page.final_url for page in pages}
            candidates_for_pages = sitemap_urls + [row["url"] for row in feed_entries] + [link["url"] for page in pages if "nofollow" not in page.directives
                for link in page.links if "nofollow" not in link.get("rel", "").casefold().split() and _internal_url(link["url"], allowed_hosts)]
            ranked: dict[str, tuple[int, int, str]] = {}
            for page_url in candidates_for_pages:
                if page_url in seen_page_urls or not _internal_url(page_url, allowed_hosts):
                    continue
                rank = _link_rank({"url": page_url, "text": ""})
                if rank[0] >= 9:
                    continue
                ranked[page_url] = min(rank, ranked.get(page_url, rank))
            for page_url, _ in sorted(ranked.items(), key=lambda item: item[1]):
                if website_page_requests >= MAX_DEFAULT_PAGES or page_limit >= MAX_ABSOLUTE_PAGES or page_total_bytes >= MAX_SITE_BYTES:
                    break
                kind = _kind(page_url)
                if delay is not None and 10 < delay <= 60 and kind not in {"about", "legal", "contact", "locations", "careers", "news"}:
                    continue
                page_limit += 1
                output.audit["page_requests"] += 1
                website_page_requests += 1
                try:
                    status, headers, body, final_url, outcome = await _fetch(gateway, page_url, purpose="website_page", allowed_hosts=allowed_hosts,
                        cap=min(MAX_PAGE_BYTES, MAX_SITE_BYTES - page_total_bytes))
                except Exception:
                    continue
                page_total_bytes += len(body)
                page = _parse_page(page_url, status, headers, body, final_url)
                if page and not page.soft_error and page.digest not in {existing.digest for existing in pages}:
                    pages.append(page)
                    output.audit["page_count"] += 1
                    output.audit["pages"].append({"url": page.final_url, "kind": kind, "sha256": page.digest, "bytes": len(page.body)})
                    eid = _public_evidence(page, output.snapshots, output.evidence, org=org)
                    proof_digest = hashlib.sha256(json.dumps(assessment["proof"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                    proof_evidence = f"website-proof-evidence:{proof_digest[:16]}"
                    proof_source = f"website-proof:{proof_digest[:16]}"
                    deep_page_verified = (not assessment["proof"].get("shared_domain") or
                        verify_site_pages(profile, [page], shared_domain=True, candidate_source=candidate["source"])["decision"] == "accepted")
                    if deep_page_verified and page.description and len(page.description.strip()) >= 30 and not re.search(
                        r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b|(?<!\d)(?:\+47\s?)?\d{8}(?!\d)|(?<!\d)\d{11}(?!\d)", page.description):
                        eid = _public_evidence(page, output.snapshots, output.evidence, org=org, excerpt=page.description, locator="/html/head/meta[name=description]/@content")
                        output.claims.append(_make_claim(org, "website_description", page.description[:500], page, eid, proof_source=proof_source, proof_evidence=proof_evidence))
                        output.audit["website_claim_families"].append("website_description")
                    if deep_page_verified and kind == "products":
                        for heading, _page in _dedupe_product_headings([(heading, page) for heading in page.headings]):
                            if len(heading) < 4:
                                continue
                            eid = _public_evidence(page, output.snapshots, output.evidence, org=org, excerpt=heading, locator="/html/body//h1|h2|h3")
                            output.claims.append(_make_claim(org, "product_or_service_heading", heading[:180], page, eid, proof_source=proof_source, proof_evidence=proof_evidence))
                            output.audit["website_claim_families"].append("product_or_service_heading")
                    for social in (_profile_links(page, org) if deep_page_verified else []):
                        if any(claim.field == "company_owned_profile" and claim.value == social for claim in output.claims):
                            continue
                        social_eid = _public_evidence(page, output.snapshots, output.evidence, org=org, excerpt=social["url"], locator="/html/body//a[@href]")
                        output.claims.append(Claim(claim_id=f"{org}:web-profile:{hashlib.sha256(social['url'].encode()).hexdigest()[:12]}",
                            organisation_number=org, section="website_owned_profiles", field_family="owned_profile", subject_id=org,
                            field="company_owned_profile", value=social, state=PublicState.AVAILABLE, scope="legal_entity",
                            verification_rule_id="outbound_link_from_exact_verified_site_v1", verification_score="1.0",
                            evidence_ids=[social_eid, proof_evidence], source_snapshot_ids=[f"website:{_page_key(page)}", proof_source]))
                        output.audit["website_claim_families"].append("company_owned_profile")
            # Feed declarations can live on careers/news pages fetched during this pass.
            observed_feed_urls = {record.final_url for _candidate_url, record, _rows in feed_observations}
            for page in pages:
                for node in BeautifulSoup(page.body.decode("utf-8", "replace"), "lxml").select('link[rel~="alternate"][href]'):
                    media_type = str(node.get("type") or "").casefold()
                    if not ("rss" in media_type or "atom" in media_type):
                        continue
                    feed_url = urllib.parse.urljoin(page.final_url, str(node.get("href")))
                    if feed_url in observed_feed_urls or not _internal_url(feed_url, _internal_hosts(candidate["url"])):
                        continue
                    if page_limit >= MAX_ABSOLUTE_PAGES or page_total_bytes >= MAX_SITE_BYTES:
                        break
                    try:
                        status, headers, body, final_url, _outcome = await _fetch(gateway, feed_url, purpose="feed",
                            allowed_hosts=_internal_hosts(candidate["url"]), cap=min(256 * 1024, MAX_SITE_BYTES - page_total_bytes))
                    except Exception:
                        continue
                    page_total_bytes += len(body)
                    page_limit += 1
                    output.audit["page_requests"] += 1
                    observed_feed_urls.add(feed_url)
                    if status == 200 and len(body) <= 256 * 1024:
                        feed_page = PageRecord(requested_url=feed_url, final_url=final_url, status=status,
                            content_type=next((v for k, v in headers.items() if k.casefold() == "content-type"), "application/xml"),
                            body=body, digest=hashlib.sha256(body).hexdigest(), retrieved_at=datetime.now(timezone.utc))
                        feed_observations.append((candidate["url"], feed_page, _parse_feed(body)))
            # M05 publishes hiring/activity only from pages still bound to the exact-site proof.
        if phase == "shallow":
            save_phase_state()
            return output

    emitted_subjects: set[tuple[str, str]] = set()
    emitted_activity_subjects: set[str] = set()
    checked_careers = False
    checked_activity_surface = False
    for candidate, pages, assessment, _delay in accepted_pages:
        proof_digest = hashlib.sha256(json.dumps(assessment["proof"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        proof_source = f"website-proof:{proof_digest[:16]}"
        proof_evidence = f"website-proof-evidence:{proof_digest[:16]}"
        verified_names = {str(profile.get("name") or "")}
        for page in pages:
            if assessment["proof"].get("shared_domain") and verify_site_pages(profile, [page], shared_domain=True,
                    candidate_source=candidate["source"])["decision"] != "accepted":
                continue
            page_kind = _kind(page.final_url, page.title)
            checked_careers = checked_careers or page_kind == "careers"
            checked_activity_surface = checked_activity_surface or page_kind == "news"
            if page_kind == "careers":
                allowed_ats = _approved_ats_hosts()
                soup = BeautifulSoup(page.body.decode("utf-8", "replace"), "lxml")
                for node in soup.select("iframe[src], a[href]"):
                    if node.name == "a" and not re.search(r"(?i)\b(apply|application|job|career|position|stilling)\b", node.get_text(" ", strip=True)):
                        continue
                    raw_url = node.get("src") or node.get("href")
                    parsed_url = urllib.parse.urlsplit(urllib.parse.urljoin(page.final_url, str(raw_url)))
                    host = (parsed_url.hostname or "").casefold().removeprefix("www.")
                    if host and host not in {item.casefold().removeprefix("www.") for item in _internal_hosts(page.final_url)}:
                        status = "approved_host_but_mode_disabled" if host in allowed_ats else "unlisted_origin_skipped"
                        output.audit["ats_origins"].append({"host": host, "status": status, "requested": False})
            for node in page.schema_organizations:
                if org in (_identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID")) + _identifier_values(node.get("vatID"))):
                    name = _as_text(node.get("name"))
                    if name and _same_legal_name(str(profile.get("name") or ""), _as_text(node.get("legalName"))):
                        verified_names.add(name)
            if page_kind == "careers" and re.search(
                    r"(?i)\b(no (?:current )?(?:open )?(?:positions|roles|vacancies|openings)|no vacancies|ingen ledige stillinger|ingen åpne stillinger)\b",
                    page.visible_text):
                output.audit["jobs"]["explicit_zero"] = True
            jobs, activities, counts = _page_footprints(page, org=org, legal_name=str(profile.get("name") or ""),
                verified_names=verified_names, cutoff=cutoff)
            for name, count in counts.items():
                if name == "job_candidates": output.audit["jobs"]["candidates"] += count
                elif name == "job_identity_rejected": output.audit["jobs"]["identity_rejected"] = output.audit["jobs"].get("identity_rejected", 0) + count
                elif name == "job_future": output.audit["jobs"].setdefault("future_dated_skipped", 0); output.audit["jobs"]["future_dated_skipped"] += count
                elif name == "activity_candidates": output.audit["activity"]["candidates"] += count
                elif name == "activity_subject_rejected": output.audit["activity"]["subject_rejected"] = output.audit["activity"].get("subject_rejected", 0) + count
                elif name == "activity_undated": output.audit["activity"]["undated"] += count
                elif name == "activity_future": output.audit["activity"]["future"] += count
                elif name == "activity_outside_window": output.audit["activity"]["outside_window"] += count
            evidence_id = _public_evidence(page, output.snapshots, output.evidence, org=org)
            for job in jobs:
                subject = job["subject"]
                values = {"job_title": job["title"], "job_location": job["location"],
                          "employment_type": job["employment_type"], "posting_date": job["posting_date"],
                          "application_deadline": job["deadline"], "canonical_job_url": job["url"], "job_status": job["status"]}
                values["posting_date"] = _source_date_value(job["posting_date"], str(job["posting_date_raw"])) if job["posting_date"] else None
                values["application_deadline"] = _source_date_value(job["deadline"], str(job["deadline_raw"])) if job["deadline"] else None
                for field_name, value in values.items():
                    if value is None or (subject, field_name) in emitted_subjects:
                        continue
                    emitted_subjects.add((subject, field_name))
                    if isinstance(value, datetime): value = value.isoformat()
                    output.claims.append(_make_footprint_claim(org, field_name, value, subject, "job", page,
                                                               evidence_id, proof_source, proof_evidence,
                                                               job["posting_date"] if field_name == "posting_date" else (job["deadline"] if field_name == "application_deadline" else None)))
                    output.audit["jobs"]["published"] += 1
            for activity in activities:
                if activity["subject"] not in emitted_activity_subjects and len(emitted_activity_subjects) >= 20:
                    continue
                subject = activity["subject"]
                emitted_activity_subjects.add(subject)
                values = {"activity_headline": activity["title"], "activity_type": activity["event_type"],
                          "source_published_at": _source_date_value(activity["published"], activity["published_raw"]),
                          "activity_source_url": activity["url"], "activity_summary": activity["summary"]}
                for field_name, value in values.items():
                    if value is None or (subject, field_name) in emitted_subjects:
                        continue
                    emitted_subjects.add((subject, field_name))
                    output.claims.append(_make_footprint_claim(org, field_name, value, subject, "event", page,
                                                               evidence_id, proof_source, proof_evidence,
                                                               activity["published"] if field_name == "source_published_at" else None))
                    output.audit["activity"]["published"] += 1
        # Feed item dates are source publication dates; feed retrieval/sitemap dates are never substituted.
        for feed_candidate, feed_page, entries in feed_observations:
            if feed_candidate != candidate["url"]:
                continue
            if assessment["proof"].get("shared_domain") and verify_site_pages(profile, [feed_page], shared_domain=True,
                    candidate_source=candidate["source"])["decision"] != "accepted":
                continue
            checked_activity_surface = True
            feed_evidence = _public_evidence(feed_page, output.snapshots, output.evidence, org=org, locator="/rss/channel/item")
            counts = {"activity_undated": 0, "activity_future": 0, "activity_outside_window": 0}
            observed: list[dict[str, Any]] = []
            for entry in entries:
                item_url = _same_host_url(entry.get("url"), feed_page.final_url)
                title = entry.get("title", "").strip()
                if not item_url or not title:
                    continue
                feed_subject = title + " " + str(entry.get("summary") or entry.get("description") or "")
                if not _article_subject_matches({}, feed_subject, org, verified_names):
                    output.audit["activity"]["subject_rejected"] = output.audit["activity"].get("subject_rejected", 0) + 1
                    continue
                event = _activity_record(org, title, item_url, _date_value(entry.get("published")),
                    entry.get("summary") or entry.get("description"), entry.get("category"), cutoff, 365, counts, entry.get("published"))
                if event:
                    event["locator"] = "/rss/channel/item"
                    observed.append(event)
            unique_events = _dedupe_activities(observed)
            output.audit["activity"]["deduplicated"] += len(observed) - len(unique_events)
            output.audit["activity"]["undated"] += counts["activity_undated"]
            output.audit["activity"]["future"] += counts["activity_future"]
            output.audit["activity"]["outside_window"] += counts["activity_outside_window"]
            for activity in unique_events:
                if activity["subject"] not in emitted_activity_subjects and len(emitted_activity_subjects) >= 100:
                    continue
                subject = activity["subject"]
                emitted_activity_subjects.add(subject)
                values = {"activity_headline": activity["title"], "activity_type": activity["event_type"],
                          "source_published_at": _source_date_value(activity["published"], activity["published_raw"]),
                          "activity_source_url": activity["url"], "activity_summary": activity["summary"]}
                for field_name, value in values.items():
                    if value is None or (subject, field_name) in emitted_subjects:
                        continue
                    emitted_subjects.add((subject, field_name))
                    output.claims.append(_make_footprint_claim(org, field_name, value, subject, "event", feed_page,
                                                               feed_evidence, proof_source, proof_evidence,
                                                               activity["published"] if field_name == "source_published_at" else None))
                    output.audit["activity"]["published"] += 1
    output.audit["jobs"]["published_subjects"] = len({claim.subject_id for claim in output.claims if claim.field_family == "jobs"})
    output.audit["activity"]["published_subjects"] = len({claim.subject_id for claim in output.claims if claim.field_family == "public_activity"})
    job_status_by_subject = {claim.subject_id: claim.value for claim in output.claims
        if claim.field_family == "jobs" and claim.field == "job_status"}
    current_job_subjects = {claim.subject_id for claim in output.claims if claim.field_family == "jobs"
        and str(job_status_by_subject.get(claim.subject_id, "")).casefold() in {"open", "active", "inprogress", "in progress"}}
    output.audit["jobs"]["current_subjects"] = len(current_job_subjects)
    output.audit["jobs"]["state"] = ("available" if current_job_subjects else
        "ambiguous" if output.audit["jobs"]["published_subjects"] else
        "not_available" if output.audit["jobs"]["explicit_zero"] else "ambiguous")
    output.audit["activity"]["lookback_days"] = 365
    output.audit["activity"]["page_discovery_target"] = 20
    output.audit["activity"]["max_from_already_fetched_feed_responses"] = 100
    output.audit["source_policy"] = {"source_class": "verified_company_owned_website", "external_sources_enabled": False,
        "terms_policy": "skip_if_prohibitive; transient factual extraction; source URL, date and hash retained"}
    skipped_outcome = ("robots_disallowed" if saw_robots_disallowed else
        "robots_unreachable" if saw_robots_unreachable else "policy_skipped" if saw_policy_skip else
        "budget_skipped" if saw_budget_skip else "not_attempted" if not saw_candidate else None)
    if output.claims:
        output.attempt_outcome = "completed"
    elif skipped_outcome:
        output.attempt_outcome = skipped_outcome
    hiring_claims = [claim for claim in output.claims if claim.section == "hiring_activity"]
    if hiring_claims:
        output.hiring_activity_state = PublicState.AVAILABLE
    elif output.audit["jobs"]["explicit_zero"] and checked_activity_surface:
        output.hiring_activity_state = PublicState.NOT_AVAILABLE
    elif output.attempt_outcome and output.attempt_outcome != "completed":
        output.hiring_activity_state = None
        output.hiring_attempt_outcome = output.attempt_outcome
    else:
        output.hiring_activity_state = PublicState.AMBIGUOUS
    output.audit["hiring_activity_state"] = (output.hiring_activity_state.value
        if output.hiring_activity_state else output.hiring_attempt_outcome or output.attempt_outcome)
    output.audit["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
    output.audit["bytes_received"] = page_total_bytes
    output.audit["max_default_pages"] = MAX_DEFAULT_PAGES
    output.audit["max_absolute_pages"] = MAX_ABSOLUTE_PAGES
    output.audit["max_depth"] = MAX_DEPTH
    output.audit["state_counts"] = {"accepted": len(accepted_pages), "ambiguous": len(output.audit["high_risk_review"]),
        "blocked": int(saw_blocked), "failed": int(saw_failure), "candidates": len(candidates)}
    if output.claims:
        output.state = PublicState.AVAILABLE
    elif unresolved:
        output.state = PublicState.AMBIGUOUS
    elif saw_blocked:
        output.state = PublicState.BLOCKED
    elif saw_failure:
        output.state = PublicState.FAILED
    elif skipped_outcome:
        output.state = None
        output.attempt_outcome = skipped_outcome
    elif saw_candidate:
        output.state = PublicState.NOT_AVAILABLE
    else:
        output.state = None
        output.attempt_outcome = "not_attempted"
    output.audit["crawl_state"] = output.state.value if output.state else output.attempt_outcome
    output.audit["website_claim_families"] = sorted(set(output.audit["website_claim_families"]))
    return output
