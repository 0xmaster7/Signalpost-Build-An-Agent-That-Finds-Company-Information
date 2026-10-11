# M12 host-bound website ownership invariant matrix

This matrix is derived from audited plan sections 8.3–8.4 and the complete
sequence of M12/Sol website ownership findings. It is a reusable review and
test checklist. A website claim must be based on the candidate response and
its host; facts about a mentioned company do not identify the site operator.

| Dimension | Accept only when | Reject or abstain when | Claim scope |
|---|---|---|---|
| Candidate host | Final fetched URL host is the verified candidate host, or a redirect is independently verified under the exact-site rules | Structured metadata names a different host; redirect changes host without target proof | URL and domain bind to verified host only |
| Structured site identity | A `WebSite` URL is same-site/root-bound and its publisher identifies the target; all relevant publisher/operator records are consistent | `WebSite.url` differs from actual response host, publisher belongs to a different host, or operators conflict | Domain only for verified operator relationship |
| Page/article subjects | Subject-scoped target Organization evidence is used only for the subject relationship it represents | Article subject, author, customer, supplier, partner, or contact card is promoted to operator | Page facts require their own target binding |
| Visible legal/contact identity | Exact legal name plus audited registered address/identifier appears in independent operator-scoped legal/contact evidence and no conflict exists | Evidence is inside article/story/customer content, footer, incidental header/sidebar, or third-party contact card | Candidate page; domain only if it proves operator identity |
| Shared group domain | Approved shared host has affirmative subsidiary-specific identity and page binding | Group root, generic group article, or unrelated page is treated as subsidiary-owned | Exact verified page/path only; never infer group-domain ownership |
| Conflicts | Independent evidence consistently identifies the target as operator | Competing publisher, operator, legal entity, or incompatible site branding remains unresolved | Withhold unsupported ownership claims |
| Provenance | Evidence and snapshot bind to the fetched response URL, hash, candidate host, and ownership decision | Evidence proves only a mention, an unrelated URL, or a separate source relationship | Claim evidence must support the exact claim scope |

## Required metamorphic checks

Changing an unrelated article subject, adding a third-party contact card,
adding unrelated JSON-LD, or changing Organization record order must not turn
an unverified host into verified target ownership. Reordering equivalent
metadata must not change the decision. Positive control fixtures cover target
homepages/legal pages with and without JSON-LD, target-owned customer stories,
and explicitly scoped subsidiary pages.

For each case, independently assert target identity, verified page URL,
verified domain, final evaluator serialization, and evidence/snapshot linkage.
Controlled fixtures establish deterministic behavior only; they do not measure
real-world population precision or recall.
