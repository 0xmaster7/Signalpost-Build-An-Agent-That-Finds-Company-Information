# M09 final live smoke — PASS

## Run identity and configuration

- Branch: `codex/m00-contract-audit`.
- Frozen live source SHA: `9ab896f9f7f39a85f2dd26a09970c9a5d8f42194`.
- Source tree at run start: clean; the smoke report records `working_tree_dirty=false` and the empty-diff SHA-256.
- Run ID: `m09-rc1-cold-100`; mode: live BRREG plus bounded exact-company websites (`--live-websites`).
- Input: `signalpost-starter-kit/tests/fixtures/m02/foundation-input.jsonl`, exactly 100 rows; SHA-256 `67c3b3903eeecdffcc294a468402351367ca549053410b7f9c1c64ee76b32e2b`.
- Configuration SHA-256: `61b5c234d2c4c431dc3e8016d349614df028d348fd2f24935b35b20966310d1d`.
- Started: `2026-10-04T23:08:05.707298Z`; completed: `2026-10-04T23:13:19.836425Z`.

## Terminal output and identity

- Input rows: **100**; terminal evaluator envelopes: **100**; state entries: **100**.
- Input order and one-envelope-per-row cardinality: **PASS**.
- Exact organisation-number identity anchors: **100/100**.
- Terminal state: 100 `available`; source-specific unavailable/incomplete results remain visible in section states and errors.
- Hard-gate failures: **0**. Recorded error codes/counts: `BRREG_POST_CUTOFF_EXCLUDED=100`, `BRREG_SUBUNITS_MALFORMED=25`, `ROBOTS_UNREACHABLE=46`; these do not convert source unavailability/incompleteness into factual zeros or absence.
- Canonical envelope, publication graph, evaluator adapter, and round-trip validation: **100/100 PASS**.
- Available claims: **5,335**. Duplicate claim IDs: **0**; duplicate evidence IDs: **0**; duplicate snapshot IDs: **0**; duplicate history event IDs: **0**.
- Cross-envelope evidence reuse: **0**; cross-envelope snapshot reuse: **0**. No wrong-company claim/evidence/snapshot/synthesis binding was found in this cohort.
- Claim → evidence → snapshot URL/hash/company bindings and required snapshots: **PASS** for all available claims. The frozen-registry aggregate-snapshot exception remains limited to its documented use.

These are structural observations for the fixed cohort, not population-wide identity precision estimates. No human-adjudicated accepted-domain review was performed during this run.

## Synthesis multiplicity and citations

- Synthesis sentences: **5,331** for 5,335 available claims.
- Duplicate factual sentence excess within a company: **0**.
- Four repeated facts recurred in their original rows: two product headings for organisation `987709324` and two descriptions for `917065101`. Each now appears once with both supporting claim IDs and the union of three evidence citations.
- Every referenced claim resolves in the same envelope, its evidence is company-bound, and required snapshots validate: **PASS**.
- The actual output was reconstituted into canonical envelopes and checked with current synthesis validation, final publication-graph validation, and evaluator serialization. Round-trip payload differences: **0**.
- The same sentence text appeared across multiple companies in **73** distinct cases (2,299 company instances); every company instance retained its own claim and evidence references. No synthesis deduplication crossed envelope boundaries.
- Distinct facts remain separately represented; synthesis remains envelope-local. The production-path multi-page fixture separately covers normalized equivalent facts, distinct facts, same-company page repeats, structured plus visible evidence, and cross-company isolation.

## Financials, roles, workplaces, and websites

- Financial history: **283 filing records**, with **1,875** available metric claims across all 100 companies; 1,854 NOK and 21 USD. Periods represented: 2023 (595 metric claims), 2024 (621), and 2025 (659). Legitimate zero values preserved: 66. Unsupported or malformed financial publications: **0**.
- Role rows: **420** across 100 companies. CEO role state: 68 available, 32 not available. Group lookups: **0**; group/parent relationship behavior was therefore not measured live.
- Workplace rows: **87**; 75 complete and 25 incomplete workplace lists. Invalid workplace attributions: **0**. Incomplete collections were not treated as complete lists.
- Available website claims: **17** (14 `owned_web`, 3 `owned_profile`); structurally wrong-company subject/evidence bindings: **0**. Human precision and population recall were not measured.
- Jobs and public activity: **NOT_MEASURED**; no claims were published for these families.

## Network and resources

- Physical requests: **470**; logical requests: **496**; physical ledger entries: **470**, matching the gateway physical count. Logical and physical counters agree with the run report; no physical request was missing from the ledger.
- Purposes: `accounts=100`, `entity=100`, `feed=7`, `robots=23`, `roles=100`, `sitemap=7`, `subunits=100`, `website_page=33`. Every purpose is in the approved policy constants for the enabled sources; no unapproved purpose occurred.
- BRREG host requests: 402; website hosts: 68 combined. Centralized gateway, host allowlisting, DNS/SSRF, redirect, source-rights, and request-accounting controls remained enabled.
- Robots: 8 HTTP 200, 3 HTTP 301, 12 transport failures, 0 explicit disallows. The transport failures remained distinct (`ROBOTS_UNREACHABLE`) and ordinary website crawling stayed fail closed.
- Website pages: 27 HTTP 200, 5 HTTP 301, 1 HTTP 500. Sitemaps: 6 HTTP 200, 1 HTTP 301. Feeds: 7 HTTP 200.
- Runtime: **311.567 seconds** in the resource report (**311.620 seconds** in the process runtime field); both are under the 1,350-second soft deadline and 1,800-second hard deadline. `soft_expired=false`, `hard_expired=false`, `completion_reserve_active=false`; 1,488.433 seconds remained to the hard deadline, exceeding the 300-second reserve.
- Physical request ceiling: 2,200; observed: 470. Per-host concurrency cap: 2; global HTTP concurrency: 32. Reserve and request limits were not exhausted.
- Declared third-party cost: **$0**; model usage: **none**; paid API usage: **none**.

## Preserved evidence

All artifacts are preserved under `/private/tmp/signalpost-m09-final-cold100-9ab896f.artifacts-artifacts`.

| Artifact | SHA-256 |
|---|---|
| Run report `/private/tmp/signalpost-m09-final-cold100-9ab896f.json` | `4966551ce9ebd0f22153af756ae669347e63e1b105bebb0a1a75a2dccdf277e7` |
| Evaluator output `run/output.jsonl` | `1af571fe6f621360c9c7b5b74713116dbeab908edd685c7caac92eeb5455ea14` |
| State `run/state.sqlite` | `0271fe9bf9d776a13cb6af06167ca79171dd7b2617d0f5f629da026b49c763b7` |
| Checkpoint `run/state.sqlite.checkpoint.sqlite` | `01ad9354bb651985ff1aa7da04ce48078a09b4e94e7fe8f4f8d283b6a95bcfdb` |
| Request ledger `request-ledger.json` | `9133629ff814d87e82c4e893a6db9209a6c1b459d9c605ecfc19ee02e00174ab` |
| Artifact manifest `manifest.json` | `933cc46868d1b1fbfd47285c713d6308619483c6418631594846ba024e1307b5` |
| Captured run stdout `stdout.log` | `40446359edc3318f2f7c227c90d1cef6edc5de06d491e1297dd9b5c4cbbf08fe` |
| Configuration `run/config.json` | `61b5c234d2c4c431dc3e8016d349614df028d348fd2f24935b35b20966310d1d` |

The command's console JSON and report JSON are byte-identical, SHA-256 `4966551ce9ebd0f22153af756ae669347e63e1b105bebb0a1a75a2dccdf277e7`.

## Measurement boundary

Live measurements describe this 100-company cohort only. Deterministic fixtures validate adversarial identity, citation, and synthesis shapes. Scheduler and 1,000/1,200/10,000-row runner measurements are offline. None estimates population-wide precision, recall, or production-scale UX latency. The earlier failed M09 reports remain unchanged as historical evidence.
