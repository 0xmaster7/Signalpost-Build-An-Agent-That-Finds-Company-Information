# JBOX site builder prompt

Build a polished, responsive, accessible company research site in Next.js using only the Signalpost export bundle described below. The site must treat the bundle as its entire data boundary: no network lookups, inferred company facts, generated citations, fallback company data, or facts from model knowledge. Read the real exported `bundle.json` supplied with the project at build/runtime. If it is absent or malformed, show a clear empty/error state and explain how to create it with `signalpost-starter-kit/scripts/export_site_data.py` from a saved evaluator JSONL. Do not show the synthetic examples in this prompt as real companies or use them as production fallback data.

## Required screens and behavior

- A home/search screen searches companies by organization number and by any name in `name_values` (case-insensitive). Show organization number, name when available, municipality, industry, and the exporter-provided section availability. If an index field is absent because the bundle is compact, resolve the company file named by `company_file` when available; otherwise explain that the field is omitted from this compact bundle. Do not substitute a guess.
- A company screen shows identity, the exporter-supported summary sentences, and claims grouped by section. Prefer `supported_summary.profile.sentences` when present; otherwise use `supported_summary.sentences`. A factual summary sentence may be shown only when all its `fact_ids`, `evidence_ids`, and `change_ids` resolve to claims/evidence/events in that same company. Render profile `unknowns` and `blocked` separately as verification status, using their section-state pointers, never as company facts. Do not paraphrase into a stronger claim. If `summary_state` is `omitted_from_bundle`, load the supplied local company file or show that the summary requires that file; do not generate a replacement.
- Render each claim with its exact value, field label, state, period, unit, currency, scope, and available as-of date. `0` is a real value; never turn zero into “missing,” “none,” or an empty state. A claim with `state: available` is a fact. Claims in other states are status records, not facts.
- Put a **Sources** button on every displayed claim. It opens a source-check view listing every associated evidence record and, where present, its source snapshot. Show source URL, retrieved time, SHA-256, snippet, page number, JSON pointer, and the claim's period. Preserve the exact source URL as text. Make it clickable only when `link_url` is a non-null HTTP(S) URL, and use safe external-link behavior. Never make a `javascript:`, `data:`, protocol-relative, credentialed, or otherwise unsafe URL clickable. If a claim has no evidence, the button opens a clear “No source record is available for this status” explanation rather than inventing source data.
- Include a source-check view reachable from each source button and a return link to the company/fact. Show evidence and snapshot IDs so a reviewer can trace the record. Resolve evidence by ID in `company.sources`; resolve a historical source in `change_history`'s previous/current evidence arrays. `provenance_resolver` describes the full company file and pointers when the compact bundle omits data. Never imply that omitted bundle data does not exist.
- Provide a compare flow for exactly two selected companies. On desktop, stack them in two columns; on mobile, stack one company after the other. Align sections and fields where possible, retain each company's state, period, unit, scope, and source buttons, and label mismatched periods/scopes instead of presenting them as directly comparable.
- Show honest empty and unavailable states. Distinguish `available`, `not_available`, `blocked`, `ambiguous`, `failed`, `not_applicable`, `null`/unasserted, and section `attempt_outcome` values. For ambiguous identity, show all `values`; do not pick a winner. For blocked/failed/not-available sections, state that the export has no available facts for that section. Do not display a fake zero, blank placeholder fact, or generic success message.
- Honor `compaction`: show when facts, summary sentences, changes, source IDs, or index fields were omitted from the bundle. Use the full company file/resolver when it is included with the site; otherwise state which detail needs the full company file. Do not silently drop data or claim that compact-bundle data is complete.
- Meet WCAG 2.2 AA interaction basics: semantic headings and landmarks, keyboard-accessible search/selection/dialogs, visible focus, labeled controls, adequate contrast, status text that is not conveyed by color alone, and responsive reflow. Include loading, no-results, missing-bundle, and malformed-bundle states. Use only design assets and code included in the project.

## Export schema (version 1)

The JSON is UTF-8. The exporter writes `index.json`, `bundle.json`, and `companies/{orgnr}.json`. The bundle embeds index entries and company objects; the standalone company files retain the full exported company data. `bundle.json` has this shape:

```ts
type PublicState = "available" | "not_available" | "blocked" | "ambiguous" | "failed" | "not_applicable";
type Claim = {
  claim_id: string; organisation_number: string | null; section: string | null;
  field_family: string | null; subject_id: string | null; field: string; value: unknown;
  state: PublicState; unit: string | null; currency: string | null;
  unit_assumed_currency: boolean; unit_assumption_basis: Record<string, unknown> | null;
  period_start: string | null; period_end: string | null; as_of: string | null; scope: string | null;
  verification_rule_id: string | null; verification_score: string | number | null;
  evidence_ids: string[]; source_snapshot_ids: string[]; confidence: string | number | null;
};
type Evidence = {
  evidence_id: string; source_url: string; retrieved_at: string; content_sha256: string;
  extraction_method: string; json_pointer: string | null;
  page_number: number | null; source_class: string; subject_organisation_number: string | null;
  source_snapshot_ids: string[]; snippet: string | null; snippet_redacted: boolean;
  snippet_truncated: boolean; link_url: string | null;
};
type SourceSnapshot = {
  source_id: string; source_url: string; retrieved_at: string; content_sha256: string;
  http_status: number | null; cache_mode: string; rights_status: string; link_url: string | null;
};
type Section = {
  state: PublicState | null; attempt_outcome: string | null; claims: Claim[];
  diagnostics?: string[]; omitted_facts?: number;
};
type IdentityFacet = {
  value: unknown | null; values: unknown[]; state: PublicState | "ambiguous" | null;
  observed_states: (PublicState | null)[]; claim_ids: string[];
};
type IndexEntry = {
  orgnr: string; name: unknown | null; name_values?: unknown[]; municipality?: unknown[];
  industry?: unknown[]; availability: { terminal_state: PublicState;
    sections: Record<string, { state: PublicState | null; attempt_outcome: string | null }> };
  company_file: string; company_sha256: string;
};
type ProfileStatus = {
  domain: string; text: string; reasons: string[]; candidate_claim_ids: string[];
  evidence_ids: string[]; change_ids: string[];
  state_context: Array<{ section: string; state: PublicState | null;
    attempt_outcome: string | null; json_pointer: string }>;
};
type SupportedProfile = {
  schema_version: number; mode: string; organisation_number: string; evidence_cutoff: string;
  sentences: Array<{ sentence_id: string; domain: string; text: string;
    fact_ids: string[]; evidence_ids: string[]; change_ids: string[] }>;
  unknowns: ProfileStatus[]; blocked: ProfileStatus[];
  refresh_context: { mode: string; previous_state_ref: string | null; current_state_ref: string | null };
};
type Company = {
  schema_version: 1; orgnr: string;
  identity: { orgnr: string; name?: IdentityFacet; municipality?: IdentityFacet; industry?: IdentityFacet };
  terminal_state: PublicState; evidence_cutoff: string;
  supported_summary: { schema_version: 1; mode: string; sentences: Array<{
    text: string; fact_ids: string[]; evidence_ids: string[]; change_ids?: string[] }>;
    unknown_sections: string[]; profile?: SupportedProfile } | null;
  summary_state: "provided" | "not_provided" | "omitted_from_bundle";
  sections: Record<string, Section>; sources: Record<string, Evidence>;
  source_snapshots: Record<string, SourceSnapshot>; change_history: ChangeEvent[];
  privacy: { omitted_claims: number; omitted_changes: number; omitted_summary_sentences: number };
  provenance_resolver: { company_file: string; evidence_pointer: string;
    snapshot_pointer: string; change_pointer: string };
  compaction?: { omitted_facts: number; omitted_summary_sentences: number; omitted_changes: number;
    snippet_character_limit: number; omitted_source_ids: string[]; omitted_snapshot_ids: string[];
    source_ids_in_company_file?: boolean };
};
type ChangeEvent = {
  event_id: string; type: string; organisation_number: string; section: string | null;
  field: string | null; old_value: unknown; new_value: unknown; effective_at: string | null;
  observed_at: string; previous_state_ref: string | null; current_state_ref: string | null;
  previous_claim_fingerprint: string | null; current_claim_fingerprint: string | null;
  previous_evidence: Evidence[]; current_evidence: Evidence[];
  previous_source_snapshots: SourceSnapshot[]; current_source_snapshots: SourceSnapshot[];
  removal_confirmation_evidence_ids: string[]; provenance_complete: boolean;
};
type Bundle = { schema_version: 1; company_count: number; index: IndexEntry[];
  companies: Record<string, Company>; compact: boolean; index_file: "index.json";
  index_fields_omitted?: string[] };
```

The standalone `index.json` has `schema_version`, `company_count`, `duplicate_rows`, `rejected_input_rows`, and `companies: IndexEntry[]`. `bundle.json`'s `index` entries contain the same fields unless compaction removes the optional identity arrays; `index_fields_omitted` names fields intentionally removed. Company section names are the seven exporter names: `identity_brand`, `accounts_history`, `leadership_workplaces`, `website_owned_profiles`, `hiring_activity`, `claims_evidence_states`, and `refresh_changes`. Input envelopes may repeat claims under `claims_evidence_states`; the exporter groups public claims in the company file by each claim's canonical `section`. Use `claim_id` defensively to avoid displaying duplicate data if a bundle contains repeated entries.

The `Evidence` object above describes exporter output: canonical evidence properties are serialized along with `snippet`, redaction/truncation flags, and `link_url`. In some historical change records, source properties follow the change-evidence model; render the fields that exist and do not fabricate missing page, pointer, or snippet details. Section, change, synthesis, and claim enum strings must be displayed as data, not converted into stronger claims. Optional keys are omitted only where marked optional; `null` is distinct from zero and from an empty string.

## Inline synthetic fixture objects

These three objects are fabricated UI fixtures based on the current exporter test helpers (`synthetic_row`, `add_fact`, and state/identity cases). The `.test` URLs, organization numbers, text, IDs, hash values, and dates are synthetic. They are examples only. Never present them as real records, mix them into a real bundle, or use them when the bundle is missing. Load the real bundle produced by the exporter for site data.

```json
[
  {
    "schema_version": 1,
    "orgnr": "000000001",
    "identity": {
      "orgnr": "000000001",
      "name": {"value": "SYNTHETIC Fjord Example AS", "values": ["SYNTHETIC Fjord Example AS"], "state": "available", "observed_states": ["available"], "claim_ids": ["000000001:claim:0"]},
      "municipality": {"value": "SYNTHETIC Municipality", "values": ["SYNTHETIC Municipality"], "state": "available", "observed_states": ["available"], "claim_ids": ["000000001:claim:1"]},
      "industry": {"value": {"kode": "00.000", "beskrivelse": "SYNTHETIC industry"}, "values": [{"kode": "00.000", "beskrivelse": "SYNTHETIC industry"}], "state": "available", "observed_states": ["available"], "claim_ids": ["000000001:claim:2"]}
    },
    "terminal_state": "available", "evidence_cutoff": "2026-11-01T00:00:00Z",
    "supported_summary": null, "summary_state": "not_provided",
    "sections": {"identity_brand": {"state": "available", "attempt_outcome": null, "claims": [{"claim_id": "000000001:claim:0", "organisation_number": "000000001", "section": "identity_brand", "field_family": "identity", "subject_id": "000000001", "field": "name", "value": "SYNTHETIC Fjord Example AS", "state": "available", "unit": null, "currency": null, "unit_assumed_currency": false, "unit_assumption_basis": null, "period_start": null, "period_end": null, "as_of": null, "scope": "legal_entity", "verification_rule_id": "synthetic_site_test_v1", "verification_score": "1", "evidence_ids": ["000000001:evidence:0"], "source_snapshot_ids": ["000000001:snapshot:0"], "confidence": null}, {"claim_id": "000000001:claim:1", "organisation_number": "000000001", "section": "identity_brand", "field_family": "identity", "subject_id": "000000001", "field": "municipality", "value": "SYNTHETIC Municipality", "state": "available", "unit": null, "currency": null, "unit_assumed_currency": false, "unit_assumption_basis": null, "period_start": null, "period_end": null, "as_of": null, "scope": "legal_entity", "verification_rule_id": "synthetic_site_test_v1", "verification_score": "1", "evidence_ids": ["000000001:evidence:1"], "source_snapshot_ids": ["000000001:snapshot:1"], "confidence": null}, {"claim_id": "000000001:claim:2", "organisation_number": "000000001", "section": "identity_brand", "field_family": "identity", "subject_id": "000000001", "field": "industry", "value": {"kode": "00.000", "beskrivelse": "SYNTHETIC industry"}, "state": "available", "unit": null, "currency": null, "unit_assumed_currency": false, "unit_assumption_basis": null, "period_start": null, "period_end": null, "as_of": null, "scope": "legal_entity", "verification_rule_id": "synthetic_site_test_v1", "verification_score": "1", "evidence_ids": ["000000001:evidence:2"], "source_snapshot_ids": ["000000001:snapshot:2"], "confidence": null}]}, "accounts_history": {"state": "not_available", "attempt_outcome": null, "claims": []}},
    "sources": {"000000001:evidence:0": {"evidence_id": "000000001:evidence:0", "source_url": "https://synthetic.example.test/000000001/0", "retrieved_at": "2026-11-01T00:00:00Z", "content_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "extraction_method": "synthetic_json_v1", "json_pointer": "/synthetic/value", "page_number": 2, "source_class": "official", "subject_organisation_number": "000000001", "source_snapshot_ids": ["000000001:snapshot:0"], "snippet": "Synthetic evidence", "snippet_redacted": false, "snippet_truncated": false, "link_url": "https://synthetic.example.test/000000001/0"}, "000000001:evidence:1": {"evidence_id": "000000001:evidence:1", "source_url": "https://synthetic.example.test/000000001/1", "retrieved_at": "2026-11-01T00:00:00Z", "content_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "extraction_method": "synthetic_json_v1", "json_pointer": "/synthetic/municipality", "page_number": 2, "source_class": "official", "subject_organisation_number": "000000001", "source_snapshot_ids": ["000000001:snapshot:1"], "snippet": "SYNTHETIC Municipality", "snippet_redacted": false, "snippet_truncated": false, "link_url": "https://synthetic.example.test/000000001/1"}, "000000001:evidence:2": {"evidence_id": "000000001:evidence:2", "source_url": "https://synthetic.example.test/000000001/2", "retrieved_at": "2026-11-01T00:00:00Z", "content_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "extraction_method": "synthetic_json_v1", "json_pointer": "/synthetic/industry", "page_number": 2, "source_class": "official", "subject_organisation_number": "000000001", "source_snapshot_ids": ["000000001:snapshot:2"], "snippet": "SYNTHETIC industry", "snippet_redacted": false, "snippet_truncated": false, "link_url": "https://synthetic.example.test/000000001/2"}},
    "source_snapshots": {"000000001:snapshot:0": {"source_id": "000000001:snapshot:0", "source_url": "https://synthetic.example.test/000000001/0", "retrieved_at": "2026-11-01T00:00:00Z", "content_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "http_status": 200, "cache_mode": "transient", "rights_status": "synthetic", "link_url": "https://synthetic.example.test/000000001/0"}, "000000001:snapshot:1": {"source_id": "000000001:snapshot:1", "source_url": "https://synthetic.example.test/000000001/1", "retrieved_at": "2026-11-01T00:00:00Z", "content_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "http_status": 200, "cache_mode": "transient", "rights_status": "synthetic", "link_url": "https://synthetic.example.test/000000001/1"}, "000000001:snapshot:2": {"source_id": "000000001:snapshot:2", "source_url": "https://synthetic.example.test/000000001/2", "retrieved_at": "2026-11-01T00:00:00Z", "content_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "http_status": 200, "cache_mode": "transient", "rights_status": "synthetic", "link_url": "https://synthetic.example.test/000000001/2"}},
    "change_history": [], "privacy": {"omitted_claims": 0, "omitted_changes": 0, "omitted_summary_sentences": 0},
    "provenance_resolver": {"company_file": "companies/000000001.json", "evidence_pointer": "/sources", "snapshot_pointer": "/source_snapshots", "change_pointer": "/change_history"}
  },
  {
    "schema_version": 1, "orgnr": "000000002",
    "identity": {"orgnr": "000000002", "name": {"value": null, "values": [], "state": "blocked", "observed_states": ["blocked"], "claim_ids": []}},
    "terminal_state": "blocked", "evidence_cutoff": "2026-11-01T00:00:00Z",
    "supported_summary": null, "summary_state": "not_provided",
    "sections": {"identity_brand": {"state": "blocked", "attempt_outcome": "synthetic_policy_block", "claims": [{"claim_id": "000000002:claim:0", "organisation_number": "000000002", "section": "identity_brand", "field_family": "identity", "subject_id": "000000002", "field": "name", "value": null, "state": "blocked", "unit": null, "currency": null, "unit_assumed_currency": false, "unit_assumption_basis": null, "period_start": null, "period_end": null, "as_of": null, "scope": "legal_entity", "verification_rule_id": "synthetic_site_test_v1", "verification_score": "1", "evidence_ids": [], "source_snapshot_ids": [], "confidence": null}]}},
    "sources": {}, "source_snapshots": {}, "change_history": [],
    "privacy": {"omitted_claims": 0, "omitted_changes": 0, "omitted_summary_sentences": 0},
    "provenance_resolver": {"company_file": "companies/000000002.json", "evidence_pointer": "/sources", "snapshot_pointer": "/source_snapshots", "change_pointer": "/change_history"}
  },
  {
    "schema_version": 1, "orgnr": "000000003",
    "identity": {"orgnr": "000000003", "name": {"value": null, "values": ["SYNTHETIC North Example AS", "SYNTHETIC South Example AS"], "state": "ambiguous", "observed_states": ["available"], "claim_ids": ["000000003:claim:0", "000000003:claim:1"]}},
    "terminal_state": "available", "evidence_cutoff": "2026-11-01T00:00:00Z",
    "supported_summary": null, "summary_state": "not_provided",
    "sections": {"identity_brand": {"state": "available", "attempt_outcome": null, "claims": [{"claim_id": "000000003:claim:0", "organisation_number": "000000003", "section": "identity_brand", "field_family": "identity", "subject_id": "000000003", "field": "name", "value": "SYNTHETIC North Example AS", "state": "available", "unit": null, "currency": null, "unit_assumed_currency": false, "unit_assumption_basis": null, "period_start": null, "period_end": null, "as_of": null, "scope": "legal_entity", "verification_rule_id": "synthetic_site_test_v1", "verification_score": "1", "evidence_ids": ["000000003:evidence:0"], "source_snapshot_ids": ["000000003:snapshot:0"], "confidence": null}, {"claim_id": "000000003:claim:1", "organisation_number": "000000003", "section": "identity_brand", "field_family": "identity", "subject_id": "000000003", "field": "legal_name", "value": "SYNTHETIC South Example AS", "state": "available", "unit": null, "currency": null, "unit_assumed_currency": false, "unit_assumption_basis": null, "period_start": null, "period_end": null, "as_of": null, "scope": "legal_entity", "verification_rule_id": "synthetic_site_test_v1", "verification_score": "1", "evidence_ids": ["000000003:evidence:1"], "source_snapshot_ids": ["000000003:snapshot:1"], "confidence": null}]}, "accounts_history": {"state": "ambiguous", "attempt_outcome": null, "claims": []}},
    "sources": {"000000003:evidence:0": {"evidence_id": "000000003:evidence:0", "source_url": "https://synthetic.example.test/000000003/0", "retrieved_at": "2026-11-01T00:00:00Z", "content_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd", "extraction_method": "synthetic_json_v1", "json_pointer": "/synthetic/name/0", "page_number": 1, "source_class": "official", "subject_organisation_number": "000000003", "source_snapshot_ids": ["000000003:snapshot:0"], "snippet": "SYNTHETIC North Example AS", "snippet_redacted": false, "snippet_truncated": false, "link_url": "https://synthetic.example.test/000000003/0"}, "000000003:evidence:1": {"evidence_id": "000000003:evidence:1", "source_url": "https://synthetic.example.test/000000003/1", "retrieved_at": "2026-11-01T00:00:00Z", "content_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "extraction_method": "synthetic_json_v1", "json_pointer": "/synthetic/name/1", "page_number": 1, "source_class": "official", "subject_organisation_number": "000000003", "source_snapshot_ids": ["000000003:snapshot:1"], "snippet": "SYNTHETIC South Example AS", "snippet_redacted": false, "snippet_truncated": false, "link_url": "https://synthetic.example.test/000000003/1"}}, "source_snapshots": {"000000003:snapshot:0": {"source_id": "000000003:snapshot:0", "source_url": "https://synthetic.example.test/000000003/0", "retrieved_at": "2026-11-01T00:00:00Z", "content_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd", "http_status": 200, "cache_mode": "transient", "rights_status": "synthetic", "link_url": "https://synthetic.example.test/000000003/0"}, "000000003:snapshot:1": {"source_id": "000000003:snapshot:1", "source_url": "https://synthetic.example.test/000000003/1", "retrieved_at": "2026-11-01T00:00:00Z", "content_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "http_status": 200, "cache_mode": "transient", "rights_status": "synthetic", "link_url": "https://synthetic.example.test/000000003/1"}}, "change_history": [],
    "privacy": {"omitted_claims": 0, "omitted_changes": 0, "omitted_summary_sentences": 0},
    "provenance_resolver": {"company_file": "companies/000000003.json", "evidence_pointer": "/sources", "snapshot_pointer": "/source_snapshots", "change_pointer": "/change_history"}
  }
]
```

Build the app around the exporter schema above. These inline objects are for rendering and accessibility development only; real site content must come from the real bundle.
