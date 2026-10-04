# M09 cold 100-company live retry: incomplete

Date: 2026-10-04  
Live-smoke source: `c01d713a492b8000878b8c9c02bf3cde3cefb623` (clean)  
Branch: `codex/m00-contract-audit`

## Decision

The single authorized host-context live run completed the 100-row evaluator
publication path, but **M09 did not pass**. Independent inspection found four
duplicate factual synthesis sentences across two companies. The same exact
website facts were observed on different pages and had distinct valid claim IDs;
the production synthesis loop emitted one sentence per claim. This violates the
release requirement to synthesize equivalent repeated observations once.

No further live cohort was run. No M09 completion, RC1 release, push, or M10
work is authorized by this failed gate.

## Run and preserved artifacts

- Input rows: 100; terminal evaluator envelopes: 100; order/cardinality: valid.
- Identity anchors: 100/100 exact organisation-number anchors.
- Started: `2026-10-04T12:13:58.646167+00:00`; completed:
  `2026-10-04T12:19:22.403622+00:00`; measured runtime: 321.638 seconds.
- Physical requests: 470 / 2,200; logical requests: 496; all requests were in
  the centralized ledger. Hard (1,800 seconds), soft (1,350 seconds), and
  completion-reserve (300 seconds) limits were not tripped; 1,478.409 seconds
  remained after reserving completion time.
- Main raw report: `/private/tmp/signalpost-m09-rc1-cold100-c01d713.json`.
- Console capture: `/private/tmp/signalpost-m09-rc1-cold100-c01d713.console.json`.
- Preserved run bundle:
  `/private/tmp/signalpost-m09-rc1-cold100-c01d713.artifacts-artifacts`.
- Request ledger SHA-256:
  `8d4d0ba748cbc9a5f8222d761ef8a9f2fd66b26b6cdf2566475e32afffad2c3c`.
- Evaluator output SHA-256:
  `10072dcb79a03b075769746037af88b8390ac324026ca31c7ab60ede4d90345e`.
- State artifact SHA-256:
  `5f33fc00cde8a2c6be79ade58f7bcddf1cf49245877ea0c199c52d157a21c62f`.
- Checkpoint SHA-256:
  `4851d0a912c6c309d8429dde17bd02641689a164fa141eeabddb60478ea026dc`.
- Configuration SHA-256:
  `61b5c234d2c4c431dc3e8016d349614df028d348fd2f24935b35b20966310d1d`.
- Cohort SHA-256: `67c3b3903eeecdffcc294a468402351367ca549053410b7f9c1c64ee76b32e2b`.

The run produced 100 state entries keyed to the inputs, 100 evaluator round
trips, and 100 canonical envelopes with no graph-validation failures. Those
checks do not override the synthesis failure.

## Live measurements

### Identity, claims, and provenance

- All 100 rows had the exact requested organisation-number anchor.
- Available claims: 5,335. Canonical claim/evidence/snapshot validation passed
  for all 100 envelopes.
- Duplicate claim IDs: 0; duplicate evidence IDs: 0; duplicate snapshot IDs: 0;
  duplicate history event IDs: 0. Cross-envelope evidence and snapshot ID reuse:
  0 each.
- The publication-graph check reported no wrong-company evidence bindings.
  This is a structural result for this cohort, not a population-wide precision
  estimate.
- Preserved frozen-registry aggregate-snapshot handling was exercised by the
  canonical graph validator as designed.

### Synthesis gate failure

- Row 11, organisation `987709324`, repeated the sentences for
  `product_or_service_heading: BioBank AS` and
  `product_or_service_heading: Tjenester`. Each fact had two distinct page
  claims and page-specific evidence, plus the shared identity proof.
- Row 57, organisation `917065101`, repeated two exact `website_description`
  sentences. Each description occurred under distinct page claim IDs.
- Total: 2 rows, 4 duplicated factual sentence texts, and 4 excess sentence
  instances.
- The deterministic six-company live-shape gate had distinct headings on a
  page and duplicate IDs/provenance coverage, but did not model an identical
  semantic fact repeated across separate pages with page-specific claim IDs.
  Thus it did not model the actual cross-page synthesis case.
- Source claims and their IDs were valid. The defect was in synthesis grouping
  and validation, not identity attribution or source provenance.

### Financials, roles, and workplaces

- 283 financial filing records preserved; 1,875 metric claims across 100
  companies; unsupported financial publications: 0. Currency observations:
  1,854 NOK and 21 USD.
- Role rows: 420 across 100 companies; workplace rows: 87; workplace lists:
  75 complete, 25 incomplete; invalid workplace attributions: 0.
- Group lookups: 0. Hiring/activity requests were not attempted for all 100
  rows; jobs/activity are `NOT_MEASURED` for this cohort.

### Website and network results

- Available website claims: 17 (14 `owned_web`, 3 `owned_profile`); structural
  wrong-company subject/evidence bindings: 0. Human precision and
  population-wide recall were not measured.
- Website pages: 27 HTTP 200, 5 HTTP 301, 1 HTTP 500. Robots: 8 HTTP 200, 3
  HTTP 301, 12 transport failures; no explicit disallow was reported. Sitemap:
  6 HTTP 200, 1 HTTP 301. Company-owned feed: 7 HTTP 200.
- Website result states: 2 completed, 2 ambiguous, 1 failed, 46
  `robots_unreachable`, and 49 not attempted. The failed robots retrievals
  remain distinct from explicit disallows; fail-closed behavior remained in
  effect.
- Source transport and availability outcomes were not converted to factual
  absence.
- Paid API usage: none. Model usage: none. Declared external cost: $0.

## Harness accounting correction

The preserved raw report also marked `only_authorized_source_classes` false.
Its request-purpose allowlist omitted `feed`, even though the existing approved
exact-company-owned website path fetches company feeds through the centralized
gateway under source-rights policy. The seven `feed` requests were all HTTP 200.
This was a smoke-validator false negative; the original JSON is preserved
unchanged. The validator now includes the narrowly scoped `feed` purpose only
when live websites are enabled. It still rejects `feed` in the BRREG-only mode
and does not allow search or browser requests.

The original validator also counted website families under names not used by
the canonical publication model (`website`, `jobs`, `public_activity`), causing
it to report zero external claims despite the 17 available `owned_web` and
`owned_profile` claims. The local validator now recognizes the canonical
families and checks their company/evidence binding.

An offline recheck of the preserved request ledger against the corrected
allowlist passes: the eight recorded purposes are authorized for this
live-websites configuration, and recorded physical/logical totals match the
ledger (470 / 496). The corrected structural website audit finds 17 available
claims and zero wrong-company subject/evidence bindings.

## Local remediation

Synthesis now groups exact identical factual sentences, preserves the sorted
set of all supporting claim IDs and evidence IDs, and requires each referenced
claim to have at least one cited item of its own evidence. The synthesis
validator rejects repeated factual sentence text, repeated claim references,
unsupported wording, foreign-company facts, and citations that do not support
each referenced claim.

Regression tests model identical website heading/description facts from two
different page URLs with page-specific claim IDs. The tests require one
sentence with both claim references and both evidence references, and verify
that incomplete citations and reintroduced duplicate sentences fail closed.
The focused M08/M09 test run passed 46 tests. The complete unittest suite
passed **357 tests and 69 subtests** in 124.711 seconds; `compileall` and
`git diff --check` also passed. No second live run will be made. The
remediation is committed locally; release completion and remote publication
remain stopped because this live gate failed.
