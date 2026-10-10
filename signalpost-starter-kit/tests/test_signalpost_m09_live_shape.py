from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from signalpost import run as run_module
from signalpost.adapter import validate_vendor_payload
from signalpost.history import validate_artifact
from signalpost.identifiers import canonical_product_heading
from signalpost.models import Envelope, validate_publication_graph
from signalpost.network import NetworkGateway


FIXTURE_PATH = Path(__file__).parent / "fixtures/m09/live-shape-companies.json"


def _accounts_record(year: int, revenue: int, filing_id: str) -> dict:
    return {
        "id": f"sanitized-account-{year}", "innsendingsId": filing_id, "versjon": 1,
        "regnskapstype": "SELSKAP", "valuta": "NOK", "enhet": "NOK",
        "regnskapsperiode": {"fraDato": f"{year}-01-01", "tilDato": f"{year}-12-31"},
        "innsendingsdato": f"{year + 1}-03-01",
        "resultatregnskapResultat": {
            "driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": {"sum": revenue, "enhet": "NOK"}},
                               "driftsresultat": {"sum": 1000 + year, "enhet": "NOK"}},
            "ordinaertResultatFoerSkattekostnad": {"sum": 900 + year, "enhet": "NOK"},
            "aarsresultat": {"sum": 700 + year, "enhet": "NOK"}},
        "eiendeler": {"sumEiendeler": {"sum": 10000 + year, "enhet": "NOK"}},
        "egenkapitalGjeld": {"egenkapital": {"sumEgenkapital": {"sum": 6000 + year, "enhet": "NOK"}},
                              "gjeldOversikt": {"sumGjeld": {"sum": 4000 + year, "enhet": "NOK"}}},
    }


def _entity_body(company: dict) -> dict:
    body = {"organisasjonsnummer": company["organisation_number"], "navn": company["name"],
        "organisasjonsform": {"kode": company["legal_form"], "beskrivelse": "Sanitized fixture entity"},
        "registrertIForetaksregisteret": True, "antallAnsatte": 12,
        "naeringskode1": {"kode": "62.010", "beskrivelse": "Programming activities"}}
    body.update(company.get("registry_status_fields", {}))
    if company.get("registry_address"):
        body["forretningsadresse"] = company["registry_address"]
    if company.get("parent"):
        body["overordnetEnhet"] = company["parent"]
    if company.get("website"):
        body["hjemmeside"] = company["website"]
    if company.get("legal_form") == "ENK":
        sentinel = company["private_address_sentinel"]
        body["forretningsadresse"] = {"adresse": [sentinel], "postnummer": "0000", "poststed": "Fixture"}
        body["postadresse"] = {"adresse": [sentinel], "postnummer": "0000", "poststed": "Fixture"}
    return body


def _role_body(company: dict, companies: dict[str, dict]) -> dict:
    mode = company["roles_mode"]
    if mode == "malformed_collection":
        return {"rollegrupper": "malformed fixture collection"}
    if mode == "empty":
        return {"rollegrupper": []}
    if mode == "parent_organisation_holder":
        parent = companies[company["parent"]]
        return {"rollegrupper": [{"type": {"kode": "STYR", "beskrivelse": "Board"}, "sistEndret": "2025-01-01",
            "roller": [{"enhet": {"organisasjonsnummer": parent["organisation_number"], "navn": parent["name"]},
                "type": {"kode": "STYRLEDER", "beskrivelse": "Chair"}, "fraDato": "2020-01-01"}]}]}
    return {"rollegrupper": [{"type": {"kode": "DAGL", "beskrivelse": "Management"}, "sistEndret": "2025-01-01",
        "roller": [{"person": {"navn": {"fornavn": "Alex", "etternavn": "Example"}},
            "type": {"kode": "DAGL", "beskrivelse": "Managing director"}, "fraDato": "2020-01-01"}]}]}


def _subunits_body(company: dict, companies: dict[str, dict]) -> dict:
    mode = company["subunits_mode"]
    if mode == "malformed_collection":
        return {"_embedded": {"underenheter": "malformed fixture collection"}}
    if mode == "child":
        child = next(item for item in companies.values() if item.get("parent") == company["organisation_number"])
        row = {"organisasjonsnummer": child["organisation_number"], "overordnetEnhet": company["organisation_number"],
            "navn": child["name"], "antallAnsatte": 3}
        # Exact duplicate source observations must become one workplace fact.
        return {"_embedded": {"underenheter": [row, dict(row)]}, "page": {"number": 0, "totalPages": 1}}
    return {"_embedded": {"underenheter": []}, "page": {"number": 0, "totalPages": 1}}


def _website_html(company: dict, *, products: bool, path: str = "/") -> bytes:
    name, org = company["name"], company["organisation_number"]
    if products:
        description = "A fictional public company site used for local Signalpost integration."
        headings = ("<h1>Acme Service Systems</h1><h2>  acme\u00a0Service   Systems </h2>"
                    "<h2>Acme Service Systems</h2><h2>Logistics Service</h2>")
        if path == "/services":
            headings = "<h1>  acme\u00a0Service   Systems </h1><h2>Logistics Service</h2>"
        elif path == "/products-two":
            headings = "<h1>Acme Service Systems</h1><h2>Cloud Platform</h2>"
        body = ("<html><head><title>Products and services</title><meta name=\"description\" content=\""
            + description + "\"></head><body>" + headings
            + "<p>Customer Acme Customer AS, organisation 100000024.</p></body></html>")
    else:
        schema = {"@context": "https://schema.org", "@type": "Organization", "name": "Fixture Brand",
            "legalName": name, "identifier": org}
        body = ("<html><head><title>" + name + "</title>"
            "<meta name=\"description\" content=\"A fictional public company site used for local Signalpost integration.\">"
            "<script type=\"application/ld+json\">" + json.dumps(schema, ensure_ascii=False, sort_keys=True) + "</script>"
            "</head><body><h1>" + name + "</h1><h2>Fixture Brand</h2><footer>" + name + "</footer>"
            "<p>Customer Acme Customer AS, organisation 100000024.</p>"
            "<a href=\"/products\">Products</a><a href=\"/products\">Services</a>"
            + ("<a href=\"/services\">Services</a><a href=\"/products-two\">More products</a>"
               if company.get("multi_page_products") else "") + "</body></html>")
    return body.encode("utf-8")


class LiveShapeTransport:
    """Deterministic response bodies; the production NetworkGateway remains active."""

    def __init__(self, companies: list[dict]):
        self.companies = {item["organisation_number"]: item for item in companies}
        self.sites = {urlsplit(item["website"]).hostname: item for item in companies if item.get("website")}
        self.calls: list[str] = []

    async def request(self, url: str, headers: dict[str, str], timeout: float):
        self.calls.append(url)
        parsed = urlsplit(url)
        host, path = parsed.hostname or "", parsed.path
        if path == "/robots.txt":
            if host == "data.brreg.no":
                return 503, {"Retry-After": "0"}, b"", url
            site = self.sites.get(host)
            if site and site["robots_mode"] == "disallow_all":
                return 200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /\n", url
            if site and site["robots_mode"] == "transport_error":
                raise OSError("deterministic fixture robots transport error")
            return 200, {"Content-Type": "text/plain"}, b"User-agent: *\nAllow: /\n", url

        if host == "data.brreg.no":
            org = path.rstrip("/").rsplit("/", 1)[-1]
            if "/enheter/" in path and path.endswith("/roller"):
                org = path.split("/enheter/")[1].split("/roller")[0]
                body = _role_body(self.companies[org], self.companies)
                return 200, {"Content-Type": "application/json"}, json.dumps(body).encode(), url
            if path.endswith("/enheter/" + org):
                body = _entity_body(self.companies[org])
                return 200, {"Content-Type": "application/json"}, json.dumps(body, ensure_ascii=False).encode(), url
            if path == "/enhetsregisteret/api/underenheter":
                org = parse_qs(parsed.query)["overordnetEnhet"][0]
                body = _subunits_body(self.companies[org], self.companies)
                return 200, {"Content-Type": "application/json"}, json.dumps(body, ensure_ascii=False).encode(), url
            if path.startswith("/regnskapsregisteret/regnskap/"):
                org = path.rsplit("/", 1)[-1]
                mode = self.companies[org]["accounts_mode"]
                if mode == "not_found":
                    return 404, {"Content-Type": "application/json"}, b"{}", url
                if mode == "server_error":
                    return 503, {"Retry-After": "0"}, b"{}", url
                if mode == "history_with_exact_duplicate":
                    recent = _accounts_record(2024, 240000, "fixture-filing-2024")
                    older = _accounts_record(2023, 210000, "fixture-filing-2023")
                    body = {"_embedded": {"regnskap": [recent, dict(recent), older]}}
                    return 200, {"Content-Type": "application/json"}, json.dumps(body).encode(), url
                return 200, {"Content-Type": "application/json"}, b"[]", url

        site = self.sites.get(host)
        if site:
            if path in {"", "/"}:
                return 200, {"Content-Type": "text/html; charset=utf-8"}, _website_html(site, products=False), url
            if path in {"/products", "/services", "/products-two"}:
                return 200, {"Content-Type": "text/html; charset=utf-8"}, _website_html(site, products=True, path=path), url
            if path == "/sitemap.xml":
                listed_pages = ["/products"]
                if site.get("multi_page_products"):
                    listed_pages.extend(["/services", "/products-two"])
                body = ("<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"
                    + "".join(f"<url><loc>https://{host}{path}</loc></url>" for path in listed_pages)
                    + "</urlset>").encode()
                return 200, {"Content-Type": "application/xml"}, body, url
        return 404, {"Content-Type": "application/json"}, b"{}", url


class SignalpostM09LiveShapeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.companies = self.fixture["companies"]

    def _run_full_pipeline(self, root: Path) -> tuple[list[dict], dict, LiveShapeTransport, NetworkGateway]:
        root.mkdir(parents=True, exist_ok=True)
        input_path = root / "input.jsonl"
        output_path, state_path, checkpoint_path = root / "output.jsonl", root / "state.json", root / "checkpoint.sqlite"
        config_path = root / "config.json"
        input_path.write_text("".join(json.dumps({"organisation_number": row["organisation_number"]}) + "\n"
            for row in self.companies), encoding="utf-8")
        config_path.write_text(json.dumps({"budget": {"hard_seconds": 120, "soft_seconds": 90,
            "completion_reserve_seconds": 15, "physical_request_limit": 500, "paid_cost_limit": "0",
            "global_http_concurrency": 8, "per_host_concurrency": 3}}), encoding="utf-8")
        transport = LiveShapeTransport(self.companies)
        gateways = []
        class FixtureGateway(NetworkGateway):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, transport=transport, **kwargs)
                gateways.append(self)

        with patch.object(run_module, "NetworkGateway", FixtureGateway), \
             patch("signalpost.network.validate_public_host", return_value=("93.184.216.34",)), \
             contextlib.redirect_stdout(io.StringIO()):
            status = run_module.main(["--input", str(input_path), "--format", "jsonl", "--live-brreg",
                "--live-websites", "--no-keyless-websites", "--config", str(config_path),
                "--evidence-cutoff", "2099-12-31T23:59:59Z",
                "--output", str(output_path), "--state-output", str(state_path), "--checkpoint", str(checkpoint_path),
                "--batch-id", "m09-live-shape-fixture"])
        self.assertEqual(status, 0)
        rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
        state = validate_artifact(json.loads(state_path.read_text(encoding="utf-8")))
        self.assertEqual(len(state.companies), len(self.companies))
        self.assertEqual(len(gateways), 1)
        return rows, state.model_dump(mode="json"), transport, gateways[0]

    def test_six_company_source_shapes_complete_production_and_publication_path(self):
        with tempfile.TemporaryDirectory(prefix="signalpost-m09-live-shape-") as temporary:
            root = Path(temporary)
            rows, state, transport, gateway = self._run_full_pipeline(root)
            self.assertEqual([row["input_ref"] for row in rows], [f"row:{i}" for i in range(1, 7)])
            self.assertEqual([row["organisation_number"] for row in rows],
                [item["organisation_number"] for item in self.companies])

            canonical_rows = []
            for index, payload in enumerate(rows, start=1):
                validate_vendor_payload(payload)
                canonical = {key: value for key, value in payload.items() if key not in {"run", "batch"}}
                canonical.update({"row_number": index, "batch_id": payload["batch"]["batch_id"],
                    "evidence_cutoff": payload["batch"]["evidence_cutoff"], "created_at": payload["run"]["created_at"]})
                envelope = validate_publication_graph(Envelope.model_validate(canonical))
                canonical_rows.append(envelope)
                self.assertEqual(to_sorted(payload["claims"], "claim_id"),
                    to_sorted([claim.model_dump(mode="json") for claim in envelope.claims], "claim_id"))

            evidence_owners: dict[str, str] = {}
            snapshot_owners: dict[str, str] = {}
            for envelope in canonical_rows:
                org = envelope.organisation_number
                evidence = {item.evidence_id: item for item in envelope.evidence}
                self.assertTrue(all(claim.organisation_number == org for claim in envelope.claims))
                for item in envelope.evidence:
                    self.assertEqual(item.subject_organisation_number, org)
                    self.assertNotIn(item.evidence_id, evidence_owners)
                    evidence_owners[item.evidence_id] = org
                for snapshot in envelope.source_snapshots:
                    self.assertNotIn(snapshot.source_id, snapshot_owners)
                    snapshot_owners[snapshot.source_id] = org
                self.assertTrue(all(ref in evidence for claim in envelope.claims for ref in claim.evidence_ids))

            by_org = {row["organisation_number"]: row for row in rows}
            acme = by_org["100000008"]
            acme_claims = acme["claims"]
            headings = [claim for claim in acme_claims if claim["field"] == "product_or_service_heading"]
            self.assertEqual({canonical_product_heading(claim["value"]) for claim in headings},
                {"acme service systems", "logistics service", "cloud platform"})
            self.assertEqual(len({claim["claim_id"] for claim in headings}), len(headings))
            heading_evidence_ids = {evidence_id for claim in headings for evidence_id in claim["evidence_ids"]}
            heading_evidence = [item for item in acme["evidence"] if item["evidence_id"] in heading_evidence_ids
                and item["json_pointer"] == "/html/body//h1|h2|h3"]
            self.assertEqual(len(heading_evidence), 6)
            self.assertEqual(len({item["evidence_id"] for item in heading_evidence}), 6)
            page_specific_heading_evidence = [item for item in heading_evidence if "/products" in item["source_url"]
                or "/services" in item["source_url"]]
            self.assertEqual(len({item["source_url"] for item in page_specific_heading_evidence}), 3)
            self.assertEqual(len({tuple(item["source_snapshot_ids"]) for item in page_specific_heading_evidence}), 3)
            page_urls = {item["source_url"] for item in page_specific_heading_evidence}
            evidence_by_id = {item["evidence_id"]: item for item in acme["evidence"]}
            for page_url in page_urls:
                same_page_equivalent_claims = [claim for claim in headings
                    if canonical_product_heading(claim["value"]) == "acme service systems"
                    and any(evidence_by_id[eid]["source_url"] == page_url
                        and evidence_by_id[eid]["json_pointer"] == "/html/body//h1|h2|h3"
                        for eid in claim["evidence_ids"])]
                self.assertEqual(len(same_page_equivalent_claims), 1)
            summary = acme["synthesis"]["summary"]["sentences"]
            factual_texts = [item["text"] for item in summary if item.get("fact_ids")]
            self.assertEqual(len(factual_texts), len(set(factual_texts)))
            normalized_heading_sentences = [item for item in summary if item.get("fact_ids")
                and item["text"].startswith("product_or_service_heading: Acme Service Systems")]
            self.assertEqual(len(normalized_heading_sentences), 1)
            self.assertGreaterEqual(len(normalized_heading_sentences[0]["fact_ids"]), 3)
            self.assertGreaterEqual(len(normalized_heading_sentences[0]["evidence_ids"]), 4)
            self.assertEqual(sum(1 for item in summary if item.get("fact_ids")
                and item["text"].startswith("product_or_service_heading: Logistics Service")), 1)
            self.assertEqual(sum(1 for item in summary if item.get("fact_ids")
                and item["text"].startswith("product_or_service_heading: Cloud Platform")), 1)

            description_claims = [claim for claim in acme_claims if claim["field"] == "website_description"]
            self.assertGreaterEqual(len(description_claims), 3)
            description_sentence = next(item for item in summary if item.get("fact_ids")
                and item["text"].startswith("website_description:"))
            self.assertEqual(len(description_sentence["fact_ids"]), len(description_claims))
            self.assertEqual(len({snapshot_id for claim in description_claims for snapshot_id in claim["source_snapshot_ids"]
                if snapshot_id.startswith("website:")}), len(description_claims))
            self.assertEqual(len([item for item in summary if item.get("fact_ids")
                and item["text"].startswith("website_description:")]), 1)

            brand_claim = next(claim for claim in acme_claims if claim["field"] == "public_brand")
            brand_evidence = [item for item in acme["evidence"] if item["evidence_id"] in brand_claim["evidence_ids"]]
            self.assertTrue(any(item["json_pointer"] == "/structured_data/Organization/name" for item in brand_evidence))
            self.assertTrue(any(item["json_pointer"] == "/html/body//h1|h2|h3" for item in brand_evidence))
            second_company = by_org["100000016"]
            for row in (acme, second_company):
                brand_sentences = [item for item in row["synthesis"]["summary"]["sentences"]
                    if item.get("fact_ids") and item["text"] == "public_brand: Fixture Brand (scope legal_entity)"]
                self.assertEqual(len(brand_sentences), 1)
            for field in ("verified_website_url", "verified_website_domain"):
                claim = next(item for item in acme_claims if item["field"] == field)
                cited = {item["evidence_id"]: item for item in acme["evidence"]}
                candidate = next(item for item in cited.values() if item["extraction_method"] == "brreg_website_candidate_v1")
                self.assertIn(candidate["evidence_id"], claim["evidence_ids"])
                self.assertTrue(set(candidate["source_snapshot_ids"]) <= set(claim["source_snapshot_ids"]))
            self.assertTrue(any(claim["field"] == "public_brand" for claim in acme_claims))
            self.assertFalse(any("100000024" in str(claim["value"]) or "Acme Customer AS" in str(claim["value"])
                for claim in acme_claims))

            finance = [claim for claim in acme_claims if claim["field_family"] == "financial"]
            revenue = [claim for claim in finance if claim["field"] == "revenue"]
            self.assertEqual(len(revenue), 2)
            self.assertEqual({claim["period_end"][:4] for claim in revenue}, {"2023", "2024"})
            self.assertEqual(acme["synthesis"]["brreg_observations"]["financial_records"], 2)
            self.assertEqual(len(acme["synthesis"]["summary"]["sentences"]),
                len({item["text"] for item in acme["synthesis"]["summary"]["sentences"]}))

            subsidiary = by_org["100000016"]
            parent_claim = next(claim for claim in subsidiary["claims"] if claim["field"] == "parent_organisation_number")
            self.assertEqual(parent_claim["value"], "100000008")
            self.assertEqual(parent_claim["organisation_number"], "100000016")
            role_holder = next((claim for claim in subsidiary["claims"] if claim["field"] == "role.holder_organisation_number"), None)
            self.assertIsNotNone(role_holder)
            self.assertEqual(role_holder["value"], "100000008")
            workplace_orgs = {claim["value"] for claim in acme_claims if claim["field"] == "workplace.organisasjonsnummer"}
            self.assertEqual(workplace_orgs, {"100000016"})
            self.assertFalse(any(claim["subject_id"] == "100000008" for claim in acme_claims if claim["field_family"] == "workplace"))

            missing = by_org["100000016"]
            self.assertEqual(missing["sections"]["accounts_history"]["state"], "not_available")
            self.assertFalse(any(claim["field_family"] == "financial" for claim in missing["claims"]))
            failed_optional = by_org["100000024"]
            self.assertEqual(failed_optional["sections"]["accounts_history"]["state"], "failed")
            self.assertEqual(failed_optional["synthesis"]["brreg_observations"]["role_family_state"], "failed")
            self.assertFalse(failed_optional["synthesis"]["brreg_observations"]["workplaces_complete"])
            self.assertFalse(any(claim["field_family"] in {"role", "workplace", "financial"}
                for claim in failed_optional["claims"]))

            blocked = by_org["100000032"]
            self.assertEqual(blocked["sections"]["website_owned_profiles"]["attempt_outcome"], "robots_disallowed")
            self.assertFalse(any(claim["section"] == "website_owned_profiles" for claim in blocked["claims"]))
            outage = by_org["100000059"]
            self.assertEqual(outage["sections"]["website_owned_profiles"]["attempt_outcome"], "robots_unreachable")
            self.assertFalse(any(claim["section"] == "website_owned_profiles" for claim in outage["claims"]))
            enk = by_org["100000040"]
            self.assertNotIn("PRIVATE_FIXTURE_HOME_ADDRESS", json.dumps(enk, sort_keys=True))
            self.assertEqual(enk["sections"]["website_owned_profiles"]["attempt_outcome"], "not_attempted")

            self.assertGreater(gateway.ledger.physical_requests, 0)
            self.assertGreater(gateway.ledger.logical_requests, 0)
            self.assertGreaterEqual(gateway.ledger.physical_requests, gateway.ledger.logical_requests)
            self.assertEqual(gateway.ledger.physical_requests, len(transport.calls))
            self.assertEqual(gateway.budget.physical_requests, gateway.ledger.physical_requests)
            self.assertTrue(any(entry.purpose == "robots" and entry.status == 503 for entry in gateway.ledger.entries))
            self.assertTrue(any(entry.purpose == "robots" and entry.outcome == "transport_error" for entry in gateway.ledger.entries))
            self.assertTrue(any(entry.purpose == "entity" and entry.status == 200 for entry in gateway.ledger.entries))
            self.assertEqual(len(state["companies"]), 6)

    def test_pipeline_identities_replay_stably_across_full_runs(self):
        with tempfile.TemporaryDirectory(prefix="signalpost-m09-identity-replay-") as temporary:
            root = Path(temporary)
            first, _state_a, _transport_a, _gateway_a = self._run_full_pipeline(root / "first")
            second, _state_b, _transport_b, _gateway_b = self._run_full_pipeline(root / "second")
            def identities(rows):
                return [{key: sorted(item[id_key] for item in row[key]) for key, id_key in
                    (("claims", "claim_id"), ("evidence", "evidence_id"), ("source_snapshots", "source_id"))}
                    for row in rows]
            self.assertEqual(identities(first), identities(second))

    def test_live_registry_status_fields_pass_closed_synthesis_and_final_publication(self):
        company = next(item for item in self.companies if item["organisation_number"] == "100000008")
        company["registry_status_fields"] = {
            "konkurs": False,
            "registrertIMvaregisteret": True,
            "underAvvikling": False,
            "underTvangsavviklingEllerTvangsopplosning": False,
            "registreringsdatoEnhetsregisteret": "2010-08-25",
            "stiftelsesdato": "2010-08-12",
        }
        company["registry_address"] = {"adresse": ["Examplegata 1"], "postnummer": "0123",
            "poststed": "OSLO", "kommunenummer": "0301", "kommune": "OSLO"}
        with tempfile.TemporaryDirectory(prefix="signalpost-m09-live-status-fields-") as temporary:
            rows, _state, _transport, _gateway = self._run_full_pipeline(Path(temporary))

        company_row = next(row for row in rows if row["organisation_number"] == "100000008")
        validate_vendor_payload(company_row)
        status = company_row["synthesis"]["brreg_observations"]["identity_profile"]["status"]
        status_fields = {key: value for key, value in company["registry_status_fields"].items()
            if key not in {"registreringsdatoEnhetsregisteret", "stiftelsesdato"}}
        self.assertEqual({key: status[key] for key in status_fields}, status_fields)
        status_dates = company_row["synthesis"]["brreg_observations"]["identity_profile"]["status_dates"]
        self.assertEqual({key: status_dates[key] for key in ("registreringsdatoEnhetsregisteret", "stiftelsesdato")},
            {key: company["registry_status_fields"][key]
                for key in ("registreringsdatoEnhetsregisteret", "stiftelsesdato")})
        status_claims = {claim["field"]: claim["value"] for claim in company_row["claims"]
            if claim["field"].startswith("status.")}
        self.assertEqual(status_claims, {f"status.{key}": value for key, value in status.items()})
        self.assertEqual(company_row["terminal_state"], "available")


def to_sorted(rows: list[dict], key: str) -> list[dict]:
    return sorted(rows, key=lambda item: item[key])


if __name__ == "__main__":
    unittest.main()
