# Final competitive live sprint — 17 October 2026

Baseline SHA: 5525f4727ff18dcfe7fbdf65b11bcbdd0920f06d. Branch: codex/m12-final-sol-remediation. Exact baseline HEAD/remote and clean state were verified before work. Final SHA and exact-SHA CI are supplied in the owner handoff; resolve this checkout with git rev-parse HEAD.

**Outcome: verified company-family coverage did not improve.** Acquisition improved, and the best working release is preserved. No official score or placement prediction is claimed. Source research was sealed closed at **172/200 physical HTTP attempts**, including current official-document retrieval, independent source checks and the attempted report download. The replacement sprint reused the already frozen baseline instead of running a second cohort or resetting the budget. No paid service, personal credential, visibility change or submission occurred.

## Live results

| Category | Before | After, same companies | Fresh holdout |
|---|---:|---:|---:|
| Verified websites | 0/10 | 0/10 | 0/2 |
| Registered business descriptions | 10/10 | 10/10 | 2/2 |
| People / roles | 10/10 | 10/10 | 2/2 |
| Locations | 0/10 | 0/10 | 0/2 |
| Numeric financial results | 0/10 | 0/10 | 0/2 |
| Jobs | 0/10 | 0/10 | 0/2 |
| Dated activity / news | 0/10 | 0/10 | 0/2 |
| Verified public profiles | 0/10 | 0/10 | 0/2 |

Descriptions above are supported registered activity/purpose, not independent web descriptions or recent news. Filing metadata is not counted as financial results. Role-context atoms are not extra people. No search/candidate URL is counted as a website.

The 10-company baseline and retest each published 1,002 available canonical atoms, including 20 registered-description statements, with identical value/dimension multisets. This is not 1,002 independent competition facts. A separate source interpreter checked all baseline values and normalizations against preserved bytes: 765 exact pointer matches, 17 address subsets, 33 explicit scope labels, 51 joined person names, 68 inactive flags and 68 typed holder relationships; no unresolved value or wrong-company publication was found in that bounded review. Holdout identity/org/name checks also passed. Population precision/recall is not established.

| Live measurement | Baseline | Same-company retest | Holdout |
|---|---:|---:|---:|
| Physical HTTP attempts | 64 | 64 | 10 |
| Logical gateway calls | 64 | 64 | 11 |
| Wall time, seconds | 31.537 | 29.336 | 5.891 |
| Companies with downloaded website HTML | 3/10 | 6/10 | 0/2 |
| Successful HTML responses | 7 | 10 | 0 |
| Ordered terminal results | 10/10 | 10/10 | 2/2 |

These are single small live runs, not a production speed guarantee. Research wall time sums to 66.764 s; independent source investigation is separate and its request timeouts are not hidden inside that number. The ledger includes all 172 physical attempts. RSS/CPU, worker-active foundation p50/p95 and detailed phase counts are in the [scorecard](evidence/final-sprint-20261017/scorecard.json). Foundation worker timings are not total company latency.

## Selection and bounded conditions

Seed: signalpost-final-sprint-20261017-v1. Streamed the verified official 411,160-company universe, excluding all prior recorded cohorts. Within employee-band/registry-website strata, order by SHA256(seed + ':' + organisation_number), choose first unused row; no result-dependent replacements. Seven baseline rows have registry website candidates and three do not. Exact cohort, strata, exclusions and pre-request selection seal are preserved.

Baseline/retest company numbers: 959312869, 923160388, 947942638, 997356624, 918652493, 987974249, 979679971, 918711759, 928208729, 976519094. Holdout: 993971804, 984060327.

Fresh production CLI/state/checkpoint each run; no saved-source replay substituted for live acceptance. Baseline/retest config: global physical limit 75, per-company limit 8 including official foundation, robots and redirects; 600 s hard / 450 s soft / 100 s completion reserve. Holdout global limit 18, same per-company cap. These are deliberately tight sprint conditions, not unrestricted recall. Both baseline/retest consumed 64 attempts; a larger budget could reach additional pages but was not falsely represented as a code improvement.

All physical HTTP sends were reserved centrally in SQLite before HTTPConnection.request, including redirects/retries. Out-of-gateway HTTP was denied. A single cumulative counter and NETWORK_CLOSED seal cover every phase. Original bodies and the experimental guard remain private outside Git, with privacy exclusions and raw-versus-redacted hash distinctions.

## Iteration 1 — demonstrated acquisition fixes

1. **Redirected robots response reuse.** A www robots URL redirected to the non-www origin's exact /robots.txt resource. Later homepage redirects downloaded that same destination robots resource again. The gateway now reuses the actually fetched destination bytes for that origin. It still applies its disallow rules and crawl delay; failed/oversized/challenged responses, non-robots redirect destinations and unfetched aliases do not create permission.
2. **Pending-link deduplication.** Repeated menu/footer links occupied the bounded identity-page queue and could evict distinct contact/about/legal pages before fetching. Normalized pending URLs are now deduplicated before truncation.

Three focused tests cover resource reuse with explicit disallow/crawl delay preserved, no inferred permission from a non-robots redirect path, and repeated navigation links that previously crowded out a distinct proof page. No ownership gate, attribution rule, evaluator envelope, source provider, UI, financial policy or dependency changed.

Live retest recovered final HTML from:
- [Folk og Fe](https://folkogfe.no/) — org 987974249. A genuine business description/services are present, but the downloaded structured operator record lacks the exact organisation number; not published.
- [Helgeland BBL](https://helgelandbbl.no/) — candidate for org 997356624 NORDMOHØGDA BORETTSLAG. It is the manager's site, not proof the housing company owns it. Correctly withheld.
- [MENY](https://meny.no/) — candidate for org 979679971 NG MENY VEST AS. Brand/group material does not resolve exact regional legal ownership. Correctly withheld.

This is **more retrieved HTML per same request budget, not more verified facts**.

## Independent missing-information investigation

| Company / public source | Observed information or failure | Why the agent missed / withheld it |
|---|---|---|
| 959312869 HOVDEN FJELLSTOGE AS, registry-listed www.hovden.fjellstoge.no | Both recorded www hostname and tested non-www alias failed DNS resolution | Stale/unresolvable starting URL; not an explicit robots disallow |
| 923160388 NBN FLORØ AS, https://www.nbnelektro.no/kontakt/ | Direct BRREG link names NBN Florø AS and 923160388; page also identifies a second legal company 916522800 | Shared trading brand/contact content; direct group/site ownership not established. A mention/link is not ownership |
| 918652493 AURA TRENING OG HELSE AS, https://www.auratrening.no/om/kontakt-oss.html | Exact org number, company copyright and contact details in footer; malformed Organization JSON-LD | Protected publication gate excludes footer-only proof; no direct typed operator-number binding |
| 987974249 FOLK OG FE AS, https://folkogfe.no/ | Substantive business/services and “Jobbe hos oss?” contact invitation | Homepage acquisition recovered; no exact operator proof. General invitation is not a dated job posting |
| 997356624 NORDMOHØGDA BORETTSLAG, https://helgelandbbl.no/ | Manager's dated news and vacancy navigation are present | Wrong legal entity for target; must not attach manager news/jobs to the borettslag |
| 979679971 NG MENY VEST AS, https://meny.no/ | Brand-level job navigation and business material | Exact regional employer/ownership association unresolved |
| 947942638 TINE SA, https://www.tine.no/om-tine | Substantive business/group description; explicit link to financial information | Homepage/contact reached, but required owned-site proof absent in bounded captured pages; no ownership shortcut used |
| 947942638, https://www.tine.no/om-tine/finansiell-informasjon | Annual-report links, financial calendar and explicitly labelled bond amounts | Bonds/calendar are not annual revenue/profit; annual PDF request timed out with zero bytes |
| 947942638, https://www.regnskapstall.no/?query=947942638 and linked financial page | Exact-ID search and historical displayed financial figures are accessible | Retrieved financial page/glossary did not explicitly prove currency/unit or complete period/scope contract; directory declares BRREG/Dun & Bradstreet upstream |
| Public Proff homepage | HTTP 403 reports geographic block | Skipped; no proxy/CAPTCHA/geographic bypass attempted |

The [company funnel](evidence/final-sprint-20261017/company-funnel.json) separates candidate, downloaded bytes, published states and per-company omissions. Most current misses are source reach/identity/proof, not an unavailable HTML parser. Default run-start cutoff also withholds undated workplace observations collected later; locations were not falsely counted as published.

Historical 100-company 49-not-attempted / 46-robots-failed / 3-ambiguous / 1-fetch-failed / 1-available and 20-company 1-site / 0-jobs/news/numeric results remain historical evidence. Current native BRREG mapping and previously fixed physical IP-attempt accounting are preserved. The 46 old failures must not be relabelled as explicit robots disallows; their inaccessible old raw bundle cannot now be freshly adjudicated. This sprint independently measured DNS failures, redirects, budget exhaustion, company mismatch and proof deficits.

## Iteration 2 — financial evidence opportunity and final acceptance

The owner's additional rule was applied: financial evidence need not be governmental. A credible directly attributable source may support a number if company, metric, reporting period, currency, units and standalone/group scope are explicit. Multiple sources only corroborate when genuinely independent, with rounding and definitions reconciled. No generic model/adapter rule requires every financial claim to have government source_class; the missing acquisition/dimension proof is the actual blocker.

Bounded investigation:
- BRREG records still lack explicit scale.
- Proff access was blocked; no bypass.
- Regnskapstall search/details and glossary were retrieved. Figures and years exist, but absence of explicit unit/currency was not resolved by guessing. Its stated BRREG/Dun & Bradstreet upstream means agreement with BRREG is not independent corroboration.
- Tine's directly linked 2025 annual report was attempted once through the gateway under the user's company-report investigation authorization. It timed out, returning no document bytes, so no figures or unit proof were extracted. This does not assert the report has no useful data.
- Published-directory automation terms were not fully established: the linked terms URL redirected outside the source allowlist and was not bypassed. No production directory integration was promoted.

Therefore no financial parser/provider was added. Numeric financial coverage gained **0 companies**. No third implementation iteration or speculative redesign was started. Prior free-provider findings (SearXNG upstream permissions/reliability, GDELT news-specific scope, Common Crawl known-URL focus, Marginalia free-use restrictions, Wikidata robots disallow) were reused rather than repeating failed provider tests.

## Release and submission

The accepted UI, financial withholding, identity/publication gates, evaluator structure and prior evidence remain unchanged. The existing historical 100-company report, source/licence/cost disclosures, contact placeholders and unsent email draft remain in submission/. API/model cost remains $0; infrastructure is runner-supplied.

The full suite passed with 487 tests and 237 subtests in 216.01 s (existing pyRdfa UTC deprecation warning). Three added focused acquisition tests passed. Exact-SHA clean-clone installation, independent evaluator/failure/refresh acceptance and CI are checked after the commit and reported in the final handoff; they are not preclaimed here. No official Builderr score is claimed. This report does not label low external coverage competitive or sufficient for top three.

One evaluator command after the pinned installation, from repository root:

~~~sh
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost.py --input companies.jsonl --output output.jsonl --state-output state.json --checkpoint checkpoint.sqlite --live-brreg --live-websites
~~~

Use the actual organizer cutoff/resource configuration when supplied. Output profiles are the JSONL file; stdout is the separate machine-readable batch report. Exact parser/schema and frozen-registry handoff remain unpublished and unverified. Keep historical smoke claims tied to their original commit.

Owner actions: confirm contact name/email; resolve organizer parser/budgets and public-artifact versus explicitly accepted private access; authorize any visibility/access change separately; review the frozen final SHA/CI and send the prepared submission or explicitly authorize that final action. No submission or publication occurred.
