# M12 website ownership P1 remediation

**Status:** host-bound implementation pushed; implementation-SHA CI passed
**Branch:** `codex/m12-final-sol-remediation`
**Earlier remediation start:** `a2c39a43648686dcdf687f1ab795d62b250a72b5`
**Host-bound continuation start:** `ac2f6fa874191c2d2b36a32dce2808ff5682f65f`
**Previous ownership implementation:** `df1f26ef9d47aad00e287a91a75d0db3b81cb838`
**Host-bound implementation SHA:** `c2ffd33a153ac5e409cf71936c831b795eaddc6d`

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

### Host-bound continuation

Two further independent production-path failures were reproduced against the
continuation start SHA `ac2f6fa874191c2d2b36a32dce2808ff5682f65f`:

1. A fetched `rival.no` page carried a `WebSite` object whose URL was
   `acme.no` and whose publisher was Acme. The unbound publisher caused
   verified URL/domain claims on `rival.no`.
2. A Rival article with Rival site branding had a target-company contact card
   containing the exact registered legal name and address. The contact block
   was treated as operator evidence and produced verified website claims.

Both regression tests failed against that starting SHA because the production
path emitted those claims. The fix applies the same host/operator/subject
distinction across candidate assessment and content extraction:

- Candidate response host must match the registry/search candidate host;
  only the ordinary `www` alias is normalized. Host-changing redirects do not
  transfer candidate ownership.
- A `WebSite` record is eligible only when its canonical root URL binds to the
  fetched response host. Its publisher then identifies the operator of that
  site record, not an unrelated host named elsewhere in the page.
- Article content and contact cards cannot establish host operator identity.
  Visible site-brand blocks are checked for conflicting legal identity.
- Off-host redirected page, sitemap, and feed responses are excluded from
  factual extraction, even when the candidate's own homepage is verified.
- All verified website URL/domain publication still flows through the
  accepted-candidate path; page-level shared-domain verification remains
  URL/path scoped.

The reusable positive/negative review matrix is in
`M12_HOST_BOUND_OWNERSHIP_INVARIANTS.md`.

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

- Earlier reproduction set: 3 false-acceptance tests reproduced and fixed.
- Host-bound continuation repros: 2 false-acceptance tests reproduced on
  `ac2f6fa` and rejected on the updated implementation.
- Focused website/M03/M04/M05/M06/M07/M08/M09/live-shape tests: 244 passed,
  84 subtests passed.
- Complete test suite: 416 passed, 117 subtests passed.
- M07 refresh replay: 12 profiles, 6 expected changes, TP 6 / FP 0 / FN 0;
  provenance complete and event replay idempotent.
- M08 gold evaluation: 4-company corpus passed; find/compare/verify accuracy
  1.0, unsupported assertions 0, citation completeness 1.0.
- M06 scale/provenance gate: passed with its report-file verifier.
- M09 crash/resume: crash points 25/50/90 recovered to 100 rows with semantic
  match; network disabled.
- Clean-CWD launcher with `PYTHONPATH` unset: passed, 4 ordered rows and 0
  physical requests.
- M08 UX/XSS smoke: passed on local loopback.
- `compileall` and `git diff --check`: passed.
- Production CLI/evaluator serialization for both new failures: passed with
  no verified website URL/domain in either final envelope.
- Host-changing initial and deep-page redirect tests: passed; the deep
  redirected page did not create a description claim or snapshot.
- Positive same-host `WebSite.publisher` and non-JSON-LD legal/contact cases:
  passed; existing target-owned customer-story and shared-page tests passed.

Synthesis boundary and release-bundle portability fixes remain in the baseline
and were not modified by this remediation. Historical live reports were not
rewritten. The prior live run does not measure this fix. No new live cohort
was run. Competition submission remains HOLD pending independent verification.

## Git/CI checkpoint

Host-bound implementation commit `c2ffd33a153ac5e409cf71936c831b795eaddc6d`
was pushed normally to the remediation branch. Remote verification matched
that exact SHA. GitHub Actions run
[38120853363](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/38120853363)
completed successfully on that exact implementation SHA. Its starter tests,
M07/M08, evaluator, M03/M04/M05, M01/cardinality, refresh replay, M06
scale/provenance, clean-CWD launcher, and UX smoke steps all passed.

This report update is documentation-only and will be included in the final
push/CI checkpoint. The source implementation SHA above remains the tested
code revision.

## Final proof-contract correction

The follow-up began at `6541eb26234a579c7f3eb56cc7c5083c9bf00148`. The
concise proof contract is recorded separately in
`M12_WEBSITE_OWNERSHIP_PROOF_CONTRACT.md`, grounded in audited plan sections
8.3–8.6. The existing acceptance and publication path was traced through
`_site_ownership_evidence`, `verify_site_pages`, `_assess_candidate`, and the
single accepted-candidate writer in `research_company`, followed by
`validate_publication_graph`/`to_evaluator`.

At the follow-up starting SHA, all three new negative cases reproduced as
verified URL/domain publications in the final evaluator payload:

1. A response on `rival.no` used a host-bound `WebSite` record whose target
   publisher Organization URL pointed to `acme.no`, while the visible site
   brand identified Rival Group AS.
2. A `/profiles/acme` response used Acme's exact legal name and registered
   address in a contact card inside ordinary `<main>` content.
3. A shared-domain `WebPage` for `/brands/other` borrowed Acme's publisher
   from a different `WebPage` record for `/brands/acme`.

The correction keeps each structured record's publisher bound to that record
and its fetched resource; an explicit publisher Organization URL on a
different host is contradictory; legal site-shell identity conflicts are
considered on every page type; and main-body identity on a profile route is
page-subject evidence. For article documents, a legal/contact identity in the
site header or navigation remains usable as operator evidence, while article
body contact cards stay excluded. Shared-domain proof remains page-only.

The header-only, non-JSON-LD customer-story positive fixture was replayed
against both historical source trees: `ac2f6fa874191c2d2b36a32dce2808ff5682f65f`
published verified URL and domain claims, while
`6541eb26234a579c7f3eb56cc7c5083c9bf00148` published neither. The current
implementation again publishes both claims from the independent legal
operator header. Existing non-JSON-LD legal/contact, owned customer-story,
shared subsidiary-page, and final-adapter fixtures remain covered.

The new and existing production-path tests exercise both URL and domain
claims through final evaluator validation. Record-order and equivalent DOM
layout variants preserve the negative outcomes when unrelated or contradictory
records are added. The complete suite passed: 420 tests and 130 subtests.
Focused ownership/M03–M05 tests passed: 133 tests and 84 subtests. The M09
live-shape tests passed within the full suite. M07 replay passed on 12 rows
(6 true positives, 0 false positives, 0 false negatives; complete provenance
and idempotent event IDs); M08 gold passed on 4 companies (find/compare/verify
1.0, unsupported assertions 0, citation completeness 1.0). M06 scale and
provenance verification passed. M09 crash/resume passed at 25/50/90 durable
envelopes, each restoring 100 ordered rows with semantic match. Clean-CWD
launch passed with 4 rows and 0 HTTP requests; local M08 UX/XSS smoke passed.
No live cohort or external source acquisition occurred.

The remediation changes only website ownership resolution and its
regressions. Financial safeguards, roles/workplaces, job/activity boundaries,
the closed synthesis schema, and release-bundle portability were not changed.
Historical live evidence remains unchanged; competition submission remains
HOLD. The implementation commit `41e63e7991b66566ece4375fade7065bd648dc31`
was pushed normally. GitHub Actions run
[38164473055](https://github.com/0xmaster7/Signalpost-Build-An-Agent-That-Finds-Company-Information/actions/runs/38164473055)
completed successfully on that exact SHA. The required starter, M07, M08,
evaluator, M03/M04/M05, M01/cardinality, refresh replay, M06 scale/provenance,
clean-CWD launcher, and UX smoke steps passed. This final documentation-only
update will receive its own exact-SHA CI verification.
