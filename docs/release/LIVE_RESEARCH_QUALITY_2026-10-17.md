# Signalpost live research quality and performance — 2026-10-17

**Engineering decision: GO with disclosed coverage limitations after the reproduced fixes pass exact-SHA CI. Competition qualification is not established. External submission remains an owner action.** UI design, evidence rules, source providers, financial-unit withholding and repository visibility are preserved.

Baseline: `f73dcfc01cff6e75888ede7351b6338da2e392d9`, branch `codex/m12-final-sol-remediation`. This report belongs to the correction commit; identify the immutable final release with `git rev-parse HEAD` and its exact-SHA CI receipt. No new source rights, credentials, paid services or licence grant were introduced.

## Authorization and immutable baseline

The new authorization was 20 distinct companies and 200 physical HTTP requests, separate from the historical 78/80 allocation. **193/200** conservative physical-send reservations were consumed: baseline waves 42 + 47 + 35 + 35 = **159**; independent source rechecks **10**; one-company refresh **24**. Seven remain unused. Source traffic is closed; no second cohort or post-fix live rebaseline was run.

The external harness used SQLite `BEGIN IMMEDIATE` reservations immediately before `HTTPConnection.request`, covering redirects, retries and individual pinned-IP fallback attempts. Uninstrumented HTTP outside the production transport context was refused. A concurrent no-network guard self-test allowed exactly three of twenty reservations at a test ceiling of three; that test used a separate, deleted database. Production timeouts, retries, robots rules, IP pinning, concurrency and BRREG pacing (3 requests/second) remained enabled. The guard counts connection attempts that may fail before a request reaches the wire, so its total is conservative. The gateway alone counted 181 across the evaluation; the guard additionally counted twelve IP fallback attempts. No source mocks were used during the live runs.

Full auditable [request ledger](evidence/live-20261017/request-ledger.json), SHA-256 `fde3313769ba76fe1a07354f93e463a161c93065f68f1a12fec527c91e76db49`. [Machine summary and complete cohort](evidence/live-20261017/summary.json). Canonical outputs, state, checkpoint copies, source-support adjudication, reproduction logs and the immutable baseline manifest are held under `/home/azureuser/projects/signalpost-live-acceptance-20261017/` on pancakes. This repository contains the non-sensitive ledger and measurements, not a redistributable raw-source cache. Personal birth dates, identifiers and private address details were removed before source copies were written; Access-restricted run-scoped bodies remain available for this authorized evaluation’s review/replay; they are not committed or reused as a general acquisition cache. Hashes, locators and permitted factual reference values remain separately recorded. Baseline output/state/checkpoint/ledger hashes are checked against `BASELINE_SEAL.json` and were not rewritten after repairs.

## Reproducible cohort and run configuration

The official universe archive was already stream-verified at 411,160 unique eligible organization numbers: gzip SHA-256 `1c89710e5b01f8617e86d09fbdff4a52f2f8dbbba297e74f7164b5984f5a0384`; uncompressed SHA-256 `b82d6a3e7231d1759a958c282bc4366b80ec2fab8095053d8ed7fa9cd01bc838`.

Seed: `signalpost-independent-live-20261017-v1`. Sort eligible rows by SHA-256 of seed + colon + identifier. Exclude 466 identifiers found in tracked audit/gold/live fixtures and the four prior live companies. Select five per employee band (undisclosed, 5–19, 20–99, 100+), alternating registry-website availability for ten with/ten without. Prefer previously unseen legal forms, two-digit industries and municipalities; hash order breaks ties. Freeze all twenty and four five-company waves before requests. There are no disclosed 0–4 employee records in this universe. This deliberately varied stress sample is **not population-weighted** and cannot estimate competition recall.

Registry-listed candidates only (`--no-keyless-websites`); no search/provider expansion. Ten companies without such candidates were not attempted on websites, not proven to lack websites. Fresh process/state per wave; no earlier company cache or frozen identity row substituted for a live response. Existing per-run robots/request coalescing remained allowed. Explicit evaluation cutoff `2026-10-17T23:59:59Z` permits current-day undated observations; this is not a claim about default run-start-cutoff coverage. Gateway request limits were 40,45,33,33; the shared physical ceiling governed additional transport attempts.

Actual production command shape (paths varied by wave):

```sh
signalpost-starter-kit/.venv/bin/python signalpost-starter-kit/run_signalpost.py \
  --input wave1/input.jsonl --output wave1/output.jsonl \
  --state-output wave1/state.json --checkpoint wave1/checkpoint.sqlite \
  --config config.json --live-brreg --live-websites --no-keyless-websites \
  --evidence-cutoff 2026-10-17T23:59:59Z
```

The external instrumentation imported this same entrypoint through `runpy`, with its source-send guard and timing hooks; actual production CLI, gateway, scheduler, extractors, graph validator, synthesis, paired persistence and evaluator adapter ran. Each wave produced five ordered terminal rows and exited zero. The 20 distinct baseline companies all had terminal `available` because supported identity facts existed; that does not make every section available.

| Organization number | Live legal name | Form | Available claim atoms | Physical attempts* |
|---|---|---|---:|---:|
| 932374099 | FLATEBYVEIEN 7-9 AS | AS | 79 | 8 |
| 912427730 | LUNNER ALMENNING | FLI | 153 | 10 |
| 984073216 | BIKUBÅ BARNEHAGE SA | SA | 120 | 4 |
| 970107592 | STIFTELSEN MODUM BAD | STI | 189 | 10 |
| 981299876 | BLINDHEIM BORETTSLAG | BRL | 111 | 10 |
| 944844139 | NORDISK KELLOGG NORGE, FILIAL TIL NORDISK KELLOGG APS DANMARK NUF | NUF | 92 | 8 |
| 959704996 | TENDEN ADVOKATFIRMA ANS | ANS | 302 | 20 |
| 882811972 | HAVILA SHIPPING ASA | ASA | 127 | 4 |
| 916876718 | VERDIPAPIRFONDET EQUINOR AKSJER PACIFIC INDEKS | VPFO | 46 | 4 |
| 955007514 | OTRA KRAFT DA | DA | 81 | 11 |
| 984068085 | VOLDA OG ØRSTA REINHALDSVERK IKS | IKS | 168 | 8 |
| 950437537 | STUDENTSAMSKIPNADEN I AGDER | SÆR | 304 | 6 |
| 917377286 | SAMEIE SOLSIKKEN 1-3 FELLESEIENDOM | SAM | 114 | 10 |
| 954799778 | VARIG ORKLA FORSIKRING GJENSIDIG | GFS | 124 | 4 |
| 976995082 | KVAM KYRKJELEGE FELLESRÅD | KIRK | 137 | 7 |
| 964938466 | ELSA ENGER TRANSPORT - innehaver Knut Enger | ENK | 76 | 8 |
| 912118576 | P/R LEIKEN DA | PRE | 75 | 4 |
| 970288945 | BRUSHYTTEN SKANSEGUTTENES FORENING | BA | 84 | 8 |
| 948205149 | HELGELAND BBL | BBL | 136 | 4 |
| 983609155 | ENOVA SF | SF | 160 | 11 |

*Host-shared robots attempts are charged to their initiating company; these are not independent marginal company costs. Counts are baseline only.

## Actual coverage

| Field family | Companies with a supported fact | Available claim atoms |
|---|---:|---:|
| exact legal identity | 20/20 (100%) | 40 |
| business industry description | 19/20 (95%) | 24 |
| financial filing metadata | 18/20 (90%) | 434 |
| promotable numeric financial | 0/20 (0%) | 0 |
| leadership roles | 20/20 (100%) | 1654 |
| workplaces locations | 19/20 (95%) | 215 |
| verified owned website | 1/20 (5%) | 1 |
| owned public profiles | 1/20 (5%) | 3 |
| hiring | 0/20 (0%) | 0 |
| dated public activity | 0/20 (0%) | 0 |
| legal historical names | 12/20 (60%) | 27 |

The filing results represent **62 records** with **434 metadata claims**, not acquired annual-report PDFs or promotable financial metrics. Roles represent **202 role records** and workplaces **34 registered subunits**; atom counts include name/code/status/association and filing dimensions, not that many distinct people or accounts. Industry classifications cover 19 companies; only one gained a verified website narrative. No company was declared to have zero jobs merely because no jobs were published.

Canonical-section mapping: identity/industry → `identity_brand`; filings/metrics → `accounts_history`; roles/subunits → `leadership_workplaces`; owned websites/profiles → `website_owned_profiles`; jobs/dated news → `hiring_activity`; claim-level support → `claims_evidence_states`; snapshots/deltas → `refresh_changes`. All seven sections were serialized for every row. Totals: **2,678 claims**, **2,729 evidence records**, **82 snapshots**. All 20 have evidence-linked deterministic synthesis (1,707 sentences), but much of it is verbose registry metadata. This is not twenty rich analytical company narratives. Historical legal names were found for 12 companies; those source histories are not manufactured live change events.

## Source outcomes and missing-information causes

Across the full 193-attempt allocation: **150 HTTP 200**, **14 redirects** (six 301, six 302, two 308), **two 404**, **two 500**, **one 403**, **24 connection failures**. No measured source timeout or paid request occurred. The 24 failures were conservative per-address attempts to BRREG robots, whose documented structured-API outage exception was applied; gateway retries account for six additional robots attempts across six fresh contexts. Website robots decisions were allowed for all ten candidates; there was no robots bypass or explicit-disallow override.

- **Identity/roles/workplaces:** 20 exact live identities and role collections; 19 positive workplace collections. The fund `916876718` returned an explicit valid empty HAL collection, originally misclassified as malformed. The narrow fix establishes source-bound completeness with a real `/page/totalElements` locator, without inventing `_embedded` bytes or workplaces.
- **Financial values:** 18 successful account responses, 62 records, 1,465 raw numeric amount nodes, **no `enhet` scale labels**. Currency is not scale. Metrics remain withheld under the approved contract; a source-contract/unit-proof decision is needed before numerical promotion. Accounts for `916876718` and `954799778` returned HTTP 500 and remained failed, not zero-valued. The 858 unit diagnostics include repeated metric/unit-state entries and are not 858 financial facts.
- **Website discovery:** ten current native BRREG homepage values reached the gateway (`registry_live`), ten attempted, zero robots blocks, one accepted owned site, one 403, three completed ambiguous decisions. Five baseline candidates ended as failed/unreachable when subsequent fetches hit the wave budget; these were **budget skips, not demonstrated website transport failures**. That misleading classification was corrected separately. Housing-manager candidates for Blindheim and the Solsikken sameie were not published as target-owned domains. Modum Bad's retrieved pages contain the target number but did not establish every required typed/name-bound ownership condition before the cap; safeguards were not weakened. Tenden's exact legal name, number, postal/municipality details, description and three outbound social profiles were supported.
- **Hiring/activity:** baseline hiring/activity remained not attempted for all twenty, rather than confirmed absent. Nine candidates never obtained usable ownership acceptance; ten had no attempted candidate under the registry-first budget. On the accepted Tenden site, sitemap HTML news pages were incorrectly fetched as feeds; four such HTML responses were observed. This wasted requests and delayed page extraction. The fix preserves explicit RSS/Atom declarations but treats ordinary sitemap articles as pages. Exhaustion also deferred the zero-network jobs/activity extraction pass, now corrected while retaining deadline/reserve gates. Captured careers content links to unlisted `app.cvideo.no`; it was refused and never fetched. Remaining no-posting/no-dated-activity results are abstentions, not evidence that the companies have none.
- **Synthesis:** exact registry facts are useful, but limited verified company-site reach restricts business explanations. No unsupported narrative, hiring fact, comparison ranking, unit or financial number was invented to increase coverage.

## Independent factual adjudication

A separate checker interpreted captured authoritative JSON values/pointers and documented display transformations, and independently verified role endpoint/company and workplace parent/child relationships. It did not call the production BRREG extractor. **2,670 available registry claim values matched, zero mismatched**: 340 identity,27 historical-name,434 filing-metadata,1,654 role,215 workplace atoms. Two ENK municipality citations could not be resolved from the saved body copy after private-address-container redaction; they are disclosed as unresolved support-copy checks, not counted as correct from those bytes.

Six published Tenden website/profile facts were separately interpreted from the HTML: exact legal-name/number/address ownership context, website URL/domain, description metadata and three actual outbound links. All six were supported. No platform API or social page was fetched, and an outbound link is not broader evidence about platform content. Two companies (Flatebyveien and Havila) were independently re-requested at entity, roles and accounts endpoints: **six successful responses, all six byte hashes identical** to their original source bodies.

Thus **2,676 source-support checks were confirmed, zero wrong-company associations or fabricated financial figures were confirmed, and two support-copy checks remain unresolved**. This is review of returned claims in this cohort, not population precision/recall, completeness, or hidden evaluator ground truth. The separately documented frozen-gold tests remain fixture evidence, not live factual accuracy.

## Performance and reliability

Four actual production waves took **25.10,57.15,27.23,21.01 seconds**, totaling **130.48 seconds** of processing (20 companies; 9.20 companies/minute; **7.95** conservative attempts/company). Elapsed time from the first source reservation through the final wave publication was **248.73 seconds including inspection pauses**. The 130.48-second sum excludes those pauses, SSH setup and initial interpreter/import setup. The recheck took 6.45 seconds; the live one-company refresh took about 29.54 seconds and 24 attempts. Fresh per-wave gateways repeat shared robots work.

Worker-active aggregate time per company: p50 **8.70s**, p95 **26.25s**, excluding queue waits, checkpoints and final batch publication. Peak process RSS **148,964 KiB (145.5 MiB)**; aggregate CPU **25.29s**; measured finalization **0.71s** across four waves. Gateway network elapsed sums to **141.47s**, overlapping across workers; it must not be added to wall time or subtracted as if sequential. Extraction-only CPU was not separately profiled. A naive linear projection is about 109–120 minutes for 1,000–1,100 companies under these small-wave observations; this is **not a demonstrated live-runtime guarantee**, and shared pacing, batch concurrency, site delays and budget choices change it. Offline 1,100-company throughput does not establish live completion time.

## Reproduced fixes and acceptance evidence

1. Explicit empty BRREG HAL workplace pages are accepted only with integer-zero first-page counts, no `_embedded` and no next link. Completeness cites `/page/totalElements`; malformed/contradictory/boolean-count pages remain rejected. Production CLI replay of the captured fund response preserves its 46 facts and publishes no workplace.
2. Sitemap HTML articles are fetched once as pages, not first as pseudo-feeds. Explicit declared feeds and bounded source policies remain intact.
3. Refresh compares `website_description` against the same source resource. Multiple page descriptions remain supported by the established M09 contract. Three original cross-page false updates become newly observed document metadata (`old_value: null`), rather than replacements of the homepage. Actual edits to the same page remain changes; same-value corroboration and repeats do not create events. Original live refresh output remains unchanged for audit.
4. HTTP/logical request exhaustion no longer discards the final extraction-only jobs/activity pass. No source request is added; time/completion-reserve gates still apply. Budget skips no longer masquerade as website transport failures, and completed extraction no longer retains a stale `not_attempted` label.
5. A refused ATS-link diagnostic previously failed evaluator serialization. The validator now accepts only the exact operational `website_research.ats_origins[*]` record with a nonempty host, a known refusal status and `requested: false`; unknown keys/other paths/requests remain rejected. Diagnostics are not facts. This latent output blocker was reproduced offline with captured legitimate source content, not as a dropped baseline company.

**Local final gate: 466 tests and 223 subtests passed** (one dependency deprecation warning). Captured-source production CLI replays, repeat refresh (zero additional events), M07 replay, M08 gold, M06 scale/provenance and independent CLI/failure acceptance passed and are recorded in the external bundle. Exact final-SHA CI must pass before the final handoff. The accepted dashboard's design and saved four-company demonstration data were not changed.

## Remaining risks and owner actions

The official [evaluation contract](https://builderr.ai/docs/signalpost-evaluation-harness.md) assigns 50 points to recall/coverage,30 to precision/evidence,12 to explanations,8 to usability; company and claim recall within a field contribute 70/30. This cohort has no labeled union-of-discoveries recall denominator, so **no official score or qualification claim is justified**. Missing numeric finances, very low verified-site coverage and absent hiring/activity are substantial competitive risks despite useful registry results and high observed source support.

Highest-impact next decisions, outside this closed evaluation: authoritative unit/scale proof under a reviewed source contract; more permitted website ownership evidence without weakened checks; approved hiring acquisition where external ATS is currently refused. No new acquisition/cohort is authorized by this report. Builderr's exact unpublished parser/argv/runtime/prior-state handoff remains unverified; obtain that clarification rather than inventing aliases. Owner review, organizer access to the private exact SHA and actual submission remain manual authorization steps. Keep the repository PRIVATE; nothing was submitted or publicly deployed.

Data attribution: Brønnøysundregistrene, retrieved 2026-10-17, NLOD 2.0; company-site facts retain their URLs, observation times, hashes and exact evidence scope. No PDF was acquired, no paid API/model was called and no source licence was broadened.
