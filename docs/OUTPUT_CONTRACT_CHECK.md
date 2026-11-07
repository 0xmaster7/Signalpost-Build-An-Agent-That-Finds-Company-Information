# Output contract check — 7 November 2026

Frozen runtime: `82703d348e894ed68bf9873404a7900886440398`. This documentation-only audit changes neither output nor validators.

## Authoritative local references

- [Starter OUTPUT_CONTRACT.md](../signalpost-starter-kit/OUTPUT_CONTRACT.md): a minimal JSON example and six availability states, not a formal JSON Schema.
- [Unchanged starter validator](../signalpost-starter-kit/src/norway_company_agent/batch.py): `validate_envelopes(rows, expected_count)`.
- [Publication adapter and decoder](../signalpost/adapter.py); [canonical models](../signalpost/models.py).
- [Prior live 10/200 compatibility results](release/COMPATIBILITY_RESULTS_2026-11-07.md).

Organizer Soham has confirmed 45 minutes and 2,000 requests per 100 companies (20/company), one result per input, and refresh by repeating the command with the state folder retained. Revision 1 `a9d0bc8` is on record; revision 2 of 5 is being prepared. Numeric budgets are no longer an unresolved organizer question. Request accounting details and the private parser implementation are not supplied by the example.

## Remaining differences and semantic qualifications

| Surface | OUTPUT_CONTRACT example | Frozen Signalpost output / remaining difference |
| --- | --- | --- |
| Required top-level keys | `organisation_number`, `run`, `claims`, `evidence`, `changes`, `errors`, `operations` | All present, with the same object/array/string container types. Additional keys include `input_ref`, `terminal_state`, `availability`, `state`, `sections`, `source_snapshots`, `refresh`, `synthesis`, `operation_log`, `batch`, `profile`, `modules`, and run/timestamp aliases. Extra-key tolerance by the private parser is unknown. |
| Run terminal status | `"completed"` | `run.terminal_status` and top-level `state` use the unchanged starter's legacy terminal vocabulary (`complete`, etc.), not the example's `completed`. Public `terminal_state` retains the six availability states. Which field/vocabulary the private parser selects is unconfirmed. |
| Legacy state mapping | Not defined in minimal contract | `available→complete`, `not_available→not_found`, `not_applicable→not_applicable`; `blocked→blocked_robots` only when error text mentions robots, otherwise `blocked_policy`; `failed→source_error` only when error text mentions source, otherwise `submission_error`; `ambiguous→submission_error`. The mapping is lossy and reason-text-dependent. `budget_exhausted` is accepted by the starter but is not emitted by this mapping. |
| Claim field vocabulary | Example `official_website` | Our verified ownership field is `verified_website_url`; registry URL references are distinct claims. Other field-family names are richer than the single example. No authoritative complete field-name registry is supplied; field-name acceptance is unproven. |
| Claim shape | `field`, `value`, `availability`, `confidence`, `evidence_ids` | All present; extra canonical fields include `claim_id`, `id`, `state`, company/section/family/scope/subject/period/unit/provenance metadata. `availability == state` uses the six public states. |
| Confidence | Numeric example `0.99` | Null when uncalibrated; no confidence invented. The unchanged starter ignores confidence. The example provides no nullable schema, so private-parser null acceptance remains unknown. |
| Evidence identifiers | `id` | `id == evidence_id`, with both retained. Required example source URL/class/retrieval/hash fields are present. Additional snapshot, extraction and pointer metadata are retained. |
| Evidence claim span | String example | Existing excerpt copied to `claim_span`; null when only structured pointer/span provenance is available. Null span acceptance is not established by the example. |
| Sections | Not in example | Seven sections and claim copies are additional. Unknown canonical section states publish `not_available` plus `canonical_state: null` and original `canonical_attempt_outcome`; synthesized `attempt_outcome: not_checked` is explicitly unknown, not proof of absence. Published section states are not null. |
| Run timestamps | Non-null example start/end | Batch start and row snapshot times, not proof all optional work completed. Initial snapshot completion/runtime can be null. Unknown values are not fabricated. |
| Changes | Top-level array | Present and identical to `refresh.changes`; richer refresh metadata and typed events remain. Full private event vocabulary is unknown. Automatic retained-folder refresh is a separate execution limitation, not fixed by this alias. |
| Operations | Object: requests/runtime_ms/third_party_cost_usd | Same three keys. Requests are company-attributed charged physical attempts at publication; shared batch requests are excluded there. Gateway aggregate counts include shared traffic. Runtime is batch elapsed at row serialization, not per-company CPU. Unknown request/runtime measurements can be null. |
| Cost | Example zero | API charge cost zero for this public-service configuration; compute/hosting unpriced, not a measured billing guarantee. |
| Detailed operations | Not in example | Previous array retained as `operation_log`; consumers of the old array must use that field. |
| Modules/profile | Not in minimal example; legacy starter batch emits them | Only persisted completed/failed phases become modules, with legacy terminal states; skipped/unattempted phases are not fabricated. Profile is supported deterministic synthesis, not the starter's original per-module observation structure. |
| Snapshots, synthesis and errors | No snapshot/synthesis example; empty errors | Additional source graph and supported synthesis; structured errors, even when output commits successfully. Exit zero establishes primary output completion, not successful optional research or paired state. |
| Duplicate inputs | One result per input; legacy validator demands unique organisation numbers | Signalpost preserves duplicate input rows with distinct input references; unchanged starter validator rejects duplicate organisation numbers. This audit's live cohorts contain unique numbers. |
| Value/source-class schemas | One illustrative website value/source class | Signalpost also emits numeric financial values, structured registered facts, legal-entity/group scope and source classes. Full private type/enum constraints are not published in the minimal example. |

## What the unchanged starter actually validates

It checks exact expected count, unique organisation numbers, top-level legacy terminal states, and terminal module states; its zero-silent-drops check repeats count/uniqueness. Empty modules are accepted. It does **not** check claims, confidence, evidence, spans, source classes, timestamps, operations, section states, synthesis, refresh semantics, or extra keys. Passing it is not proof of full OUTPUT_CONTRACT/private-parser acceptance.

Signalpost's separate canonical graph and round-trip validation provide stronger internal provenance checks, not independent official acceptance. The starter source is unchanged. Live whole-output results and exact commands are recorded in [RESULTS.md](../RESULTS.md). No official score or private-parser acceptance is claimed.
