# M11 calibration, ablation, and holdout report

Date: 2026-10-10
Evaluation source SHA: `fccd18d2f4f92c157aa76cffac78ada9636ba2a7`
Branch: `codex/signalpost-m11`

## Decision summary

No production revision was justified. The measured optional discovery path added no exact-company coverage, the jobs/activity sample published no claims, and every proposed additional source or provider either lacks required rights/semantics, has no reproducible configuration, or would require authorization not present here. No verification threshold was changed. This is an evidence-based rejection of unsupported candidate changes, not a claim that recall improved.

Official Builderr feedback for this repository is unavailable: no score, adjudicated error list, or run-specific labels were supplied. The current public challenge page reports an aggregate board only (reviewed 2026-10-05: 28 assessed entries, none qualified); it does not identify a Signalpost run or provide company-level labels. No score is inferred from it. No Builderr message was sent and no submission was made.

## Development report

The frozen development/opportunity cohort is `docs/audit/m00-company-sample-200.jsonl`, SHA-256 `cee97e17af7e8b2d9dc9f5ee60548b9e186a11a2e485469446219ea10a1e38ed` (200 companies). It was already used for M03/M04/M05; it is not an independent holdout and was not relabelled as one.

The recorded registry-only versus registry-plus-keyless comparison found:

| Variant | Candidate sites | Accepted exact domains | Wrong-company promotions | Physical / logical requests | Recorded runtime |
|---|---:|---:|---:|---:|---:|
| Registry-only | 21 | 1 | 0 | 91 / 72 | 71.330 s |
| Registry + one bounded keyless `.no` candidate | 98 | 1 | 0 | 94 / 149 | 68.711 s |

The keyless path added 77 candidates and 3 physical requests, but added zero accepted domains and zero company coverage. The runtime difference is not treated as a performance gain because these were separate live runs. Search was disabled and returned no candidates because no reproducible, rights-approved provider was configured. Source: `docs/audit/m04-discovery-benchmark.json` and `docs/audit/m04-discovery-method.md`.

The M05 200-company exact-site/jobs/activity run reported 96 physical and 152 logical requests in 68.844 s, 80 `ROBOTS_UNREACHABLE` outcomes, zero published job claims, zero activity claims, and zero newly covered companies. It is a historical cohort measurement, not a precision estimate or current-code live result. Source: `docs/audit/m05-external-footprint-benchmark.json` and `docs/audit/m05-external-footprint-method.md`.

## Ablation ledger

| Component / ablation | Evidence available | M11 result |
|---|---|---|
| Frozen/registry baseline | The M04 registry-only website candidate path is measured above; there is no comparable company-fact score or evaluator label set. | Keep as baseline; do not claim a recall score. |
| Live structured BRREG | Historical 100-company post-Sol report at SHA `43dc4cb32d5a3b2f2e50796049c81b4a16ca383f`: exact identity and roles were measured; financial candidate metrics remained withheld for unit/scale gaps. This predates the current source SHA. | No safe scale inference or current-code gain can be claimed. |
| Registry website verification | M04 registry-only path: 1 accepted exact domain among 21 candidates; zero observed wrong-company promotions in that cohort. | Preserve deterministic identity gate. |
| Sitemap/feed shallow work | Present in broader M04/M05 runs but not isolated as a comparable variant. Historical post-Sol 100 run observed 6 sitemap and 2 feed requests; no family gain is attributable to that isolated path. | `NOT_ISOLATED`; no threshold or budget change. |
| Keyless discovery | M04 ablation above: +77 candidate domains, 0 exact-domain gain. | Do not expand beyond the bounded candidate rule. |
| Search provider | Disabled; no provider or reproducible approved credential is configured. | `NOT_RUN`; not a zero-recall result. |
| Jobs/activity | M05 200-company sample: 0 job and 0 activity claims; source reach was limited, including robots transport failures. | `NOT_MEASURED_FOR_POPULATION`; do not publish absence from skipped/unreachable sources. |
| Annual-account PDF | The M10 source-contract review found endpoint/document reuse and retention rights unresolved, and no standardized extraction contract. No PDF was acquired in M11. | `BLOCKED_BY_RIGHTS_AND_SEMANTICS`; no extraction experiment. |
| Cheap/strong model | No Builderr model key or authorized model budget is available; paid services are not approved. | `NOT_RUN`; no credential or paid call. |

## Validation and calibration report

The M11 identity verifier uses deterministic evidence predicates, not a probabilistic acceptance threshold. An accepted website must satisfy the audited subject-scoped organisation-number/legal-name rule or the documented exact-name/address-plus-independent-signal path, with the shared-domain and conflicting-subject guards. The serialized verification score of `1.0` denotes a passed deterministic rule; it is not a calibrated probability. There is no observable numeric identity cutoff to tune without changing the publication policy.

Financial publication remains an explicit unit/currency/scope validation gate. Since the authoritative structured source still lacks a documented scale contract, raising recall by admitting unlabeled values would violate the financial safety boundary. The M10 report remains the source decision and fallback.

Error taxonomy from available evidence:

- **Identity/publication:** zero observed wrong-company promotions in the recorded M04/M05 cohorts; this is sample evidence, not a population precision claim.
- **Website access:** robots transport/server failures remain `ROBOTS_UNREACHABLE` and fail closed. They are not disallows and not permission to crawl.
- **Financial semantics:** the post-Sol report records 1,875 unit-withheld candidate metrics, but its then-current source response artifacts did not provide an auditable field-level scale breakdown. Do not infer a recoverable amount.
- **Jobs/activity coverage:** no claims in the 200-company M05 run; the denominator and source reach do not support a precision/recall estimate.
- **Provider/rights:** search and models are unavailable by policy/configuration; PDFs are not authorized. These are unavailable experiments, not measured failures.

## Zero-overlap holdout/regression replay

Re-ran the available M08 four-profile gold evaluation at evaluation source SHA `fccd18d2f4f92c157aa76cffac78ada9636ba2a7` using the checked-in harness. Result: find accuracy 1.0, compare accuracy 1.0, verify accuracy 1.0, unsupported assertions 0, citation completeness 1.0. Gold SHA-256: `28bf4eb40d80723c787bfc57de16a8ef8046657c5e0fe74ef6bd0f119baea05c`; canonical corpus SHA-256: `36874e3c642561d740d6563aa39f442d4bfe551789e0decd98a915a5e4baba75`.

The four fixture organisation numbers (`001234567`, `123456789`, `923609016`, `923609025`) have zero overlap with the 200-company development cohort. This is a zero-overlap **query/evaluator regression**, not a real-company source-extraction or identity-threshold holdout: the profiles use `.example.test` fixture sources and must not be treated as coverage or precision observations.

The M07 12-scenario recorded refresh replay also passed on the current evaluation SHA: 6 expected/produced changes, TP=6, FP=0, FN=0, complete event provenance, deterministic IDs, and idempotent repeat. This validates refresh regression behavior, not external factual coverage.

No independent human-adjudicated real-company zero-overlap holdout exists in the repository. Therefore no real-world identity precision, website threshold calibration, family recall, or official score is reported. No existing live cohort was re-run and no new external traffic was generated.

## Promotion decision

The largest measured potential gap is external recall, but the measured candidate paths do not support a safe code change: keyless discovery adds candidates without accepted companies; robots transport remains fail-closed; the structured financial source has no authoritative scale; PDF rights/extraction are unresolved; and jobs/activity have no isolated, reproducible positive held-out result. Search and models lack approved, reproducible providers. No candidate meets the M11 promotion rule. Scheduler/network code was unchanged, so no new scale/deadline simulation was triggered by a runtime change.

Paid cost: `$0`. Models, search, ATS, browser automation, new external providers, and PDF acquisition: disabled/not used. No official submission, version slot, or external contact occurred.
