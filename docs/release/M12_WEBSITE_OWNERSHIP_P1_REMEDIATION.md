# M12 website ownership P1 remediation

**Status:** implemented locally; exact-SHA CI pending  
**Branch:** `codex/m12-final-sol-remediation`  
**Starting SHA:** `a2c39a43648686dcdf687f1ab795d62b250a72b5`  
**Implementation SHA:** `df1f26ef9d47aad00e287a91a75d0db3b81cb838`

## Finding and correction

The starting implementation could treat a target-company mention as evidence
that the target operated the candidate website. This confused three different
subjects: the researched legal entity, the website operator/publisher, and
entities described by an individual page.

The three latest independent findings were first replayed through
`research_company` against the starting SHA. Each test failed against that
version because it emitted a verified website claim:

1. A rival article's `.about` block repeated Acme AS's exact name and address.
2. A group-hosted article described a subsidiary with its exact name/address.
3. A rival `NewsArticle` named Rival as publisher while a target `Organization`
   record used the article URL.

The implementation now resolves an explicit ownership decision before site
identity can be published. A `WebSite.publisher` Organization or a qualifying
site-root Organization can establish the operator when no competing operator
identity exists. Visible legal/contact evidence must be scoped to operator
blocks; article, `.about`, and footer content cannot establish that identity.
Article publishers and competing site identities cause rejection. A
`WebPage.publisher` or `WebPage.mainEntity` can establish only a target-specific
representation on an explicitly configured shared domain, with exact target
identity and page-URL binding. That result publishes the verified page URL,
never ownership of the shared domain.

The decision records its method, subject scope, identity block hash where
applicable, page URL, and page content hash in the existing closed proof
envelope. No synthesis or release-bundle code/schema was changed.

## Adversarial results

The production-path test matrix rejects article/customer/supplier/partner/
auditor/press mentions; incidental organization numbers; repeated target
addresses in article, `.about`, or footer content; a target Organization URL
that matches a rival article; competing Organization or publisher identities;
and page-specific shared-domain evidence presented as root-domain ownership.

Positive cases retain a registry candidate corroborated by the target's exact
registered address in a legal/contact block, a target-published `WebSite`,
target-owned customer articles, and an exact target-specific shared-domain
page. The latter produces a URL claim only. Sites without JSON-LD remain
eligible when independent legal/contact operator evidence is sufficient.

The conservative trade-off is that a site whose only target identity is in an
article/footer/about block remains ambiguous, and a target-specific shared
page does not verify its whole group domain. This may withhold valid candidates
whose operator cannot be independently established; it avoids converting a
mention into ownership.

## Verification

All checks below used local deterministic fixtures; no new live cohort or
external source acquisition was performed.

- Starting-SHA reproductions: 3 failures as expected (each was a false
  acceptance).
- Focused website/M03/M04/live-shape tests: 99 passed, 59 subtests passed.
- Complete test suite: 409 passed, 115 subtests passed.
- M07 refresh replay: 12 profiles, 6 expected changes, TP 6 / FP 0 / FN 0;
  provenance complete and event replay idempotent.
- M08 gold evaluation: 4-company corpus passed; find/compare/verify accuracy
  1.0, unsupported assertions 0, citation completeness 1.0.
- M06 scale/provenance gate: passed.
- M09 crash/resume: crash points 25/50/90 recovered to 100 rows with semantic
  match; network disabled.
- Clean-CWD launcher with `PYTHONPATH` unset: passed, 4 ordered rows and 0
  physical requests.
- M08 UX/XSS smoke: passed on local loopback.
- `compileall` and `git diff --check`: passed.

Synthesis boundary and release-bundle portability fixes remain in the baseline
and were not modified by this remediation. Historical live reports were not
rewritten. The prior live run does not measure this fix. No new live cohort
was run. Competition submission remains HOLD pending independent verification.

## Git/CI checkpoint

The implementation is committed as `df1f26ef9d47aad00e287a91a75d0db3b81cb838`.
The remediation branch has not yet been pushed for this change, and CI for the
final remediation SHA is pending.
