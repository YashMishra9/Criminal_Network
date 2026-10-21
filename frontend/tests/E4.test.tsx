/**
 * tests/E4.test.tsx — E4 component tests (E4.md §13)
 *
 * Acceptance criteria (E4.md §12):
 *   AC1: The disclaimer is always visible alongside every rendered Finding.
 *   AC2: Moving the timeline slider correctly re-queries with the new as_of value.
 *
 * Additional tests:
 *   - Timeline renders with correct bounds derived from relationship valid_from
 *   - Timeline label reflects current asOf (or "full current graph" when null)
 *   - Timeline calls onAsOfChange with null when slider is at max position
 *   - Timeline reset button calls onAsOfChange(null)
 *   - AnalyticsPanel renders centrality and community data
 *   - AnalyticsPanel renders findings with disclaimer unconditionally
 *   - AnalyticsPanel re-fetches when asOf prop changes (AC2)
 *   - AnalyticsPanel evidence affordance present for every finding (DOC3 §9.4)
 *   - AnalyticsPanel shows EvidencePanel on click, hides on second click
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type {
  Relationship,
  Finding,
  AnalyticsResult,
  Evidence,
} from "../lib/types";

// ---------------------------------------------------------------------------
// Mock api-client — must be declared before component imports
// ---------------------------------------------------------------------------

vi.mock("../lib/api-client", () => ({
  isMockMode: vi.fn(() => true),
  getAnalytics: vi.fn(),
  getPatterns: vi.fn(),
  getEvidence: vi.fn(),
}));

import Timeline from "../components/Timeline/Timeline";
import AnalyticsPanel from "../components/AnalyticsPanel/AnalyticsPanel";
import * as apiClient from "../lib/api-client";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const RELATIONSHIPS: Relationship[] = [
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
  {
    relationship_id: "rel-002",
    relationship_type: "OWNS",
    from_entity_id: "ent-001",
    to_entity_id: "ent-004",
    dataset: "synthetic_demo",
    attributes: {},
    valid_from: "2024-01-07T16:00:00Z",
    valid_to: null,
    evidence_ids: ["ev-001"],
    created_at: "2024-01-10T08:00:00Z",
    updated_at: "2024-01-10T08:00:00Z",
  },
];

const FINDING_1: Finding = {
  finding_id: "find-001",
  dataset: "synthetic_demo",
  rule_id: "frequency_rule_v1",
  rule_name: "High-Frequency Communication",
  subject_entity_ids: ["ent-001", "ent-003"],
  subject_relationship_ids: ["rel-001"],
  explanation:
    "17 calls between these two numbers over 4 days, exceeding the 10-call/7-day threshold.",
  triggering_values: { call_count: 17, threshold: 10 },
  evidence_ids: ["ev-002"],
  disclaimer: "This is an investigative lead, not evidence of wrongdoing.",
  detected_at: "2024-01-10T09:00:00Z",
};

const FINDING_2: Finding = {
  finding_id: "find-002",
  dataset: "synthetic_demo",
  rule_id: "bridge_entity_v1",
  rule_name: "Bridge Entity",
  subject_entity_ids: ["ent-001"],
  subject_relationship_ids: [],
  explanation:
    "Rahul Sharma connects 3 otherwise-disconnected network components.",
  triggering_values: { betweenness: 0.74, threshold: 0.5 },
  evidence_ids: ["ev-001"],
  disclaimer: "This is an investigative lead, not evidence of wrongdoing.",
  detected_at: "2024-01-10T09:00:00Z",
};

const ANALYTICS: AnalyticsResult = {
  computed_at: "2024-01-10T09:00:00Z",
  dataset: "synthetic_demo",
  as_of: null,
  centrality: [
    { entity_id: "ent-001", degree: 4, betweenness: 0.74, pagerank: 0.31 },
    { entity_id: "ent-002", degree: 2, betweenness: 0.12, pagerank: 0.18 },
  ],
  communities: [
    { entity_id: "ent-001", community_id: "comm-A" },
    { entity_id: "ent-003", community_id: "comm-A" },
    { entity_id: "ent-002", community_id: "comm-B" },
  ],
};

const EVIDENCE: Evidence = {
  evidence_id: "ev-002",
  dataset: "synthetic_demo",
  source_id: "cdr_001",
  source_type: "CDR",
  record_timestamp: "2024-01-06T10:15:00Z",
  ingested_at: "2024-01-10T08:00:00Z",
  snippet: "17 calls between +919876543210 and +919812345678 over 4 days.",
  pointer: null,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function setupAnalyticsMocks(findings = [FINDING_1, FINDING_2]) {
  vi.mocked(apiClient.getAnalytics).mockResolvedValue(ANALYTICS);
  vi.mocked(apiClient.getPatterns).mockResolvedValue({ findings });
  vi.mocked(apiClient.getEvidence).mockResolvedValue({ evidence: [EVIDENCE] });
}

// ---------------------------------------------------------------------------
// Timeline tests
// ---------------------------------------------------------------------------

describe("Timeline — render", () => {
  it("renders the timeline container", () => {
    const onChange = vi.fn();
    render(
      <Timeline relationships={RELATIONSHIPS} asOf={null} onAsOfChange={onChange} />
    );
    expect(screen.getByTestId("timeline")).toBeInTheDocument();
  });

  it("renders the slider", () => {
    const onChange = vi.fn();
    render(
      <Timeline relationships={RELATIONSHIPS} asOf={null} onAsOfChange={onChange} />
    );
    expect(screen.getByTestId("timeline-slider")).toBeInTheDocument();
  });

  it("shows 'full current graph' label when asOf is null", () => {
    const onChange = vi.fn();
    render(
      <Timeline relationships={RELATIONSHIPS} asOf={null} onAsOfChange={onChange} />
    );
    expect(screen.getByTestId("timeline-label")).toHaveTextContent(
      "Showing full current graph"
    );
  });

  it("shows as_of date in label when asOf is set", () => {
    const onChange = vi.fn();
    render(
      <Timeline
        relationships={RELATIONSHIPS}
        asOf="2024-01-06T23:59:59Z"
        onAsOfChange={onChange}
      />
    );
    expect(screen.getByTestId("timeline-label")).toHaveTextContent("2024-01-06");
  });

  it("renders date bounds from relationship valid_from values", () => {
    const onChange = vi.fn();
    render(
      <Timeline relationships={RELATIONSHIPS} asOf={null} onAsOfChange={onChange} />
    );
    // minDate = 2024-01-06, maxDate = 2024-01-07
    expect(screen.getByText("2024-01-06")).toBeInTheDocument();
    expect(screen.getByText("2024-01-07")).toBeInTheDocument();
  });

  it("disables the slider when loading=true", () => {
    const onChange = vi.fn();
    render(
      <Timeline
        relationships={RELATIONSHIPS}
        asOf={null}
        onAsOfChange={onChange}
        loading={true}
      />
    );
    expect(screen.getByTestId("timeline-slider")).toBeDisabled();
  });

  it("disables the slider when relationships is empty", () => {
    const onChange = vi.fn();
    render(
      <Timeline relationships={[]} asOf={null} onAsOfChange={onChange} />
    );
    expect(screen.getByTestId("timeline-slider")).toBeDisabled();
  });

  it("shows Reset button when asOf is set", () => {
    const onChange = vi.fn();
    render(
      <Timeline
        relationships={RELATIONSHIPS}
        asOf="2024-01-06T23:59:59Z"
        onAsOfChange={onChange}
      />
    );
    expect(screen.getByTestId("timeline-reset")).toBeInTheDocument();
  });

  it("does not show Reset button when asOf is null", () => {
    const onChange = vi.fn();
    render(
      <Timeline relationships={RELATIONSHIPS} asOf={null} onAsOfChange={onChange} />
    );
    expect(screen.queryByTestId("timeline-reset")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Timeline — AC2: slider changes drive as_of re-querying
// ---------------------------------------------------------------------------

describe("Timeline — AC2: as_of-driven re-querying", () => {
  it("calls onAsOfChange with null when slider is dragged to max position", () => {
    const onChange = vi.fn();
    render(
      <Timeline
        relationships={RELATIONSHIPS}
        asOf="2024-01-06T23:59:59Z"
        onAsOfChange={onChange}
      />
    );
    const slider = screen.getByTestId("timeline-slider");
    // Simulate dragging to max (100)
    fireEvent.change(slider, { target: { value: "100" } });
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("calls onAsOfChange with an ISO-8601 string when slider moves away from max", () => {
    const onChange = vi.fn();
    render(
      <Timeline
        relationships={RELATIONSHIPS}
        asOf={null}
        onAsOfChange={onChange}
      />
    );
    const slider = screen.getByTestId("timeline-slider");
    fireEvent.change(slider, { target: { value: "0" } });
    // Should receive a date string (not null) starting with 2024
    expect(onChange).toHaveBeenCalledOnce();
    const called = onChange.mock.calls[0][0] as string;
    expect(called).toMatch(/^2024-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
  });

  it("Reset button calls onAsOfChange(null) — AC2", () => {
    const onChange = vi.fn();
    render(
      <Timeline
        relationships={RELATIONSHIPS}
        asOf="2024-01-06T23:59:59Z"
        onAsOfChange={onChange}
      />
    );
    fireEvent.click(screen.getByTestId("timeline-reset"));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});

// ---------------------------------------------------------------------------
// AnalyticsPanel tests
// ---------------------------------------------------------------------------

describe("AnalyticsPanel — render", () => {
  beforeEach(() => {
    setupAnalyticsMocks();
  });

  it("renders the analytics panel container", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      expect(screen.getByTestId("analytics-panel")).toBeInTheDocument();
    });
  });

  it("renders centrality section with data", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      expect(screen.getByTestId("centrality-section")).toBeInTheDocument();
      expect(screen.getAllByTestId("centrality-item").length).toBeGreaterThan(0);
    });
  });

  it("renders community section with community IDs", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      expect(screen.getByTestId("communities-section")).toBeInTheDocument();
      expect(screen.getAllByTestId("community-item").length).toBe(2);
    });
  });

  it("renders the findings section", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      expect(screen.getByTestId("findings-section")).toBeInTheDocument();
    });
  });

  it("renders all findings in the list", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      expect(screen.getAllByTestId("finding-item").length).toBe(2);
    });
  });
});

// ---------------------------------------------------------------------------
// AnalyticsPanel — AC1: disclaimer always visible alongside every Finding
// ---------------------------------------------------------------------------

describe("AnalyticsPanel — AC1: disclaimer always present", () => {
  beforeEach(() => {
    setupAnalyticsMocks();
  });

  it("every finding has its disclaimer rendered (Contract Invariant 5)", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      const items = screen.getAllByTestId("finding-item");
      expect(items.length).toBeGreaterThan(0);
      items.forEach((item) => {
        const disclaimer = item.querySelector(
          "[data-testid='finding-disclaimer']"
        );
        expect(disclaimer).not.toBeNull();
        expect(disclaimer?.textContent).toBe(
          "This is an investigative lead, not evidence of wrongdoing."
        );
      });
    });
  });

  it("disclaimer is the exact fixed literal from DOC3 §1.8", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      const disclaimers = screen.getAllByTestId("finding-disclaimer");
      disclaimers.forEach((el) => {
        expect(el.textContent).toBe(
          "This is an investigative lead, not evidence of wrongdoing."
        );
      });
    });
  });

  it("disclaimer count equals finding count (no finding without disclaimer)", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      const items = screen.getAllByTestId("finding-item");
      const disclaimers = screen.getAllByTestId("finding-disclaimer");
      expect(disclaimers.length).toBe(items.length);
    });
  });

  it("disclaimer is present even when only one finding is returned", async () => {
    vi.mocked(apiClient.getAnalytics).mockResolvedValue(ANALYTICS);
    vi.mocked(apiClient.getPatterns).mockResolvedValue({
      findings: [FINDING_1],
    });
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      const disclaimers = screen.getAllByTestId("finding-disclaimer");
      expect(disclaimers.length).toBe(1);
      expect(disclaimers[0].textContent).toBe(
        "This is an investigative lead, not evidence of wrongdoing."
      );
    });
  });

  it("renders finding explanation text", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      expect(
        screen.getByText(/17 calls between these two numbers/)
      ).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// AnalyticsPanel — AC2: as_of-driven re-querying
// ---------------------------------------------------------------------------

describe("AnalyticsPanel — AC2: re-queries with new as_of on prop change", () => {
  beforeEach(() => {
    setupAnalyticsMocks();
  });

  it("calls getAnalytics with as_of=null on initial render", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      expect(apiClient.getAnalytics).toHaveBeenCalledWith({
        dataset: "synthetic_demo",
        as_of: undefined,
      });
    });
  });

  it("calls getPatterns with as_of=null on initial render", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      expect(apiClient.getPatterns).toHaveBeenCalledWith({
        dataset: "synthetic_demo",
        as_of: undefined,
      });
    });
  });

  it("re-fetches analytics with new as_of when prop changes", async () => {
    const { rerender } = render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => screen.getByTestId("analytics-panel"));

    vi.mocked(apiClient.getAnalytics).mockClear();
    vi.mocked(apiClient.getPatterns).mockClear();

    rerender(<AnalyticsPanel asOf="2024-01-06T23:59:59Z" />);

    await waitFor(() => {
      expect(apiClient.getAnalytics).toHaveBeenCalledWith({
        dataset: "synthetic_demo",
        as_of: "2024-01-06T23:59:59Z",
      });
      expect(apiClient.getPatterns).toHaveBeenCalledWith({
        dataset: "synthetic_demo",
        as_of: "2024-01-06T23:59:59Z",
      });
    });
  });

  it("shows as_of badge when asOf is set", async () => {
    render(<AnalyticsPanel asOf="2024-01-06T23:59:59Z" />);
    await waitFor(() => {
      expect(screen.getByTestId("analytics-as-of-badge")).toBeInTheDocument();
      expect(screen.getByTestId("analytics-as-of-badge")).toHaveTextContent(
        "2024-01-06"
      );
    });
  });

  it("does not show as_of badge when asOf is null", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => screen.getByTestId("analytics-panel"));
    expect(screen.queryByTestId("analytics-as-of-badge")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// AnalyticsPanel — evidence affordance (DOC3 §9.4)
// ---------------------------------------------------------------------------

describe("AnalyticsPanel — evidence affordance (DOC3 §9.4)", () => {
  beforeEach(() => {
    setupAnalyticsMocks();
  });

  it("every finding has a 'view evidence' button", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      const buttons = screen.getAllByTestId("finding-view-evidence-button");
      expect(buttons.length).toBe(2);
    });
  });

  it("clicking 'view evidence' expands the EvidencePanel", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => screen.getAllByTestId("finding-view-evidence-button"));

    fireEvent.click(screen.getAllByTestId("finding-view-evidence-button")[0]);

    await waitFor(() => {
      expect(screen.getByTestId("evidence-panel")).toBeInTheDocument();
    });
  });

  it("clicking 'view evidence' again collapses the EvidencePanel", async () => {
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => screen.getAllByTestId("finding-view-evidence-button"));

    const [firstButton] = screen.getAllByTestId("finding-view-evidence-button");
    fireEvent.click(firstButton); // expand
    await waitFor(() => screen.getByTestId("evidence-panel"));
    fireEvent.click(firstButton); // collapse

    expect(screen.queryByTestId("evidence-panel")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// AnalyticsPanel — empty states
// ---------------------------------------------------------------------------

describe("AnalyticsPanel — empty states", () => {
  it("shows 'no flagged patterns' message when findings is empty", async () => {
    setupAnalyticsMocks([]); // empty findings
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      expect(
        screen.getByText(/No flagged patterns for this time window/)
      ).toBeInTheDocument();
    });
  });

  it("shows error when api calls fail", async () => {
    vi.mocked(apiClient.getAnalytics).mockRejectedValue(new Error("net error"));
    vi.mocked(apiClient.getPatterns).mockRejectedValue(new Error("net error"));
    render(<AnalyticsPanel asOf={null} />);
    await waitFor(() => {
      expect(
        screen.getByText("Failed to load analytics data.")
      ).toBeInTheDocument();
    });
  });
});
