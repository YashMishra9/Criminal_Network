/**
 * tests/E3.test.tsx — E3 component tests (E3.md §13)
 *
 * Acceptance criterion (E3.md §12):
 *   No relationship or finding can be displayed without a reachable evidence path.
 *
 * Covers:
 *   - EntityPanel renders entity name, type, resolution rationale
 *   - Every rendered relationship has a "view evidence" button (DOC3 §9.4)
 *   - Clicking "view evidence" expands the EvidencePanel inline
 *   - EvidencePanel renders evidence items from pre-loaded evidence
 *   - EvidencePanel fetches via §12.7 when given a relationship_id
 *   - EvidencePanel renders correctly with no evidence
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type {
  CanonicalEntity,
  ResolutionDecision,
  RelationshipWithEvidence,
  Evidence,
} from "../lib/types";

// ---------------------------------------------------------------------------
// Mock api-client — must be declared before component imports
// ---------------------------------------------------------------------------

vi.mock("../lib/api-client", () => ({
  isMockMode: vi.fn(() => true),
  getEntity: vi.fn(),
  getEntityRelationships: vi.fn(),
  getEvidence: vi.fn(),
}));

import EntityPanel from "../components/EntityPanel/EntityPanel";
import EvidencePanel from "../components/EvidencePanel/EvidencePanel";
import * as apiClient from "../lib/api-client";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ENTITY: CanonicalEntity = {
  entity_id: "ent-001",
  entity_type: "Person",
  dataset: "synthetic_demo",
  display_name: "Rahul Sharma",
  attributes: { aliases: "R. Sharma" },
  resolved_from: ["m-001", "m-002"],
  resolution_method: "fuzzy_match",
  created_at: "2024-01-10T08:00:00Z",
  updated_at: "2024-01-10T08:00:00Z",
};

const RESOLUTION: ResolutionDecision[] = [
  {
    decision_id: "dec-001",
    entity_id: "ent-001",
    mention_ids: ["m-001", "m-002"],
    source_record_ids: ["fir_001"],
    outcome: "merged",
    method: "fuzzy_match",
    matched_on: ["name_similarity>0.92"],
    score: 0.92,
    decided_at: "2024-01-10T08:00:00Z",
  },
];

const EVIDENCE_1: Evidence = {
  evidence_id: "ev-001",
  dataset: "synthetic_demo",
  source_id: "fir_001",
  source_type: "FIR",
  record_timestamp: "2024-01-05T14:30:00Z",
  ingested_at: "2024-01-10T08:00:00Z",
  snippet: "Rahul Sharma was named in FIR #2024/001.",
  pointer: null,
};

const EVIDENCE_2: Evidence = {
  evidence_id: "ev-002",
  dataset: "synthetic_demo",
  source_id: "cdr_001",
  source_type: "CDR",
  record_timestamp: "2024-01-06T10:15:00Z",
  ingested_at: "2024-01-10T08:00:00Z",
  snippet: "17 calls between +919876543210 and +919812345678.",
  pointer: null,
};

const RELATIONSHIPS: RelationshipWithEvidence[] = [
  {
    relationship_id: "rel-001",
    relationship_type: "CALLED",
    from_entity_id: "ent-001",
    to_entity_id: "ent-003",
    dataset: "synthetic_demo",
    attributes: {},
    valid_from: "2024-01-06T10:00:00Z",
    valid_to: null,
    evidence_ids: ["ev-002"],
    created_at: "2024-01-10T08:00:00Z",
    updated_at: "2024-01-10T08:00:00Z",
    evidence: [EVIDENCE_2],
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
    evidence: [EVIDENCE_1],
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function setupEntityMocks() {
  vi.mocked(apiClient.getEntity).mockResolvedValue({
    entity: ENTITY,
    resolution: RESOLUTION,
  });
  vi.mocked(apiClient.getEntityRelationships).mockResolvedValue({
    relationships: RELATIONSHIPS,
  });
}

// ---------------------------------------------------------------------------
// EntityPanel tests
// ---------------------------------------------------------------------------

describe("EntityPanel — render", () => {
  beforeEach(() => {
    setupEntityMocks();
  });

  it("renders the entity panel container", async () => {
    render(<EntityPanel entityId="ent-001" />);
    await waitFor(() => {
      expect(screen.getByTestId("entity-panel")).toBeInTheDocument();
    });
  });

  it("renders the entity display name", async () => {
    render(<EntityPanel entityId="ent-001" />);
    await waitFor(() => {
      expect(screen.getByText("Rahul Sharma")).toBeInTheDocument();
    });
  });

  it("renders the entity type", async () => {
    render(<EntityPanel entityId="ent-001" />);
    await waitFor(() => {
      expect(screen.getByText(/Person/)).toBeInTheDocument();
    });
  });

  it("renders resolution rationale when present", async () => {
    render(<EntityPanel entityId="ent-001" />);
    await waitFor(() => {
      expect(screen.getByTestId("resolution-list")).toBeInTheDocument();
      expect(screen.getByText("fuzzy_match")).toBeInTheDocument();
      expect(screen.getByText("merged")).toBeInTheDocument();
    });
  });

  it("calls onClose when close button is clicked", async () => {
    const onClose = vi.fn();
    render(<EntityPanel entityId="ent-001" onClose={onClose} />);
    await waitFor(() => screen.getByTestId("entity-panel"));
    fireEvent.click(screen.getByLabelText("Close entity panel"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("EntityPanel — evidence affordance (DOC3 §9.4)", () => {
  beforeEach(() => {
    setupEntityMocks();
  });

  it("renders a 'view evidence' button for every relationship", async () => {
    render(<EntityPanel entityId="ent-001" />);
    await waitFor(() => {
      const buttons = screen.getAllByTestId("view-evidence-button");
      // One button per relationship — must equal the number of relationships
      expect(buttons.length).toBe(RELATIONSHIPS.length);
    });
  });

  it("every relationship item has a view-evidence button (DOC3 §9.4 — no claim without evidence path)", async () => {
    render(<EntityPanel entityId="ent-001" />);
    await waitFor(() => {
      const items = screen.getAllByTestId("relationship-item");
      items.forEach((item) => {
        expect(item.querySelector("[data-testid='view-evidence-button']")).not.toBeNull();
      });
    });
  });

  it("clicking 'view evidence' expands the EvidencePanel inline", async () => {
    render(<EntityPanel entityId="ent-001" />);
    await waitFor(() => screen.getAllByTestId("view-evidence-button"));

    const [firstButton] = screen.getAllByTestId("view-evidence-button");
    fireEvent.click(firstButton);

    expect(screen.getByTestId("evidence-panel")).toBeInTheDocument();
  });

  it("clicking 'view evidence' again collapses the EvidencePanel", async () => {
    render(<EntityPanel entityId="ent-001" />);
    await waitFor(() => screen.getAllByTestId("view-evidence-button"));

    const [firstButton] = screen.getAllByTestId("view-evidence-button");
    fireEvent.click(firstButton); // expand
    fireEvent.click(firstButton); // collapse

    expect(screen.queryByTestId("evidence-panel")).not.toBeInTheDocument();
  });

  it("expanded EvidencePanel shows the relationship's evidence items", async () => {
    render(<EntityPanel entityId="ent-001" />);
    await waitFor(() => screen.getAllByTestId("view-evidence-button"));

    fireEvent.click(screen.getAllByTestId("view-evidence-button")[0]);

    // rel-001 has EVIDENCE_2 (CDR snippet)
    expect(screen.getByText(/17 calls between/)).toBeInTheDocument();
  });
});

describe("EntityPanel — error state", () => {
  it("shows error message when entity fetch fails", async () => {
    vi.mocked(apiClient.getEntity).mockRejectedValue(new Error("Network error"));
    vi.mocked(apiClient.getEntityRelationships).mockResolvedValue({ relationships: [] });

    render(<EntityPanel entityId="ent-999" />);
    await waitFor(() => {
      expect(screen.getByText("Failed to load entity details.")).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// EvidencePanel tests
// ---------------------------------------------------------------------------

describe("EvidencePanel — pre-loaded evidence", () => {
  it("renders the evidence panel container", () => {
    render(<EvidencePanel evidence={[EVIDENCE_1]} />);
    expect(screen.getByTestId("evidence-panel")).toBeInTheDocument();
  });

  it("renders all pre-loaded evidence items", () => {
    render(<EvidencePanel evidence={[EVIDENCE_1, EVIDENCE_2]} />);
    const items = screen.getAllByTestId("evidence-item");
    expect(items.length).toBe(2);
  });

  it("renders evidence source type and snippet", () => {
    render(<EvidencePanel evidence={[EVIDENCE_1]} />);
    expect(screen.getByText("FIR")).toBeInTheDocument();
    expect(screen.getByText(/Rahul Sharma was named/)).toBeInTheDocument();
  });

  it("renders 'No evidence records found' when evidence array is empty", () => {
    render(<EvidencePanel evidence={[]} />);
    expect(screen.getByText(/No evidence records found/)).toBeInTheDocument();
  });

  it("calls onClose when close button is clicked", () => {
    const onClose = vi.fn();
    render(<EvidencePanel evidence={[EVIDENCE_1]} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText("Close evidence panel"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("EvidencePanel — fetched via §12.7", () => {
  beforeEach(() => {
    vi.mocked(apiClient.getEvidence).mockResolvedValue({ evidence: [EVIDENCE_2] });
  });

  it("fetches and renders evidence when given a relationshipId", async () => {
    render(<EvidencePanel relationshipId="rel-001" />);
    await waitFor(() => {
      expect(screen.getByTestId("evidence-list")).toBeInTheDocument();
      expect(screen.getByText(/17 calls between/)).toBeInTheDocument();
    });
    expect(apiClient.getEvidence).toHaveBeenCalledWith({
      relationship_id: "rel-001",
      finding_id: undefined,
    });
  });

  it("fetches and renders evidence when given a findingId", async () => {
    render(<EvidencePanel findingId="find-001" />);
    await waitFor(() => {
      expect(screen.getByTestId("evidence-list")).toBeInTheDocument();
    });
    expect(apiClient.getEvidence).toHaveBeenCalledWith({
      relationship_id: undefined,
      finding_id: "find-001",
    });
  });

  it("shows error message when fetch fails", async () => {
    vi.mocked(apiClient.getEvidence).mockRejectedValue(new Error("Network error"));
    render(<EvidencePanel relationshipId="rel-bad" />);
    await waitFor(() => {
      expect(screen.getByText("Failed to load evidence.")).toBeInTheDocument();
    });
  });
});
