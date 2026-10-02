# M00 website opportunity audit

Run: 2026-10-03 Asia/Kolkata. This audit uses the actual Builderr public 2025-filer universe, not an inferred or synthetic company list.

## Method

- Input archive: `https://builderr.ai/signalpost-company-universe-2025.jsonl.gz` (12,631,607 bytes; downloaded archive SHA-256 `1c89710e5b01f8617e86d09fbdff4a52f2f8dbbba297e74f7164b5984f5a0384`, matching the published archive hash).
- Decompressed content SHA-256: `b82d6a3e7231d1759a958c282bc4366b80ec2fab8095053d8ed7fa9cd01bc838`, matching the published content hash. Count: 411,160 eligible rows (active entities whose latest submitted accounts year is 2025).
- Sample: 200 companies, seed `20261003`, allocated proportionally across legal-form (`AS`, `ASA`, `ENK`, `OTHER`), employee-count band, and registry website present/missing strata. Frozen selected-organisation-number SHA-256: `90362b0441ff5c1a5846b68cb00a4308c785e8b2575524198618a5f8b8cec869`. Sample JSONL SHA-256: `cee97e17af7e8b2d9dc9f5ee60548b9e186a11a2e485469446219ea10a1e38ed`.
- Utility: [`../../signalpost-starter-kit/scripts/audit_website_opportunity.py`](../../signalpost-starter-kit/scripts/audit_website_opportunity.py), current SHA-256 `45c511ae1755e2085c2ea89e98c3eb45a0e5c2899c92fe5362bc5c496c5bcdd1`. Run it with the public gzip universe and the same `--count 200 --seed 20261003`; it writes the sampled manifest and result report. After the live fetch, the utility was hardened to reject URL user information, honor reported crawl delays, and parse structured homepage data; the saved report was stripped of page titles/descriptions. The frozen membership is unchanged; current live website statuses can change.
- Candidate policy: the sole candidate was each company's registry-listed homepage. The recorded run fetched at most one candidate homepage per sampled company, checked `robots.txt` once per origin, required public HTTP(S), and did not use search results or guess a domain. Page text was processed transiently for the deterministic identity assessment. The retained report stores source URL, status, retrieval time and content hash, not page text. The first live run did not record robots crawl-delay values; the current utility records and honors them on future runs.

## Results

| Outcome | Companies |
|---|---:|
| Registry website missing | 179 |
| Robots origin unreachable; homepage not fetched | 3 |
| Homepage responded with non-HTML content | 2 |
| HTML homepage responded; exact identity accepted | 9 |
| HTML homepage responded; identity uncertain/related | 7 |
| Redirect to another registrable domain without exact identity | 1 |
| Shared registrable domain among responding sample companies | 0 |

The rows are mutually exclusive by website-opportunity status except identity labels, which further qualify the responding HTML pages. There were 21 companies with a syntactically usable registry URL: 18 homepage candidate fetches and 3 conservative skips after robots access failed. No homepage returned an HTTP 404/410 in this sample. Thus 89.5% had no registry website to use as a starting point, and 9/16 fetched HTML homepages passed the starter's deterministic exact-identity gate. This makes reproducible missing-site discovery a high-priority recall path. It does not establish how much a paid search provider would add.

This is a stratified 200-company opportunity audit, not a precision benchmark: only 16 fetched HTML pages were identity-assessed and no human-labelled hard-negative set was assembled. The recorded exact-site check used homepage title, description, host and extracted body text; it did not include structured JSON-LD, so the exact-accepted count is a conservative lower bound. It must not be treated as the plan's 300-decision search-provider promotion gate. Search remains disabled pending rights, reproducible credentials and the required independent audit.

Machine-readable company-by-company results are in [`m00-website-opportunity-200.json`](m00-website-opportunity-200.json), SHA-256 `3aa750526beae8d506c4953b78ba75c2dc5eb518f5240a6c80e7a6ca104f8ffe`; the frozen population sample is [`m00-company-sample-200.jsonl`](m00-company-sample-200.jsonl), SHA-256 `cee97e17af7e8b2d9dc9f5ee60548b9e186a11a2e485469446219ea10a1e38ed`.
