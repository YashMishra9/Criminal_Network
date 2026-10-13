/**
 * frontend/lib/api-client.ts
 *
 * Typed API client matching DOC3 §12 endpoint shapes exactly.
 *
 * Mock-mode toggle (E1.md §11):
 *   Set NEXT_PUBLIC_MOCK_MODE=true (env var) to return fixture data without
 *   a live backend. Swapping mock→real requires no signature changes — only
 *   the env var changes.
 *
 * All endpoint signatures match DOC3 §12 exactly:
 *   §12.1  searchEntities
 *   §12.2  getEntity
 *   §12.3  getEntityRelationships
 *   §12.4  getGraph
 *   §12.5  getAnalytics
 *   §12.6  getPatterns
 *   §12.7  getEvidence
 *   §12.8  ask
 *   §12.9  createCase / getCase / addCaseEntity / addCaseRelationship /
 *           addCaseNote / getCaseSummary
 *   §12.10 runIngestion / getIngestionStatus
 */

import type {
  CanonicalEntity,
  Relationship,
  RelationshipWithEvidence,
  Evidence,
  ResolutionDecision,
  Finding,
  AnalyticsResult,
  AskRequest,
  AskResponse,
  Case,
  Note,
  EdgeRef,
  AdapterDescriptor,
  CaseSummaryResult,
  IngestionRunResponse,
} from "./types";

import {
  MOCK_ENTITIES,
  MOCK_RELATIONSHIPS,
  MOCK_RELATIONSHIPS_WITH_EVIDENCE,
  MOCK_EVIDENCE,
  MOCK_RESOLUTION_DECISIONS,
  MOCK_FINDINGS,
  MOCK_ANALYTICS,
  MOCK_ASK_RESPONSE_OK,
  MOCK_CASE,
  MOCK_NOTES,
  MOCK_EDGE_REF,
  MOCK_ADAPTERS,
} from "./mock-data";

// ---------------------------------------------------------------------------
// Mock-mode detection
// ---------------------------------------------------------------------------

/**
 * Returns true when the client should return fixture data instead of calling
 * the real backend. Controlled by NEXT_PUBLIC_MOCK_MODE env var.
 *
 * In test environments (vitest) this is always true — tests never hit a real
 * backend.
 */
export function isMockMode(): boolean {
  if (typeof process !== "undefined" && process.env.VITEST) return true;
  if (typeof process !== "undefined" && process.env.NODE_ENV === "test") return true;
  return process.env.NEXT_PUBLIC_MOCK_MODE === "true";
}

// ---------------------------------------------------------------------------
// Base URL
// ---------------------------------------------------------------------------

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

// ---------------------------------------------------------------------------
// Internal fetch helper (real mode only)
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw Object.assign(new Error(body?.error?.message ?? res.statusText), {
      status: res.status,
      errorBody: body,
    });
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// §12.1  GET /entities/search
// ---------------------------------------------------------------------------

export interface SearchEntitiesParams {
  q?: string;
  dataset?: string;
  entity_type?: string;
}

export async function searchEntities(
  params: SearchEntitiesParams = {}
): Promise<{ results: CanonicalEntity[] }> {
  if (isMockMode()) {
    const { q, entity_type } = params;
    let results = MOCK_ENTITIES;
    if (entity_type) results = results.filter((e) => e.entity_type === entity_type);
    if (q) {
      const lq = q.toLowerCase();
      results = results.filter((e) => e.display_name.toLowerCase().includes(lq));
    }
    return { results };
  }
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.dataset) qs.set("dataset", params.dataset);
  if (params.entity_type) qs.set("entity_type", params.entity_type);
  return apiFetch(`/entities/search?${qs}`);
}

// ---------------------------------------------------------------------------
// §12.2  GET /entities/{entity_id}
// ---------------------------------------------------------------------------

export async function getEntity(
  entityId: string
): Promise<{ entity: CanonicalEntity; resolution: ResolutionDecision[] }> {
  if (isMockMode()) {
    const entity = MOCK_ENTITIES.find((e) => e.entity_id === entityId);
    if (!entity) throw Object.assign(new Error("Not found"), { status: 404 });
    const resolution = MOCK_RESOLUTION_DECISIONS.filter(
      (d) => d.entity_id === entityId
    );
    return { entity, resolution };
  }
  return apiFetch(`/entities/${encodeURIComponent(entityId)}`);
}

// ---------------------------------------------------------------------------
// §12.3  GET /entities/{entity_id}/relationships
// ---------------------------------------------------------------------------

export interface GetEntityRelationshipsParams {
  dataset?: string;
  as_of?: string;
}

export async function getEntityRelationships(
  entityId: string,
  params: GetEntityRelationshipsParams = {}
): Promise<{ relationships: RelationshipWithEvidence[] }> {
  if (isMockMode()) {
    const relationships = MOCK_RELATIONSHIPS_WITH_EVIDENCE.filter(
      (r) => r.from_entity_id === entityId || r.to_entity_id === entityId
    );
    return { relationships };
  }
  const qs = new URLSearchParams();
  if (params.dataset) qs.set("dataset", params.dataset);
  if (params.as_of) qs.set("as_of", params.as_of);
  return apiFetch(
    `/entities/${encodeURIComponent(entityId)}/relationships?${qs}`
  );
}

// ---------------------------------------------------------------------------
// §12.4  GET /graph
// ---------------------------------------------------------------------------

export interface GetGraphParams {
  dataset?: string;
  as_of?: string;
  entity_types?: string;
  relationship_types?: string;
  community?: string;
  pattern?: string;
}

export async function getGraph(
  params: GetGraphParams = {}
): Promise<{ entities: CanonicalEntity[]; relationships: Relationship[] }> {
  if (isMockMode()) {
    return { entities: MOCK_ENTITIES, relationships: MOCK_RELATIONSHIPS };
  }
  const qs = new URLSearchParams();
  if (params.dataset) qs.set("dataset", params.dataset);
  if (params.as_of) qs.set("as_of", params.as_of);
  if (params.entity_types) qs.set("entity_types", params.entity_types);
  if (params.relationship_types) qs.set("relationship_types", params.relationship_types);
  if (params.community) qs.set("community", params.community);
  if (params.pattern) qs.set("pattern", params.pattern);
  return apiFetch(`/graph?${qs}`);
}

// ---------------------------------------------------------------------------
// §12.5  GET /analytics
// ---------------------------------------------------------------------------

export interface GetAnalyticsParams {
  dataset?: string;
  as_of?: string;
  algorithms?: string;
}

export async function getAnalytics(
  params: GetAnalyticsParams = {}
): Promise<AnalyticsResult> {
  if (isMockMode()) return MOCK_ANALYTICS;
  const qs = new URLSearchParams();
  if (params.dataset) qs.set("dataset", params.dataset);
  if (params.as_of) qs.set("as_of", params.as_of);
  if (params.algorithms) qs.set("algorithms", params.algorithms);
  return apiFetch(`/analytics?${qs}`);
}

// ---------------------------------------------------------------------------
// §12.6  GET /patterns
// ---------------------------------------------------------------------------

export interface GetPatternsParams {
  dataset?: string;
  as_of?: string;
}

export async function getPatterns(
  params: GetPatternsParams = {}
): Promise<{ findings: Finding[] }> {
  if (isMockMode()) return { findings: MOCK_FINDINGS };
  const qs = new URLSearchParams();
  if (params.dataset) qs.set("dataset", params.dataset);
  if (params.as_of) qs.set("as_of", params.as_of);
  return apiFetch(`/patterns?${qs}`);
}

// ---------------------------------------------------------------------------
// §12.7  GET /evidence
// ---------------------------------------------------------------------------

export interface GetEvidenceParams {
  entity_id?: string;
  relationship_id?: string;
  finding_id?: string;
  decision_id?: string;
}

export async function getEvidence(
  params: GetEvidenceParams
): Promise<{ evidence: Evidence[] }> {
  if (isMockMode()) {
    // Return evidence matching the requested id across all mock evidence
    return { evidence: MOCK_EVIDENCE };
  }
  const qs = new URLSearchParams();
  if (params.entity_id) qs.set("entity_id", params.entity_id);
  if (params.relationship_id) qs.set("relationship_id", params.relationship_id);
  if (params.finding_id) qs.set("finding_id", params.finding_id);
  if (params.decision_id) qs.set("decision_id", params.decision_id);
  return apiFetch(`/evidence?${qs}`);
}

// ---------------------------------------------------------------------------
// §12.8  POST /ask
// ---------------------------------------------------------------------------

export async function ask(request: AskRequest): Promise<AskResponse> {
  if (isMockMode()) return MOCK_ASK_RESPONSE_OK;
  return apiFetch("/ask", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

// ---------------------------------------------------------------------------
// §12.9  Case Workspace
// ---------------------------------------------------------------------------

export async function createCase(
  title: string,
  dataset: string
): Promise<Case> {
  if (isMockMode()) return MOCK_CASE;
  return apiFetch("/cases", {
    method: "POST",
    body: JSON.stringify({ title, dataset }),
  });
}

export async function getCase(caseId: string): Promise<{
  case: Case;
  entities: CanonicalEntity[];
  edge_refs: EdgeRef[];
  evidence: Evidence[];
  notes: Note[];
}> {
  if (isMockMode()) {
    return {
      case: MOCK_CASE,
      entities: [MOCK_ENTITIES[0]],
      edge_refs: [MOCK_EDGE_REF],
      evidence: [MOCK_EVIDENCE[0]],
      notes: MOCK_NOTES,
    };
  }
  return apiFetch(`/cases/${encodeURIComponent(caseId)}`);
}

export async function addCaseEntity(
  caseId: string,
  entityId: string
): Promise<void> {
  if (isMockMode()) return;
  await apiFetch(`/cases/${encodeURIComponent(caseId)}/entities`, {
    method: "POST",
    body: JSON.stringify({ entity_id: entityId }),
  });
}

export async function addCaseRelationship(
  caseId: string,
  relationshipId: string
): Promise<EdgeRef> {
  if (isMockMode()) return MOCK_EDGE_REF;
  return apiFetch(`/cases/${encodeURIComponent(caseId)}/relationships`, {
    method: "POST",
    body: JSON.stringify({ relationship_id: relationshipId }),
  });
}

export async function addCaseNote(
  caseId: string,
  text: string,
  about?: { type: "entity" | "edge_ref" | "evidence"; id: string }
): Promise<Note> {
  if (isMockMode()) return MOCK_NOTES[0];
  return apiFetch(`/cases/${encodeURIComponent(caseId)}/notes`, {
    method: "POST",
    body: JSON.stringify({ text, about }),
  });
}

export async function getCaseSummary(
  caseId: string
): Promise<CaseSummaryResult> {
  if (isMockMode()) {
    return {
      status: "ok",
      summary:
        "This case centres on Rahul Sharma, who connects the communication and financial sub-networks. Key evidence includes CDR records showing 17 calls and a ₹85,000 transfer.",
      generated_at: "2024-01-10T10:10:00Z",
    };
  }
  return apiFetch(`/cases/${encodeURIComponent(caseId)}/summary`);
}

// ---------------------------------------------------------------------------
// §12.10  Ingestion / Adapter Status
// ---------------------------------------------------------------------------

export async function runIngestion(
  adapterId: string
): Promise<IngestionRunResponse> {
  if (isMockMode()) {
    return { status: "ok", records_ingested: 42, message: null };
  }
  return apiFetch(`/ingestion/run?adapter_id=${encodeURIComponent(adapterId)}`, {
    method: "POST",
  });
}

export async function getIngestionStatus(): Promise<{
  adapters: AdapterDescriptor[];
}> {
  if (isMockMode()) return { adapters: MOCK_ADAPTERS };
  return apiFetch("/ingestion/status");
}
