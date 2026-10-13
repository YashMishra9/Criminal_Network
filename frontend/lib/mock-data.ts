/**
 * frontend/lib/mock-data.ts
 *
 * Realistic DOC3-shaped fixture data for mock-mode development and testing.
 * All shapes match DOC3 §1 exactly — no invented fields.
 *
 * Used by api-client.ts when NEXT_PUBLIC_MOCK_MODE=true (or in test environments).
 */

import type {
  CanonicalEntity,
  Relationship,
  RelationshipWithEvidence,
  Evidence,
  ResolutionDecision,
  Finding,
  AnalyticsResult,
  AskResponse,
  Case,
  Note,
  EdgeRef,
  AdapterDescriptor,
} from "./types";

// ---------------------------------------------------------------------------
// Entities
// ---------------------------------------------------------------------------

export const MOCK_ENTITIES: CanonicalEntity[] = [
  {
    entity_id: "ent-001",
    entity_type: "Person",
    dataset: "synthetic_demo",
    display_name: "Rahul Sharma",
    attributes: { aliases: ["R. Sharma", "Rahul S."] },
    resolved_from: ["m-001", "m-002"],
    resolution_method: "fuzzy_match",
    created_at: "2024-01-10T08:00:00Z",
    updated_at: "2024-01-10T08:00:00Z",
  },
  {
    entity_id: "ent-002",
    entity_type: "Person",
    dataset: "synthetic_demo",
    display_name: "Priya Mehta",
    attributes: {},
    resolved_from: ["m-003"],
    resolution_method: "exact_match",
    created_at: "2024-01-10T08:00:00Z",
    updated_at: "2024-01-10T08:00:00Z",
  },
  {
    entity_id: "ent-003",
    entity_type: "Phone",
    dataset: "synthetic_demo",
    display_name: "+919876543210",
    attributes: { carrier: "Airtel" },
    resolved_from: ["m-004"],
    resolution_method: "exact_match",
    created_at: "2024-01-10T08:00:00Z",
    updated_at: "2024-01-10T08:00:00Z",
  },
  {
    entity_id: "ent-004",
    entity_type: "Vehicle",
    dataset: "synthetic_demo",
    display_name: "MH12AB1234",
    attributes: { make: "Maruti", model: "Swift", color: "White" },
    resolved_from: ["m-005"],
    resolution_method: "exact_match",
    created_at: "2024-01-11T09:00:00Z",
    updated_at: "2024-01-11T09:00:00Z",
  },
  {
    entity_id: "ent-005",
    entity_type: "Organization",
    dataset: "synthetic_demo",
    display_name: "Apex Trading Co.",
    attributes: { registration_number: "MH-2019-12345" },
    resolved_from: ["m-006"],
    resolution_method: "exact_match",
    created_at: "2024-01-12T10:00:00Z",
    updated_at: "2024-01-12T10:00:00Z",
  },
  {
    entity_id: "ent-006",
    entity_type: "BankAccount",
    dataset: "synthetic_demo",
    display_name: "HDFC ****4521",
    attributes: { bank: "HDFC", branch: "Pune Main" },
    resolved_from: ["m-007"],
    resolution_method: "exact_match",
    created_at: "2024-01-12T10:00:00Z",
    updated_at: "2024-01-12T10:00:00Z",
  },
  {
    entity_id: "ent-007",
    entity_type: "Location",
    dataset: "synthetic_demo",
    display_name: "Shivaji Nagar, Pune",
    attributes: { lat: 18.5308, lon: 73.8475 },
    resolved_from: ["m-008"],
    resolution_method: "exact_match",
    created_at: "2024-01-13T11:00:00Z",
    updated_at: "2024-01-13T11:00:00Z",
  },
];

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------

export const MOCK_EVIDENCE: Evidence[] = [
  {
    evidence_id: "ev-001",
    dataset: "synthetic_demo",
    source_id: "fir_001",
    source_type: "FIR",
    record_timestamp: "2024-01-05T14:30:00Z",
    ingested_at: "2024-01-10T08:00:00Z",
    snippet: "Rahul Sharma (also known as R. Sharma) was named in FIR #2024/001.",
    pointer: { file: "fir/fir_001.json", record_index: 0 },
  },
  {
    evidence_id: "ev-002",
    dataset: "synthetic_demo",
    source_id: "cdr_001",
    source_type: "CDR",
    record_timestamp: "2024-01-06T10:15:00Z",
    ingested_at: "2024-01-10T08:00:00Z",
    snippet: "17 calls between +919876543210 and +919812345678 over 4 days.",
    pointer: { file: "cdr/records.json", record_index: 0 },
  },
  {
    evidence_id: "ev-003",
    dataset: "synthetic_demo",
    source_id: "txn_001",
    source_type: "transaction",
    record_timestamp: "2024-01-07T16:00:00Z",
    ingested_at: "2024-01-10T08:00:00Z",
    snippet: "Transfer of ₹85,000 from HDFC ****4521 to SBI ****9988.",
    pointer: { file: "transactions/records.json", record_index: 0 },
  },
];

// ---------------------------------------------------------------------------
// Relationships
// ---------------------------------------------------------------------------

export const MOCK_RELATIONSHIPS: Relationship[] = [
  {
    relationship_id: "rel-001",
    relationship_type: "CALLED",
    from_entity_id: "ent-001",
    to_entity_id: "ent-003",
    dataset: "synthetic_demo",
    attributes: { call_count: 17, total_duration_seconds: 3420 },
    valid_from: "2024-01-06T10:15:00Z",
    valid_to: null,
    evidence_ids: ["ev-002"],
    created_at: "2024-01-10T08:00:00Z",
    updated_at: "2024-01-10T08:00:00Z",
  },
  {
    relationship_id: "rel-002",
    relationship_type: "OWNS",
    from_entity_id: "ent-001",
    to_entity_id: "ent-004",
    dataset: "synthetic_demo",
    attributes: {},
    valid_from: "2024-01-05T14:30:00Z",
    valid_to: null,
    evidence_ids: ["ev-001"],
    created_at: "2024-01-10T08:00:00Z",
    updated_at: "2024-01-10T08:00:00Z",
  },
  {
    relationship_id: "rel-003",
    relationship_type: "WORKS_FOR",
    from_entity_id: "ent-002",
    to_entity_id: "ent-005",
    dataset: "synthetic_demo",
    attributes: { role: "Director" },
    valid_from: "2024-01-05T14:30:00Z",
    valid_to: null,
    evidence_ids: ["ev-001"],
    created_at: "2024-01-10T08:00:00Z",
    updated_at: "2024-01-10T08:00:00Z",
  },
  {
    relationship_id: "rel-004",
    relationship_type: "TRANSFERRED",
    from_entity_id: "ent-006",
    to_entity_id: "ent-006",
    dataset: "synthetic_demo",
    attributes: { amount: 85000, currency: "INR" },
    valid_from: "2024-01-07T16:00:00Z",
    valid_to: null,
    evidence_ids: ["ev-003"],
    created_at: "2024-01-10T08:00:00Z",
    updated_at: "2024-01-10T08:00:00Z",
  },
];

// Relationships with inline evidence (§12.3 shape)
export const MOCK_RELATIONSHIPS_WITH_EVIDENCE: RelationshipWithEvidence[] =
  MOCK_RELATIONSHIPS.map((rel) => ({
    ...rel,
    evidence: rel.evidence_ids
      .map((id) => MOCK_EVIDENCE.find((e) => e.evidence_id === id))
      .filter((e): e is Evidence => e !== undefined),
  }));

// ---------------------------------------------------------------------------
// ResolutionDecisions
// ---------------------------------------------------------------------------

export const MOCK_RESOLUTION_DECISIONS: ResolutionDecision[] = [
  {
    decision_id: "dec-001",
    entity_id: "ent-001",
    mention_ids: ["m-001", "m-002"],
    source_record_ids: ["fir_001", "police_report_001"],
    outcome: "merged",
    method: "fuzzy_match",
    matched_on: ["name_similarity>0.92", "shared_vehicle_MH12AB1234"],
    score: 0.92,
    decided_at: "2024-01-10T08:00:00Z",
  },
];

// ---------------------------------------------------------------------------
// Findings (§1.8)
// ---------------------------------------------------------------------------

export const MOCK_FINDINGS: Finding[] = [
  {
    finding_id: "find-001",
    dataset: "synthetic_demo",
    rule_id: "frequency_rule_v1",
    rule_name: "High-Frequency Communication",
    subject_entity_ids: ["ent-001", "ent-003"],
    subject_relationship_ids: ["rel-001"],
    explanation:
      "17 calls between these two numbers over 4 days, exceeding the 10-call/7-day threshold.",
    triggering_values: { call_count: 17, threshold: 10, window_days: 7 },
    evidence_ids: ["ev-002"],
    disclaimer:
      "This is an investigative lead, not evidence of wrongdoing.",
    detected_at: "2024-01-10T09:00:00Z",
  },
  {
    finding_id: "find-002",
    dataset: "synthetic_demo",
    rule_id: "bridge_entity_v1",
    rule_name: "Bridge Entity",
    subject_entity_ids: ["ent-001"],
    subject_relationship_ids: [],
    explanation:
      "Rahul Sharma connects 3 otherwise-disconnected network components, giving them a betweenness centrality score of 0.74.",
    triggering_values: { betweenness: 0.74, threshold: 0.5 },
    evidence_ids: ["ev-001"],
    disclaimer:
      "This is an investigative lead, not evidence of wrongdoing.",
    detected_at: "2024-01-10T09:00:00Z",
  },
];

// ---------------------------------------------------------------------------
// AnalyticsResult (§1.12)
// ---------------------------------------------------------------------------

export const MOCK_ANALYTICS: AnalyticsResult = {
  computed_at: "2024-01-10T09:00:00Z",
  dataset: "synthetic_demo",
  as_of: null,
  centrality: [
    { entity_id: "ent-001", degree: 4, betweenness: 0.74, pagerank: 0.31 },
    { entity_id: "ent-002", degree: 2, betweenness: 0.12, pagerank: 0.18 },
    { entity_id: "ent-003", degree: 1, betweenness: 0.0, pagerank: 0.09 },
    { entity_id: "ent-005", degree: 1, betweenness: 0.0, pagerank: 0.08 },
  ],
  communities: [
    { entity_id: "ent-001", community_id: "comm-A" },
    { entity_id: "ent-003", community_id: "comm-A" },
    { entity_id: "ent-004", community_id: "comm-A" },
    { entity_id: "ent-002", community_id: "comm-B" },
    { entity_id: "ent-005", community_id: "comm-B" },
    { entity_id: "ent-006", community_id: "comm-B" },
    { entity_id: "ent-007", community_id: "comm-C" },
  ],
};

// ---------------------------------------------------------------------------
// AskResponse variants (§10) — one fixture per status
// ---------------------------------------------------------------------------

export const MOCK_ASK_RESPONSE_OK: AskResponse = {
  status: "ok",
  narration:
    "Rahul Sharma (ent-001) made 17 calls to phone +919876543210 (ent-003) between 6–9 January 2024, as recorded in CDR evidence ev-002.",
  path: {
    entities: [MOCK_ENTITIES[0], MOCK_ENTITIES[2]],
    relationships: [MOCK_RELATIONSHIPS[0]],
    paths: [{ entity_ids: ["ent-001", "ent-003"], relationship_ids: ["rel-001"] }],
  },
  evidence: [MOCK_EVIDENCE[1]],
};

export const MOCK_ASK_RESPONSE_LLM_UNAVAILABLE: AskResponse = {
  status: "llm_unavailable",
  message:
    "The AI assistant is temporarily unavailable. Try exploring the graph directly, or retry shortly.",
};

export const MOCK_ASK_RESPONSE_VALIDATION_FAILED: AskResponse = {
  status: "validation_failed",
  reason: "Generated query contained a forbidden CALL clause.",
};

export const MOCK_ASK_RESPONSE_NO_RESULT: AskResponse = {
  status: "no_result",
  message: "No graph data matched your question.",
};

// ---------------------------------------------------------------------------
// Case Workspace (§1.9–1.11)
// ---------------------------------------------------------------------------

export const MOCK_CASE: Case = {
  case_id: "case-001",
  title: "Operation Apex — Initial Investigation",
  status: "open",
  dataset: "synthetic_demo",
  created_at: "2024-01-10T10:00:00Z",
  updated_at: "2024-01-10T10:00:00Z",
};

export const MOCK_NOTES: Note[] = [
  {
    note_id: "note-001",
    case_id: "case-001",
    text: "Rahul Sharma appears to be the central node connecting the financial and communication sub-networks.",
    about_entity_id: "ent-001",
    about_edge_ref_id: null,
    about_evidence_id: null,
    created_at: "2024-01-10T10:05:00Z",
  },
];

export const MOCK_EDGE_REF: EdgeRef = {
  edge_ref_id: "eref-001",
  relationship_id: "rel-001",
  from_entity_id: "ent-001",
  to_entity_id: "ent-003",
  relationship_type: "CALLED",
  created_at: "2024-01-10T08:00:00Z",
};

// ---------------------------------------------------------------------------
// AdapterDescriptor (§1.2)
// ---------------------------------------------------------------------------

export const MOCK_ADAPTERS: AdapterDescriptor[] = [
  {
    adapter_id: "synthetic_v1",
    source_type: "synthetic",
    dataset: "synthetic_demo",
    mode: "batch",
    enabled: true,
    poll_interval_seconds: null,
    last_run_at: "2024-01-10T08:00:00Z",
    last_run_status: "ok",
    last_error: null,
  },
  {
    adapter_id: "rss_public_v1",
    source_type: "rss",
    dataset: "live_public",
    mode: "poll",
    enabled: false,
    poll_interval_seconds: 300,
    last_run_at: null,
    last_run_status: "never_run",
    last_error: null,
  },
];
