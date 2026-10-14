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

## Direct ownership proof repair — failed audit SHA `290ab9126fadac2b4b577f3309b555ebf875011b`

This pass began from the failed audit commit above on
`codex/m12-final-sol-remediation`, with a clean tree and matching remote. No
historical live report was changed and no new live cohort was run.

Before changing production logic, four new production-path regressions were
run through `research_company`, canonical publication-graph validation, and
`to_evaluator`. The starting code serialized verified website URL/domain
claims for all four unsafe cases: (1) a rival-branded header with a target
`WebSite.publisher`; (2) a Person publisher whose nested `worksFor` was the
target; (3) a group `WebPage.publisher` whose nested `subOrganization` was the
target; and (4) a rival-hosted root target Organization with an explicit
off-host URL. The corrected code blocks all four negative reproductions and
accepts the positive only as a page URL, never as a target-owned domain.

Ownership now follows direct typed relationships and resource scope. A
host-level `WebSite.publisher` must directly be the exact target Organization;
related-entity descendants are not publisher proof. Site-level records bind to
the fetched host and explicit identity URLs must not contradict it. The
shared-domain exception is page-only and requires a direct target
`WebPage.mainEntity` or publisher on the same record bound to the exact page
resource, with a coherent known group operator. Contradictory site identity
abstains. Internal diagnostics distinguish insufficient proof, conflicting
operator identity, and unsupported publisher relationship types. URL and
domain claims are asserted independently by tests.

The table-driven production-path suite covers direct and nested publishers,
multiple conflicting publishers, rival/site branding conflicts, off-host and
unrelated structured records, article/profile/contact/footer mentions,
group and parent/subsidiary boundaries, path/host/subdomain/redirect/canonical
bindings, non-JSON-LD legal-contact proof, same-site redirects, target-owned
customer stories, and direct shared subsidiary pages. Metamorphic cases
reorder unrelated records and add target mentions/related entities without
turning a rival resource into verified ownership. Each case checks canonical
claims, company-owned evidence, snapshot linkage, final publication graph, and
evaluator output. Both false acceptance and false rejection cases are
represented.

Verification on the remediation tree:

- Focused ownership/M03/M05 tests: 127 passed, 132 subtests.
- Full suite: 425 passed, 178 subtests; one existing pyRdfa deprecation
  warning.
- M07 tests: 33 passed. M07 replay: 12 profiles, 6 true positives, 0 false
  positives, 0 false negatives, complete provenance and idempotent event IDs.
- M08 tests: 35 passed, 3 subtests. M08 gold: four-company corpus, find /
  compare / verify accuracy 1.0, unsupported assertions 0, citation
  completeness 1.0. Local M08 UI/XSS smoke passed for three companies.
- Offline M06 scale/provenance verifier passed. Clean-CWD launcher passed
  with four fixture rows and zero physical HTTP requests. `compileall` and
  `git diff --check` passed.
- No live cohort, external source acquisition, Builderr submission, paid
  provider, or independent Sol audit was performed. Submission remains HOLD.

The correction intentionally abstains from group homepage ownership for a
subsidiary and when identity proof is only nested, unbound, conflicting, or
incidental. This conservative result is permitted by the audited shared-domain
contract. The previously verified synthesis publication boundary and portable
release-evidence behavior were not changed.

## Final fail-closed publication repair — starting SHA `ac20826f45a9d605f9169d2590496d1d2532c992`

This follow-up preserves the starting commit and earlier live evidence. Before
production edits, both requested failures were reproduced through
`research_company`, canonical publication-graph validation, and
`to_evaluator`:

1. On `rival.no`, a direct Acme `WebSite.publisher` produced both verified URL
   and domain claims despite the visible site shell identifying Rival Media
   Ltd and its distinct organization number. The same bypass reproduced with
   a separate top-level Acme Organization record.
2. On `group.no/brands?company=other`, a WebPage for
   `?company=acme` produced an Acme page URL claim because the earlier shared
   page check compared only the path.

All three unsafe variants are now blocked. The website decision flow resolves
resource-bound root Organization conflicts, direct site publishers, explicit
site-shell operator identifiers, and explicit logo/site-name identity before
any proof can pass the single final acceptance gate. Domain proofs must have
site-operator scope and cannot pass when an explicit operator conflict exists.
The rival-brand rule uses explicit logo/site-name slots and a non-target
organization number in the site shell; ordinary customer, supplier, partner,
and article mentions outside those identity signals are not treated as
operator conflicts. A no-suffix explicit logo is also covered.

Shared-page records now bind to the fetched host, normalized path, and decoded
query parameter multiset. Parameter order and percent-encoding variations
that decode to the same name/value pairs compare as the same resource; changed
company selectors or any other changed query value do not. Duplicate
parameters remain significant. Only direct relationships on the matching
WebPage record establish subsidiary representation; the result stays page
only.

The production-path table covers Rival operators with AS, Ltd, LLC, GmbH, and
no suffix; Acme as customer/supplier/partner/article subject; false publisher
metadata with and without a separate Acme root record; shared query mismatch;
query ordering, percent encoding, and multiple query fields; and legitimate
customer/partner mentions on a directly verified Acme site. Prior tests
continue to cover unrelated/reordered Organization and WebPage records,
canonical URLs, same-site and cross-host redirects, target-owned sites,
non-JSON-LD contact/address proof, customer stories, and correctly bound
shared subsidiary pages. Every added case checks URL and domain claims
separately through the final evaluator.

Verification for this follow-up:

- Focused ownership/M03/M05 tests: 131 passed, 143 subtests.
- Full suite: 429 passed, 189 subtests; one existing pyRdfa deprecation
  warning.
- M07 replay: 12 profiles, 6 true positives, 0 false positives, 0 false
  negatives, complete event provenance, and idempotent event IDs.
- M08 gold: four companies; find, compare, and verify accuracy 1.0; unsupported
  assertions 0; citation completeness 1.0.
- M09 crash/resume: passed at 25, 50, and 90 durable envelopes, restoring
  100 ordered rows with semantic matches.
- Offline M06 scale/provenance gate passed. Clean-CWD launch produced four
  ordered fixture envelopes and zero physical requests. Local M08 UI/XSS
  smoke passed for three companies. Compile and diff checks passed.
- No live cohort, paid provider, source-rights change, Builderr submission,
  release tag, or independent Sol audit occurred. Submission remains HOLD.

The conservative tradeoff is limited to explicit conflicting identity: a
target publisher claim abstains when a distinct operator is affirmatively
identified by the site’s explicit logo/site-name slot, a non-navigation
site-shell organization number, or a resource-bound Organization record.
Ordinary navigation links and body mentions do not establish operator identity.
The existing audited group exception
continues to allow a directly supported subsidiary page without promoting
the group domain.

## Shared-page final gate and trading-name correction — start `8850abeb`

On the clean starting SHA `8850abeb54e51016fe8bf99aa3e18bcd6920fb37`, two
new cases were reproduced through `research_company`, final publication-graph
validation, and `to_evaluator` before production changes:

1. On the configured `group.no` shared domain, both a directly bound
   `WebPage.mainEntity=Acme` proof and an HTML legal-contact proof emitted an
   Acme verified page URL, although the page's explicit logo/operator block
   identified Rival Media Ltd and organization number `987654321` while the
   site publisher identified Group AS.
2. An Acme homepage with direct `WebSite.publisher=Acme AS`, its matching
   legal contact identity, and the exact logo `Acme` abstained. The parser had
   treated the whole header, including the separate legal contact block, as a
   single brand string (`Acme Acme AS ...`), creating a false brand conflict.

The correction is limited to `signalpost/websites.py` and its production-path
regressions. Header parsing now prefers explicit logo/site-name/legal-name
slots when they exist, rather than merging their text with the complete
header. The existing exact legal-name normalization recognizes `Acme` as the
legal-name stem of `Acme AS`; the final proof still requires the independently
verified direct publisher or legal-contact identity. Longer similar names
such as `Acme Services` remain contradictory. When there is no explicit brand
slot, the prior header fallback remains in effect.

The one final acceptance gate now applies the already-computed material
`site_operator_conflict` to page-only shared-domain proofs as well as
site-operator/domain proofs. Thus a target's valid, resource-bound
`WebPage.mainEntity` cannot override a conflicting visible site operator.
Group-operated subsidiary pages remain page-only and pass when the Group
operator is coherent and no material conflict is present. Both structured and
HTML proof methods use this same gate.

The added cases verify separate URL and domain publication through the final
evaluator, including Rival's different organization number, a compatible
short Acme brand, a longer similar logo, and customer/partner mentions that
cannot substitute for publisher identity. Existing ownership fixtures cover
the prior Sol reproductions, the positive group-operated subsidiary page,
target-owned customer stories, redirects, resource binding, evidence, and
snapshot integrity.

Verification on this correction:

- Before-fix production-path reproductions: both shared-page proof methods
  emitted the unsafe URL; compatible Acme logo case abstained.
- Focused ownership remediation suite: 66 passed, 121 subtests passed.
- Complete suite: 432 passed, 194 subtests passed; one existing pyRdfa
  deprecation warning.
- M03 website identity tests: 44 passed, 17 subtests. M05 jobs/activity tests:
  24 passed, 10 subtests. M07/M08 contract tests: 68 passed, 3 subtests.
- M07 replay: 12/12 envelopes; 6 expected changes, TP 6 / FP 0 / FN 0;
  provenance complete and event IDs idempotent.
- M08 gold: four-company corpus passed; find/compare/verify accuracy 1.0,
  unsupported assertions 0, citation completeness 1.0.
- M09 live-shape deterministic integration: 4 passed. M09 crash/resume:
  25/50/90 crash points restored 100 ordered envelopes with semantic match;
  network disabled.
- M06 offline scale/provenance report passed its independent verifier.
  Clean-CWD evaluator produced four ordered envelopes and zero HTTP requests;
  the local M08 UX/XSS smoke passed. Frozen RC1 evidence validation passed.
- `compileall`, `git diff --check`, and final evaluator/publication graph checks
  passed. No live cohort or external source acquisition was performed.

The conservative trade-off is unchanged for ambiguous brand/operator evidence:
the verifier abstains unless an accepted direct proof exists, and an explicit
competing brand blocks publication. This correction does not alter financial,
job/activity, synthesis, release-bundle, or source-policy behavior. Competition
submission remains HOLD. Exact-SHA push and CI status will be recorded after
the remediation commit is pushed.
