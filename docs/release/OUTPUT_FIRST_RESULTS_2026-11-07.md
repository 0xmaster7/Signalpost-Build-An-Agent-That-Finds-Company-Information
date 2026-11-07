# Output-first live results — 7 November 2026

**Operational replacement gate PASSED at runtime `f0902cb0cbb1a4cd5e9ac1d471f0c8459545ed73`.** Both authorized stages self-exited with code 0, complete contract-valid output and zero duplicate IDs. This is the revised output-first gate, not the original paired-state/replay/coverage acceptance. No extractor or identity tuning occurred. Nothing was sent or submitted.

## Exact source and verification

- Runtime remained frozen across live 200 and the single live 1000 run. Input/configuration hashes are frozen in the private acceptance manifest; configuration SHA-256 is `6bc8c7126ce4d981042a78e58399f45b28b4b9ef70cdb19120a748ce45ecebca`.
- [Exact-runtime CI is green](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/42364033937): 1,342 tests and 252 subtests passed, followed by all remaining CI gates, including clean setup, local OCR, refresh and scale checks. CI completed **10:48:11 UTC**, not a live coverage measurement.
- This report is a documentation-only follow-up. Its own commit/CI is separate from the measured runtime SHA. Obtain the package SHA with `git rev-parse HEAD`; do not relabel a docs commit as the live-run commit.
- Validation reconstructs each JSONL row as the repository Envelope, applies the adapter, and checks the cross-envelope publication graph, cardinality, order and identifiers. The organizer's final private parser and numeric resource limits remain unverified.

## Results

| Cohort | Budget s | Process elapsed s | Exit | Valid envelopes | Duplicate IDs | Finance | Explicit FTE | Verified sites | Jobs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 200 | 360 | 332.033 | 0 | 200 | 0 | 196 | 1 | 0 | 1 |
| 1000 | 1800 | 1659.034 | 0 | 1000 | 0 | 983 | 8 | 0 | 1 |

Counts are counts, not scored recall, accuracy, negative coverage or a claim of coverage improvement. Both aggregates survive as `batch_complete` stdout events and in private reports. **Neither state pair committed; both captures remain incomplete/unsealed, so exact scale replay is unproven.** All checkpoint shells remain `baseline_done` (200/1000): terminal primary JSONL is distinct from secondary checkpoint terminalization. Durable phase rows total 2,000/10,000; secondary finalization counters are absent.

## Diagnosis and changes

[Saved-run profiling](OUTPUT_FIRST_PROFILE_2026-11-07.md) found breadth was about 0.497–0.504 seconds/input, not 1.5–1.8 seconds/input. The fatal bottleneck was withholding output publication behind repeated full-batch validation/encoding, canonical state, checkpoint and recording work. Previously 200 shells terminalized but the watchdog killed the process at 354.431 seconds before a pair/aggregate committed.

Validated row bytes now accumulate after phase publication; complete snapshots are prepared/fsynced off the promotion path. Primary commitment uses fixed-count rename/directory-fsync operations before secondary work. Secondary failures retain supported primary facts; interrupted paired promotion restores the previous primary and marker, and restoration failure fails closed. Resume seeds supported checkpoint facts. The watchdog never kills before durable-output acknowledgement; after acknowledgement, deadline signals can cleanly abandon secondary work.

Documented BRREG collection queries fetch at most 100 exact entities per request, preserving real response hash/URL and entity-specific JSON pointers. Missing/duplicate/foreign identities do not publish through the batch cache. Finance retains eight workers, an eight-starts/second host pacing ceiling and existing adaptive rate handling. Finance deliberately makes one attempt per company; Retry-After retry behavior is not newly established for that path. No website/FTE extraction or ownership thresholds changed.

## Throughput and finalization

Live 200 breadth completed between 82.326144 seconds (last financial response) and 83.597655 seconds (first optional official-details request), including startup. The upper bound is **0.417988 seconds/input**, meeting the <=0.5 target on this stage. Foundation had four physical attempts (two batch responses and two robots failures), versus 202 in the saved attempt. Finance had 200 attempts, seven peak overlapping receipt intervals and 69.729 seconds phase wall time. For 1000, foundation/finance phase walls alone sum to 483.473 seconds; batch preloading and startup are additional, so the <=0.5 target is **not certified at scale**. Physical foundation attempts were 14 and finance attempts 1,000; finance had three timeouts. Full input-to-breadth timing at scale is not persisted in the aggregate.

| Stage | Cached validation/encoding mean s/accepted row update | Last full snapshot preparation s | Primary promotion s | Reserve s |
| --- | ---: | ---: | ---: | ---: |
| 200 | 0.055683 | 1.116938 | 0.024532 | 36.000 |
| 1000 | 0.052735 | 8.722520 | 0.024308 | 180.000 |

The cached preparation mean includes initial rows and repeated phase updates; it is not a unique-company latency distribution. Promotion amortizes to 0.000123/0.000024 seconds per input respectively. Snapshot preparation still scales with bytes, but promotion does not revalidate or encode rows. Reserve = max(2 × (measured row preparation × input count + measured flush), 10% budget), capped by the total. Both measured reserves used the 10% floor. Individual-company finalization p50/p95 is not measured.

## Phase evidence: live 200

| Phase | Ran | Other skipped | Deadline skipped | Failed (within ran) | Phase wall s | Receipt span s | Physical attempts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| annual_documents | 2 | 0 | 198 | 1 | 116.111 | 116.028 | 9 |
| financial_statements | 200 | 0 | 0 | 0 | 69.729 | 68.475 | 200 |
| nav_batch | 200 | 0 | 0 | 0 | 52.345 | 51.740 | 18 |
| official | 200 | 0 | 0 | 0 | 8.471 | 5.030 | 4 |
| official_details | 96 | 0 | 104 | 0 | 60.222 | 60.200 | 203 |
| website_verify | 43 | 0 | 157 | 4 | not recorded | 101.653 | 174 |
| wiki_batch | 200 | 0 | 0 | 0 | 1.849 | 1.676 | 1 |
| nav_apply | 1 | 0 | 199 | 0 | 0.419 | — | 0 |
| website_shallow | 0 | 0 | 200 | 0 | not recorded | — | 0 |
| jobs_activity | 0 | 0 | 200 | 0 | not recorded | — | 0 |

## Phase evidence: live 1000

| Phase | Ran | Other skipped | Deadline skipped | Failed (within ran) | Phase wall s | Receipt span s | Physical attempts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| annual_documents | 10 | 0 | 990 | 2 | 550.885 | 503.673 | 30 |
| financial_statements | 1000 | 0 | 0 | 3 | 449.194 | 389.606 | 1000 |
| nav_batch | 1000 | 0 | 0 | 0 | 240.775 | 240.185 | 63 |
| official | 1000 | 0 | 0 | 2 | 34.279 | 52.742 | 14 |
| official_details | 408 | 0 | 592 | 0 | 279.202 | 279.140 | 831 |
| website_verify | 196 | 0 | 804 | 23 | not recorded | 482.674 | 559 |
| wiki_batch | 1000 | 0 | 0 | 0 | 6.204 | 5.700 | 1 |
| nav_apply | 1 | 0 | 999 | 0 | 0.643 | — | 0 |
| website_shallow | 0 | 0 | 1000 | 0 | not recorded | — | 0 |
| jobs_activity | 0 | 0 | 1000 | 0 | not recorded | — | 0 |

Company counts come from persisted outcome records, not scheduler eligibility estimates. Failed is included in ran. NAV/Wikidata are one shared batch action, reflected in every company's status: their company-second sums duplicate the shared elapsed time and must not be interpreted as CPU/worker or wall time. Phase walls overlap and cannot be added to derive total runtime. Website wall `0` is an unfilled aggregate placeholder, reported as not recorded. Receipt spans are request lifetimes, not full phase durations; canceled thread-backed requests may physically outlive the await. The 1000 capture includes one incomplete website attempt; this is not a complete recording.

## Remaining failures and unproven claims

- Canonical state pair, checkpoint terminalization and exact replay remain incomplete. Output-only success must not be used as a refresh-ready pair or hermetic capture.
- Explicit FTE and verified-site counts remain low; no extractor tuning or coverage improvement is claimed. No new all-field wrong-company/precision audit or official score exists.
- <=0.5 seconds/input breadth is established only for 200, not certified for 1000. Financial Retry-After handling with retries disabled remains a limitation.
- Complete recorded status coverage for the ten research phases survives, but secondary finalization per-company counters do not. Deadline recovery can replace earlier unpersisted ineligible/budget-skipped outcomes with deadline-skipped; do not equate them with proof that work ran or no source exists.
- The watchdog waits for output fsync acknowledgement. A blocked filesystem/startup/native call, different RAM/CPU limits or an earlier organizer deadline can still cause overrun; no universal completion guarantee is claimed. The tested VM has about two cores/7.7 GiB RAM and swap; these are not organizer requirements.
- Follow-up independent re-review failed to start because the delegated provider token expired. The preceding review's three concrete findings were repaired and covered by regressions before the frozen live run; no fresh independent sign-off is claimed.

## Run and evidence

```sh
./setup.sh
SIGNALPOST_TIME_BUDGET_SECONDS=1800 ./run.sh --output-first --input companies.jsonl --output output.jsonl
```

Dependencies remain pinned in `signalpost-starter-kit/uv.lock`. Public APIs have assumed $0 API charges; VM, network and storage costs are unpriced, not a measured bill. See [limitations](../../LIMITATIONS.md), [rights](../source-rights.md) and the [unsent email](../../SUBMISSION_EMAIL_DRAFT.md). Contact and `[JBOX_SITE_URL]` remain owner placeholders. No submission occurred.

Sanitized receipts: [200](evidence/output-first-20261107/live-200.json), [1000](evidence/output-first-20261107/live-1000.json). Private envelopes, HTTP/PDF captures and checkpoints stay outside Git at `pancakes:/home/azureuser/projects/signalpost-outputfirst-acceptance-f0902cb/`. No retries or additional live runs were made. **Safe as a replacement under the latest operational output-only definition: yes at the tested runtime commit; not a claim that the original coverage/state/replay gates passed.**
