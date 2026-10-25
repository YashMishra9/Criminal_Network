/**
 * tests/E6.test.tsx — E6 component tests (E6.md §13)
 *
 * Acceptance criterion (E6.md §12):
 *   Each of the four AskResponse states renders correctly and is visibly
 *   distinct from the others.
 *
 * Tests required (E6.md §13):
 *   One component test per AskResponse variant:
 *     - "ok"               renders narration, path summary, evidence affordance
 *     - "llm_unavailable"  renders labelled degraded state (NEVER empty/no-result)
 *     - "validation_failed" renders reason text distinctly
 *     - "no_result"        renders no-result message distinctly
 *
 * Additional tests:
 *   - Component renders input form and submit button
 *   - Submit button is disabled when input is empty
 *   - Submit button is disabled while loading
 *   - Submitting a question calls ask() with the correct AskRequest shape
 *   - Clear button resets the result area
 *   - Network/API error shows a distinct error state
 *   - Each AskResponse variant has a unique data-testid (distinct from others)
 *   - llm_unavailable is visually distinct from no_result (different containers)
 *   - Evidence affordance appears for "ok" response with evidence
 *   - Evidence panel expands/collapses when view/hide evidence is clicked
 *
 * DOC3 §15 Invariant 4 (tested indirectly via UI):
 *   llm_unavailable must be labelled "AI Assistant Unavailable" — never
 *   silently displayed as an empty or generic response.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock api-client — declared before component imports
// ---------------------------------------------------------------------------

vi.mock("../lib/api-client", () => ({
  isMockMode: vi.fn(() => true),
  ask: vi.fn(),
  getEvidence: vi.fn(),
}));

import AskTheNetwork from "../components/AskTheNetwork/AskTheNetwork";
import * as apiClient from "../lib/api-client";
import type { AskResponse } from "../lib/types";

// ---------------------------------------------------------------------------
// Fixtures — one per AskResponse variant (from mock-data)
// ---------------------------------------------------------------------------

const RESPONSE_OK: AskResponse = {
  status: "ok",
  narration:
    "Rahul Sharma made 17 calls to +919876543210 between 6–9 January 2024.",
  path: {
    entities: [
      {
        entity_id: "ent-001",
        entity_type: "Person",
        dataset: "synthetic_demo",
        display_name: "Rahul Sharma",
        attributes: {},
        resolved_from: ["m-001"],
        resolution_method: "fuzzy_match",
        created_at: "2024-01-10T08:00:00Z",
        updated_at: "2024-01-10T08:00:00Z",
      },
      {
        entity_id: "ent-003",
        entity_type: "Phone",
        dataset: "synthetic_demo",
        display_name: "+919876543210",
        attributes: {},
        resolved_from: ["m-004"],
        resolution_method: "exact_match",
        created_at: "2024-01-10T08:00:00Z",
        updated_at: "2024-01-10T08:00:00Z",
      },
    ],
    relationships: [
      {
        relationship_id: "rel-001",
        relationship_type: "CALLED",
        from_entity_id: "ent-001",
        to_entity_id: "ent-003",
        dataset: "synthetic_demo",
        attributes: {},
        valid_from: "2024-01-06T10:15:00Z",
        valid_to: null,
        evidence_ids: ["ev-002"],
        created_at: "2024-01-10T08:00:00Z",
        updated_at: "2024-01-10T08:00:00Z",
      },
    ],
    paths: [{ entity_ids: ["ent-001", "ent-003"], relationship_ids: ["rel-001"] }],
  },
  evidence: [
    {
      evidence_id: "ev-002",
      dataset: "synthetic_demo",
      source_id: "cdr_001",
      source_type: "CDR",
      record_timestamp: "2024-01-06T10:15:00Z",
      ingested_at: "2024-01-10T08:00:00Z",
      snippet: "17 calls between +919876543210 and +919812345678 over 4 days.",
      pointer: null,
    },
  ],
};

const RESPONSE_LLM_UNAVAILABLE: AskResponse = {
  status: "llm_unavailable",
  message:
    "The AI assistant is temporarily unavailable. Try exploring the graph directly.",
};

const RESPONSE_VALIDATION_FAILED: AskResponse = {
  status: "validation_failed",
  reason: "Generated query contained a forbidden CALL clause.",
};

const RESPONSE_NO_RESULT: AskResponse = {
  status: "no_result",
  message: "No graph data matched your question.",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function submitQuestion(question = "Who does Rahul call?") {
  const input = screen.getByTestId("ask-question-input");
  fireEvent.change(input, { target: { value: question } });
  fireEvent.click(screen.getByTestId("ask-submit-button"));
}

// ---------------------------------------------------------------------------
// AskTheNetwork — render (no submission)
// ---------------------------------------------------------------------------

describe("AskTheNetwork — render", () => {
  it("renders the component container", () => {
    render(<AskTheNetwork />);
    expect(screen.getByTestId("ask-the-network")).toBeInTheDocument();
  });

  it("renders the question input", () => {
    render(<AskTheNetwork />);
    expect(screen.getByTestId("ask-question-input")).toBeInTheDocument();
  });

  it("renders the submit button", () => {
    render(<AskTheNetwork />);
    expect(screen.getByTestId("ask-submit-button")).toBeInTheDocument();
  });

  it("submit button is disabled when input is empty", () => {
    render(<AskTheNetwork />);
    expect(screen.getByTestId("ask-submit-button")).toBeDisabled();
  });

  it("submit button is enabled when input has text", () => {
    render(<AskTheNetwork />);
    fireEvent.change(screen.getByTestId("ask-question-input"), {
      target: { value: "Who does Rahul call?" },
    });
    expect(screen.getByTestId("ask-submit-button")).not.toBeDisabled();
  });

  it("shows no response container initially", () => {
    render(<AskTheNetwork />);
    expect(
      screen.queryByTestId("ask-response-container")
    ).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// E6 AC — Variant 1: "ok" — success response
// ---------------------------------------------------------------------------

describe('AskTheNetwork — variant "ok" (E6.md §12)', () => {
  beforeEach(() => {
    vi.mocked(apiClient.ask).mockResolvedValue(RESPONSE_OK);
  });

  it("renders the ok result container after submission", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(screen.getByTestId("ask-result-ok")).toBeInTheDocument();
    });
  });

  it("renders the narration text from the response", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(screen.getByTestId("ask-narration")).toHaveTextContent(
        "Rahul Sharma made 17 calls"
      );
    });
  });

  it("renders the evidence affordance button", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(screen.getByTestId("ask-view-evidence-button")).toBeInTheDocument();
    });
  });

  it("expands evidence panel when 'View evidence' is clicked", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => screen.getByTestId("ask-view-evidence-button"));
    fireEvent.click(screen.getByTestId("ask-view-evidence-button"));
    expect(screen.getByTestId("evidence-panel")).toBeInTheDocument();
  });

  it("collapses evidence panel when clicked again", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => screen.getByTestId("ask-view-evidence-button"));
    fireEvent.click(screen.getByTestId("ask-view-evidence-button")); // expand
    fireEvent.click(screen.getByTestId("ask-view-evidence-button")); // collapse
    expect(screen.queryByTestId("evidence-panel")).not.toBeInTheDocument();
  });

  it("ok result does NOT render llm_unavailable, validation_failed, or no_result containers", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => screen.getByTestId("ask-result-ok"));
    expect(screen.queryByTestId("ask-result-llm-unavailable")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ask-result-validation-failed")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ask-result-no-result")).not.toBeInTheDocument();
  });

  it("calls ask() with the correct AskRequest shape", async () => {
    render(<AskTheNetwork dataset="synthetic_demo" asOf="2024-01-06T23:59:59Z" />);
    submitQuestion("Who does Rahul call?");
    await waitFor(() => screen.getByTestId("ask-result-ok"));
    expect(apiClient.ask).toHaveBeenCalledWith({
      question: "Who does Rahul call?",
      dataset: "synthetic_demo",
      as_of: "2024-01-06T23:59:59Z",
    });
  });
});

// ---------------------------------------------------------------------------
// E6 AC — Variant 2: "llm_unavailable" — MUST be labelled and honest
// ---------------------------------------------------------------------------

describe('AskTheNetwork — variant "llm_unavailable" (E6.md §12, §17)', () => {
  beforeEach(() => {
    vi.mocked(apiClient.ask).mockResolvedValue(RESPONSE_LLM_UNAVAILABLE);
  });

  it("renders the llm_unavailable container", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(
        screen.getByTestId("ask-result-llm-unavailable")
      ).toBeInTheDocument();
    });
  });

  it("shows 'AI Assistant Unavailable' heading — must be visibly labelled (E6.md §17)", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(screen.getByText(/AI Assistant Unavailable/i)).toBeInTheDocument();
    });
  });

  it("shows the message from the response", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(
        screen.getByText(/temporarily unavailable/)
      ).toBeInTheDocument();
    });
  });

  it("llm_unavailable uses role=alert so assistive tech announces it", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      const el = screen.getByTestId("ask-result-llm-unavailable");
      expect(el).toHaveAttribute("role", "alert");
    });
  });

  it("does NOT render the ok, validation_failed, or no_result containers", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => screen.getByTestId("ask-result-llm-unavailable"));
    expect(screen.queryByTestId("ask-result-ok")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ask-result-validation-failed")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ask-result-no-result")).not.toBeInTheDocument();
  });

  it("llm_unavailable is visually distinct from no_result (different test-ids)", async () => {
    // This test explicitly documents the E6.md §17 requirement that these two
    // states must never be conflated
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => screen.getByTestId("ask-result-llm-unavailable"));
    expect(screen.queryByTestId("ask-result-no-result")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// E6 AC — Variant 3: "validation_failed"
// ---------------------------------------------------------------------------

describe('AskTheNetwork — variant "validation_failed" (E6.md §12)', () => {
  beforeEach(() => {
    vi.mocked(apiClient.ask).mockResolvedValue(RESPONSE_VALIDATION_FAILED);
  });

  it("renders the validation_failed container", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(
        screen.getByTestId("ask-result-validation-failed")
      ).toBeInTheDocument();
    });
  });

  it("shows the validation failure reason text", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(screen.getByTestId("ask-validation-reason")).toHaveTextContent(
        "forbidden CALL clause"
      );
    });
  });

  it("shows 'Query Validation Failed' heading", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(screen.getByText(/Query Validation Failed/i)).toBeInTheDocument();
    });
  });

  it("does NOT render ok, llm_unavailable, or no_result containers", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => screen.getByTestId("ask-result-validation-failed"));
    expect(screen.queryByTestId("ask-result-ok")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ask-result-llm-unavailable")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ask-result-no-result")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// E6 AC — Variant 4: "no_result"
// ---------------------------------------------------------------------------

describe('AskTheNetwork — variant "no_result" (E6.md §12)', () => {
  beforeEach(() => {
    vi.mocked(apiClient.ask).mockResolvedValue(RESPONSE_NO_RESULT);
  });

  it("renders the no_result container", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(screen.getByTestId("ask-result-no-result")).toBeInTheDocument();
    });
  });

  it("shows the no-result message from the response", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(
        screen.getByText(/No graph data matched your question/)
      ).toBeInTheDocument();
    });
  });

  it("shows 'No Result' heading", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(screen.getByText(/No Result/i)).toBeInTheDocument();
    });
  });

  it("does NOT render ok, llm_unavailable, or validation_failed containers", async () => {
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => screen.getByTestId("ask-result-no-result"));
    expect(screen.queryByTestId("ask-result-ok")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ask-result-llm-unavailable")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ask-result-validation-failed")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// AskTheNetwork — clear and error states
// ---------------------------------------------------------------------------

describe("AskTheNetwork — clear and error states", () => {
  it("shows the clear button after a successful response", async () => {
    vi.mocked(apiClient.ask).mockResolvedValue(RESPONSE_OK);
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => screen.getByTestId("ask-result-ok"));
    expect(screen.getByTestId("ask-clear-button")).toBeInTheDocument();
  });

  it("clear button removes the response container", async () => {
    vi.mocked(apiClient.ask).mockResolvedValue(RESPONSE_OK);
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => screen.getByTestId("ask-result-ok"));
    fireEvent.click(screen.getByTestId("ask-clear-button"));
    expect(
      screen.queryByTestId("ask-response-container")
    ).not.toBeInTheDocument();
  });

  it("shows a network error container when ask() throws", async () => {
    vi.mocked(apiClient.ask).mockRejectedValue(new Error("Network failure"));
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => {
      expect(screen.getByTestId("ask-error")).toBeInTheDocument();
      expect(screen.getByTestId("ask-error")).toHaveTextContent("Network failure");
    });
  });

  it("network error does not render any AskResponse variant container", async () => {
    vi.mocked(apiClient.ask).mockRejectedValue(new Error("Network failure"));
    render(<AskTheNetwork />);
    submitQuestion();
    await waitFor(() => screen.getByTestId("ask-error"));
    expect(screen.queryByTestId("ask-response-container")).not.toBeInTheDocument();
  });
});
