/**
 * tests/E7.test.tsx — E7 component tests (E7.md §13)
 *
 * Acceptance criteria (E7.md §12):
 *   AC1: Case creation, association, notes, and summary all function correctly.
 *   AC2: A forced dataset-isolation violation is visibly reported, not hidden.
 *
 * Tests required (E7.md §13):
 *   - Full case-building flow (create, add entity, add relationship, add note)
 *   - CaseSummaryResult "ok" state
 *   - CaseSummaryResult "llm_unavailable" state (must be distinct, labelled)
 *   - dataset_isolation_violation error visible (must use dedicated banner)
 *
 * DOC3 §15 Contract Invariant 11:
 *   Every entity/edge/evidence added to a case must share the case's dataset.
 *   Violations are rejected with dataset_isolation_violation — never silently
 *   swallowed. The component must surface this with a distinct UI element.
 *
 * DOC3 §11:
 *   CaseSummaryResult "llm_unavailable" must be displayed distinctly — never
 *   disguised as an empty or generic response.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock api-client — declared before component imports
// ---------------------------------------------------------------------------

vi.mock("../lib/api-client", () => ({
  isMockMode: vi.fn(() => true),
  createCase: vi.fn(),
  getCase: vi.fn(),
  addCaseEntity: vi.fn(),
  addCaseRelationship: vi.fn(),
  addCaseNote: vi.fn(),
  getCaseSummary: vi.fn(),
}));

import CaseWorkspace from "../components/CaseWorkspace/CaseWorkspace";
import * as apiClient from "../lib/api-client";
import type { Case, CanonicalEntity, EdgeRef, Evidence, Note, CaseSummaryResult } from "../lib/types";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MOCK_CASE: Case = {
  case_id: "case-001",
  title: "Operation Apex",
  status: "open",
  dataset: "synthetic_demo",
  created_at: "2024-01-10T10:00:00Z",
  updated_at: "2024-01-10T10:00:00Z",
};

const MOCK_ENTITY: CanonicalEntity = {
  entity_id: "ent-001",
  entity_type: "Person",
  dataset: "synthetic_demo",
  display_name: "Rahul Sharma",
  attributes: {},
  resolved_from: ["m-001"],
  resolution_method: "fuzzy_match",
  created_at: "2024-01-10T08:00:00Z",
  updated_at: "2024-01-10T08:00:00Z",
};

const MOCK_EDGE_REF: EdgeRef = {
  edge_ref_id: "eref-001",
  relationship_id: "rel-001",
  from_entity_id: "ent-001",
  to_entity_id: "ent-003",
  relationship_type: "CALLED",
  created_at: "2024-01-10T08:00:00Z",
};

const MOCK_EVIDENCE: Evidence = {
  evidence_id: "ev-001",
  dataset: "synthetic_demo",
  source_id: "fir_001",
  source_type: "FIR",
  record_timestamp: "2024-01-05T14:30:00Z",
  ingested_at: "2024-01-10T08:00:00Z",
  snippet: "Rahul Sharma was named in FIR #2024/001.",
  pointer: null,
};

const MOCK_NOTE: Note = {
  note_id: "note-001",
  case_id: "case-001",
  text: "Rahul Sharma is the central node.",
  about_entity_id: "ent-001",
  about_edge_ref_id: null,
  about_evidence_id: null,
  created_at: "2024-01-10T10:05:00Z",
};

/** The baseline case detail returned by getCase (empty associations) */
const EMPTY_CASE_DETAIL = {
  case: MOCK_CASE,
  entities: [],
  edge_refs: [],
  evidence: [],
  notes: [],
};

/** A populated case detail */
const POPULATED_CASE_DETAIL = {
  case: MOCK_CASE,
  entities: [MOCK_ENTITY],
  edge_refs: [MOCK_EDGE_REF],
  evidence: [MOCK_EVIDENCE],
  notes: [MOCK_NOTE],
};

const SUMMARY_OK: CaseSummaryResult = {
  status: "ok",
  summary:
    "Rahul Sharma connects the communication and financial sub-networks.",
  generated_at: "2024-01-10T10:10:00Z",
};

const SUMMARY_LLM_UNAVAILABLE: CaseSummaryResult = {
  status: "llm_unavailable",
  message: "The AI assistant is temporarily unavailable.",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Creates standard mocks for a fresh case with no associations */
function setupEmptyCase() {
  vi.mocked(apiClient.createCase).mockResolvedValue(MOCK_CASE);
  vi.mocked(apiClient.getCase).mockResolvedValue(EMPTY_CASE_DETAIL);
  vi.mocked(apiClient.addCaseEntity).mockResolvedValue(undefined);
  vi.mocked(apiClient.addCaseRelationship).mockResolvedValue(MOCK_EDGE_REF);
  vi.mocked(apiClient.addCaseNote).mockResolvedValue(MOCK_NOTE);
}

/** Helper: render, fill title, click Create Case, wait for active case view */
async function renderAndCreate(props = {}) {
  render(<CaseWorkspace dataset="synthetic_demo" {...props} />);
  fireEvent.change(screen.getByTestId("case-title-input"), {
    target: { value: "Operation Apex" },
  });
  fireEvent.click(screen.getByTestId("create-case-button"));
  await waitFor(() =>
    expect(screen.getByTestId("active-case-view")).toBeInTheDocument()
  );
}

// ---------------------------------------------------------------------------
// CaseWorkspace — initial render
// ---------------------------------------------------------------------------

describe("CaseWorkspace — render", () => {
  it("renders the component container", () => {
    render(<CaseWorkspace />);
    expect(screen.getByTestId("case-workspace")).toBeInTheDocument();
  });

  it("shows the create case form when no case is active", () => {
    render(<CaseWorkspace />);
    expect(screen.getByTestId("create-case-form")).toBeInTheDocument();
  });

  it("create button is disabled when title is empty", () => {
    render(<CaseWorkspace />);
    expect(screen.getByTestId("create-case-button")).toBeDisabled();
  });

  it("create button is enabled when title is entered", () => {
    render(<CaseWorkspace />);
    fireEvent.change(screen.getByTestId("case-title-input"), {
      target: { value: "My Case" },
    });
    expect(screen.getByTestId("create-case-button")).not.toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// AC1a — Case creation flow
// ---------------------------------------------------------------------------

describe("CaseWorkspace — case creation (AC1)", () => {
  beforeEach(() => {
    setupEmptyCase();
  });

  it("calls createCase with correct title and dataset", async () => {
    await renderAndCreate();
    expect(apiClient.createCase).toHaveBeenCalledWith(
      "Operation Apex",
      "synthetic_demo"
    );
  });

  it("shows the active case view after creation", async () => {
    await renderAndCreate();
    expect(screen.getByTestId("active-case-view")).toBeInTheDocument();
  });

  it("shows the case title after creation", async () => {
    await renderAndCreate();
    expect(screen.getByTestId("case-title")).toHaveTextContent("Operation Apex");
  });

  it("hides the create form after creation", async () => {
    await renderAndCreate();
    expect(screen.queryByTestId("create-case-form")).not.toBeInTheDocument();
  });

  it("shows empty entity list after creation", async () => {
    await renderAndCreate();
    expect(screen.queryByTestId("case-entities-list")).not.toBeInTheDocument();
    expect(screen.getByText(/No entities added yet/i)).toBeInTheDocument();
  });

  it("shows empty notes list after creation", async () => {
    await renderAndCreate();
    expect(screen.queryByTestId("case-notes-list")).not.toBeInTheDocument();
    expect(screen.getByText(/No notes yet/i)).toBeInTheDocument();
  });

  it("closes the case when close button is clicked", async () => {
    await renderAndCreate();
    fireEvent.click(screen.getByTestId("close-case-button"));
    expect(screen.getByTestId("create-case-form")).toBeInTheDocument();
    expect(screen.queryByTestId("active-case-view")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// AC1b — Add entity to case
// ---------------------------------------------------------------------------

describe("CaseWorkspace — add entity (AC1)", () => {
  beforeEach(() => {
    setupEmptyCase();
  });

  it("shows add-entity button when selectedEntityId is provided", async () => {
    await renderAndCreate({ selectedEntityId: "ent-001" });
    expect(screen.getByTestId("add-entity-button")).toBeInTheDocument();
  });

  it("calls addCaseEntity with correct args when button is clicked", async () => {
    // After adding entity, getCase returns populated detail
    vi.mocked(apiClient.getCase)
      .mockResolvedValueOnce(EMPTY_CASE_DETAIL) // initial after createCase
      .mockResolvedValueOnce(POPULATED_CASE_DETAIL); // after addCaseEntity

    await renderAndCreate({ selectedEntityId: "ent-001" });
    fireEvent.click(screen.getByTestId("add-entity-button"));

    await waitFor(() => {
      expect(apiClient.addCaseEntity).toHaveBeenCalledWith(
        "case-001",
        "ent-001"
      );
    });
  });

  it("shows the entity in the list after it is added", async () => {
    vi.mocked(apiClient.getCase)
      .mockResolvedValueOnce(EMPTY_CASE_DETAIL)
      .mockResolvedValueOnce(POPULATED_CASE_DETAIL);

    await renderAndCreate({ selectedEntityId: "ent-001" });
    fireEvent.click(screen.getByTestId("add-entity-button"));

    await waitFor(() => {
      expect(screen.getByTestId("case-entities-list")).toBeInTheDocument();
      expect(screen.getByTestId("case-entity-item")).toHaveTextContent(
        "Rahul Sharma"
      );
    });
  });
});

// ---------------------------------------------------------------------------
// AC1c — Add relationship to case
// ---------------------------------------------------------------------------

describe("CaseWorkspace — add relationship (AC1)", () => {
  beforeEach(() => {
    setupEmptyCase();
  });

  it("shows add-relationship button when selectedRelationshipId is provided", async () => {
    await renderAndCreate({ selectedRelationshipId: "rel-001" });
    expect(screen.getByTestId("add-relationship-button")).toBeInTheDocument();
  });

  it("calls addCaseRelationship with correct args when button is clicked", async () => {
    vi.mocked(apiClient.getCase)
      .mockResolvedValueOnce(EMPTY_CASE_DETAIL)
      .mockResolvedValueOnce(POPULATED_CASE_DETAIL);

    await renderAndCreate({ selectedRelationshipId: "rel-001" });
    fireEvent.click(screen.getByTestId("add-relationship-button"));

    await waitFor(() => {
      expect(apiClient.addCaseRelationship).toHaveBeenCalledWith(
        "case-001",
        "rel-001"
      );
    });
  });

  it("shows the edge ref in the list after relationship is added", async () => {
    vi.mocked(apiClient.getCase)
      .mockResolvedValueOnce(EMPTY_CASE_DETAIL)
      .mockResolvedValueOnce(POPULATED_CASE_DETAIL);

    await renderAndCreate({ selectedRelationshipId: "rel-001" });
    fireEvent.click(screen.getByTestId("add-relationship-button"));

    await waitFor(() => {
      expect(screen.getByTestId("case-edge-refs-list")).toBeInTheDocument();
      expect(screen.getByTestId("case-edge-ref-item")).toHaveTextContent("CALLED");
    });
  });
});

// ---------------------------------------------------------------------------
// AC1d — Add note to case
// ---------------------------------------------------------------------------

describe("CaseWorkspace — add note (AC1)", () => {
  beforeEach(() => {
    setupEmptyCase();
  });

  it("shows the add note form when a case is active", async () => {
    await renderAndCreate();
    expect(screen.getByTestId("add-note-form")).toBeInTheDocument();
  });

  it("add-note button is disabled when note input is empty", async () => {
    await renderAndCreate();
    expect(screen.getByTestId("add-note-button")).toBeDisabled();
  });

  it("calls addCaseNote with correct args when note is submitted", async () => {
    vi.mocked(apiClient.getCase)
      .mockResolvedValueOnce(EMPTY_CASE_DETAIL)
      .mockResolvedValueOnce({
        ...EMPTY_CASE_DETAIL,
        notes: [MOCK_NOTE],
      });

    await renderAndCreate();
    fireEvent.change(screen.getByTestId("case-note-input"), {
      target: { value: "Rahul Sharma is the central node." },
    });
    fireEvent.click(screen.getByTestId("add-note-button"));

    await waitFor(() => {
      expect(apiClient.addCaseNote).toHaveBeenCalledWith(
        "case-001",
        "Rahul Sharma is the central node."
      );
    });
  });

  it("shows the note in the list after it is added", async () => {
    vi.mocked(apiClient.getCase)
      .mockResolvedValueOnce(EMPTY_CASE_DETAIL)
      .mockResolvedValueOnce({ ...EMPTY_CASE_DETAIL, notes: [MOCK_NOTE] });

    await renderAndCreate();
    fireEvent.change(screen.getByTestId("case-note-input"), {
      target: { value: "Rahul Sharma is the central node." },
    });
    fireEvent.click(screen.getByTestId("add-note-button"));

    await waitFor(() => {
      expect(screen.getByTestId("case-notes-list")).toBeInTheDocument();
      expect(screen.getByTestId("case-note-item")).toHaveTextContent(
        "Rahul Sharma is the central node."
      );
    });
  });

  it("clears the note input after successful submission", async () => {
    vi.mocked(apiClient.getCase)
      .mockResolvedValueOnce(EMPTY_CASE_DETAIL)
      .mockResolvedValueOnce({ ...EMPTY_CASE_DETAIL, notes: [MOCK_NOTE] });

    await renderAndCreate();
    fireEvent.change(screen.getByTestId("case-note-input"), {
      target: { value: "Some note" },
    });
    fireEvent.click(screen.getByTestId("add-note-button"));

    await waitFor(() => {
      expect(screen.getByTestId("case-note-input")).toHaveValue("");
    });
  });
});

// ---------------------------------------------------------------------------
// AC1e — Summary generation — "ok" variant
// ---------------------------------------------------------------------------

describe("CaseWorkspace — summary \"ok\" (AC1, DOC3 §11)", () => {
  beforeEach(() => {
    setupEmptyCase();
    vi.mocked(apiClient.getCaseSummary).mockResolvedValue(SUMMARY_OK);
  });

  it("shows the generate summary button when a case is active", async () => {
    await renderAndCreate();
    expect(screen.getByTestId("generate-summary-button")).toBeInTheDocument();
  });

  it("calls getCaseSummary with the correct case_id", async () => {
    await renderAndCreate();
    fireEvent.click(screen.getByTestId("generate-summary-button"));
    await waitFor(() => {
      expect(apiClient.getCaseSummary).toHaveBeenCalledWith("case-001");
    });
  });

  it("renders the ok summary container", async () => {
    await renderAndCreate();
    fireEvent.click(screen.getByTestId("generate-summary-button"));
    await waitFor(() => {
      expect(screen.getByTestId("case-summary-ok")).toBeInTheDocument();
    });
  });

  it("renders the summary text", async () => {
    await renderAndCreate();
    fireEvent.click(screen.getByTestId("generate-summary-button"));
    await waitFor(() => {
      expect(screen.getByTestId("case-summary-text")).toHaveTextContent(
        "Rahul Sharma connects"
      );
    });
  });

  it("ok summary does NOT render the llm_unavailable container", async () => {
    await renderAndCreate();
    fireEvent.click(screen.getByTestId("generate-summary-button"));
    await waitFor(() => screen.getByTestId("case-summary-ok"));
    expect(
      screen.queryByTestId("case-summary-llm-unavailable")
    ).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// AC1f — Summary generation — "llm_unavailable" variant (DOC3 §11)
// ---------------------------------------------------------------------------

describe("CaseWorkspace — summary \"llm_unavailable\" (AC1, DOC3 §11)", () => {
  beforeEach(() => {
    setupEmptyCase();
    vi.mocked(apiClient.getCaseSummary).mockResolvedValue(SUMMARY_LLM_UNAVAILABLE);
  });

  it("renders the llm_unavailable summary container", async () => {
    await renderAndCreate();
    fireEvent.click(screen.getByTestId("generate-summary-button"));
    await waitFor(() => {
      expect(
        screen.getByTestId("case-summary-llm-unavailable")
      ).toBeInTheDocument();
    });
  });

  it("shows 'AI Assistant Unavailable' heading — must be labelled (DOC3 §11)", async () => {
    await renderAndCreate();
    fireEvent.click(screen.getByTestId("generate-summary-button"));
    await waitFor(() => {
      expect(screen.getByText(/AI Assistant Unavailable/i)).toBeInTheDocument();
    });
  });

  it("shows the unavailability message from the response", async () => {
    await renderAndCreate();
    fireEvent.click(screen.getByTestId("generate-summary-button"));
    await waitFor(() => {
      expect(screen.getByText(/temporarily unavailable/i)).toBeInTheDocument();
    });
  });

  it("llm_unavailable uses role=alert", async () => {
    await renderAndCreate();
    fireEvent.click(screen.getByTestId("generate-summary-button"));
    await waitFor(() => {
      const el = screen.getByTestId("case-summary-llm-unavailable");
      expect(el).toHaveAttribute("role", "alert");
    });
  });

  it("does NOT render the ok summary container", async () => {
    await renderAndCreate();
    fireEvent.click(screen.getByTestId("generate-summary-button"));
    await waitFor(() => screen.getByTestId("case-summary-llm-unavailable"));
    expect(screen.queryByTestId("case-summary-ok")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// AC2 — dataset_isolation_violation — must be surfaced clearly, not hidden
// ---------------------------------------------------------------------------

describe("CaseWorkspace — dataset_isolation_violation (AC2, DOC3 Invariant 11)", () => {
  beforeEach(() => {
    setupEmptyCase();
  });

  it("shows the isolation violation banner when addCaseEntity returns isolation error", async () => {
    const isolationError = Object.assign(
      new Error("Dataset isolation violation"),
      {
        errorBody: {
          error: {
            type: "dataset_isolation_violation",
            message:
              "Entity ent-live-001 belongs to dataset live_public but case case-001 uses synthetic_demo.",
          },
        },
      }
    );
    vi.mocked(apiClient.addCaseEntity).mockRejectedValue(isolationError);

    await renderAndCreate({ selectedEntityId: "ent-live-001" });
    fireEvent.click(screen.getByTestId("add-entity-button"));

    await waitFor(() => {
      expect(
        screen.getByTestId("case-isolation-violation-banner")
      ).toBeInTheDocument();
    });
  });

  it("isolation violation banner has role=alert", async () => {
    const isolationError = Object.assign(
      new Error("Dataset isolation violation"),
      {
        errorBody: {
          error: {
            type: "dataset_isolation_violation",
            message: "Cross-dataset association rejected.",
          },
        },
      }
    );
    vi.mocked(apiClient.addCaseEntity).mockRejectedValue(isolationError);

    await renderAndCreate({ selectedEntityId: "ent-live-001" });
    fireEvent.click(screen.getByTestId("add-entity-button"));

    await waitFor(() => {
      const el = screen.getByTestId("case-isolation-violation-banner");
      expect(el).toHaveAttribute("role", "alert");
    });
  });

  it("shows 'Dataset Isolation Violation' heading explicitly (AC2 — must NOT be hidden)", async () => {
    const isolationError = Object.assign(
      new Error("Dataset isolation violation"),
      {
        errorBody: {
          error: {
            type: "dataset_isolation_violation",
            message: "Cross-dataset association rejected.",
          },
        },
      }
    );
    vi.mocked(apiClient.addCaseEntity).mockRejectedValue(isolationError);

    await renderAndCreate({ selectedEntityId: "ent-live-001" });
    fireEvent.click(screen.getByTestId("add-entity-button"));

    await waitFor(() => {
      expect(
        screen.getByText(/Dataset Isolation Violation/i)
      ).toBeInTheDocument();
    });
  });

  it("isolation violation uses a different banner than generic errors (AC2)", async () => {
    const isolationError = Object.assign(
      new Error("Dataset isolation violation"),
      {
        errorBody: {
          error: {
            type: "dataset_isolation_violation",
            message: "Cross-dataset association rejected.",
          },
        },
      }
    );
    vi.mocked(apiClient.addCaseEntity).mockRejectedValue(isolationError);

    await renderAndCreate({ selectedEntityId: "ent-live-001" });
    fireEvent.click(screen.getByTestId("add-entity-button"));

    await waitFor(() =>
      screen.getByTestId("case-isolation-violation-banner")
    );
    // Generic error banner must NOT appear alongside the isolation banner
    expect(screen.queryByTestId("case-error-banner")).not.toBeInTheDocument();
  });

  it("shows generic error banner for non-isolation errors", async () => {
    vi.mocked(apiClient.addCaseEntity).mockRejectedValue(
      new Error("Graph unavailable")
    );

    await renderAndCreate({ selectedEntityId: "ent-001" });
    fireEvent.click(screen.getByTestId("add-entity-button"));

    await waitFor(() => {
      expect(screen.getByTestId("case-error-banner")).toBeInTheDocument();
      expect(screen.getByTestId("case-error-banner")).toHaveTextContent(
        "Graph unavailable"
      );
    });
    expect(
      screen.queryByTestId("case-isolation-violation-banner")
    ).not.toBeInTheDocument();
  });

  it("isolation violation during addCaseRelationship is also surfaced (AC2)", async () => {
    const isolationError = Object.assign(
      new Error("Dataset isolation violation"),
      {
        errorBody: {
          error: {
            type: "dataset_isolation_violation",
            message: "Relationship dataset mismatch.",
          },
        },
      }
    );
    vi.mocked(apiClient.addCaseRelationship).mockRejectedValue(isolationError);

    await renderAndCreate({ selectedRelationshipId: "rel-live-001" });
    fireEvent.click(screen.getByTestId("add-relationship-button"));

    await waitFor(() => {
      expect(
        screen.getByTestId("case-isolation-violation-banner")
      ).toBeInTheDocument();
    });
  });

  it("createCase error shows generic error banner", async () => {
    vi.mocked(apiClient.createCase).mockRejectedValue(
      new Error("Server error")
    );
    render(<CaseWorkspace dataset="synthetic_demo" />);
    fireEvent.change(screen.getByTestId("case-title-input"), {
      target: { value: "My Case" },
    });
    fireEvent.click(screen.getByTestId("create-case-button"));
    await waitFor(() => {
      expect(screen.getByTestId("case-error-banner")).toBeInTheDocument();
    });
    expect(screen.getByTestId("create-case-form")).toBeInTheDocument();
  });
});
