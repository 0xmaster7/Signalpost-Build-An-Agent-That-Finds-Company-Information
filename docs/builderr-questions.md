# Questions for Builderr

Prepared 2026-10-03 from §49 of the audited plan after checking the live challenge page and linked public contract. The public materials resolve some items below; they are marked so the request can focus on what remains. No message has been sent from this workspace.

**Subject:** Signalpost evaluator details and reproducible model/search access

Hi Builderr team — I’m implementing against the current Signalpost page, evaluation contract and starter. Could you confirm the remaining evaluator details below?

1. What wall-clock, CPU, memory, outbound-request and external-cost limits apply to the current official batch? What counts as a request, including robots, redirects, retries, conditional requests, search/model calls and browser subresources?
2. What exact input schema and input/output path/environment-variable interface will the evaluator provide? Is the one-command runner expected to accept JSONL organisation numbers as in the starter?
3. If duplicate organisation numbers occur in an input batch, should output be one envelope per input row or one per unique organisation number?
4. The public contract requires an envelope with identity, claims, evidence, states, source snapshots, refresh metadata and errors, but does not link a JSON Schema. Could you provide the exact current schema/version and confirm whether extra fields are accepted?
5. The contract says you provide a frozen official registry snapshot. How is it mounted and what format/path should the runner use? Should live BRREG be used only as a fallback?
6. How are the network policy/proxy and evidence cutoff supplied? How should undated mutable web content be handled when a cutoff precedes retrieval time, and what activity lookback window applies?
7. How is prior state supplied for refresh evaluation, and does state persist between scheduled batches?
8. Which source-snapshot/evidence fields are mandatory when source rights or directives prohibit retaining raw text or spans?
9. Which external caches/datasets may be used, and how should they be declared? Are cached entries from the public company universe allowed as candidates only, as the contract presently says?
10. Which exact external families, claim types and claim granularity contribute to recall? Are all account periods, roles, workplaces, jobs and activity items checked?
11. Which ATS/job providers and acquisition modes are approved for official scoring?
12. Which credential may be used for search/discovery, and what result-storage/retention terms apply? The plan requests reproducible permitted search guidance because personal-account credentials cannot be reproduced.
13. Please provide the reproducible model key mentioned on the challenge page and confirm supported provider/model identifiers and environment-variable name.
14. How is the UX launched or hosted for the find/compare/verify assessment? Builderr's gallery hosting is mentioned for qualified entries; is a local static app sufficient for evaluation?
15. If a source cannot be attempted because of robots, evaluator networking, or remaining budget, what field/family state should the result use?
16. How should declared third-party cost count free tiers, monthly bundles and cache hits?
17. May exact reversible unit conversion (such as TNOK to NOK) be included in numeric claims while derived analytics remain excluded?
18. The page says the current board uses a locked 1,200-company checked collection and the shared official set may grow from 1,000 to 1,100. Please confirm those are distinct reference-set and input-batch counts, as described.
19. What timezone applies to the revision cutoff on 18 October 2026? Does any older Unstop 17 October project-link requirement affect Builderr's technical cutoff?

Thanks.
