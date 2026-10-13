/**
 * frontend/lib/types.ts
 *
 * TypeScript mirrors of DOC3 §1 data models.
 * Must be kept in sync with backend/app/contracts/ (H5 drift check).
 *
 * Rules (DOC3 §1, E1.md §17):
 *   - Every field name and type matches DOC3 §1 exactly.
 *   - No fields are invented or omitted.
 *   - All timestamps are ISO-8601 UTC strings.
 *   - All IDs are strings.
 */

// ---------------------------------------------------------------------------
// §2.1 Dataset identifiers — exactly two values
// ---------------------------------------------------------------------------

export type Dataset = "synthetic_demo" | "live_public";

// ---------------------------------------------------------------------------
// §1.2 AdapterDescriptor
// ---------------------------------------------------------------------------

export interface AdapterDescriptor {
  adapter_id: string;
  source_type: string;
  dataset: Dataset;
  mode: "batch" | "poll";
  enabled: boolean;
  poll_interval_seconds: number | null;
  last_run_at: string | null;
  last_run_status: "ok" | "error" | "never_run";
  last_error: string | null;
}

// ---------------------------------------------------------------------------
// §1.3 EntityMention / RelationshipMention
// ---------------------------------------------------------------------------

export type EntityType =
  | "Person"
  | "Phone"
  | "Vehicle"
  | "Location"
  | "Organization"
  | "BankAccount"
  | "Transaction"
  | "Event";

export type RelationshipType =
  | "CALLED"
  | "OWNS"
  | "USED"
  | "TRANSFERRED"
  | "VISITED"
  | "MET"
  | "WORKS_FOR"
  | "ASSOCIATED_WITH"
  | "MENTIONED_IN"
  | "PART_OF";

export type ExtractionMethod = "spacy" | "regex" | "llm";

export interface EntityMention {
  mention_id: string;
  record_id: string;
  dataset: string;
  entity_type: EntityType;
  raw_text: string;
  normalized_value: string | null;
  attributes: object;
  extraction_method: ExtractionMethod;
  confidence: number | null;
}

export interface RelationshipMention {
  relationship_mention_id: string;
  record_id: string;
  dataset: string;
  relationship_type: RelationshipType;
  from_mention_id: string;
  to_mention_id: string;
  occurred_at: string | null;
  attributes: object;
  extraction_method: ExtractionMethod;
}

// ---------------------------------------------------------------------------
// §1.4 CanonicalEntity
// ---------------------------------------------------------------------------

export type ResolutionMethod =
  | "exact_match"
  | "fuzzy_match"
  | "shared_attribute"
  | "embedding_similarity"
  | "manual";

export interface CanonicalEntity {
  entity_id: string;
  entity_type: EntityType;
  dataset: string;
  display_name: string;
  attributes: object;
  resolved_from: string[];
  resolution_method: ResolutionMethod;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// §1.5 Relationship
// ---------------------------------------------------------------------------

export interface Relationship {
  relationship_id: string;
  relationship_type: RelationshipType;
  from_entity_id: string;
  to_entity_id: string;
  dataset: string;
  attributes: object;
  valid_from: string;
  valid_to: string | null;
  evidence_ids: string[];
  created_at: string;
  updated_at: string;
}

// §12.3 variant: relationship with inline evidence
export interface RelationshipWithEvidence extends Relationship {
  evidence: Evidence[];
}

// ---------------------------------------------------------------------------
// §1.6 Evidence
// ---------------------------------------------------------------------------

export interface Evidence {
  evidence_id: string;
  dataset: string;
  source_id: string;
  source_type: string;
  record_timestamp: string | null;
  ingested_at: string;
  snippet: string | null;
  pointer: object | null;
}

// ---------------------------------------------------------------------------
// §1.7 ResolutionDecision
// ---------------------------------------------------------------------------

export interface ResolutionDecision {
  decision_id: string;
  entity_id: string;
  mention_ids: string[];
  source_record_ids: string[];
  outcome: "merged" | "rejected";
  method: ResolutionMethod;
  matched_on: string[];
  score: number | null;
  decided_at: string;
}

// ---------------------------------------------------------------------------
// §1.8 Finding
// ---------------------------------------------------------------------------

export interface Finding {
  finding_id: string;
  dataset: string;
  rule_id: string;
  rule_name: string;
  subject_entity_ids: string[];
  subject_relationship_ids: string[];
  explanation: string;
  triggering_values: object;
  evidence_ids: string[];
  disclaimer: "This is an investigative lead, not evidence of wrongdoing.";
  detected_at: string;
}

// ---------------------------------------------------------------------------
// §1.9 Case
// ---------------------------------------------------------------------------

export interface Case {
  case_id: string;
  title: string;
  status: "open" | "closed";
  dataset: string;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// §1.10 Note
// ---------------------------------------------------------------------------

export interface Note {
  note_id: string;
  case_id: string;
  text: string;
  about_entity_id: string | null;
  about_edge_ref_id: string | null;
  about_evidence_id: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// §1.11 EdgeRef
// ---------------------------------------------------------------------------

export interface EdgeRef {
  edge_ref_id: string;
  relationship_id: string;
  from_entity_id: string;
  to_entity_id: string;
  relationship_type: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// §1.12 AnalyticsResult
// ---------------------------------------------------------------------------

export interface AnalyticsResult {
  computed_at: string;
  dataset: string;
  as_of: string | null;
  centrality: {
    entity_id: string;
    degree: number;
    betweenness: number;
    pagerank: number;
  }[];
  communities: {
    entity_id: string;
    community_id: string;
  }[];
}

// §7 ShortestPathResult
export interface ShortestPathResult {
  found: boolean;
  path_entity_ids: string[];
  path_relationship_ids: string[];
}

// ---------------------------------------------------------------------------
// §10 Ask-the-Network types
// ---------------------------------------------------------------------------

export interface AskRequest {
  question: string;
  dataset: string;
  as_of: string | null;
}

export interface GraphQueryResult {
  entities: CanonicalEntity[];
  relationships: Relationship[];
  paths: { entity_ids: string[]; relationship_ids: string[] }[];
}

export type AskResponse =
  | { status: "ok"; narration: string; path: GraphQueryResult; evidence: Evidence[] }
  | { status: "llm_unavailable"; message: string }
  | { status: "validation_failed"; reason: string }
  | { status: "no_result"; message: string };

// ---------------------------------------------------------------------------
// §11 Case Workspace types
// ---------------------------------------------------------------------------

export type CaseSummaryResult =
  | { status: "ok"; summary: string; generated_at: string }
  | { status: "llm_unavailable"; message: string };

// ---------------------------------------------------------------------------
// §13 ErrorResponse
// ---------------------------------------------------------------------------

export type ErrorType =
  | "not_found"
  | "validation_error"
  | "llm_unavailable"
  | "dataset_isolation_violation"
  | "graph_unavailable"
  | "internal_error";

export interface ErrorResponse {
  error: {
    type: ErrorType;
    message: string;
    details: object | null;
  };
}

// ---------------------------------------------------------------------------
// §12.10 Ingestion run response
// ---------------------------------------------------------------------------

export interface IngestionRunResponse {
  status: "ok" | "error";
  records_ingested: number;
  message: string | null;
}
