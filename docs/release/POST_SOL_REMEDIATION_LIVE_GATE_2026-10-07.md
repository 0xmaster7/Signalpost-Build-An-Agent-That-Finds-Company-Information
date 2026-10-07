# RC1 post-Sol remediation live gate — 2026-10-07

Status: the fixed-cohort live safety and publication gates passed on the clean remediation source. This report is distinct from the original RC1 live report and does not rewrite it. No independent Sol verification audit is claimed.

## Run identity and artifacts

- Live-run SHA: `43dc4cb32d5a3b2f2e50796049c81b4a16ca383f` (`codex/m00-contract-audit`), clean at run start.
- Fixed input: `signalpost-starter-kit/tests/fixtures/m02/foundation-input.jsonl`, 100 rows, SHA-256 `67c3b3903eeecdffcc294a468402351367ca549053410b7f9c1c64ee76b32e2b`.
- Configuration SHA-256: `61b5c234d2c4c431dc3e8016d349614df028d348fd2f24935b35b20966310d1d`.
- Full sanitized runner report: [POST_SOL_REMEDIATION_LIVE_SMOKE_2026-10-07.json](POST_SOL_REMEDIATION_LIVE_SMOKE_2026-10-07.json).
- Durable hashes and measured-count receipt: [POST_SOL_REMEDIATION_LIVE_EVIDENCE_2026-10-07.json](POST_SOL_REMEDIATION_LIVE_EVIDENCE_2026-10-07.json).
- The 12 MB evaluator output and state/checkpoint files remain in the host's temporary artifact bundle; they are not checked into the repository. Their exact hashes, sizes, ledger hash, publication marker hash, stdout hash, and bundle-manifest hash are recorded in the runner report and receipt. Every artifact in the temporary bundle manifest was rehashed and matched before packaging.

## Live gate results

- Input/output: **100 → 100** terminal envelopes, in input order; all 100 exact organisation-number anchors matched; state contains all 100 companies.
- Final publication: all 100 serialized through the production evaluator adapter; all 100 reconstituted, canonically validated, and serialized again offline. Batch publication-graph validation passed. There were 3,449 claim objects, 7,590 evidence records, and 388 snapshots; no duplicate claim, evidence, or snapshot IDs across these rows. No refresh/history events were emitted, so history-event collision behavior was not exercised by this cohort.
- Paired publication: marker status is `committed`; the output and state hashes in the marker match the preserved run artifacts. The state artifact validates for 100 companies.
- Website ownership: 51 candidates; 1 accepted site/domain; 3 ambiguous; 46 `robots_unreachable`; 1 source `unreachable`. The accepted target had six `owned_web` claims and zero `owned_profile` claims. There were zero demonstrated wrong-company publications. The accepted proof bound organisation `987709324` to `BIOBANK AS` and its registered postcode/municipality on `https://biobank.no/kontakt/`; it marked `shared_domain=false`, had no conflicting subject IDs, and did not rely on a matching JSON-LD Organization (`json_ld_subject_match=false`). The other 3 ambiguous candidates were withheld. A human precision review was not performed.
- Financials: 283 records were preserved; **zero financial metric claims were published**; zero unsupported financial claims passed publication. There were 1,875 `BRREG_FINANCIAL_UNIT_UNSUPPORTED` errors and no `financial_record.raw_unit` metadata claims for the 283 records. The runner uses one combined error for missing/unsupported/conflicting units, and raw source response bodies are not retained, so the exact split among those subreasons and any metric-level raw unit values is **not measurable from this run's durable output**. Currency was not substituted as a unit. No TNOK or other scaled-unit metric was published; zero-value metric behavior was not measured live. This is a material recall limitation, not a numeric correctness failure.
- Roles/workplaces: 420 role rows; all 100 role collections were reported complete with completeness evidence; role-family state was available for all 100; CEO state was available for 68 and not available for 32. No `ended_role` event occurred. Twenty-five subunit/workplace responses were malformed and remained identified as errors; no invalid workplace attribution was published. Group lookups were not performed.
- Jobs/activity: zero current job candidates/publications. On the one accepted site, activity candidates were not published (5 undated and 7 outside the configured window). These observations do not establish population recall.
- Source rights: all 51 website candidates carried `unknown_not_reviewed`; no explicit blocked host was configured in the established smoke config. Unknown remained explicitly labeled and was not presented as an affirmative license. The deterministic suite separately verifies that an explicit block prevents network setup.

## Network and resources

- Physical requests: **459 / 2,200**. Logical requests: **485**. The preserved ledger matches these counts; all observed purposes were `accounts` 100, `entity` 100, `feed` 2, `robots` 23, `roles` 100, `sitemap` 6, `subunits` 100, and `website_page` 28.
- Runtime: **348.32 seconds**. Hard deadline (1,800 seconds) and soft deadline (1,350 seconds) were not reached. Completion reserve remaining: **1,451.68 seconds**. Paid/model/provider use: none.
- Robots outcomes: 8 HTTP 200, 3 HTTP 301, 12 transport errors; no explicit robots disallow response was recorded. The 46 `robots_unreachable` candidate decisions remained fail-closed. Website source outcomes included 22 HTTP 200, 5 HTTP 301, and 1 HTTP 500; BRREG entity/accounts/roles/subunits requests returned 200.

## Findings exercised

| Finding | Live result | Deterministic-only or limitation |
|---|---|---|
| A01 ownership | One accepted, target-bound site; 6 owned-web claims; 0 wrong-company bindings. | Rival-footer, multi-company, conflicting identity, and ownership-proof mutation cases remain covered by the Sol/live-shape suites. JSON-LD was not the accepted site's proof. |
| A02 provenance IDs | Batch validator passed; zero claim/evidence/snapshot ID collisions. | Subject-bound evidence and shareable snapshot mutations remain covered offline. |
| A03 financial units | Zero metric publications; 1,875 candidate metric values withheld; no currency-only publication. | Exact missing/unsupported/conflict breakdown and source-level metric units were not retained by the runner. Unit parsing, TNOK inheritance, and conflict rules are deterministic tests. |
| A04 roles | 100 complete role collections; no removals. | A malformed live roles response was not observed; incomplete-response/removal mutation is covered by M07 and Sol tests. |
| A05 final boundary | Production evaluator serialization and offline reconstruction/serialization passed for all 100; batch graph passed. | Adversarial content mutations remain deterministic tests. |
| A06 input cardinality | 100 input rows produced 100 ordered envelopes. | Strict malformed-CSV behavior is deterministic-only. |
| A07 frozen hash exception | No frozen registry was used (`registry_snapshot_sha256` is null). | Spoof and exact-exception checks are deterministic-only. |
| A08 numeric equivalence | Not exercised by the live data path. | Integer/float Decimal equivalence and dimension checks are deterministic M08 tests. |
| A09 job freshness | No live job candidates. | Historical/unknown job behavior is deterministic-only. |
| A10 output aliases | Run output/state were distinct and published successfully. | Input/symlink alias rejection is deterministic-only. |
| A11 paired publication | Live marker committed and both hashes matched. | Failure-between-writes injection is deterministic-only. |
| A12 evidence retention | Durable report/receipt and hashes were packaged; raw bundle remains outside Git. | Packaging gate revalidates the receipt/report linkage and hash formats. |
| A13 source rights | Unknown status recorded for all candidates; no configured explicit block. | Explicitly blocked-source behavior is deterministic-only. |

## Verification and release status

The smoke runner reported no hard-gate failures. Offline post-run validation rechecked manifest member hashes, exact input order, all 100 envelopes, evaluator adapter round trips, batch provenance, state artifact, and paired marker hashes. The request ledger contains exactly 459 entries, and its per-purpose counts reconcile with all 459 physical requests. The complete offline suite passed with **383 tests**; M09 live-shape (2), M07, M08, UX/XSS, crash/resume, input matrix, adapter mutations, publication failure injection, and clean-install launcher are included. The 1,000/1,200/10,000 offline scale gate passed with network disabled. The durable evidence packaging gate, compileall, and `git diff --check` passed.

The original M09 live run remains historical. Its report and measurements are unchanged and are not substituted for this post-Sol run. This report does not claim that an independent Sol verification audit passed.
