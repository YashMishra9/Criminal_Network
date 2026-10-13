/**
 * tests/smoke.test.ts — E1 component smoke tests (E1.md §13)
 *
 * Verifies:
 *   1. isMockMode() returns true in the test environment.
 *   2. Every api-client function returns DOC3-shaped data in mock mode.
 *   3. types.ts shapes are structurally correct (compile-time + runtime checks).
 *   4. Mock fixtures satisfy DOC3 invariants (non-empty evidence_ids on
 *      Relationship and Finding — Contract Invariant 1).
 *   5. Finding disclaimer is the exact DOC3 §1.8 literal (Contract Invariant 5).
 *
 * These tests run entirely in mock mode — no backend or Neo4j required.
 */

import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import {
  isMockMode,
  searchEntities,
  getEntity,
  getEntityRelationships,
  getGraph,
  getAnalytics,
  getPatterns,
  getEvidence,
  ask,
  createCase,
  getCase,
  addCaseRelationship,
  addCaseNote,
  getCaseSummary,
  runIngestion,
  getIngestionStatus,
} from "../lib/api-client";
import { MOCK_ENTITIES, MOCK_FINDINGS, MOCK_RELATIONSHIPS } from "../lib/mock-data";
import type {
  CanonicalEntity,
  Relationship,
  Evidence,
  Finding,
} from "../lib/types";

// ---------------------------------------------------------------------------
// Mock mode detection
// ---------------------------------------------------------------------------

describe("isMockMode", () => {
  it("returns true in the vitest test environment", () => {
    expect(isMockMode()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// §12.1 searchEntities
// ---------------------------------------------------------------------------

describe("searchEntities", () => {
  it("returns { results: CanonicalEntity[] } shape", async () => {
    const res = await searchEntities();
    expect(res).toHaveProperty("results");
    expect(Array.isArray(res.results)).toBe(true);
  });

  it("returns at least one entity", async () => {
    const res = await searchEntities();
    expect(res.results.length).toBeGreaterThan(0);
  });

  it("each entity has all required DOC3 §1.4 fields", async () => {
    const res = await searchEntities();
    for (const e of res.results) {
      expect(e).toHaveProperty("entity_id");
      expect(e).toHaveProperty("entity_type");
      expect(e).toHaveProperty("dataset");
      expect(e).toHaveProperty("display_name");
      expect(e).toHaveProperty("attributes");
      expect(e).toHaveProperty("resolved_from");
      expect(e).toHaveProperty("resolution_method");
      expect(e).toHaveProperty("created_at");
      expect(e).toHaveProperty("updated_at");
    }
  });

  it("filters by entity_type", async () => {
    const res = await searchEntities({ entity_type: "Person" });
    expect(res.results.every((e) => e.entity_type === "Person")).toBe(true);
  });

  it("filters by query string (case-insensitive)", async () => {
    const res = await searchEntities({ q: "rahul" });
    expect(res.results.length).toBeGreaterThan(0);
    expect(
      res.results.every((e) =>
        e.display_name.toLowerCase().includes("rahul")
      )
    ).toBe(true);
  });

  it("returns empty array for non-matching query", async () => {
    const res = await searchEntities({ q: "zzznomatch" });
    expect(res.results).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// §12.2 getEntity
// ---------------------------------------------------------------------------

describe("getEntity", () => {
  it("returns { entity, resolution } shape", async () => {
    const res = await getEntity("ent-001");
    expect(res).toHaveProperty("entity");
    expect(res).toHaveProperty("resolution");
    expect(Array.isArray(res.resolution)).toBe(true);
  });

  it("entity has all required DOC3 §1.4 fields", async () => {
    const { entity } = await getEntity("ent-001");
    const required: (keyof CanonicalEntity)[] = [
      "entity_id", "entity_type", "dataset", "display_name",
      "attributes", "resolved_from", "resolution_method",
      "created_at", "updated_at",
    ];
    for (const field of required) {
      expect(entity).toHaveProperty(field);
    }
  });

  it("throws with status 404 for unknown entity", async () => {
    await expect(getEntity("does-not-exist")).rejects.toMatchObject({
      status: 404,
    });
  });

  it("resolution decisions have all required DOC3 §1.7 fields", async () => {
    const { resolution } = await getEntity("ent-001");
    for (const d of resolution) {
      expect(d).toHaveProperty("decision_id");
      expect(d).toHaveProperty("entity_id");
      expect(d).toHaveProperty("mention_ids");
      expect(d).toHaveProperty("source_record_ids");
      expect(d).toHaveProperty("outcome");
      expect(d).toHaveProperty("method");
      expect(d).toHaveProperty("matched_on");
      expect(d).toHaveProperty("decided_at");
    }
  });
});

// ---------------------------------------------------------------------------
// §12.3 getEntityRelationships
// ---------------------------------------------------------------------------

describe("getEntityRelationships", () => {
  it("returns { relationships: [...] } shape", async () => {
    const res = await getEntityRelationships("ent-001");
    expect(res).toHaveProperty("relationships");
    expect(Array.isArray(res.relationships)).toBe(true);
  });

  it("each relationship has all required DOC3 §1.5 fields", async () => {
    const res = await getEntityRelationships("ent-001");
    const required: (keyof Relationship)[] = [
      "relationship_id", "relationship_type", "from_entity_id",
      "to_entity_id", "dataset", "attributes", "valid_from",
      "valid_to", "evidence_ids", "created_at", "updated_at",
    ];
    for (const r of res.relationships) {
      for (const field of required) {
        expect(r).toHaveProperty(field);
      }
    }
  });

  it("each relationship includes inline evidence[] (DOC3 §12.3)", async () => {
    const res = await getEntityRelationships("ent-001");
    for (const r of res.relationships) {
      expect(r).toHaveProperty("evidence");
      expect(Array.isArray(r.evidence)).toBe(true);
    }
  });

  it("Contract Invariant 1: evidence_ids is non-empty on every relationship", async () => {
    const res = await getEntityRelationships("ent-001");
    for (const r of res.relationships) {
      expect(r.evidence_ids.length).toBeGreaterThan(0);
    }
  });
});

// ---------------------------------------------------------------------------
// §12.4 getGraph
// ---------------------------------------------------------------------------

describe("getGraph", () => {
  it("returns { entities, relationships } shape", async () => {
    const res = await getGraph();
    expect(res).toHaveProperty("entities");
    expect(res).toHaveProperty("relationships");
    expect(Array.isArray(res.entities)).toBe(true);
    expect(Array.isArray(res.relationships)).toBe(true);
  });

  it("relationships carry evidence_ids only, not inline evidence (DOC3 §12.4)", async () => {
    const res = await getGraph();
    for (const r of res.relationships) {
      expect(r).toHaveProperty("evidence_ids");
      expect(r).not.toHaveProperty("evidence");
    }
  });

  it("Contract Invariant 1: all mock relationships have non-empty evidence_ids", async () => {
    const res = await getGraph();
    for (const r of res.relationships) {
      expect((r as Relationship).evidence_ids.length).toBeGreaterThan(0);
    }
  });
});

// ---------------------------------------------------------------------------
// §12.5 getAnalytics
// ---------------------------------------------------------------------------

describe("getAnalytics", () => {
  it("returns AnalyticsResult shape with required DOC3 §1.12 fields", async () => {
    const res = await getAnalytics();
    expect(res).toHaveProperty("computed_at");
    expect(res).toHaveProperty("dataset");
    expect(res).toHaveProperty("as_of");
    expect(res).toHaveProperty("centrality");
    expect(res).toHaveProperty("communities");
    expect(Array.isArray(res.centrality)).toBe(true);
    expect(Array.isArray(res.communities)).toBe(true);
  });

  it("centrality entries have degree, betweenness, pagerank", async () => {
    const res = await getAnalytics();
    for (const c of res.centrality) {
      expect(c).toHaveProperty("entity_id");
      expect(c).toHaveProperty("degree");
      expect(c).toHaveProperty("betweenness");
      expect(c).toHaveProperty("pagerank");
    }
  });
});

// ---------------------------------------------------------------------------
// §12.6 getPatterns
// ---------------------------------------------------------------------------

describe("getPatterns", () => {
  it("returns { findings: Finding[] } shape", async () => {
    const res = await getPatterns();
    expect(res).toHaveProperty("findings");
    expect(Array.isArray(res.findings)).toBe(true);
  });

  it("each finding has all required DOC3 §1.8 fields", async () => {
    const res = await getPatterns();
    const required: (keyof Finding)[] = [
      "finding_id", "dataset", "rule_id", "rule_name",
      "subject_entity_ids", "subject_relationship_ids",
      "explanation", "triggering_values", "evidence_ids",
      "disclaimer", "detected_at",
    ];
    for (const f of res.findings) {
      for (const field of required) {
        expect(f).toHaveProperty(field);
      }
    }
  });

  it("Contract Invariant 1: evidence_ids is non-empty on every finding", async () => {
    const res = await getPatterns();
    for (const f of res.findings) {
      expect(f.evidence_ids.length).toBeGreaterThan(0);
    }
  });

  it("Contract Invariant 5: disclaimer is the exact DOC3 §1.8 literal", async () => {
    const res = await getPatterns();
    const EXPECTED =
      "This is an investigative lead, not evidence of wrongdoing.";
    for (const f of res.findings) {
      expect(f.disclaimer).toBe(EXPECTED);
    }
  });
});

// ---------------------------------------------------------------------------
// §12.7 getEvidence
// ---------------------------------------------------------------------------

describe("getEvidence", () => {
  it("returns { evidence: Evidence[] } shape", async () => {
    const res = await getEvidence({ entity_id: "ent-001" });
    expect(res).toHaveProperty("evidence");
    expect(Array.isArray(res.evidence)).toBe(true);
  });

  it("each evidence item has required DOC3 §1.6 fields", async () => {
    const res = await getEvidence({ relationship_id: "rel-001" });
    const required: (keyof Evidence)[] = [
      "evidence_id", "dataset", "source_id", "source_type",
      "record_timestamp", "ingested_at", "snippet", "pointer",
    ];
    for (const e of res.evidence) {
      for (const field of required) {
        expect(e).toHaveProperty(field);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// §12.8 ask
// ---------------------------------------------------------------------------

describe("ask", () => {
  it("returns AskResponse with status 'ok' in mock mode", async () => {
    const res = await ask({
      question: "Who called Rahul Sharma?",
      dataset: "synthetic_demo",
      as_of: null,
    });
    expect(res.status).toBe("ok");
    if (res.status === "ok") {
      expect(res).toHaveProperty("narration");
      expect(res).toHaveProperty("path");
      expect(res).toHaveProperty("evidence");
    }
  });
});

// ---------------------------------------------------------------------------
// §12.9 Case Workspace
// ---------------------------------------------------------------------------

describe("Case Workspace", () => {
  it("createCase returns a Case with required DOC3 §1.9 fields", async () => {
    const c = await createCase("Test Case", "synthetic_demo");
    expect(c).toHaveProperty("case_id");
    expect(c).toHaveProperty("title");
    expect(c).toHaveProperty("status");
    expect(c).toHaveProperty("dataset");
    expect(c).toHaveProperty("created_at");
    expect(c).toHaveProperty("updated_at");
  });

  it("getCase returns case with entities, edge_refs, evidence, notes", async () => {
    const res = await getCase("case-001");
    expect(res).toHaveProperty("case");
    expect(res).toHaveProperty("entities");
    expect(res).toHaveProperty("edge_refs");
    expect(res).toHaveProperty("evidence");
    expect(res).toHaveProperty("notes");
  });

  it("addCaseRelationship returns an EdgeRef with required DOC3 §1.11 fields", async () => {
    const ref = await addCaseRelationship("case-001", "rel-001");
    expect(ref).toHaveProperty("edge_ref_id");
    expect(ref).toHaveProperty("relationship_id");
    expect(ref).toHaveProperty("from_entity_id");
    expect(ref).toHaveProperty("to_entity_id");
    expect(ref).toHaveProperty("relationship_type");
    expect(ref).toHaveProperty("created_at");
  });

  it("addCaseNote returns a Note with required DOC3 §1.10 fields", async () => {
    const note = await addCaseNote("case-001", "Test note");
    expect(note).toHaveProperty("note_id");
    expect(note).toHaveProperty("case_id");
    expect(note).toHaveProperty("text");
    expect(note).toHaveProperty("about_entity_id");
    expect(note).toHaveProperty("about_edge_ref_id");
    expect(note).toHaveProperty("about_evidence_id");
    expect(note).toHaveProperty("created_at");
  });

  it("getCaseSummary returns CaseSummaryResult with status 'ok'", async () => {
    const res = await getCaseSummary("case-001");
    expect(res.status).toBe("ok");
    if (res.status === "ok") {
      expect(res).toHaveProperty("summary");
      expect(res).toHaveProperty("generated_at");
    }
  });
});

// ---------------------------------------------------------------------------
// §12.10 Ingestion
// ---------------------------------------------------------------------------

describe("Ingestion", () => {
  it("runIngestion returns IngestionRunResponse shape", async () => {
    const res = await runIngestion("synthetic_v1");
    expect(res).toHaveProperty("status");
    expect(res).toHaveProperty("records_ingested");
    expect(res).toHaveProperty("message");
  });

  it("getIngestionStatus returns { adapters: AdapterDescriptor[] }", async () => {
    const res = await getIngestionStatus();
    expect(res).toHaveProperty("adapters");
    expect(Array.isArray(res.adapters)).toBe(true);
    for (const a of res.adapters) {
      expect(a).toHaveProperty("adapter_id");
      expect(a).toHaveProperty("dataset");
      expect(a).toHaveProperty("mode");
      expect(a).toHaveProperty("enabled");
    }
  });
});

// ---------------------------------------------------------------------------
// Mock fixture integrity checks
// ---------------------------------------------------------------------------

describe("Mock fixture integrity", () => {
  it("all MOCK_ENTITIES have valid EntityType values", () => {
    const valid = new Set([
      "Person", "Phone", "Vehicle", "Location",
      "Organization", "BankAccount", "Transaction", "Event",
    ]);
    for (const e of MOCK_ENTITIES) {
      expect(valid.has(e.entity_type)).toBe(true);
    }
  });

  it("all MOCK_RELATIONSHIPS have non-empty evidence_ids (Contract Invariant 1)", () => {
    for (const r of MOCK_RELATIONSHIPS) {
      expect(r.evidence_ids.length).toBeGreaterThan(0);
    }
  });

  it("all MOCK_FINDINGS have non-empty evidence_ids (Contract Invariant 1)", () => {
    for (const f of MOCK_FINDINGS) {
      expect(f.evidence_ids.length).toBeGreaterThan(0);
    }
  });

  it("all MOCK_FINDINGS have the exact disclaimer literal (Contract Invariant 5)", () => {
    const EXPECTED =
      "This is an investigative lead, not evidence of wrongdoing.";
    for (const f of MOCK_FINDINGS) {
      expect(f.disclaimer).toBe(EXPECTED);
    }
  });

  it("dataset values are only 'synthetic_demo' or 'live_public'", () => {
    const valid = new Set(["synthetic_demo", "live_public"]);
    for (const e of MOCK_ENTITIES) expect(valid.has(e.dataset)).toBe(true);
    for (const r of MOCK_RELATIONSHIPS) expect(valid.has(r.dataset)).toBe(true);
    for (const f of MOCK_FINDINGS) expect(valid.has(f.dataset)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// DashboardPage render smoke test (E1.md §13 — component render requirement)
// ---------------------------------------------------------------------------

import DashboardPage from "../app/page";

describe("DashboardPage render", () => {
  it("renders the page heading", async () => {
    render(<DashboardPage />);
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /criminal network analysis/i })
      ).toBeInTheDocument();
    });
  });

  it("renders mock-backed entity names after data loads", async () => {
    render(<DashboardPage />);
    // Wait for useEffect → getGraph mock to resolve and entities to appear
    await waitFor(() => {
      expect(screen.getByText("Rahul Sharma")).toBeInTheDocument();
    });
  });

  it("renders the MOCK MODE badge in test environment", async () => {
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByText("MOCK MODE")).toBeInTheDocument();
    });
  });

  it("renders stat cards with non-zero counts after data loads", async () => {
    render(<DashboardPage />);
    await waitFor(() => {
      // 7 mock entities — the stat card value should be visible
      expect(screen.getByText("7")).toBeInTheDocument();
    });
  });

  it("renders the Contract Invariant 5 disclaimer text on every finding", async () => {
    render(<DashboardPage />);
    await waitFor(() => {
      const disclaimers = screen.getAllByText(
        "This is an investigative lead, not evidence of wrongdoing."
      );
      // One disclaimer per finding — 2 mock findings
      expect(disclaimers.length).toBe(2);
    });
  });
});
