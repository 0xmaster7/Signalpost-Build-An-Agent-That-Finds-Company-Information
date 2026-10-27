from signalpost.identifiers import stable_claim_id
from signalpost.websites import WebsiteResearchResult, _append_website_claim, _make_claim, _parse_page


def test_claim_identity_is_order_independent_and_binds_dimensions():
    dimensions = {"source": "https://data.brreg.no/statement", "content_sha256": "a" * 64,
        "subject": "filing:123", "period_start": "2024-01-01", "period_end": "2024-12-31",
        "scope": "legal_entity", "unit": "NOK", "currency": "NOK", "unit_state": "assumed"}
    original = stable_claim_id("987974249", "revenue", 100, **dimensions)
    assert original == stable_claim_id("987974249", "revenue", 100, **dict(reversed(list(dimensions.items()))))
    assert original != stable_claim_id("987974249", "revenue", 101, **dimensions)
    assert original != stable_claim_id("987974249", "profit", 100, **dimensions)
    assert original != stable_claim_id("923609016", "revenue", 100, **dimensions)
    for key in dimensions:
        assert original != stable_claim_id("987974249", "revenue", 100, **{**dimensions, key: "different"})


def test_website_identity_binds_scope_source_and_value_and_dedupes():
    page = _parse_page("https://example.no/", 200, {"Content-Type": "text/html"},
        b"<html><body>Storage racks</body></html>", "https://example.no/")
    first = _make_claim("987974249", "product_or_service_heading", "Storage racks", page, "one")
    repeated = _make_claim("987974249", "product_or_service_heading", "STORAGE  RACKS", page, "two")
    other_scope = _make_claim("987974249", "product_or_service_heading", "Storage racks", page, "three", scope="group")
    other_value = _make_claim("987974249", "product_or_service_heading", "Other racks", page, "four")
    assert first.claim_id == repeated.claim_id
    assert len({first.claim_id, other_scope.claim_id, other_value.claim_id}) == 3
    output = WebsiteResearchResult()
    for item in (first, repeated, other_scope, other_value):
        _append_website_claim(output, item)
    assert len(output.claims) == 3
    assert set(output.claims[0].evidence_ids) == {"one", "two"}
