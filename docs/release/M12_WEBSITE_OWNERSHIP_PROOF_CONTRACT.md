# M12 Website Ownership Proof Contract

This contract records the audited website-identity decision rules in
`CODEX_SIGNALPOST_FINAL_IMPLEMENTATION_PLAN_AUDITED.md` sections 8.3–8.6 and
the final website-ownership remediation request. It does not amend the
publication contract.

## Subjects and scope

- **Target entity** is the legal entity identified by the requested
  organisation number.
- **Fetched resource** is the actual response URL and host after redirects;
  a redirect or canonical URL is a navigation hint, not ownership proof.
- **Site operator** is the entity shown by coherent site-level evidence to
  operate or officially represent the website.
- **Page subject** is an entity discussed or profiled by an individual page.
- **Structured-record subject** is the entity or resource identified by that
  specific JSON-LD record. A record's publisher, URL, and subject stay bound
  to that record; records are never stitched together by proximity or order.
- **Claim scope** is either the verified host/domain or one verified page URL.
  Page-scope evidence cannot establish domain-scope ownership.

## Acceptance rule

Publish an owned website claim only when affirmative evidence binds the same
fetched resource, operator or represented entity, and target at the exact
claim scope. Use the audited exact-site table: an appropriately scoped exact
organisation-number plus compatible legal name; or a registry website
candidate plus compatible legal name and exact registered address/postcode;
or the documented strong independent contact/address combination. A shared
group host may support only a subsidiary-specific page when that page itself
contains the subsidiary proof required by section 8.3.

Evaluate positive and contradictory evidence together before acceptance.
Conflicting operator or publisher identity, a target appearing only as a
customer/supplier/partner/article subject, unrelated metadata records, or
unbound canonical/redirect destinations resolve to abstention. A contact
card is operator evidence only when its resource location and semantic role
show that it identifies the site operator; page-body subject details alone
are not site ownership. Missing proof means no owned-site claim, not a claim
that the target has no website.

The implementation must keep URL and domain decisions separate, preserve
claim provenance, and remain deterministic under record ordering and
semantically equivalent DOM rearrangement. No JSON-LD requirement is added:
non-JSON-LD sites remain acceptable when the audited independent operator
proof is present.

## Direct relationship and resource binding

- `WebSite.publisher` must directly name a typed Organization, Corporation,
  or LocalBusiness whose legal name and organisation number match the target.
  A nested `worksFor`, `subOrganization`, `parentOrganization`, `memberOf`, or
  other related entity never becomes the publisher.
- Every WebSite `url` and `@id` must bind to the actual response host. Every
  explicit Organization `url` and `@id` must also agree with that host; an
  off-host identity cannot verify the current resource.
- A shared-domain page is considered only when its own WebPage record binds
  to the exact response path. Its direct typed `mainEntity` may identify the
  subsidiary. Publisher, mainEntity, URL, and identifiers from separate
  WebPage records are never combined.
- A group's verified homepage is never promoted as a subsidiary's homepage.
  The subsidiary claim is limited to its independently supported page path.
- Competing direct publishers or a conflict between the site brand and the
  identified operator cause abstention. Unsupported relationship types and
  insufficient proof remain distinct internal diagnostic reasons.
