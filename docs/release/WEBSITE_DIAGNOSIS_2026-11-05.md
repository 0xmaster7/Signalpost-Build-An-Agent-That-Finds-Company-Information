# Website diagnosis, 5 November 2026

Diagnosis precedes fixes (A3). Audited source baseline: `725eb6375feb0529da4cbe4f73bff05bd6e693f2`. No production changes, live source requests, commits, pushes, or benchmarks were made. Final freeze: 7 November 2026, 18:00 IST / 12:30 UTC.

## Proven findings

The 3 November matched run verified **0/100 companies**. Its website-verification checkpoints contain **192 candidate decisions across 81 companies**; **19 companies have no candidates**. Every one of the 100 matched website audits equals its saved replay audit. The capture manifest is complete, and the analysis verified the content hashes and index correspondence of all **269 physical website-verification attempts**. This checks recorded evidence consistency, not the truth of a site's ownership claims.

The original 26 October comparison is a different execution: our website phase was `deadline_skipped` for all 100 companies, with reason `soft_deadline_or_completion_reserve`. Arnav's comparison reports 25 companies with verified websites. Those labels are comparison outputs, not an independent correctness assessment. Original source versions were ours `455d97925b3bcd4e7c47a643da5e4328a8299f5d`, Arnav `d2666383328c1779973af9d74b1d0d9b884b66e4`. Do not attribute the original zero to the newer run's robots or identity decisions.

### The 116 `robots_unreachable` decisions

Counts below are candidate decisions, not requests, companies, or unique domains. Retries and redirects are counted separately only in the physical-attempt inventory.

| Classification | Decisions | Captured evidence |
| --- | ---: | --- |
| DNS | 103 | Each has `robots_error=hostname did not resolve` and a matching recorded `dns_policy` control with `failure=unresolved` for its exact robots URL. Preflight failure precedes HTTP capture. |
| Timeout | 4 | Terminal robots attempt is `timeout`; eight timeout attempts include retries. |
| HTTP 5xx | 1 | `renderburger.no`: two recorded 503 attempts. |
| Connect failure specifically established | 0 | The recording does not retain transport exception subtype; zero here means none proven. |
| HTTP 403 | 0 | None explains these 116 decisions. |
| HTTP 404 | 0 | None explains these 116 decisions. |
| Explicit disallow | 0 | Recorded separately as `blocked_robots`. |
| Unknown transport subtype | 8 | Sixteen `transport_error` attempts with no response. Cannot distinguish connect refusal, TLS, socket, or other transport failure. |
| Unknown with no captured/control evidence | 0 | All 116 have DNS controls or relevant physical attempts. |
| **Total** | **116** | **103 + 4 + 1 + 8** |

Timeout candidates: `886658702` / `bdm-elektro.no`, `911564092` / `visitgeilo.no`, `975381781` / `vectura.no`, `995871807` / `husnesroyr.no`.

Unknown transport candidates: `918113843` / `skiptvetbilservice.no`, `923799206` / `takeawaymat.no`, `941831753` / `fordski.no` and `folloautoco.no`, `976466306` / `kapitalstyring.no`, `976934318` / `byggmesteradnekvam.no`, `989030760` / `rockpocket.no`, `993955299` / `ngbutikk.net`.

DNS accounts for 88.8% of unreachable decisions. Of the 103 DNS decisions, **97 are name guesses**; the remaining six are four registry-domain leads, one workplace lead, and one registry homepage. Across all 116 unreachable decisions, source totals are 104 `keyless_no`, eight `registry_email`, two `registry_live`, one `workplace_contact`, and one `wikidata`.

Physical robots attempts in the website phase: 43 HTTP 200, 34 HTTP 301, two HTTP 307, three HTTP 403, ten HTTP 404, two HTTP 503, eight timeouts, and sixteen unspecified transport errors: **118 attempts**. These are not a substitute for the candidate classification. In `NetworkGateway.robots_decision`, 4xx responses become empty rules and normally allow the page attempt; timeouts, transport failures, and 5xx become unreachable. Explicit disallow is evaluated from retrieved rules. No evidence supports treating the 116 as 116 robots policy refusals.

The remaining candidate decisions are 46 `ambiguous`, 22 `candidate_policy_rejected`, two `blocked`, two `duplicate_page`, two `blocked_robots`, one `rejected_http`, and one `unreachable` during page fetching. Together with 116 robots-unreachable decisions these sum to 192. Publication can overwrite an identity tier with `registry_declared`; that tier alone does not mean the identity gate passed.

### Arnav's 25 reported verified companies

For every row, the original comparison's **our fetch / robots / identity evidence is unavailable because our phase was deadline-skipped**. The newer matched run provides the divergences below. The historical Arnav envelope retains page status/URL/hash metadata and identity proof descriptions, but no raw page body in its page records. The inspected original artifact tree contains reports, envelopes, registry caches, and state; it does not provide a raw website HTTP capture store. Arnav robots outcomes are therefore unavailable, and its historical ownership decisions cannot be independently reproduced from retained raw HTML.

All 25 Arnav rows record successful HTTP 200 page metadata. Arnav labels 13 of them `exact` and 12 `strong`. These identity labels use different acceptance logic and must not be equated with our exact-site gate.

`Pages` below is the matched audit's logical page-request count for the company, including other candidates; physical redirects and retries can increase attempts. `Allowed` describes our robots decision on the comparison host; missing comparison hosts have no robots/fetch evidence. Reasons are retained `review_reason` values, abbreviated as follows:

- `publisher`: `unsupported_publisher_relationship_type`.
- `insufficient`: `insufficient_direct_ownership_proof`.
- `name-only`: `name_only_or_missing_address_and_subject_scoped_id`.
- `conflict`: `conflicting_structured_company_identity`.

| Org / company | Arnav website / identity | Our matched candidate and robots divergence | Pages / fetch / identity divergence |
| --- | --- | --- | --- |
| 912444899 SUGAR SHOP AS | sugarshop.no / exact | Same host generated; allowed. Hyphenated guess fails DNS. | 4; HTTP 200; ambiguous, publisher. |
| 980170519 KJELLS HYTTESERVICE AS | kjellshytteservice.no / strong | Registry and domain leads reach same host; allowed. Hyphenated guess fails DNS. | 4; HTTP 200; ambiguous, insufficient. |
| 989748319 PRIMA ASSISTANSE AS | prima-assistanse.no / strong | Same host generated; allowed. Alternate primaassistanse.no explicitly disallowed; primaomsorg.no policy-skipped. | 8; HTTP 200; ambiguous, publisher. |
| 917445060 NORSKE TOG AS | norsketog.no / strong | Wikidata supplies same host; allowed after robots 404. | 6; HTTP 200; ambiguous, conflict. |
| 976537076 PALLESEN SVEIS AS | pallesensveis.no / exact | Same host generated; allowed. Hyphenated guess fails DNS. | 5; HTTP 200; final candidate label duplicate_page; review reason publisher. |
| 963915411 AS KONGSVINGER RØRLEGGERSERVICE | kongsvingerrorleggerservice.no / strong | Same host generated; allowed. Hyphenated guess fails DNS. | 1; HTTP 200; ambiguous, conflict. |
| 914631408 M VEST WATER AS | mvestwater.com / strong | Comparison host absent. Only vest-water.no and vestwater.no generated; both fail DNS. | 0; no page fetch or identity evaluation. |
| 997722094 STEINMILJØ AS | steinmiljo.no / strong | Same host generated; allowed. | 7; six physical HTTP 200 pages, two page timeouts; one ambiguous candidate and one unreachable candidate, publisher review reason. |
| 932225999 BUNADSMESTEREN AS | bunadsmesteren.no / exact | Registry supplies same host; allowed. | 1; HTTP 200; ambiguous, publisher. |
| 937322364 MESNA BYGGSERVICE AS | mesnabyggservice.no / exact | Same host generated; allowed. Hyphenated guess fails DNS. | 1; HTTP 200; ambiguous, insufficient. |
| 991504125 ADVOKATFIRMA OLAFSEN AS | advokatolafsen.no / strong | Domain lead supplies same host; allowed. Two legal-name guesses fail DNS. | 3; HTTP 200; ambiguous, name-only. |
| 989389009 CASA BYGG AS | casabygg.no / exact | Registry supplies same host; allowed. | 1; HTTP 200; ambiguous, name-only. |
| 923774688 KBE MASKINUTLEIE AS | kbe-maskinutleie.no / exact | Same host generated; allowed. Unhyphenated guess fails DNS. | 5; HTTP 200; final candidate label duplicate_page; review reason publisher. |
| 890397832 FRYDENBØ FORWARD AS | frydenbo-maritime.no / exact | Registry supplies same host; allowed. Group-domain leads also fetched; guesses fail DNS or policy. | 10; HTTP 200; ambiguous, insufficient. Group pages remain distinct ownership evidence. |
| 985865108 W-TEK AS | wtek.no / exact | Comparison host absent. Registry/domain leads point at alfacomputing.no; robots redirects rejected outside source allowlist. | 0; no comparison-host fetch or identity evaluation. |
| 979573464 CUROTECH AS | fdvweb.no / exact | Registry supplies same host; allowed. curotech.no policy-skipped. | 3; HTTP 200; ambiguous, name-only. |
| 913543351 OLASTUEN BYGG AS | olastuenbygg.no / strong | No candidates. | 0; robots/fetch/identity not evaluated. |
| 979956258 KNOWLEDGEGROUP AS | knowledgegroup.no / exact | No candidates. | 0; robots/fetch/identity not evaluated. |
| 989030760 ROCK POCKET AS | rockpocket.games / exact | Registry/domain leads supply same host; allowed after robots 404. .no guesses fail DNS or unspecified transport. | 6; HTTP 200; ambiguous, insufficient. |
| 920710514 LAUVVERKET AS | lauvverket.no / strong | No candidates. | 0; robots/fetch/identity not evaluated. |
| 914786703 INNSTRANDA LEGESENTER AS | innstranda-legesenter.no / strong | Same host generated; allowed. Workplace lead fails DNS; unhyphenated guess policy-skipped. | 1; HTTP 200; ambiguous, insufficient. |
| 968091336 TVEIT AS | tveitas.no / strong | No candidates. | 0; robots/fetch/identity not evaluated. |
| 958260563 ETNE CONTAINERSERVICE AS | bestillcontainer.no / strong | Comparison host absent. etne-containerservice.no policy-skipped; etnecontainerservice.no fails DNS. | 0; no comparison-host fetch or identity evaluation. |
| 827442852 MASKINSALG AS | maskinsalg.no / exact | Registry supplies same host; allowed. | 3; HTTP 200; ambiguous, name-only. |
| 998463548 PULS OASEN AS | pulsoasen.no / exact | Registry/domain leads supply same host; allowed. Hyphenated guess fails DNS. | 4; HTTP 200; ambiguous, insufficient. |

Thus **18/25 comparison hosts are generated and fetched**, and **7/25 are absent**: four no-candidate companies, two mismatched name/domain guesses, and one registry alias whose robots redirect is blocked by host policy. Among the 18 reached hosts, six companies have publisher-reference reasons, six insufficient ownership proof, four name-only reasons, and two structured conflicts. None is proven recoverable without a separate gate-preserving change and evaluation.

All 19 no-candidate orgs: `821194652`, `912156915`, `913015185`, `913543351`, `914790514`, `916359667`, `920710514`, `924356715`, `925733415`, `930181358`, `931769944`, `934093054`, `935821622`, `937060092`, `940940842`, `952780093`, `968091336`, `979956258`, `998688957`.

## Exact source diagnosis

### Formatted organization numbers

In `signalpost/websites.py`, `_identifier_values` recognizes nine digits separated by any repetition of whitespace, periods, or hyphens: `(?<!\d)\d(?:[\s.\-]*\d){8}(?!\d)`. It removes nondigits from matches. This accepts ordinary spaces, nonbreaking spaces, periods, hyphens, and surrounding `NO … MVA` text. It handles strings and recursively handles dictionary `value`/`identifier` fields and lists. Integer values are ignored, slash-separated numbers are ignored, and a contiguous ten-digit value is rejected.

HTML paths are inconsistent with that parser:

- `_site_ownership_evidence` uses an exact contiguous target-number regex for `exact_org` in an operator block.
- `_negative_subject_context` also searches for a contiguous target number when locating non-owner role context.
- `_site_shell_has_competing_identifier` extracts only contiguous nine-digit competing IDs.

A formatting fix restricted to positive matching could therefore weaken safeguards: the same formatted number could begin to establish ownership while a formatted foreign number or non-owner context still evades a veto. Normalize number spans consistently in both positive and negative paths, preserve DOM/block scope and original span evidence, and preserve exact legal identity, resource binding, conflicts, related-entity restrictions, and gate requirements. Do not strip every nondigit from a whole page or concatenate across blocks.

Captured diagnostic scanning found formatted target-number strings in pages for PALLESEN SVEIS (5 physical 200 pages), BUNADSMESTEREN (1), CASA BYGG (1), KBE MASKINUTLEIE (5), FRYDENBØ FORWARD (6), CUROTECH (3), MASKINSALG (3), and PULS OASEN (4). These counts scan parsed HTML text and script strings and do **not** establish an operator block, ownership, or fix yield. Some companies also contain contiguous target numbers on other pages. Formatted-number inconsistency is proven in source; its contribution to final acceptance remains unproven.

### Same-document publisher references

`_direct_typed_entities` accepts a direct dictionary but does not resolve `@id` references against sibling `@graph` records. `_site_ownership_evidence` treats a bound WebSite's `publisher` dictionary lacking a supported `@type` as `unsupported_publisher_relationship_type`, and returns before trying HTML operator evidence.

In retained matched page bodies, `publisher` is an `@id`-only dictionary with a same-document typed Organization target for SUGAR SHOP (4 pages), PRIMA ASSISTANSE (8), PALLESEN SVEIS (5), STEINMILJØ (6), BUNADSMESTEREN (1), and KBE MASKINUTLEIE (5). Their candidate review reasons match this source path. This proves a representation mismatch in the evaluated evidence. It does not prove the resolved Organization is the target company or that all other ownership requirements pass.

A focused proposal is strict same-document resolution for directly referenced relationship entities, with bounded traversal, duplicate-ID/cycle/ambiguous-target rejection, supported relationship types, exact response-resource binding, exact target name/identifier checks, and all current conflicting-operator checks. Never use a matching Organization merely because it occurs elsewhere in the graph. Existing structured-conflict cases for NORSKE TOG and KONGSVINGER must continue to abstain until separately resolved by evidence.

### Candidate generation

`normalize_name` removes legal suffix tokens. `_distinctive_tokens` then retains only tokens at least three characters long. `keyless_no_candidate` removes `GENERIC_KEYLESS` terms and requires **two distinct remaining tokens**, takes at most five tokens, transliterates æ→ae / ø→o / å→a, and generates one hyphenated `.no` host. `additional_no_candidates` adds the unhyphenated variant, for at most two guesses. Discovery sources are sanitized, URL-deduplicated, and capped at six candidates in source order; guesses consume the same candidate and crawl budgets.

Consequences reproduced from exact baseline helper functions:

- OLASTUEN BYGG loses generic `bygg`, leaving one token; no guess.
- KNOWLEDGEGROUP, LAUVVERKET, and TVEIT each have one token; no guess.
- W-TEK loses the one-character `w`, leaving one token; no guess.
- M VEST WATER loses `m` and guesses `vest-water.no` / `vestwater.no`; it cannot generate the comparison's `mvestwater.com`.
- SUGAR SHOP yields `sugar-shop.no` and `sugarshop.no`; the latter reaches the comparison host.
- ETNE CONTAINERSERVICE cannot derive an unrelated trading domain such as `bestillcontainer.no` from legal-name concatenation.

Focused proposals: prioritize already evidenced registry/workplace/discovery candidates; preserve provenance and source budgets; separately evaluate a small bounded class of distinctive single-token and initial-preserving guesses; and use existing supported discovery adapters for unrelated trading names. Keep all generated URLs as candidates subject to the full current gate. Do not blanket-enable arbitrary single words, assume `.no` is the only valid TLD, relax redirect allowlists, or promote registry URLs to verified ownership. The measured 97 guessed-host DNS failures justify candidate-quality work, not relaxing robots behavior.

## Integration hooks and required follow-up

No fixes are implemented by this audit. Suggested independently reviewable hooks are `_identifier_values` and the three HTML identifier consumers; `_direct_typed_entities` and `_site_ownership_evidence`; and `keyless_no_candidate` / `additional_no_candidates` plus source ordering in `research_company`. `verify_site_pages` remains the acceptance gate. The scheduler owner can consume the distinction between original deadline skips and newer completed-but-unverified website work; no scheduler files were changed.

Before accepting a later fix, use retained captures to demonstrate both improved valid coverage and unchanged rejection of foreign-company identifiers, unrelated publishers, customer/supplier mentions, mixed graph identities, shared group homepages, ambiguous IDs, and source-host redirects. Keep scope, period, unit, and evidence checks unchanged. Preserve the two genuine robots-disallow decisions. Replay success alone does not establish precision or recovery: this audit found exact replay equality despite zero verified websites.

The eight transport failures need retained exception class/reason metadata in a future authorized recording change before they can be classified as connect/TLS/other. This audit neither guesses their cause nor edits recording behavior.

## Reproduction and checks

Changed files only:

- `docs/release/WEBSITE_DIAGNOSIS_2026-11-05.md`.
- `signalpost-starter-kit/scripts/audit_website_diagnosis.py` (standard-library-only, read-only SQLite and captured files; public-safe projections, no HTTP client).

Run on the isolated evidence host without writing the script there:

```sh
ssh pancakes 'python3 - <acceptance-root> <original-comparison-root>' < signalpost-starter-kit/scripts/audit_website_diagnosis.py
```

Artifact roots are private operational inputs, deliberately omitted here. The script reads `matched`, `matched-replay`, and the original `comparison/per-company.jsonl` and `arnav/out/envelopes.jsonl`. It never prints raw bodies, proof spans, mailboxes, phone numbers, credentials, or request headers. No private capture is included in this report.

Passed: complete capture audit with 269 verified website-attempt hashes; 100/100 website audit comparisons equal between matched and replay; 116 unreachable decisions exhaustively partitioned; all 25 comparison companies joined; captured publisher-reference and formatted-number presence diagnostics; exact-source helper probes using AST-selected baseline functions:

```sh
python3 signalpost-starter-kit/scripts/audit_website_diagnosis.py --source-probes signalpost/websites.py
```

Source probes passed six identifier formats, four boundary/type cases, and seven candidate cases. Full production-module import was unavailable in the local clone because `bs4` is absent; no dependency installation or full application suite was performed. No changed production behavior is claimed. Historical Arnav raw-HTML/robots reproduction, transport-error subtype, prospective fix yield, and end-to-end precision remain unproven.
