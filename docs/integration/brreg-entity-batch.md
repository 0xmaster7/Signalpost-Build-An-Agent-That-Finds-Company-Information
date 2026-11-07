# BRREG entity batch preload

Verified against official documentation on 2026-11-07; no company endpoint,
benchmark, or live cohort was requested for this implementation.

Official source: https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html

The embedded OpenAPI 3.0.1 specification documents:

- `GET /enhetsregisteret/api/enheter`.
- Query parameter `organisasjonsnummer`: array of strings, `maxItems: 2000`,
  description **“Comma-separated list of organisation numbers, 9 digits”**,
  example `248969180,248969181` (the docs explicitly say their entities are fictional).
- `size`: page size; `page`: page number.
- HTTP 200 `application/json` schema `Enheter`, whose `_embedded.enheter`
  property is an array of `Enhet` objects.

The downloaded official documentation had SHA-256
`15cb38c3b72b1c4bb8c45a24283dcfdaef0e4ae0eea5fc006950909dc1f65d8e`.
Documentation confirms the contract; live performance and completeness were not measured.

## Parent integration

Before the existing per-company identity projection, using the same gateway:

```python
from signalpost.brreg import preload_entity_batch

loaded = await preload_entity_batch(orgs, gateway, cutoff)
# Existing fetch_company calls then consume exact cached matches automatically.
```

Default chunks contain at most 100 unique nine-digit strings, with `size` set to
that chunk's length. Invalid identifiers are excluded; ordinary caller input
validation remains authoritative. The optional `chunk_size` accepts 1–100.
The return value maps only successfully matched organisation numbers to
`EntityBatchItem`. Each item retains the actual full response bytes, parsed
response, final batch source URL, retrieval time, full-response SHA-256, and
`/_embedded/enheter/{index}` pointer. Items share their chunk's response storage.
The cache is transient and scoped to the gateway instance.

`fetch_company` projects each matched row with a prefix on every entity claim,
website-candidate evidence, and contact-lead evidence. Its source URL remains
the actual batch URL and its hash remains the hash of the actual response
bytes. No per-company response or URL is synthesized. Identity is checked when
indexing the batch and again on use. Duplicate identities are rejected even if
the rows appear identical. Missing rows, malformed responses, failures, and
unusable rows fall back to the existing individual entity endpoint; absence
from a batch is never treated as evidence of removal. Only returned exact
matches are cached, so a partial first page is safe without following server
pagination links. Cutoff eligibility remains controlled by `fetch_company`,
including its explicit current-identity option. Accounts requests remain
individual and retain their existing gateway profile and projection.

**Network policy constraint:** the helper uses `brreg_structured_api` with
purpose `entity`. Its collection allowance requires HTTPS on exactly
`data.brreg.no` (default port or 443), the exact path
`/enhetsregisteret/api/enheter`, and exactly one each of the query keys
`organisasjonsnummer` and `size`. The comma-separated list must contain 1–100
unique ASCII nine-digit organisation numbers, and `size` must equal the count
in decimal form. Credentials, fragments, extra or duplicate keys, and other
collection paths are rejected, including on redirects. Explicit robots
disallow remains binding; only robots unreachability receives the existing
structured API exception. The official host allowlist, response size cap,
request ledger, rate controls, and gateway security controls remain in force.
Blocked or failed preloads fall back to individual lookups. Parent owns
orchestration in `run.py`.

## Offline validation

Dedicated coverage is in
`signalpost-starter-kit/tests/test_signalpost_brreg_entity_batch.py`.
Run it with the local test virtualenv and `PYTHONPATH=.`. Fixtures cover actual
response provenance and resolvable pointers, chunking, fallback, foreign and
duplicate rows, identity rechecks, cutoff handling, and unchanged per-company
accounts requests. Public network requests are disabled by the test suite.
