# OFFLINE REPLAY OF PRESERVED LIVE DATA

Date: 2026-10-04
Replay implementation SHA: `f400ec096a47dcacddc0fcfa8eead78e1a1f7a33`
Replay working tree: clean
Branch: `codex/m00-contract-audit`

This report documents an offline replay of the post-retrieval stages from the
preserved M09 cohort. It is not a successful live smoke and does not replace a
future, separately authorized live run.

## Preserved live source and artifacts

- Live source SHA: `c01d713a492b8000878b8c9c02bf3cde3cefb623` (clean at run time).
- Cohort/input SHA-256: `67c3b3903eeecdffcc294a468402351367ca549053410b7f9c1c64ee76b32e2b`.
- Configuration SHA-256: `61b5c234d2c4c431dc3e8016d349614df028d348fd2f24935b35b20966310d1d`.
- Preserved evaluator JSONL SHA-256:
  `10072dcb79a03b075769746037af88b8390ac324026ca31c7ab60ede4d90345e`.
- Preserved state SHA-256:
  `5f33fc00cde8a2c6be79ade58f7bcddf1cf49245877ea0c199c52d157a21c62f`.
- Preserved checkpoint SHA-256:
  `4851d0a912c6c309d8429dde17bd02641689a164fa141eeabddb60478ea026dc`.
- Preserved request-ledger SHA-256:
  `8d4d0ba748cbc9a5f8222d761ef8a9f2fd66b26b6cdf2566475e32afffad2c3c`.
- Preserved bundle:
  `/private/tmp/signalpost-m09-rc1-cold100-c01d713.artifacts-artifacts`.

The replay input was the actual 100-row `run/output.jsonl` from that bundle.
Each row was reconstructed as a canonical `Envelope` from its saved claims,
evidence, snapshots, sections, refresh data, and metadata. No source data was
fabricated and no network access was used. Preserved files were not altered.

## Stages replayed and results

For all 100 preserved envelopes, the replay ran:

1. Canonical model validation and final publication-graph validation.
2. Current `synthesize()` over the saved canonical claims and evidence.
3. Current synthesis support and citation-completeness validation.
4. `to_evaluator()` serialization, including its final graph validation, then
   evaluator-envelope validation.
5. Structural checks for cross-company ownership, unique IDs, and financial
   publication metadata.

Results:

- Envelopes replayed: **100/100**.
- Claims: **5,335**, all available in this preserved cohort.
- Factual synthesis sentences after replay: **5,331**.
- Duplicate factual sentence texts after replay: **0**.
- Canonical envelope/publication graph failures: **0**.
- Synthesis/citation-completeness failures: **0**.
- Evaluator serialization/adapter failures: **0**.
- Unique claim IDs, evidence IDs, snapshot IDs, and history event IDs: **pass**.
- Structural wrong-company failures: **0**.
- Unsupported financial publications: **0**.

The saved pre-fix synthesis contained the exact four excess duplicate sentence
instances that failed the live gate: two product headings for organisation
`987709324` and two website descriptions for organisation `917065101`. Current
synthesis emits each of those sentences once. Supporting claim IDs and the
union of all their evidence IDs remain on each deduplicated sentence; removing
any referenced claim's evidence now fails validation.

The replayed evaluator JSONL is preserved at
`/private/tmp/signalpost-m09-preserved-cohort-replay-f400ec0-output.jsonl` with
SHA-256 `846da7440cba84f426ab4a04360ef140b594ab53141c2ed1f522a49649fa5893`.
Machine-readable replay measurements are at
`/private/tmp/signalpost-m09-preserved-cohort-replay-f400ec0-report.json`.

## Multi-page production-path live-shape corpus

The deterministic six-company test still runs the production CLI, gateway,
robots checks, site identity verifier, page parser, canonical claim/evidence/
snapshot construction, synthesis, evaluator serialization, graph validation,
and state publication. Only HTTP transport is replaced by deterministic
source-shaped fixtures.

The target company fixture now serves three separate product/service URLs and
exercises all requested multiplicity cases:

- Exact product facts repeated across pages, with distinct page-specific
  claims, evidence, and snapshots.
- One repeated description on the home page and product pages.
- A case/whitespace/NFKC-equivalent product heading under the established
  canonical heading rule.
- Two genuinely distinct headings retained as two separate sentences.
- An exact duplicate heading on one page collapsed by the production page
  extractor, plus repeated observations across multiple pages grouped by
  synthesis.
- Three or more claims and evidence records supporting the same fact, all
  retained and required by citation validation.
- Structured Organization brand data and matching visible text retained as
  distinct evidence for the same canonical brand claim.
- The same brand sentence emitted once independently for two companies; no
  cross-envelope deduplication occurs.

The full production-path integration test passes. It verifies the synthesized
sentences and their claim/evidence multiplicity after the complete run.

## Synthesis contract and mutation coverage

Semantic grouping is scoped to one company envelope and includes subject,
section, family, field, value, and dimensions. Product headings use the same
Unicode, whitespace, and case normalization helper as website claim identity.
Each factual sentence retains all grouped fact IDs and the complete union of
their evidence IDs. Validation rejects combining different canonical facts,
repeated claim references, a second sentence for an existing fact, incomplete
or unrelated citations, missing claims, foreign-company evidence, and altered
wording.

The regression suite covers removed citations, nonexistent claims, foreign
company citations, duplicate sentences, altered wording, distinct facts, and
normalized equivalent headings. It confirms all cited evidence resolves to
same-company records and required snapshots through the canonical graph.

## Smoke-validator and ledger audit

The request-purpose allowlist is built from the approved BRREG API-purpose set
in the network policy and the approved website-purpose set in the website
implementation. Website purposes are included only for a live-websites run.
Regression tests verify the BRREG-only and website-enabled sets exactly match
those producer policy constants and reject unapproved purposes. The external
claim audit uses the canonical producer family names (`owned_web`,
`owned_profile`, `jobs`, `public_activity`); the production-path test exercises
the website families and keeps same-named text isolated by envelope.

Offline ledger recheck:

- Physical ledger entries: **470**; logical calls: **496**; logical minus
  physical: **26** policy/cache-stage calls that did not result in physical
  transport. No budget or deadline limit was exhausted.
- Ledger physical/logical totals match the preserved run report; purpose and
  host tallies independently match the report. Every observed physical request
  is represented by one ledger entry.
- All eight observed purposes are approved for this configuration:
  `entity=100`, `accounts=100`, `roles=100`, `subunits=100`, `website_page=33`,
  `robots=23`, `sitemap=7`, `feed=7`.
- Physical request ceiling: 2,200; observed: **470**. Run time was 321.638
  seconds against the 1,800-second hard limit. Soft deadline and 300-second
  completion reserve were not tripped.
- Robots entries remain separated as 8 HTTP 200 responses, 3 HTTP 301
  responses, and 12 transport failures. A transport failure is not recorded as
  an explicit disallow.
- No unaccounted physical request or request-policy bypass was found in the
  preserved report/ledger comparison. The production gateway architecture
  regression also passes.

## Deterministic release gates

- Complete unittest suite: **358 tests passed; 69 subtests passed** in 132.916
  seconds.
- Focused M09 suite: **12 passed**.
- Extended live-shape integration: **2 passed**, including the multi-page
  production-path corpus.
- M08 synthesis and mutation tests: passed within the full suite.
- M07 refresh replay: **PASS**; 12 rows, 6 expected events, 0 false positives,
  0 false negatives, complete provenance, stable event IDs.
- M08 gold: **PASS**; find, compare, and verify accuracy 1.0; zero unsupported
  assertions; citation completeness 1.0.
- M08 local UX/XSS smoke on the replayed 100-company output: **PASS** for
  launch, profile, evidence, compare, verify, changes, and XSS escaping.
- Crash/resume at 25%, 50%, and 90% durable checkpoints: **PASS**; all three
  resumed outputs matched uninterrupted semantics.
- Offline scale: **PASS**; 1,000 and 1,200 ordered operational rows and 10,000
  distinct ordered offline rows, with zero physical requests. Operational
  writer runtimes were 5.952 s, 6.666 s, and 56.721 s respectively. Scheduler
  simulations and all four budget stress modes preserved official
  cardinality.
- Clean-install launcher from `/private/tmp` with `PYTHONPATH` unset and a
  frozen local registry row: **PASS**, one ordered available envelope, zero
  physical requests.
- Evaluator adapter and final graph validation: **PASS** for all 100 replayed
  envelopes.
- `compileall`: **PASS**. `git diff --check`: **PASS**.

## Limits and release disposition

This replay starts from saved canonical post-retrieval data. It does not repeat
BRREG retrieval, website fetches, robots retrieval, page parsing, or the live
cohort. Deterministic fixtures establish the new page-multiplicity structural
case; the 100-row replay establishes that the preserved real claims/evidence
now synthesize without the four observed duplicates. Neither proves
population-wide recall or identity precision. Jobs/activity remain
`NOT_MEASURED` in the preserved live cohort.

No new external network traffic was made during this hardening/replay phase.
No live cohort was started, no push or CI run was performed, and M10 was not
started. This report and implementation do not constitute M09 live-smoke
acceptance; another cohort requires the user's separate authorization.
