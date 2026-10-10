# M12 live smoke outcome — 2026-10-10

**Disposition: LIVE ACCEPTANCE FAIL; release remains HOLD.** This records the one authorized current-source live attempt. It is not a successful live smoke and does not certify the repaired code against a new live run.

## Source, cohort, and configuration

- Branch: `codex/signalpost-m12`.
- Source used for live transport: `7a8e1690793f4f7e1b5c36f07daea1bf0443c787` (clean before execution; working tree was modified only after the failure to fix the reproduced defect).
- Cohort: fixed M09 100-company foundation cohort, 100 distinct organisation numbers; input SHA-256 `67c3b3903eeecdffcc294a468402351367ca549053410b7f9c1c64ee76b32e2b`.
- Runtime configuration SHA-256: `61b5c234d2c4c431dc3e8016d349614df028d348fd2f24935b20966310d1d` (as recorded by the runner; preserved config file SHA is in the artifact manifest).
- Configured request cap 2,200 physical; hard runtime 1,800 seconds; soft deadline 1,350 seconds; completion reserve 300 seconds; paid cost limit zero. Existing gateway, per-host, concurrency, robots, DNS/SSRF, rights, and source rules remained active.
- The initial sandbox-only attempt made zero physical requests because DNS was sandbox-blocked. The one source-contacting attempt used the same fixed cohort/configuration from the confirmed host network context; no second cohort was run.

## Live attempt result

BRREG retrieval completed for all 100 inputs and all rows were terminalized in the checkpoint, but final evaluator serialization failed. The closed synthesis schema rejected six valid, source-derived BRREG fields nested under `identity_profile`: four registry status booleans, two `status_dates` keys, plus other known BRREG observation structure (address members) encountered during replay. The initial failure named `konkurs`, `registrertIMvaregisteret`, `underAvvikling`, and `underTvangsavviklingEllerTvangsopplosning`. This is an application schema defect; the runner therefore did not publish a committed output/state pair.

| Measurement | Result |
|---|---:|
| Input rows / terminalized checkpoint envelopes | 100 / 100 |
| Preserved input order | Yes |
| Exact organisation-number anchors | 100/100 |
| Physical / logical requests | 459 / 485 |
| Runtime | 352.625 seconds |
| Physical request cap / runtime cap | 2,200 / 1,800 seconds |
| Soft deadline / hard deadline / reserve exhausted | No / No / No |
| Request purposes | entity 100; accounts 100; roles 100; subunits 100; website pages 28; robots 23; sitemap 6; feed 2 |
| Robots | 11 received (8 HTTP 200, 3 redirects); 12 transport errors; no transport error was counted as an explicit disallow |
| Claims / evidence / snapshots in preserved envelopes | 3,449 / 7,590 / 388 |
| Duplicate claim / evidence / snapshot IDs across batch | 0 / 0 / 0 |
| Canonical financial metrics published | 0 |
| Website claims / hiring-activity claims | 6 / 0 |
| Final evaluator envelopes / committed paired output-state | 0 / no |

Website section execution was `not_attempted` for 49 companies, `robots_unreachable` for 46, completed for one, with the remaining four represented by their per-row outcomes (`ambiguous` three, `failed` one). These measurements indicate a real access limitation for much of this cohort while robots retrieval failed closed; they do not justify changing robots policy. The hiring/activity section was not attempted for all 100 rows. The leadership/workplaces section had no published facts and was `not_available` for all 100 rows. None of those states is evidence of factual absence.

All 100 canonical financial account histories were retrieved, but zero financial metric claims were published because authoritative scale semantics remain unresolved. The batch recorded 3,750 `BRREG_FINANCIAL_UNIT_UNSUPPORTED` diagnostics; those candidate values were withheld rather than guessed. No population-level precision or recall claim is made from this cohort.

## Preserved live evidence

Artifacts are preserved under `/private/tmp/signalpost-m12-final-live-hostnetwork-7a8e1690793f4f7e1b5c36f07daea1bf0443c787.failure-artifacts` and the report is `/private/tmp/signalpost-m12-final-live-hostnetwork-7a8e1690793f4f7e1b5c36f07daea1bf0443c787.json`.

- Live report SHA-256: `cd2fea5ffdb2abb198e62c16903428f05530c7e6394dd26d9eb5f4509a23e315`.
- Artifact manifest SHA-256: `4581bb2de0d0c39c6d72613fd1194e4cf39a1ceeae71b7a5344b80affa4be6fa`.
- Request ledger SHA-256: `4842498c8aea006f98b03a4da5e11825d2735d835d52bf741dc12373832d6dcc` (459 ledger entries, 485 logical requests).
- The original artifact manifest recorded the SQLite main file at SHA-256 `bcc69f506235d33f0b613dc0148224b2259eefb53d3b007a2f732f1b053896e9` (12,595,200 bytes), with its WAL at `63198396caf5f57fd2ceaee663dcfc548100e2720f09d70e68fb5bf9f748a32a` (4,264,232 bytes). During offline inspection I opened the checkpoint with SQLite's default read-write connection; SQLite checkpointed the WAL on close. The current main file is SHA-256 `22e27e0bc07bc464f87fae9f7b80262d35cf9fd3913c15305a7144e387e550f5` (12,734,464 bytes), and the WAL/SHM files are gone. The original manifest is preserved unchanged, and its recorded hashes establish the pre-inspection bytes, but the original checkpoint byte stream is no longer present. The current database still yielded all 100 canonical envelopes used in the offline replay. This evidence-preservation deviation is recorded explicitly rather than representing the checkpoint as byte-immutable.
- Preserved traceback SHA-256: `738d289dcca882c965e5190139342a918641b6f18a362bff652fa4e47195f498`.
- The temporary output's publication marker remains `publishing`; no committed output or canonical state artifact was reported. The immutable failed-run bundle was retained.

## Fix and offline replay

The original M12 source failed because the closed synthesis key allowlist omitted observed BRREG identity/status-date/address members and a `robots_error` audit field. The fix admits only the concrete observed fields in the existing closed schema; unknown nested keys still fail closed. The deterministic six-company production-path test now includes registry status booleans, status dates, and business-address data and checks their final evaluator serialization.

The preserved checkpoint was replayed offline through canonical envelope validation, per-envelope and batch claim/evidence/snapshot graph validation, current synthesis schema/support validation, `to_evaluator`, and final vendor-payload validation. It produced 100 ordered evaluator envelopes from 100 preserved canonical envelopes, 3,449 claims, 7,590 evidence records, 388 snapshots, and 3,447 synthesis sentences. There were zero duplicate factual sentence texts within an envelope, zero evaluator serialization failures, and zero publication-graph failures. The replay JSONL SHA-256 is `22cce477f2415b7c8bc70d8ea07a3756ebf883ba6e37998fa7b93e2cf99b4cca` at `/private/tmp/signalpost-m12-offline-replay-fixed-synthesis/evaluator.jsonl`.

This replay proves the captured canonical data now passes the fixed post-retrieval validation path. It does **not** retroactively convert the live attempt into a pass: the original execution did not publish its output/state pair, and no second live cohort was run. The checkpoint retained `refresh.current_state_ref`, but the runner failed before emitting the matching canonical state file, so paired live state/output hash validation could not be completed for this attempt.

## Repair verification

- Complete pytest suite: **390 passed, 91 subtests passed**.
- M07 contract suite: **32 passed**; deterministic refresh replay: **12/12 profiles**, six expected changes, zero FP/FN, provenance complete, idempotent event IDs.
- M08 contract suite: **35 passed, 3 subtests passed**; M08 gold: find/compare/verify accuracy 1.0, citation completeness 1.0, unsupported assertions 0; local UX smoke and XSS gate passed.
- M09 live-shape and M09 tests: **15 passed, 5 subtests passed**, including the new source-shaped status/address serialization test.
- Offline process crash/resume gate: pass at kill points 25, 50, and 90 of 100 rows; all resumed outputs matched uninterrupted semantics and retained cardinality/order.
- M06 scale gate: passed with the current verifier; offline measurement remains a scheduler simulation with identity safety explicitly `not_measured`.
- Clean-CWD evaluator: four of four offline input rows published, with zero physical requests.
- `compileall` and `git diff --check`: pass.

These are deterministic/offline checks; none substitutes for the failed live publication gate. The loopback UX smoke was run after the clean-CWD artifact existed, using local loopback permission for its temporary HTTP server.

## Release decision

The live acceptance gate failed on the starting SHA. The defect is fixed and covered locally; full suite, exact-SHA CI, and documentation release gates must pass on the repair before a future live attempt is considered. No additional cohort is authorized by this report. Submission remains **HOLD** because coverage is low and no current-source successful live publication exists. BRREG unit scale, PDF reuse/extraction semantics, Builderr evaluator details, and high website `robots_unreachable` incidence remain external or measured limitations. Search, model, paid API, ATS, external provider, and PDF paths remain disabled.
