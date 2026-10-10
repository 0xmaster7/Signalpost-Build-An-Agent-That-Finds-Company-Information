# M12 post-repair live acceptance — 2026-10-10

**Disposition: M12 live acceptance PASS. Submission remains HOLD pending materially higher measured coverage and the independent Sol High audit.** This report records the one additional cold 100-company cohort authorized for the repaired implementation. It does not reclassify the failed attempt at `7a8e1690793f4f7e1b5c36f07daea1bf0443c787`.

## Source, cohort, configuration

- Branch: `codex/signalpost-m12`.
- Live source SHA: `7d4fe04867cd746389c48a47f360afd7ac4b8fb1` (clean tree; no source changes before or during the run).
- Fixed cohort: `signalpost-starter-kit/tests/fixtures/m02/foundation-input.jsonl`, 100 distinct rows; SHA-256 `67c3b3903eeecdffcc294a468402351367ca549053410b7f9c1c64ee76b32e2b`.
- Existing production configuration SHA-256: `61b5c234d2c4c431dc3e8016d349614df028d348fd2f24935b20966310d1d`.
- Command: `PYTHONPATH=. ./.venv/bin/python scripts/run_m02_foundation_smoke.py --live-websites --output /private/tmp/signalpost-m12-postrepair-live-7d4fe04867cd746389c48a47f360afd7ac4b8fb1.json`.
- The existing centralized gateway, source rules, robots behavior, DNS/SSRF checks, identity checks, and publication validation remained enabled. Paid APIs, models, search, ATS, credentials, PDFs, and browser automation were not used.

## Offline preflight

- Local HEAD and the cached remote-tracking ref were both the expected SHA; branch was `codex/signalpost-m12`; working tree clean. GitHub's branch history showed `7d4fe04` as the branch tip. GitHub Actions run [38044614342](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/38044614342) showed Success for exact SHA `7d4fe04867cd746389c48a47f360afd7ac4b8fb1`; the `starter` job completed successfully. A direct shell `git ls-remote`/`gh` refresh was blocked by local DNS, so remote/CI were verified in the signed-in GitHub browser view, not by shell API.
- The original `7a8e169` serializer was run against the preserved canonical cohort and failed closed on an unrecognized nested synthesis field (`adresse`, `kommune`, `kommunenummer`, `postnummer`, `poststed`). The preserved historical traceback from the failed live attempt records its first failure on the BRREG status keys. Both are the same closed-schema boundary defect class.
- The repaired adapter serialized all 100 preserved envelopes and passed canonical envelope, synthesis, evaluator, and batch publication-graph validation: 3,449 claims, 3,447 synthesis sentences, zero validation failures.
- Every schema field represented in those preserved envelopes was accepted by the repaired closed schema; the regression suite still rejects unknown nested synthesis keys and unsupported synthesis content. Targeted production-path/adapter/publication checks passed: **43 tests, 25 subtests**.
- Official BRREG role documentation places `sistEndret` on the **role group** and includes it separately from individual role fields. The adapter retains it as source freshness (`Claim.as_of`) for cutoff comparison; it does not infer role start/end dates or M07 `effective_at`. The official response schema's role-specific dates remain separate, and unknown/missing effective dates stay unknown. See [BRREG's public role endpoint documentation](https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html).
- Existing production-path regression coverage verifies a group date before the cutoff can publish, a future date is withheld, and a missing date is withheld. Unit tests also cover unknown schema keys/prose, contradictory section data, invalid financial units, missing provenance, and injected failure between paired output/state writes.
- Prior failure-bundle inspection was done from a copied bundle and read-only SQLite connection; hashes were unchanged during this turn. The old failure bundle had already been rewritten during an earlier inspection: its manifest still records the original main/WAL hashes, which no longer match the bundle's current checkpoint bytes. That historical deviation remains disclosed in [the failed-run report](M12_LIVE_SMOKE_FAILURE_2026-10-10.md); it does not affect the separate post-repair bundle, whose complete manifest verified without mismatches.
- Complete suite before the live run: **391 tests and 91 subtests passed**.

## Live acceptance results

| Gate | Result |
|---|---|
| Input rows / ordered terminal evaluator envelopes | **100 / 100**; order and organisation-number sequence match the fixed input |
| Exact organisation-number anchors | **100/100** |
| Final adapter and publication graph | **PASS** for all envelopes; no canonical failures |
| State companies / input identity match | **100 / 100** |
| Available claims / evidence / snapshots / synthesis sentences | **6,916 / 7,590 / 388 / 5,658** |
| Duplicate claim IDs across the batch / duplicate evidence IDs / duplicate snapshot IDs / duplicate refresh-event IDs | **0 / 0 / 0 / 0** |
| Cross-envelope evidence-ID reuse / snapshot-ID reuse | **0 / 0** |
| Company ownership / wrong-company structural binding failures | **0** |
| Financial metrics published / unsupported financial publications | **0 / 0**; the 3,750 unsupported-unit diagnostics remain withheld |
| Invalid workplace attributions | **0** |
| Final hard-gate failures | **0** |

The full replay after the live run re-parsed all 100 evaluator rows, revalidated every vendor payload, reconstructed and validated each canonical envelope, reran synthesis schema/support checks and adapter serialization, and reran the batch provenance graph. Claims, evidence, and snapshots had unique identities at the required scopes; available claim → evidence → snapshot references, company ownership, URL/hash bindings, and synthesis citations validated.

## Measured coverage

Coverage below is the number of companies with an available claim in that family, not population recall. Financial record metadata is not a published financial metric.

| Company family | Companies | Available claims / observations | Result |
|---|---:|---:|---|
| Legal identity | 100/100 | 1,439 identity claims | Exact target organisation-number anchoring passed |
| Financial record metadata | 100/100 | 1,981 metadata claims covering 283 records | Period, currency and record metadata retained; no value/scale semantics inferred |
| Canonical financial metrics | 0/100 | 0 metrics; 3,750 unsupported-unit diagnostics | Fail-closed withholding preserved |
| Registered roles | 100/100 | 420 role rows represented by 3,467 role claims | Code change restored eligible source-dated role publication; `sistEndret` is freshness only |
| Workplaces | 0/100 | 87 returned rows; 75 complete and 25 incomplete collections | No workplace claims published: live retrieval was after the run-start cutoff and no equivalent source date was available; incomplete absence was not asserted |
| Owned website | 1/100 | 6 claims (verified URL/domain plus four product/service headings) | Structural claim/evidence binding passed; no independent human precision sample was performed |
| Jobs | 0/100 | 0 claims | No current hiring assertion |
| Activity | 0/100 | 0 claims | No activity assertion |

Website terminal crawl state was `not_attempted=49`, `robots_unreachable=46`, `available=1`, `ambiguous=3`, `failed=1`. This is an observed access limitation under existing fail-closed policy, not a robots-policy change. Hiring/activity remained unasserted; their empty output is not evidence of absence.

All 100 account histories were available, with 283 records. Zero metrics were published because unit/scale evidence remains insufficient. This preserves legitimate uncertainty rather than converting missing semantics into zero.

All 100 role collections were available and contained 420 role rows. The repaired mapping yielded 3,467 role-field claims across 100 companies; the prior live attempt published no role claims. Workplace claims remained withheld under the current run-start cutoff, and the 25 malformed/incomplete subunit collections remained incomplete rather than establishing absence. No group lookup was performed.

## Network and resources

- Physical / logical requests: **459 / 485**, matching the request ledger and run accounting; 0 coalesced requests. Physical limit: 2,200.
- By purpose: entity 100, accounts 100, roles 100, subunits 100, robots 23, website pages 28, sitemaps 6, feeds 2. Every physical request appears in the centralized gateway ledger and uses an approved purpose.
- Runtime: **347.077 seconds** runner-accounted; the wrapper reports 347.138 seconds. Soft deadline 1,350 seconds not reached; hard deadline 1,800 seconds not reached; 1,452.923 seconds remained in the reported completion budget; reserve was not active at completion.
- Robots: 8 HTTP 200, 3 redirects, 12 transport failures, 0 explicit disallows. Transport failures stayed distinct from prohibition.
- No paid cost, model use, or unapproved source use.

## Published artifacts and integrity

Preserved run report: `/private/tmp/signalpost-m12-postrepair-live-7d4fe04867cd746389c48a47f360afd7ac4b8fb1.json` — SHA-256 `4baf2b58ffa0612dc972cc29cbd63d55185fb8fd6b36abb660b302380ae466e4`.

Artifact bundle: `/private/tmp/signalpost-m12-postrepair-live-7d4fe04867cd746389c48a47f360afd7ac4b8fb1.artifacts-artifacts`.

- Manifest SHA-256: `474ed5a9122acb0bf03fa6b581e8c8417a208e9556d43755fa25b2ada420dd57`; all seven listed files independently rehashed with matching lengths and hashes.
- Request ledger SHA-256: `304c8effcc62e9ff0afac7a3e409959809f95ac3197263660388a9b38ad797ec`.
- Evaluator output SHA-256: `401791971d5669156643af61428d0e8c918bf16e6cb7eaf348a1ba2730dcf31f`.
- Canonical state SHA-256: `98b1274c2bf8786d5a8f34021f6fd9c334dfb6ec66e8c2ed40b74e1cbe098b4e`.
- Publication marker SHA-256: `f81111684c958819b61d3c2307ad5912fd72b9ac1b8ad9c425b0778ca5da1b6f`; marker status is `committed`, and both recorded output/state hashes exactly match the archived pair. Its absolute paths point to the runner's temporary directory, which is removed after the bundle is copied; independent validation therefore compared the marker hashes directly with the retained files rather than dereferencing those expired paths.
- The JSONL output and JSON state both parse; output cardinality/order is exact; the state artifact validates with all 100 input companies. The checkpoint was preserved as an artifact and not opened during this validation.

## Comparison and interpretation

Against the prior 100-company M12 attempt, the fixed cohort and configuration produced the same 459 physical / 485 logical requests, website crawl-state distribution, 420 role rows, 87 workplace rows, 75 complete / 25 incomplete workplace collections, and six website claims. No source-availability change was measured. The material implementation change was publication of source-dated role claims (0 previously, 3,467 role-field claims now). Financial metric withholding is unchanged and intentional. Jobs/activity remain unmeasured for coverage because the run published none.

## Deterministic release gates after the live run

All these gates used source code at `7d4fe04867cd746389c48a47f360afd7ac4b8fb1`; the working tree contained only the documentation packet changes listed for the final commit. None generated external requests.

| Gate | Result |
|---|---|
| Complete test suite (before live, clean source tree) | **391 passed, 91 subtests passed** |
| Focused live-shape / M09 / Sol-remediation integration tests | **43 passed, 25 subtests passed** |
| M07 refresh replay | **12/12 profiles**, six expected events, TP=6, FP=0, FN=0; complete provenance and idempotent event IDs |
| M08 independent gold | Four profiles; find/compare/verify accuracy **1.0**, citation completeness **1.0**, unsupported assertions **0** |
| M08 UI / XSS smoke on preserved 100-row output | **PASS** for launch, profile, evidence, compare, verify, changes, and XSS escaping |
| Crash/resume | **PASS** at durable checkpoints 25/50/90; each resumed 100-row result matched uninterrupted semantics and order |
| M06 operational scale | **PASS**: 1,000 rows in 13.986 s; 1,200 in 13.891 s; 10,000 in 100.307 s. All distinct-company rows, ordered outputs, zero physical requests |
| M06 stress and provenance verifier | **PASS**, modes A–D; max per-host concurrency 2. Synthetic identity remains explicitly `not_measured` |
| Clean-CWD evaluator launcher | **4/4 rows**, ordered, all available, zero physical requests, `PYTHONPATH` unset |
| Compile and whitespace checks | `compileall` and `git diff --check` passed |

The M06 report was captured at `/private/tmp/signalpost-m12-postrepair-m06-scale.json` and accepted by `scripts/verify_m06_scale_gate.py`. Because the acceptance packet was being edited during that run, its metadata marks the worktree dirty and contains a diff hash; the source commit is still the exact live-tested SHA above. The complete suite ran before the live run on the same clean source SHA, and final exact-SHA CI is required after the documentation commit.

Zero structural wrong-company bindings in this cohort do not estimate population-wide precision; the output also has no human-adjudicated website audit, official Builderr score, or population recall measurement. Competition submission therefore remains **HOLD**. Financial scale semantics, workplace cutoff freshness, high `robots_unreachable` incidence, Builderr evaluator details, and Builderr evaluation feedback remain unresolved limitations. No Builderr submission, email, or revision slot was used. The independent Sol High audit is still pending.
