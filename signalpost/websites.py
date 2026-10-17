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
    "contact": ("contact", "kontakt", "contact-us", "kontaktinformasjon"),
    "careers": ("career", "careers", "jobb", "jobbe", "ledige-stillinger", "stillinger", "work-with-us"),
    "news": ("news", "nyheter", "press", "presserom", "pressrom", "aktuelt", "blog", "rss", "feed"),
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


def _contains_schema_type(value: Any, wanted: set[str]) -> bool:
    if isinstance(value, dict):
        kind = value.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if any(isinstance(item, str) and item.casefold().rsplit("/", 1)[-1] in wanted for item in kinds):
            return True
        return any(_contains_schema_type(child, wanted) for child in value.values())
    if isinstance(value, list):
        return any(_contains_schema_type(child, wanted) for child in value)
    return False


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
    operator_identity_blocks: list[str] = field(default_factory=list)
    site_brand_blocks: list[str] = field(default_factory=list)
    article_document: bool | None = None


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
    operator_identity_blocks: list[str] = []
    for node in soup.select("address, [itemprop='legalName'], [itemprop='address'], [itemprop='identifier'], .legal, #legal, .contact, #contact"):
        if (node.find_parent(["article", "footer"]) or node.find_parent(class_=re.compile(r"(?i)(?:^|[-_ ])(?:about|article|story|case-study|blog-post)(?:$|[-_ ])"))
                or node.find_parent(id=re.compile(r"(?i)^(?:about|article|story|case-study|blog-post)$"))):
            continue
        text_block = " ".join(node.get_text(" ", strip=True).split())[:3000]
        if text_block and text_block not in operator_identity_blocks:
            operator_identity_blocks.append(text_block)
    site_brand_blocks: list[str] = []
    brand_nodes: list[Any] = []
    for header in soup.find_all("header"):
        header_copy = BeautifulSoup(str(header), "lxml")
        for nav in header_copy.find_all("nav"):
            nav.decompose()
        explicit_brands = header_copy.select(
            ".logo, [class~='site-name'], [itemprop='legalName'], [itemprop='name'], [id*='logo' i]")
        # Prefer the explicit logo/site-name slot. Treating the whole header as
        # a brand conflates a short trading name with its separate legal contact
        # block (for example, "Acme" + "Acme AS, registered address").
        brand_nodes.extend(explicit_brands or header_copy.find_all("header"))
    brand_nodes.extend(soup.select(
        'meta[property="og:site_name"][content], [class~="logo"], [id*="logo" i]'))
    for node in brand_nodes:
        if node.find_parent(["article", "footer", "nav"]):
            continue
        text_block = str(node.get("content") or node.get("alt") or "").strip()
        if not text_block:
            text_block = " ".join(node.get_text(" ", strip=True).split())
        text_block = text_block[:1000]
        if text_block and text_block not in site_brand_blocks:
            site_brand_blocks.append(text_block)
    article_document = bool(soup.select_one("article, [itemprop='articleBody'], [itemtype*='Article'], .article, .news-article, .blog-post"))
    article_document = article_document or _contains_schema_type(jsonld, {"article", "newsarticle", "blogposting", "blog"})
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
    page.operator_identity_blocks = operator_identity_blocks
    page.site_brand_blocks = site_brand_blocks
    page.article_document = article_document
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


def _schema_record_roots(value: Any, wanted: set[str]) -> list[dict[str, Any]]:
    """Return typed top-level JSON-LD records, including direct @graph members only."""
    roots = value if isinstance(value, list) else [value]
    records: list[dict[str, Any]] = []
    for root in roots:
        if not isinstance(root, dict):
            continue
        candidates = root.get("@graph") if isinstance(root.get("@graph"), list) else [root]
        for node in candidates:
            if not isinstance(node, dict):
                continue
            raw_types = node.get("@type")
            types = raw_types if isinstance(raw_types, list) else [raw_types]
            if any(isinstance(kind, str) and kind.casefold().rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                   in wanted for kind in types):
                records.append(node)
    return records


def _direct_typed_entities(value: Any, wanted: set[str] | None = None) -> list[dict[str, Any]]:
    """Read only entities directly named by a relationship property."""
    values = value if isinstance(value, list) else [value]
    result: list[dict[str, Any]] = []
    for node in values:
        if not isinstance(node, dict):
            continue
        raw_types = node.get("@type")
        types = raw_types if isinstance(raw_types, list) else [raw_types]
        normalized = {kind.casefold().rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                      for kind in types if isinstance(kind, str)}
        if wanted is None or normalized & wanted:
            result.append(node)
    return result


def _schema_record_urls(node: dict[str, Any]) -> list[str]:
    """Return every explicit resource identity field without hiding conflicts."""
    values: list[str] = []
    for key in ("url", "@id"):
        value = node.get(key)
        items = value if isinstance(value, list) else [value]
        values.extend(item.strip() for item in items if isinstance(item, str) and item.strip())
    return values


def _canonical_resource_query(url: str) -> tuple[tuple[str, str], ...]:
    """Compare decoded query fields independent of parameter order."""
    parsed = urllib.parse.urlsplit(url)
    return tuple(sorted(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)))


def _schema_entity_url_binds_page(node: dict[str, Any], page: PageRecord, *, shared_domain: bool) -> bool:
    """Require the record's explicit URL identities to bind to this exact resource."""
    values = _schema_record_urls(node)
    if not values:
        return False
    page_url = urllib.parse.urlsplit(page.final_url)
    page_host = _normalized_site_host(page.final_url)
    page_path = page_url.path.rstrip("/") or "/"
    matched = False
    for value in values:
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(page.final_url, value))
        if parsed.scheme not in {"http", "https"} or _normalized_site_host(parsed.geturl()) != page_host:
            return False
        if shared_domain and (parsed.path.rstrip("/") or "/") != page_path:
            return False
        if shared_domain and _canonical_resource_query(parsed.geturl()) != _canonical_resource_query(page.final_url):
            return False
        matched = True
    return matched


def _schema_entity_url_same_resource(node: dict[str, Any], page: PageRecord) -> bool:
    """Bind a structured page to this response path, including query identity."""
    if not _schema_entity_url_binds_page(node, page, shared_domain=True):
        return False
    expected = urllib.parse.urlsplit(page.final_url)
    expected_path = expected.path.rstrip("/") or "/"
    for value in _schema_record_urls(node):
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(page.final_url, value))
        if (_canonical_resource_query(parsed.geturl()) != _canonical_resource_query(page.final_url)
                or (parsed.path.rstrip("/") or "/") != expected_path):
            return False
    return True


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


def _negative_subject_context(text: str, org: str, legal_names: list[str] | None = None) -> bool:
    """Detect when the target is locally described in a non-owner role.

    Both exact identifiers and exact legal-name forms are classified. This is
    intentionally local to the subject mention; a target-owned site may still
    discuss its customers when independent target ownership evidence exists.
    """
    normalized_text = unicodedata.normalize("NFC", text)
    negative_labels = (
        "customer", "customers", "customer case", "customer story", "customer reference", "client", "clients",
        "kunde", "kunder", "partner", "supplier", "leverandør", "designer", "webmaster", "auditor", "revisor",
        "board member", "styremedlem", "procurement", "anskaffelse", "case study", "case-study", "reference customer",
        "article subject", "subject of this article", "group member", "subsidiary of", "member of the group",
        "designed by", "design by", "website by", "site by", "web by", "developed by", "provided by", "powered by",
        "hosted by", "web developer", "web agency", "webbyrå", "webbureau", "website development",
        "website design", "leverandør av nettside", "our customers", "our client", "our partner", "our supplier",
    )
    # Do not let a separate paragraph/title/footer role spill into a target
    # mention merely because the flattened page text is nearby. Classify within
    # one sentence or DOM-derived block.
    segments = [part for part in re.split(r"\n+|(?<=[.!?])\s+", normalized_text) if part.strip()]
    for segment in segments:
        lowered = segment.casefold()
        subject_spans: list[tuple[int, int]] = []
        if org:
            subject_spans.extend((match.start(), match.end()) for match in
                re.finditer(r"(?<!\d)" + re.escape(org) + r"(?!\d)", segment))
        # Match exact legal-name spellings (including punctuation variants
        # around legal suffixes), never partial brand tokens.
        for legal in legal_names or []:
            raw = unicodedata.normalize("NFC", str(legal or "")).strip()
            if not raw:
                continue
            words = normalize_name(raw).split()
            if not words:
                continue
            base = r"[\W_]+".join(re.escape(word) for word in words)
            suffix_present = re.search(r"(?i)\s+(?:a\s*[./-]?\s*s(?:\s*[./-]?\s*a)?|as|asa|enk|nuf|da|ans|ba|ab|oy|ltd|limited|inc|gmbh|plc)\s*[.,]?\s*$", raw)
            suffix = (r"[\W_]+(?:a\s*[./-]?\s*s(?:\s*[./-]?\s*a)?|as|asa|enk|nuf|da|ans|ba|ab|oy|ltd|limited|inc|gmbh|plc)"
                      if suffix_present else "")
            subject_spans.extend((match.start(), match.end()) for match in
                re.finditer(r"(?<!\w)" + base + suffix + r"(?!\w)", segment, re.IGNORECASE))
        for start, end in subject_spans:
            context = lowered[max(0, start - 100):min(len(lowered), end + 80)]
            if any(label in context for label in negative_labels):
                return True
    return False


def _schema_entity_matches(profile: dict[str, Any], node: dict[str, Any]) -> bool:
    org = str(profile.get("organisation_number") or "")
    names = [str(profile.get("name") or ""), *[
        str(item.get("name") or "") for item in profile.get("historical_names", []) if isinstance(item, dict)]]
    ids = _identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID")) + _identifier_values(node.get("vatID"))
    name = _as_text(node.get("legalName") or node.get("name"))
    return org in ids and bool(name) and any(_same_legal_name(expected, name) for expected in names if expected)


def _schema_entity_name_matches(profile: dict[str, Any], node: dict[str, Any]) -> bool:
    names = [str(profile.get("name") or ""), *[
        str(item.get("name") or "") for item in profile.get("historical_names", []) if isinstance(item, dict)]]
    name = _as_text(node.get("legalName") or node.get("name"))
    return bool(name and any(_same_legal_name(expected, name) for expected in names if expected))


def _schema_entity_has_conflicting_ids(profile: dict[str, Any], node: dict[str, Any]) -> bool:
    org = str(profile.get("organisation_number") or "")
    related = {str(value) for value in profile.get("related_organisation_numbers", []) if str(value).isdigit()}
    ids = set(_identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID")) + _identifier_values(node.get("vatID")))
    return any(identifier != org and identifier not in related for identifier in ids)


def _schema_entity_is_site_root(node: dict[str, Any], page: PageRecord) -> bool:
    values = _schema_record_urls(node)
    if not values:
        return False
    expected = _normalized_site_host(page.final_url)
    for value in values:
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(page.final_url, value))
        if (parsed.scheme not in {"http", "https"} or _normalized_site_host(parsed.geturl()) != expected
                or parsed.path.rstrip("/") not in {"", "/"}):
            return False
    return True


def _normalized_site_host(url: str) -> str:
    """Normalize only the common www alias; other subdomains remain distinct."""
    return (urllib.parse.urlsplit(url).hostname or "").casefold().rstrip(".").removeprefix("www.")


def _website_record_binds_response_host(node: dict[str, Any], page: PageRecord) -> bool:
    """A WebSite object is relevant only when its canonical root is this response host."""
    values = _schema_record_urls(node)
    if not values:
        return False
    response_host = _normalized_site_host(page.final_url)
    for raw in values:
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(page.final_url, raw))
        if (parsed.scheme not in {"http", "https"} or _normalized_site_host(parsed.geturl()) != response_host
                or parsed.query or (parsed.path or "/").rstrip("/") not in {"", "/"}):
            return False
    return True


def _explicit_schema_url_host_conflicts(node: dict[str, Any], page: PageRecord) -> bool:
    """An explicit Organization URL/ID cannot contradict its containing resource host."""
    values = _schema_record_urls(node)
    expected = _normalized_site_host(page.final_url)
    for raw in values:
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(page.final_url, raw))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or _normalized_site_host(parsed.geturl()) != expected:
            return True
    return False


def _site_brand_conflicts_with_target(profile: dict[str, Any], page: PageRecord, *,
                                      allowed_operator_names: set[str] | None = None) -> bool:
    """Reject a second legal site identity; allow the known operator of shared pages."""
    names = [str(profile.get("name") or ""), *[
        str(item.get("name") or "") for item in profile.get("historical_names", []) if isinstance(item, dict)]]
    legal_form = re.compile(r"(?i)\b(?:AS|ASA|NUF|ENK|DA|ANS|BA)\b")
    allowed = {normalize_name(name) for name in (allowed_operator_names or set())}
    brand_blocks = _site_brand_blocks(page)
    page_parts = urllib.parse.urlsplit(page.final_url)
    if page_parts.path in {"", "/"}:
        brand_blocks.extend([page.title, *page.headings])
    for block in brand_blocks:
        if not block or not legal_form.search(block):
            continue
        mentions = [match.group(1).strip(" ,.;:·|–—-") for match in _LEGAL_NAME_MENTION.finditer(block)]
        if mentions:
            if any(not any(_same_legal_name(target, mention) for target in names)
                   and normalize_name(mention) not in allowed for mention in mentions):
                return True
        elif not _exact_name(names, block) and normalize_name(block) not in allowed:
            return True
    return False


def _site_shell_has_competing_identifier(profile: dict[str, Any], page: PageRecord) -> bool:
    """A foreign number alongside explicit site branding is operator conflict, not a body mention."""
    target = str(profile.get("organisation_number") or "")
    related = {str(value) for value in profile.get("related_organisation_numbers", []) if str(value).isdigit()}
    soup = BeautifulSoup(page.body.decode("utf-8", "replace"), "lxml")
    for header in soup.find_all("header"):
        fragment = BeautifulSoup(str(header), "lxml")
        for nav in fragment.find_all("nav"):
            nav.decompose()
        if not fragment.select(".logo, [class~='site-name'], [itemprop='legalName'], [itemprop='name'], [id*='logo' i]"):
            continue
        identifiers = re.findall(r"(?<!\d)\d{9}(?!\d)", fragment.get_text(" ", strip=True))
        if any(identifier != target and identifier not in related for identifier in identifiers):
            return True
    return False


def _explicit_site_brand_conflicts_with_target(profile: dict[str, Any], page: PageRecord,
                                               allowed_operator_names: set[str] | None = None) -> bool:
    """Compare explicit logo/site-name fields, without interpreting body mentions as ownership."""
    names = [str(profile.get("name") or ""), *[
        str(item.get("name") or "") for item in profile.get("historical_names", []) if isinstance(item, dict)]]
    allowed = {normalize_name(name) for name in (allowed_operator_names or set())}
    soup = BeautifulSoup(page.body.decode("utf-8", "replace"), "lxml")
    nodes = list(soup.select('meta[property="og:site_name"][content]'))
    nodes.extend(soup.select("header .logo, header [class~='site-name'], header [itemprop='legalName'], header [itemprop='name']"))
    nodes.extend(soup.select("header [id*='logo' i]"))
    seen: set[str] = set()
    for node in nodes:
        text = str(node.get("content") or node.get("alt") or " ".join(node.get_text(" ", strip=True).split()))
        text = text.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        comparable_text = re.sub(r"(?<!\d)\d{9}(?!\d)", " ", text).strip(" ,.;:|–—-")
        if any(_same_legal_name(target, comparable_text) for target in names if target):
            continue
        if normalize_name(comparable_text) in allowed:
            continue
        if _mentions_exact_entity(names, comparable_text) and not any(
                normalize_name(brand) in normalize_name(comparable_text) for brand in allowed if brand):
            return True
        # These selectors are explicit brand/operator slots. Their identity
        # conflicts with the target even when the rival has no legal suffix.
        return True
    return False


def _target_is_profile_subject(profile: dict[str, Any], page: PageRecord) -> bool:
    """Identify target-specific profile pages whose body identity describes the subject."""
    path = urllib.parse.urlsplit(page.final_url).path.casefold()
    # On a profile route the main body describes the profiled entity; it cannot
    # identify the host operator even when the body happens to omit a heading.
    return bool(re.search(r"(?:^|/)profiles?(?:/|$)", path))


def _operator_blocks(page: PageRecord, *, exclude_main: bool = False, site_shell_only: bool = False) -> list[str]:
    """Identity-bearing contact/legal blocks, excluding article, about, and footer content."""
    if page.operator_identity_blocks and not exclude_main and not site_shell_only:
        return page.operator_identity_blocks
    soup = BeautifulSoup(page.body.decode("utf-8", "replace"), "lxml")
    blocks: list[str] = []
    selectors = "address, [itemprop='legalName'], [itemprop='address'], [itemprop='identifier'], .legal, #legal, .contact, #contact"
    excluded_classes = re.compile(r"(?i)(?:^|[-_ ])(?:about|article|story|case-study|blog-post)(?:$|[-_ ])")
    for node in soup.select(selectors):
        if (node.find_parent(["article", "footer"]) or (exclude_main and node.find_parent("main"))
                or (site_shell_only and not node.find_parent(["header", "nav"]))
                or node.find_parent(class_=excluded_classes)
                or node.find_parent(id=re.compile(r"(?i)^(?:about|article|story|case-study|blog-post)$"))):
            continue
        text = " ".join(node.get_text(" ", strip=True).split())[:3000]
        if text and text not in blocks:
            blocks.append(text)
    return blocks


def _site_brand_blocks(page: PageRecord) -> list[str]:
    if page.site_brand_blocks:
        return page.site_brand_blocks
    soup = BeautifulSoup(page.body.decode("utf-8", "replace"), "lxml")
    result: list[str] = []
    for header in soup.find_all("header"):
        fragment = BeautifulSoup(str(header), "lxml")
        for nav in fragment.find_all("nav"):
            nav.decompose()
        text = " ".join(fragment.get_text(" ", strip=True).split())
        if text and text not in result:
            result.append(text[:1000])
    for node in soup.select('meta[property="og:site_name"][content], [class~="logo"], [id*="logo" i]'):
        if node.find_parent(["article", "footer", "nav"]):
            continue
        text = str(node.get("content") or node.get("alt") or "").strip()
        if not text:
            text = " ".join(node.get_text(" ", strip=True).split())
        if text and text not in result:
            result.append(text[:1000])
    return result


def _is_article_document(page: PageRecord) -> bool:
    if page.article_document is not None:
        return page.article_document
    soup = BeautifulSoup(page.body.decode("utf-8", "replace"), "lxml")
    if soup.select_one("article, [itemprop='articleBody'], [itemtype*='Article'], .article, .news-article, .blog-post"):
        return True
    jsonld = page.structured.get("json-ld", []) if isinstance(page.structured, dict) else []
    return _contains_schema_type(jsonld, {"article", "newsarticle", "blogposting", "blog"})


def _site_ownership_evidence(profile: dict[str, Any], page: PageRecord, *, candidate_source: str,
                             shared_domain: bool, diagnostics: list[str] | None = None) -> dict[str, Any] | None:
    """Prove the operator and page subject through direct, resource-bound records."""
    def abstain(reason: str) -> None:
        if diagnostics is not None:
            diagnostics.append(reason)

    if page.soft_error:
        abstain("insufficient_direct_ownership_proof")
        return None
    jsonld = page.structured.get("json-ld", []) if isinstance(page.structured, dict) else []
    article_document = _is_article_document(page)
    org = str(profile.get("organisation_number") or "")
    legal_names = [str(profile.get("name") or ""), *[
        str(item.get("name") or "") for item in profile.get("historical_names", []) if isinstance(item, dict)]]
    related = {str(value) for value in profile.get("related_organisation_numbers", []) if str(value).isdigit()}
    website_nodes = _schema_record_roots(jsonld, {"website"})
    webpage_nodes = _schema_record_roots(jsonld, {"webpage"})
    organization_nodes = _schema_record_roots(jsonld, {"organization", "corporation", "localbusiness"})
    bound_websites = [node for node in website_nodes if _website_record_binds_response_host(node, page)]
    if website_nodes and not bound_websites:
        abstain("unbound_site_operator_record")

    site_publishers_by_record = [(website, _direct_typed_entities(website.get("publisher"),
        {"organization", "corporation", "localbusiness"})) for website in bound_websites]
    site_publishers = [publisher for _website, publishers in site_publishers_by_record for publisher in publishers]
    site_publisher_values = [publisher for website in bound_websites
        for publisher in _direct_typed_entities(website.get("publisher"))]
    unsupported_site_publishers = [node for node in site_publisher_values
        if not ({kind.casefold().rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                 for kind in (node.get("@type") if isinstance(node.get("@type"), list) else [node.get("@type")])
                 if isinstance(kind, str)} & {"organization", "corporation", "localbusiness"})]
    site_operator_names = {_as_text(node.get("legalName") or node.get("name")) for node in site_publishers
                           if _as_text(node.get("legalName") or node.get("name"))}
    matching_target_site_publishers = [node for node in site_publishers if _schema_entity_matches(profile, node)
        and not _schema_entity_has_conflicting_ids(profile, node)]
    malformed_target_site_publishers = [node for node in site_publishers
        if _schema_entity_name_matches(profile, node)
        and str(profile.get("organisation_number") or "") in
            (_identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID"))
             + _identifier_values(node.get("vatID")))
        and _schema_entity_has_conflicting_ids(profile, node)]
    if malformed_target_site_publishers:
        abstain("conflicting_structured_company_identity")
        return None
    if any(_explicit_schema_url_host_conflicts(node, page) for node in matching_target_site_publishers):
        abstain("conflicting_site_operator_identity")
        return None
    target_site_publishers = matching_target_site_publishers
    conflicting_site_publishers = [node for node in site_publishers
        if _as_text(node.get("legalName") or node.get("name"))
        and (not _schema_entity_matches(profile, node)
             or _schema_entity_has_conflicting_ids(profile, node))
        and not any(identifier in related for identifier in
            _identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID"))
            + _identifier_values(node.get("vatID")))]
    if shared_domain:
        foreign_operator_signatures = {
            (normalize_name(_as_text(node.get("legalName") or node.get("name"))),
             tuple(sorted(set(_identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID"))
                              + _identifier_values(node.get("vatID"))))))
            for node in conflicting_site_publishers
        }
        if (len(foreign_operator_signatures) > 1
                or (matching_target_site_publishers and conflicting_site_publishers)):
            abstain("conflicting_site_operator_identity")
            return None
    if unsupported_site_publishers:
        abstain("unsupported_publisher_relationship_type")
        return None

    page_parts = urllib.parse.urlsplit(page.final_url)
    is_homepage = page_parts.path in {"", "/"} and not page_parts.query
    bound_webpages = [node for node in webpage_nodes if _schema_entity_url_same_resource(node, page)]
    page_records_at_resource = [node for node in webpage_nodes
        if _schema_record_urls(node) and _schema_entity_url_same_resource(node, page)]

    # A direct representation must identify one coherent company. Selecting
    # the matching member of a mixed mainEntity list loses contradictory
    # subject evidence. Publisher names likewise cannot override explicit IDs.
    if shared_domain:
        def company_ids(node: dict[str, Any]) -> set[str]:
            return set(_identifier_values(node.get("identifier"))
                       + _identifier_values(node.get("taxID"))
                       + _identifier_values(node.get("vatID")))

        for webpage in bound_webpages:
            entities = _direct_typed_entities(webpage.get("mainEntity"),
                {"organization", "corporation", "localbusiness"})
            if (any(_schema_entity_matches(profile, node) for node in entities)
                    and any(not _schema_entity_matches(profile, node)
                            or _schema_entity_has_conflicting_ids(profile, node) for node in entities)):
                abstain("conflicting_page_publisher_identity")
                return None
            for publisher in _direct_typed_entities(webpage.get("publisher"),
                    {"organization", "corporation", "localbusiness"}):
                name = _as_text(publisher.get("legalName") or publisher.get("name"))
                identifiers = company_ids(publisher)
                for operator in site_publishers:
                    operator_name = _as_text(operator.get("legalName") or operator.get("name"))
                    operator_ids = company_ids(operator)
                    if (name and _same_legal_name(name, operator_name)
                            and identifiers and operator_ids and identifiers != operator_ids):
                        abstain("conflicting_page_publisher_identity")
                        return None

    # Shared-domain representation is page scoped. Only the direct typed
    # mainEntity/publisher of this exact WebPage record can establish it.
    shared_page_proof: dict[str, Any] | None = None
    if shared_domain and not is_homepage and not article_document:
        for webpage in bound_webpages:
            publisher_values = _direct_typed_entities(webpage.get("publisher"))
            publishers = _direct_typed_entities(webpage.get("publisher"),
                {"organization", "corporation", "localbusiness"})
            if any(not ({kind.casefold().rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                         for kind in (node.get("@type") if isinstance(node.get("@type"), list) else [node.get("@type")])
                         if isinstance(kind, str)} & {"organization", "corporation", "localbusiness"})
                   for node in publisher_values):
                abstain("unsupported_publisher_relationship_type")
                continue
            main_entities = _direct_typed_entities(webpage.get("mainEntity"),
                {"organization", "corporation", "localbusiness"})
            page_publishers = [node for node in publishers if _as_text(node.get("legalName") or node.get("name"))]
            if any(not _schema_entity_matches(profile, node) and not any(identifier in related for identifier in
                    _identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID"))
                    + _identifier_values(node.get("vatID"))) for node in page_publishers):
                # A page's direct publisher may be the verified group operator.
                if not all(any(_same_legal_name(name, operator) for operator in site_operator_names)
                           for name in (_as_text(node.get("legalName") or node.get("name"))
                                        for node in page_publishers if not _schema_entity_matches(profile, node))):
                    abstain("conflicting_page_publisher_identity")
                    continue
            target_main = [node for node in main_entities if _schema_entity_matches(profile, node)
                and not _schema_entity_has_conflicting_ids(profile, node)
                and not _explicit_schema_url_host_conflicts(node, page)]
            target_page_publishers = [node for node in publishers if _schema_entity_matches(profile, node)
                and not _schema_entity_has_conflicting_ids(profile, node)
                and not _explicit_schema_url_host_conflicts(node, page)]
            if target_main or target_page_publishers:
                entity = (target_main or target_page_publishers)[0]
                shared_page_proof = {"method": "shared_page_main_entity" if target_main else "shared_page_publisher",
                    "subject_scope": "shared_page_representation",
                    "operator_name": _as_text(entity.get("legalName") or entity.get("name")),
                    "operator_organisation_number": org, "page_only": True}
                break
            if webpage.get("publisher") or webpage.get("mainEntity"):
                if _direct_typed_entities(webpage.get("publisher")) or _direct_typed_entities(webpage.get("mainEntity")):
                    abstain("unsupported_page_relationship_type")

    # Conflicting legal site branding blocks domain ownership. On a configured
    # shared host, the directly identified group operator is an allowed brand
    # for the subsidiary page, while the target remains page scoped.
    shared_page_brand_names = {_as_text(node.get("legalName") or node.get("name"))
        for webpage in bound_webpages
        for node in _direct_typed_entities(webpage.get("publisher"), {"organization", "corporation", "localbusiness"})
        if _schema_entity_url_same_resource(webpage, page)
        and _as_text(node.get("legalName") or node.get("name"))}
    allowed_brand_names = (site_operator_names | shared_page_brand_names) if shared_domain else set()
    visible_operator_conflict = _site_brand_conflicts_with_target(
        profile, page, allowed_operator_names=allowed_brand_names)
    visible_operator_conflict = visible_operator_conflict or _explicit_site_brand_conflicts_with_target(
        profile, page, allowed_operator_names=allowed_brand_names)
    shell_identifier_conflict = _site_shell_has_competing_identifier(profile, page)

    if conflicting_site_publishers and not shared_domain:
        abstain("conflicting_site_operator_identity")
        return None
    if shared_domain and bound_webpages:
        page_publishers_all = [node for webpage in bound_webpages
            for node in _direct_typed_entities(webpage.get("publisher"), {"organization", "corporation", "localbusiness"})]
        if any(_as_text(node.get("legalName") or node.get("name")) and
               not any(_same_legal_name(_as_text(node.get("legalName") or node.get("name")), brand)
                       for brand in site_operator_names)
               and not _schema_entity_matches(profile, node) for node in page_publishers_all):
            abstain("conflicting_page_publisher_identity")
            return None

    # Resolve all explicit operator conflicts before considering any proof
    # route. In particular, a target publisher must not return before a
    # resource-bound rival operator record or site-shell identifier is read.
    root_operator_conflict = False
    target_root_url_conflict = False
    malformed_target_root = False
    target_name_wrong_identifier = False
    for node in organization_nodes:
        root_name = _as_text(node.get("legalName") or node.get("name"))
        root_ids = set(_identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID"))
                       + _identifier_values(node.get("vatID")))
        urls = _schema_record_urls(node)
        root_bound = (_schema_entity_is_site_root(node, page)
                      or (is_homepage and not urls))
        if _schema_entity_name_matches(profile, node):
            if org in root_ids and any(identifier not in related and identifier != org for identifier in root_ids):
                malformed_target_root = True
            if org in root_ids and _explicit_schema_url_host_conflicts(node, page):
                target_root_url_conflict = True
            if org not in root_ids and any(identifier not in related for identifier in root_ids) and root_bound:
                malformed_target_root = True
                target_name_wrong_identifier = True
        elif root_name and root_bound:
            if not (shared_domain and root_ids and root_ids <= related):
                root_operator_conflict = True
    if malformed_target_root:
        abstain("target_name_with_conflicting_org_number" if target_name_wrong_identifier
                else "conflicting_structured_company_identity")
        return None
    if target_root_url_conflict:
        abstain("conflicting_site_operator_identity")
    site_operator_conflict = (
        visible_operator_conflict or (shell_identifier_conflict and not shared_domain)
        or root_operator_conflict or target_root_url_conflict
        or (bool(conflicting_site_publishers) and not shared_domain)
    )
    if shared_domain:
        site_signatures = {
            (normalize_name(_as_text(node.get("legalName") or node.get("name"))),
             tuple(sorted(set(_identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID"))
                              + _identifier_values(node.get("vatID"))))))
            for node in site_publishers
        }
        if len(site_signatures) > 1:
            site_operator_conflict = True

    def final_acceptance_gate(proof: dict[str, Any] | None) -> dict[str, Any] | None:
        """The only path from a candidate proof to an accepted ownership result."""
        if proof is None:
            return None
        scope = proof.get("subject_scope")
        if page.soft_error:
            abstain("insufficient_direct_ownership_proof")
            return None
        resource_url = str(proof.get("resource_url") or "")
        proof_resource, fetched_resource = (urllib.parse.urlsplit(resource_url),
                                            urllib.parse.urlsplit(page.final_url))
        if (not resource_url or _normalized_site_host(resource_url) != _normalized_site_host(page.final_url)
                or (proof_resource.path.rstrip("/") or "/") != (fetched_resource.path.rstrip("/") or "/")
                or _canonical_resource_query(resource_url) != _canonical_resource_query(page.final_url)):
            abstain("insufficient_direct_ownership_proof")
            return None
        if scope == "site_operator":
            if shared_domain or site_operator_conflict:
                abstain("conflicting_site_operator_identity" if site_operator_conflict
                        else "insufficient_direct_ownership_proof")
                return None
        elif scope == "shared_page_representation":
            if not shared_domain or not proof.get("page_only"):
                abstain("insufficient_direct_ownership_proof")
                return None
            # Page representation is independent of domain ownership, but it
            # cannot override affirmative evidence that a different entity
            # operates the shared host. The same conflict gate applies to the
            # structured and HTML page-proof routes.
            if site_operator_conflict:
                abstain("conflicting_site_operator_identity")
                return None
        else:
            abstain("insufficient_direct_ownership_proof")
            return None
        return proof

    conflicting_root_identity = False
    for node in organization_nodes:
        root_name = _as_text(node.get("legalName") or node.get("name"))
        root_ids = set(_identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID"))
                       + _identifier_values(node.get("vatID")))
        if (_schema_entity_name_matches(profile, node) and org not in root_ids
                and any(identifier not in related for identifier in root_ids)):
            abstain("target_name_with_conflicting_org_number")
            return None
        if (_schema_entity_name_matches(profile, node) and org in root_ids
                and any(identifier not in related and identifier != org for identifier in root_ids)):
            abstain("conflicting_structured_company_identity")
            return None
        if root_name and not _schema_entity_matches(profile, node):
            related_record = bool(root_ids) and root_ids <= related
            known_shared_operator = shared_domain and normalize_name(root_name) in {
                normalize_name(name) for name in site_operator_names}
            if not related_record and not known_shared_operator:
                conflicting_root_identity = True
                break
    if conflicting_root_identity and not shared_domain:
        abstain("conflicting_structured_company_identity")
        return None
    if conflicting_root_identity and shared_domain:
        abstain("conflicting_site_operator_identity")
        return None

    if target_site_publishers and not shared_domain:
        if conflicting_site_publishers:
            abstain("conflicting_site_operator_identity")
            return None
        return final_acceptance_gate({"method": "website_publisher_organization", "subject_scope": "site_operator",
                "operator_name": _as_text(target_site_publishers[0].get("legalName") or target_site_publishers[0].get("name")),
                "operator_organisation_number": org, "resource_url": page.final_url})

    # A standalone Organization is operator proof only when it is a direct
    # resource record and its explicit URL (when present) binds to this host.
    target_root: dict[str, Any] | None = None
    foreign_root = False
    target_root_url_conflict = False
    malformed_target_root = False
    for node in organization_nodes:
        name = _as_text(node.get("legalName") or node.get("name"))
        ids = _identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID")) + _identifier_values(node.get("vatID"))
        if _schema_entity_matches(profile, node) and not _schema_entity_has_conflicting_ids(profile, node):
            if _explicit_schema_url_host_conflicts(node, page):
                target_root_url_conflict = True
                abstain("conflicting_site_operator_identity")
                continue
            if (not _schema_record_urls(node) and is_homepage) or _schema_entity_is_site_root(node, page):
                target_root = target_root or node
        elif (_schema_entity_name_matches(profile, node) and org in ids
              and any(identifier not in related and identifier != org for identifier in ids)):
            malformed_target_root = True
        elif name and (not ids or any(identifier not in related and identifier != org for identifier in ids)):
            foreign_root = True
    if malformed_target_root:
        abstain("conflicting_structured_company_identity")
        return None
    if target_root_url_conflict:
        return None
    if foreign_root and not shared_domain:
        abstain("conflicting_structured_company_identity")
        return None
    if target_root and not shared_domain and not article_document:
        if target_site_publishers and conflicting_site_publishers:
            abstain("conflicting_site_operator_identity")
            return None
        return final_acceptance_gate({"method": "site_operator_organization", "subject_scope": "site_operator",
                "operator_name": _as_text(target_root.get("legalName") or target_root.get("name")),
                "operator_organisation_number": org, "resource_url": page.final_url})

    if shared_page_proof:
        # Multiple records bound to this same path cannot contradict the
        # selected direct representation relationship.
        if len(page_records_at_resource) > 1:
            target_records = [record for record in page_records_at_resource
                if _direct_typed_entities(record.get("mainEntity"), {"organization", "corporation", "localbusiness"})]
            if len(target_records) > 1:
                abstain("conflicting_page_publisher_identity")
                return None
        shared_page_proof["resource_url"] = page.final_url
        return final_acceptance_gate(shared_page_proof)

    # HTML operator evidence remains available for sites without JSON-LD.
    # Article pages can use only site-shell identity; page body identity is
    # never promoted to site ownership.
    profile_subject = _target_is_profile_subject(profile, page)
    non_owner_mention = _negative_subject_context(
        "\n".join([page.title, *page.headings, page.identity_text, page.visible_text]), org, legal_names)
    blocks = _operator_blocks(page, exclude_main=profile_subject,
        site_shell_only=article_document or non_owner_mention)
    registered_roles = [str(value) for value in profile.get("registered_roles", []) if value]
    has_contact_endpoint = bool(re.search(rb"(?i)(?:mailto:|tel:)", page.body))
    for block in blocks:
        compatible_name = _exact_name(legal_names, block)
        if not compatible_name:
            continue
        exact_org = bool(org and re.search(r"(?<!\d)" + re.escape(org) + r"(?!\d)", block))
        address = _address_match(profile, block)
        role = next((item for item in registered_roles if normalize_name(item) and normalize_name(item) in normalize_name(block)), None)
        if shared_domain and not is_homepage and not article_document and candidate_source in {"registry_live", "registry_frozen"} and (exact_org or address):
            return final_acceptance_gate({"method": "shared_page_operator_identity", "subject_scope": "shared_page_representation",
                    "operator_name": compatible_name, "operator_organisation_number": org,
                    "address_match": address, "identity_block_sha256": hashlib.sha256(block.encode()).hexdigest(),
                    "page_only": True, "resource_url": page.final_url})
        if candidate_source in {"registry_live", "registry_frozen"} and address:
            return final_acceptance_gate({"method": "registry_candidate_contact_identity", "subject_scope": "site_operator",
                    "operator_name": compatible_name, "operator_organisation_number": org,
                    "address_match": address, "identity_block_sha256": hashlib.sha256(block.encode()).hexdigest(),
                    "resource_url": page.final_url})
        if candidate_source == "keyless_no" and address and (role or has_contact_endpoint):
            return final_acceptance_gate({"method": "keyless_contact_identity", "subject_scope": "site_operator",
                    "operator_name": compatible_name, "operator_organisation_number": org,
                    "address_match": address, "registered_role": role,
                    "contact_endpoint_present": has_contact_endpoint,
                    "identity_block_sha256": hashlib.sha256(block.encode()).hexdigest(),
                    "resource_url": page.final_url})
        if candidate_source in {"registry_live", "registry_frozen"} and exact_org:
            return final_acceptance_gate({"method": "site_operator_contact_org_number", "subject_scope": "site_operator",
                    "operator_name": compatible_name, "operator_organisation_number": org,
                    "identity_block_sha256": hashlib.sha256(block.encode()).hexdigest(),
                    "resource_url": page.final_url})
    abstain("insufficient_direct_ownership_proof")
    return None


def verify_site_pages(profile: dict[str, Any], pages: list[PageRecord], *, shared_domain: bool = False,
                      candidate_source: str = "registry_live", candidate_url: str | None = None) -> dict[str, Any]:
    """Apply the audited exact-site table; name-only and self-derived brand never pass."""
    org = str(profile.get("organisation_number") or "")
    legal_names = [str(profile.get("name") or ""), *[str(item.get("name") or "") for item in profile.get("historical_names", []) if isinstance(item, dict)]]
    legal_names = [name for name in legal_names if name]
    related = {str(item) for item in profile.get("related_organisation_numbers", []) if str(item).isdigit()}
    identity_pages: list[dict[str, Any]] = []
    ownership_failures: list[str] = []
    candidate_host = _normalized_site_host(candidate_url) if candidate_url else None
    for page in pages:
        if candidate_host and _normalized_site_host(page.final_url) != candidate_host:
            continue
        page_ownership_failures: list[str] = []
        ownership = _site_ownership_evidence(profile, page, candidate_source=candidate_source,
            shared_domain=shared_domain, diagnostics=page_ownership_failures)
        if ownership is None:
            ownership_failures.extend(page_ownership_failures)
            continue
        identity_pages.append({"page": page, "method": ownership["method"],
            "name": ownership["operator_name"], "address": ownership.get("address_match"),
            "subject_ids": [], "ownership": ownership})
    if not identity_pages:
        if candidate_host and any(_normalized_site_host(page.final_url) != candidate_host for page in pages):
            return {"decision": "ambiguous", "reason": "candidate_host_mismatch", "proof": None, "target_page": None}
        if "conflicting_structured_company_identity" in ownership_failures:
            return {"decision": "ambiguous", "reason": "conflicting_structured_company_identity", "proof": None, "target_page": None}
        if "target_name_with_conflicting_org_number" in ownership_failures:
            return {"decision": "rejected", "reason": "conflicting_structured_company_identity", "proof": None, "target_page": None}
        if "conflicting_site_operator_identity" in ownership_failures or "conflicting_page_publisher_identity" in ownership_failures:
            return {"decision": "rejected", "reason": "conflicting_operator_identity", "proof": None, "target_page": None}
        if "unsupported_publisher_relationship_type" in ownership_failures or "unsupported_page_relationship_type" in ownership_failures:
            return {"decision": "ambiguous", "reason": "unsupported_publisher_relationship_type", "proof": None, "target_page": None}
        if "unbound_site_operator_record" in ownership_failures:
            return {"decision": "ambiguous", "reason": "site_record_not_bound_to_response_host", "proof": None, "target_page": None}
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
        return {"decision": "ambiguous", "reason": "insufficient_direct_ownership_proof", "proof": None, "target_page": None}
    selected = sorted(identity_pages, key=lambda row: (
        0 if row["ownership"]["subject_scope"] == "site_operator" else 1,
        row["page"].requested_url))[0]
    page = selected["page"]
    parsed_target = urllib.parse.urlsplit(page.final_url)
    is_homepage = parsed_target.path in {"", "/"} and not parsed_target.query
    if shared_domain and is_homepage:
        # A group homepage never becomes a subsidiary homepage solely from a brand or name mention.
        if selected["ownership"]["subject_scope"] != "site_operator":
            return {"decision": "ambiguous", "reason": "shared_group_homepage_without_target_subject_proof", "proof": None, "target_page": None}
    proof = {
        "rule_id": "audited_exact_site_identity_v1", "method": selected["method"],
        "organisation_number": org, "compatible_legal_name": selected["name"],
        "page_url": page.final_url, "page_sha256": page.digest,
        "json_ld_subject_match": selected["method"] in {"site_operator_organization", "website_publisher_organization", "shared_page_main_entity"},
        "registered_address_match": selected.get("address"), "shared_domain": shared_domain,
        "conflicting_subject_ids": sorted(identifier for identifier in selected.get("subject_ids", []) if identifier != org and identifier not in related),
    }
    return {"decision": "accepted", "reason": None, "proof": proof, "target_page": page.final_url, "proof_page": page}


def _kind(url: str, text: str = "") -> str:
    # A specific child route takes precedence over generic parents such as
    # /om-oss. Match token boundaries: "press" must not classify "depression".
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path).casefold()
    for value in [*reversed(path.split("/")), text.casefold()]:
        for kind, tokens in POSITIVE_PATHS.items():
            if any(re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)",
                             value.replace("_", "-")) for token in tokens):
                return kind
    return "other"


def _link_rank(item: dict[str, str]) -> tuple[int, int, str]:
    path = urllib.parse.urlsplit(item["url"]).path.casefold()
    if any(token in path for token in NEGATIVE_PATHS):
        return (9, 9, item["url"])
    kind = _kind(item["url"], item.get("text", ""))
    rank = {"legal": 0, "contact": 1, "about": 2, "locations": 3, "careers": 4,
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


def _profile_locator(page: PageRecord, profile_url: str, org: str) -> str:
    for node in page.schema_organizations:
        ids = (_identifier_values(node.get("identifier")) + _identifier_values(node.get("taxID"))
               + _identifier_values(node.get("vatID")))
        values = node.get("sameAs")
        if org in ids and profile_url in (values if isinstance(values, list) else [values]):
            return "/structured_data/Organization/sameAs"
    return "/html/body//a[@href]"


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


def _feed_document(body: bytes) -> bool:
    try:
        root = ET.fromstring(body[:MAX_PAGE_BYTES])
    except (ET.ParseError, ValueError):
        return False
    return root.tag in {"rss", "feed", "{http://www.w3.org/2005/Atom}feed",
                        "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF"}


def _parse_feed(body: bytes) -> list[dict[str, str]]:
    """Parse bounded RSS/Atom entries retaining only explicit source fields."""
    if not _feed_document(body):
        return []
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


def _schema_types(value: Any) -> set[str]:
    values = value if isinstance(value, list) else [value]
    result = set()
    for kind in values:
        if not isinstance(kind, str):
            continue
        if kind.startswith(("https://schema.org/", "http://schema.org/")):
            kind = kind.rsplit("/", 1)[-1]
        elif ":" in kind or "/" in kind:
            continue
        result.add(kind.casefold())
    return result


def _schema_nodes(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if _schema_types(value.get("@type")) & {"jobposting", "newsarticle", "article", "blogposting"}:
            found.append(value)
        for child in value.values():
            found.extend(_schema_nodes(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_schema_nodes(child))
    return found


def _footprint_schema_nodes(structured: Any) -> list[dict[str, Any]]:
    """Resolve exact local graph references only; never fetch contexts or IDs.

    Conflicting definitions are deliberately unresolved. This adapter applies
    only to job/activity extraction after ownership has already been verified.
    """
    jsonld = structured.get("json-ld", []) if isinstance(structured, dict) else []
    roots = jsonld if isinstance(jsonld, list) else [jsonld]
    definitions: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    for root in roots:
        if not isinstance(root, dict):
            continue
        for node in root.get("@graph", []) if isinstance(root.get("@graph"), list) else [root]:
            if not isinstance(node, dict) or not isinstance(node.get("@id"), str) or len(node) < 2:
                continue
            key = node["@id"]
            if key in definitions and definitions[key] != node:
                conflicts.add(key)
            definitions[key] = node

    def resolve(value: Any, visited: frozenset[str] = frozenset(), depth: int = 0) -> Any:
        if depth >= 12:
            return value
        if isinstance(value, list):
            return [resolve(item, visited, depth + 1) for item in value]
        if not isinstance(value, dict):
            return value
        if set(value) == {"@id"} and isinstance(value["@id"], str):
            key = value["@id"]
            if key not in conflicts and key in definitions and key not in visited:
                return resolve(definitions[key], visited | {key}, depth + 1)
            return value
        return {key: resolve(item, visited, depth + 1) for key, item in value.items()}

    return [resolve(node) for node in _schema_nodes(structured)]


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
                if all(identifier == org for identifier in identifiers) and (not name or _employer_matches({"identifier": org, "name": name}, org, verified_names)):
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


def _job_status(raw: Any, deadline: datetime | None, cutoff: datetime) -> str | None:
    """Resolve posting status conservatively; closure wins any contradiction."""
    token = _schema_text(raw)
    token = token.rsplit("/", 1)[-1].rsplit("#", 1)[-1].casefold().replace("-", "_").replace(" ", "_") if token else ""
    explicit_closed = token in {"closed", "expired", "inactive", "closed_to_applications"}
    explicit_open = token in {"open", "active", "open_for_applications"}
    deadline_closed = bool(deadline and deadline < cutoff)
    if explicit_closed or deadline_closed:
        return "closed"
    if explicit_open:
        return "open"
    if token:
        return None
    return "open" if deadline and deadline >= cutoff else None


def _page_footprints(page: PageRecord, *, org: str, legal_name: str, verified_names: set[str],
                     cutoff: datetime, lookback_days: int = 365) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Extract conservative same-site job and dated activity observations."""
    jobs: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []
    counts = {"job_candidates": 0, "job_identity_rejected": 0, "job_future": 0, "activity_candidates": 0,
              "activity_undated": 0, "activity_future": 0, "activity_outside_window": 0}
    for node in _footprint_schema_nodes(page.structured):
        kinds = _schema_types(node.get("@type"))
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
            status_raw = node.get("jobStatus") if node.get("jobStatus") is not None else node.get("employmentStatus")
            status = _job_status(status_raw, deadline, cutoff)
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
        status = _job_status(itemprop("jobStatus") or itemprop("employmentStatus"), deadline, cutoff)
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
                                   candidate_source=str(candidate.get("source") or "registry_live"),
                                   candidate_url=str(candidate.get("url") or "") or None)
    if candidate.get("source") == "search_provider":
        proof_page = assessment.get("proof_page") or (pages[0] if pages else None)
        if proof_page is None:
            return assessment
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
        if assessment.get("decision") != "accepted" or assessment.get("proof", {}).get("method") not in {
                "website_publisher_organization", "site_operator_organization"}:
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
                candidate = {**sanitized, "source": source, "source_ref": source_ref,
                    "discovery": source_ref.get("discovery") if isinstance(source_ref, dict) else None}
                if candidate not in candidates:
                    candidates.append(candidate)
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
            candidate_host_key = _normalized_site_host(url)
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
                    if outcome == "budget_exhausted":
                        candidate_row["decision"] = "budget_skipped"
                        saw_budget_skip = True
                        break
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
                seen_urls.add(_clean_url(page.final_url) or page.final_url)
                page.rights_status = rights_status
                output.audit["page_count"] += 1
                output.audit["pages"].append({"url": page.final_url, "kind": _kind(page.final_url, page.title), "sha256": page.digest, "bytes": len(page.body)})
                if page.soft_error:
                    candidate_row["decision"] = "rejected_" + page.soft_error
                    break
                if _normalized_site_host(page.final_url) != candidate_host_key:
                    candidate_row.setdefault("host_mismatch_pages", []).append({
                        "requested_url": normalized, "final_url": page.final_url, "content_sha256": page.digest})
                    candidate_row["final_url"] = page.final_url
                    candidate_row["content_sha256"] = page.digest
                    candidate_row["http_status"] = status
                    continue
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
            if not pages and candidate_row.get("host_mismatch_pages"):
                assessment = {"decision": "ambiguous", "reason": "candidate_host_mismatch",
                    "proof": None, "proof_page": None, "target_page": None}
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
            page_only = proof.get("method", "").startswith("shared_page_")
            if not page_only:
                output.claims.append(_make_claim(org, "verified_website_domain", domain, proof_page,
                    all_eids[0], **claim_provenance))
            candidate_row["proof_record_id"] = proof_digest
            candidate_row["proof_evidence_id"] = proof_evidence
            candidate_row["source_candidate_evidence_id"] = source_candidate_id
            if page_only:
                output.audit.setdefault("accepted_pages", []).append({"url": proof_page.final_url,
                    "host": urllib.parse.urlsplit(proof_page.final_url).hostname, "source": candidate["source"],
                    "proof_record_id": proof_digest, "proof_method": proof["method"], "organisation_number": org})
                output.audit["website_claim_families"].append("verified_website_url")
            else:
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
                    eid = _public_evidence(page, output.snapshots, output.evidence, org=org, excerpt=social["url"], locator=_profile_locator(page, social["url"], org))
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
                if _normalized_site_host(final_url) != _normalized_site_host(candidate["url"]):
                    output.audit["request_outcomes"]["off_host_sitemap_redirect"] = output.audit["request_outcomes"].get("off_host_sitemap_redirect", 0) + 1
                    continue
                if status != 200 or len(body) > 256 * 1024:
                    continue
                urls, indexes = _parse_sitemap(body)
                known_content = {_kind(link["url"], link.get("text", ""))
                    for page in pages if "nofollow" not in page.directives for link in page.links
                    if "nofollow" not in link.get("rel", "").casefold().split()
                    and _internal_url(link["url"], allowed_hosts)}
                # With direct careers AND news surfaces, reach them before
                # optional sitemap-index depth. Sitemap-only sites retain the
                # bounded fallback; sitemap dates never become claim dates.
                if indexes and level < 1 and not {"careers", "news"} <= known_content:
                    queue.extend((url, level + 1) for url in indexes[:MAX_SITEMAP_INDEXES - sitemap_count])
                sitemap_urls.extend(urls[:MAX_SITEMAP_URLS - len(sitemap_urls)])
            for item in sitemap_urls:
                if not _internal_url(item, allowed_hosts):
                    continue
                # A news article in a sitemap is an HTML page candidate, not
                # an RSS/Atom declaration. Avoid fetching it twice under two
                # purposes (and spending the budget before page extraction).
                feed_path = urllib.parse.urlsplit(item).path.casefold()
                if re.search(r"(?:^|/)(?:feed|rss|atom)(?:/|\.|$)|\.(?:rss|atom|xml)$", feed_path) and item not in feed_candidates:
                    feed_candidates.append(item)
            feed_candidates = list(dict.fromkeys(url for url in feed_candidates if _internal_url(url, allowed_hosts)))[:MAX_FEEDS]
            feed_entries: list[dict[str, str]] = []
            downloaded_html: dict[str, tuple[int, dict[str, str], bytes, str, str]] = {}
            fetched_feed_urls: set[str] = set()
            actual_feed_urls: set[str] = set()
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
                if _normalized_site_host(final_url) != _normalized_site_host(candidate["url"]):
                    output.audit["request_outcomes"]["off_host_feed_redirect"] = output.audit["request_outcomes"].get("off_host_feed_redirect", 0) + 1
                    continue
                fetched_feed_urls.update({feed_url, final_url})
                if status == 200 and len(body) <= 256 * 1024:
                    media_type = next((v for k, v in headers.items() if k.casefold() == "content-type"), "")
                    if "html" in media_type.casefold():
                        downloaded_html[feed_url] = (status, headers, body, final_url, outcome)
                        continue
                    if not _feed_document(body):
                        continue
                    actual_feed_urls.update({feed_url, final_url})
                    parsed_entries = _parse_feed(body)
                    feed_page = PageRecord(requested_url=feed_url, final_url=final_url, status=status,
                        content_type=next((v for k, v in headers.items() if k.casefold() == "content-type"), "application/xml"),
                        body=body, digest=hashlib.sha256(body).hexdigest(), retrieved_at=datetime.now(timezone.utc))
                    feed_observations.append((candidate["url"], feed_page, parsed_entries))
                    feed_entries.extend(row for row in parsed_entries if _same_host_url(row.get("url"), final_url))
            seen_page_urls = {page.final_url for page in pages}
            candidates_for_pages = list(downloaded_html) + sitemap_urls + [row["url"] for row in feed_entries] + [link["url"] for page in pages if "nofollow" not in page.directives
                for link in page.links if "nofollow" not in link.get("rel", "").casefold().split() and _internal_url(link["url"], allowed_hosts)]
            ranked: dict[str, tuple[int, int, str]] = {}
            for page_url in candidates_for_pages:
                if (page_url in seen_page_urls or not _internal_url(page_url, allowed_hosts)
                        or (page_url in actual_feed_urls and page_url not in downloaded_html)):
                    continue
                rank = _link_rank({"url": page_url, "text": ""})
                if rank[0] >= 9:
                    continue
                # Identity is already proven. Reach careers/news/products before
                # spending the content budget on more legal/about pages.
                kind = _kind(page_url)
                content_rank = {"careers": 0, "news": 1, "products": 2}.get(kind, rank[0] + 3)
                rank = (content_rank, rank[1], rank[2])
                ranked[page_url] = min(rank, ranked.get(page_url, rank))
            for page_url, _ in sorted(ranked.items(), key=lambda item: (item[0] not in downloaded_html, item[1])):
                if page_url not in downloaded_html and (website_page_requests >= MAX_DEFAULT_PAGES or page_limit >= MAX_ABSOLUTE_PAGES or page_total_bytes >= MAX_SITE_BYTES):
                    continue
                kind = _kind(page_url)
                if delay is not None and 10 < delay <= 60 and kind not in {"about", "legal", "contact", "locations", "careers", "news"}:
                    continue
                if page_url in downloaded_html:
                    status, headers, body, final_url, outcome = downloaded_html[page_url]
                else:
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
                if page and _normalized_site_host(page.final_url) != _normalized_site_host(candidate["url"]):
                    output.audit["request_outcomes"]["off_host_website_page_redirect"] = output.audit["request_outcomes"].get("off_host_website_page_redirect", 0) + 1
                    continue
                if page and not page.soft_error and page.digest not in {existing.digest for existing in pages}:
                    pages.append(page)
                    output.audit["page_count"] += 1
                    output.audit["pages"].append({"url": page.final_url, "kind": kind, "sha256": page.digest, "bytes": len(page.body)})
                    eid = _public_evidence(page, output.snapshots, output.evidence, org=org)
                    proof_digest = hashlib.sha256(json.dumps(assessment["proof"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                    proof_evidence = f"website-proof-evidence:{proof_digest[:16]}"
                    proof_source = f"website-proof:{proof_digest[:16]}"
                    deep_page_verified = (not assessment["proof"].get("shared_domain") or
                        verify_site_pages(profile, [page], shared_domain=True, candidate_source=candidate["source"],
                            candidate_url=candidate["url"])["decision"] == "accepted")
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
                        social_eid = _public_evidence(page, output.snapshots, output.evidence, org=org, excerpt=social["url"], locator=_profile_locator(page, social["url"], org))
                        output.claims.append(Claim(claim_id=f"{org}:web-profile:{hashlib.sha256(social['url'].encode()).hexdigest()[:12]}",
                            organisation_number=org, section="website_owned_profiles", field_family="owned_profile", subject_id=org,
                            field="company_owned_profile", value=social, state=PublicState.AVAILABLE, scope="legal_entity",
                            verification_rule_id="outbound_link_from_exact_verified_site_v1", verification_score="1.0",
                            evidence_ids=[social_eid, proof_evidence], source_snapshot_ids=[f"website:{_page_key(page)}", proof_source]))
                        output.audit["website_claim_families"].append("company_owned_profile")
            # Feed declarations can live on careers/news pages fetched during this pass.
            observed_feed_urls = fetched_feed_urls | {record.final_url for _candidate_url, record, _rows in feed_observations}
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
                    if _normalized_site_host(final_url) != _normalized_site_host(candidate["url"]):
                        output.audit["request_outcomes"]["off_host_feed_redirect"] = output.audit["request_outcomes"].get("off_host_feed_redirect", 0) + 1
                        continue
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
    if output.hiring_activity_state is not None:
        output.hiring_attempt_outcome = "completed"
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
