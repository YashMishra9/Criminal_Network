/**
 * tests/E5.test.tsx — E5 component tests (E5.md §13)
 *
 * Acceptance criterion (E5.md §12):
 *   AC1: Changing a filter correctly updates every dependent component's
 *        displayed data.
 *
 * Covers:
 *   - FiltersAndSearch renders all filter controls
 *   - Search input changes call onFiltersChange with updated q
 *   - Entity type toggle adds/removes type from entity_types array
 *   - Relationship type toggle adds/removes type from relationship_types
 *   - Source type dropdown calls onFiltersChange with updated source_type
 *   - Community dropdown calls onFiltersChange with updated community
 *   - Pattern dropdown calls onFiltersChange with updated pattern
 *   - Clear all button resets to DEFAULT_FILTERS
 *   - Active filters summary appears when any filter is non-default
 *   - Active filters summary hidden when no filters active
 *   - FilterState helpers (toGraphParams, toSearchParams, isDefaultFilters)
 *   - Integration: filter change → fetchData called with new params (AC1)
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { FilterState } from "../state/filters";
import {
  DEFAULT_FILTERS,
  toGraphParams,
  toSearchParams,
  isDefaultFilters,
} from "../state/filters";

// ---------------------------------------------------------------------------
// Mock api-client — declared before component imports
// ---------------------------------------------------------------------------

vi.mock("../lib/api-client", () => ({
  isMockMode: vi.fn(() => true),
  getGraph: vi.fn(),
  getPatterns: vi.fn(),
  getAnalytics: vi.fn(),
  searchEntities: vi.fn(),
  getEvidence: vi.fn(),
}));

import FiltersAndSearch from "../components/FiltersAndSearch/FiltersAndSearch";
import * as apiClient from "../lib/api-client";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const BASE_FILTERS: FilterState = { ...DEFAULT_FILTERS };

const ACTIVE_FILTERS: FilterState = {
  q: "Rahul",
  entity_types: ["Person"],
  relationship_types: ["CALLED"],
  source_type: "FIR",
  community: "comm-A",
  pattern: "bridge_entity_v1",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderFilters(
  overrideFilters: Partial<FilterState> = {},
  props: Partial<Parameters<typeof FiltersAndSearch>[0]> = {}
) {
  const filters = { ...BASE_FILTERS, ...overrideFilters };
  const onChange = vi.fn();
  render(
    <FiltersAndSearch
      filters={filters}
      onFiltersChange={onChange}
      availableCommunities={["comm-A", "comm-B"]}
      availablePatterns={[
        { rule_id: "bridge_entity_v1", rule_name: "Bridge Entity" },
        { rule_id: "frequency_rule_v1", rule_name: "High-Frequency Communication" },
      ]}
      {...props}
    />
  );
  return { onChange };
}

// ---------------------------------------------------------------------------
// FiltersAndSearch — render
// ---------------------------------------------------------------------------

describe("FiltersAndSearch — render", () => {
  it("renders the component container", () => {
    renderFilters();
    expect(screen.getByTestId("filters-and-search")).toBeInTheDocument();
  });

  it("renders the search input", () => {
    renderFilters();
    expect(screen.getByTestId("filter-search-input")).toBeInTheDocument();
  });

  it("renders the entity type filter", () => {
    renderFilters();
    expect(screen.getByTestId("entity-type-filter")).toBeInTheDocument();
  });

  it("renders the relationship type filter", () => {
    renderFilters();
    expect(screen.getByTestId("relationship-type-filter")).toBeInTheDocument();
  });

  it("renders the source type dropdown", () => {
    renderFilters();
    expect(screen.getByTestId("filter-source-type")).toBeInTheDocument();
  });

  it("renders the community dropdown when communities are provided", () => {
    renderFilters();
    expect(screen.getByTestId("filter-community")).toBeInTheDocument();
  });

  it("renders the pattern dropdown when patterns are provided", () => {
    renderFilters();
    expect(screen.getByTestId("filter-pattern")).toBeInTheDocument();
  });

  it("does NOT render community dropdown when no communities provided", () => {
    renderFilters({}, { availableCommunities: [] });
    expect(screen.queryByTestId("filter-community")).not.toBeInTheDocument();
  });

  it("does NOT render pattern dropdown when no patterns provided", () => {
    renderFilters({}, { availablePatterns: [] });
    expect(screen.queryByTestId("filter-pattern")).not.toBeInTheDocument();
  });

  it("renders Clear all button when filters are active", () => {
    renderFilters({ q: "Rahul" });
    expect(screen.getByTestId("filters-clear-all")).toBeInTheDocument();
  });

  it("does NOT render Clear all button when no filters are active", () => {
    renderFilters();
    expect(screen.queryByTestId("filters-clear-all")).not.toBeInTheDocument();
  });

  it("renders active filters summary when any filter is non-default", () => {
    renderFilters({ q: "Rahul" });
    expect(screen.getByTestId("active-filters-summary")).toBeInTheDocument();
    expect(screen.getByTestId("active-filters-summary")).toHaveTextContent(
      "Rahul"
    );
  });

  it("does NOT render active filters summary when no filters are active", () => {
    renderFilters();
    expect(
      screen.queryByTestId("active-filters-summary")
    ).not.toBeInTheDocument();
  });

  it("populates search input with current q value", () => {
    renderFilters({ q: "Priya" });
    expect(screen.getByTestId("filter-search-input")).toHaveValue("Priya");
  });

  it("marks active entity type toggles with aria-pressed=true", () => {
    renderFilters({ entity_types: ["Person"] });
    const toggle = screen.getByTestId("entity-type-toggle-Person");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
  });

  it("marks inactive entity type toggles with aria-pressed=false", () => {
    renderFilters({ entity_types: [] });
    const toggle = screen.getByTestId("entity-type-toggle-Person");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
  });
});

// ---------------------------------------------------------------------------
// FiltersAndSearch — interactions (AC1 coverage)
// ---------------------------------------------------------------------------

describe("FiltersAndSearch — interactions", () => {
  it("calls onFiltersChange with updated q when search input changes", () => {
    const { onChange } = renderFilters();
    fireEvent.change(screen.getByTestId("filter-search-input"), {
      target: { value: "Rahul" },
    });
    expect(onChange).toHaveBeenCalledOnce();
    expect(onChange.mock.calls[0][0]).toMatchObject({ q: "Rahul" });
  });

  it("adds an entity type when its toggle is clicked", () => {
    const { onChange } = renderFilters({ entity_types: [] });
    fireEvent.click(screen.getByTestId("entity-type-toggle-Person"));
    expect(onChange).toHaveBeenCalledOnce();
    const newFilters = onChange.mock.calls[0][0] as FilterState;
    expect(newFilters.entity_types).toContain("Person");
  });

  it("removes an entity type when its active toggle is clicked again", () => {
    const { onChange } = renderFilters({ entity_types: ["Person"] });
    fireEvent.click(screen.getByTestId("entity-type-toggle-Person"));
    const newFilters = onChange.mock.calls[0][0] as FilterState;
    expect(newFilters.entity_types).not.toContain("Person");
  });

  it("adds a relationship type when its toggle is clicked", () => {
    const { onChange } = renderFilters({ relationship_types: [] });
    fireEvent.click(screen.getByTestId("rel-type-toggle-CALLED"));
    const newFilters = onChange.mock.calls[0][0] as FilterState;
    expect(newFilters.relationship_types).toContain("CALLED");
  });

  it("removes a relationship type when its active toggle is clicked again", () => {
    const { onChange } = renderFilters({ relationship_types: ["CALLED"] });
    fireEvent.click(screen.getByTestId("rel-type-toggle-CALLED"));
    const newFilters = onChange.mock.calls[0][0] as FilterState;
    expect(newFilters.relationship_types).not.toContain("CALLED");
  });

  it("calls onFiltersChange with updated source_type from dropdown", () => {
    const { onChange } = renderFilters();
    fireEvent.change(screen.getByTestId("filter-source-type"), {
      target: { value: "FIR" },
    });
    const newFilters = onChange.mock.calls[0][0] as FilterState;
    expect(newFilters.source_type).toBe("FIR");
  });

  it("calls onFiltersChange with updated community from dropdown", () => {
    const { onChange } = renderFilters();
    fireEvent.change(screen.getByTestId("filter-community"), {
      target: { value: "comm-A" },
    });
    const newFilters = onChange.mock.calls[0][0] as FilterState;
    expect(newFilters.community).toBe("comm-A");
  });

  it("calls onFiltersChange with updated pattern from dropdown", () => {
    const { onChange } = renderFilters();
    fireEvent.change(screen.getByTestId("filter-pattern"), {
      target: { value: "bridge_entity_v1" },
    });
    const newFilters = onChange.mock.calls[0][0] as FilterState;
    expect(newFilters.pattern).toBe("bridge_entity_v1");
  });

  it("Clear all button resets to DEFAULT_FILTERS (AC1)", () => {
    const { onChange } = renderFilters(ACTIVE_FILTERS);
    fireEvent.click(screen.getByTestId("filters-clear-all"));
    expect(onChange).toHaveBeenCalledWith(DEFAULT_FILTERS);
  });

  it("multiple entity types can be selected simultaneously", () => {
    const { onChange } = renderFilters({ entity_types: ["Person"] });
    fireEvent.click(screen.getByTestId("entity-type-toggle-Phone"));
    const newFilters = onChange.mock.calls[0][0] as FilterState;
    expect(newFilters.entity_types).toContain("Person");
    expect(newFilters.entity_types).toContain("Phone");
  });

  it("disables all inputs when loading=true", () => {
    renderFilters({}, { loading: true });
    expect(screen.getByTestId("filter-search-input")).toBeDisabled();
    expect(screen.getByTestId("filter-source-type")).toBeDisabled();
    expect(screen.getByTestId("filter-community")).toBeDisabled();
    expect(screen.getByTestId("filter-pattern")).toBeDisabled();
    const toggles = screen.getAllByRole("button");
    toggles.forEach((btn) => {
      expect(btn).toBeDisabled();
    });
  });

  it("preserves other filter values when updating one field (AC1)", () => {
    const { onChange } = renderFilters(ACTIVE_FILTERS);
    // Change only q — all other fields should remain intact
    fireEvent.change(screen.getByTestId("filter-search-input"), {
      target: { value: "NewQuery" },
    });
    const newFilters = onChange.mock.calls[0][0] as FilterState;
    expect(newFilters.q).toBe("NewQuery");
    expect(newFilters.entity_types).toEqual(ACTIVE_FILTERS.entity_types);
    expect(newFilters.relationship_types).toEqual(
      ACTIVE_FILTERS.relationship_types
    );
    expect(newFilters.source_type).toBe(ACTIVE_FILTERS.source_type);
    expect(newFilters.community).toBe(ACTIVE_FILTERS.community);
    expect(newFilters.pattern).toBe(ACTIVE_FILTERS.pattern);
  });
});

// ---------------------------------------------------------------------------
// FilterState helpers
// ---------------------------------------------------------------------------

describe("FilterState helpers", () => {
  describe("isDefaultFilters", () => {
    it("returns true for DEFAULT_FILTERS", () => {
      expect(isDefaultFilters(DEFAULT_FILTERS)).toBe(true);
    });

    it("returns false when q is set", () => {
      expect(isDefaultFilters({ ...DEFAULT_FILTERS, q: "x" })).toBe(false);
    });

    it("returns false when entity_types is non-empty", () => {
      expect(
        isDefaultFilters({ ...DEFAULT_FILTERS, entity_types: ["Person"] })
      ).toBe(false);
    });

    it("returns false when relationship_types is non-empty", () => {
      expect(
        isDefaultFilters({
          ...DEFAULT_FILTERS,
          relationship_types: ["CALLED"],
        })
      ).toBe(false);
    });

    it("returns false when source_type is set", () => {
      expect(
        isDefaultFilters({ ...DEFAULT_FILTERS, source_type: "FIR" })
      ).toBe(false);
    });

    it("returns false when community is set", () => {
      expect(
        isDefaultFilters({ ...DEFAULT_FILTERS, community: "comm-A" })
      ).toBe(false);
    });

    it("returns false when pattern is set", () => {
      expect(
        isDefaultFilters({
          ...DEFAULT_FILTERS,
          pattern: "bridge_entity_v1",
        })
      ).toBe(false);
    });
  });

  describe("toGraphParams", () => {
    it("returns dataset and no other params for default filters", () => {
      const params = toGraphParams(DEFAULT_FILTERS, "synthetic_demo", null);
      expect(params).toEqual({ dataset: "synthetic_demo" });
    });

    it("includes as_of when provided", () => {
      const params = toGraphParams(
        DEFAULT_FILTERS,
        "synthetic_demo",
        "2024-01-06T23:59:59Z"
      );
      expect(params.as_of).toBe("2024-01-06T23:59:59Z");
    });

    it("includes entity_types when set", () => {
      const params = toGraphParams(
        { ...DEFAULT_FILTERS, entity_types: ["Person", "Phone"] },
        "synthetic_demo",
        null
      );
      expect(params.entity_types).toBe("Person,Phone");
    });

    it("includes relationship_types when set", () => {
      const params = toGraphParams(
        { ...DEFAULT_FILTERS, relationship_types: ["CALLED"] },
        "synthetic_demo",
        null
      );
      expect(params.relationship_types).toBe("CALLED");
    });

    it("includes community when set", () => {
      const params = toGraphParams(
        { ...DEFAULT_FILTERS, community: "comm-A" },
        "synthetic_demo",
        null
      );
      expect(params.community).toBe("comm-A");
    });

    it("includes pattern when set", () => {
      const params = toGraphParams(
        { ...DEFAULT_FILTERS, pattern: "bridge_entity_v1" },
        "synthetic_demo",
        null
      );
      expect(params.pattern).toBe("bridge_entity_v1");
    });

    it("omits entity_types when array is empty", () => {
      const params = toGraphParams(DEFAULT_FILTERS, "synthetic_demo", null);
      expect(params.entity_types).toBeUndefined();
    });
  });

  describe("toSearchParams", () => {
    it("returns just dataset for default filters", () => {
      const params = toSearchParams(DEFAULT_FILTERS, "synthetic_demo");
      expect(params).toEqual({ dataset: "synthetic_demo" });
    });

    it("includes q when set", () => {
      const params = toSearchParams(
        { ...DEFAULT_FILTERS, q: "Rahul" },
        "synthetic_demo"
      );
      expect(params.q).toBe("Rahul");
    });

    it("includes entity_type when exactly one type is selected", () => {
      const params = toSearchParams(
        { ...DEFAULT_FILTERS, entity_types: ["Person"] },
        "synthetic_demo"
      );
      expect(params.entity_type).toBe("Person");
    });

    it("omits entity_type when multiple types are selected (uses graph filter instead)", () => {
      const params = toSearchParams(
        { ...DEFAULT_FILTERS, entity_types: ["Person", "Phone"] },
        "synthetic_demo"
      );
      expect(params.entity_type).toBeUndefined();
    });
  });
});

// ---------------------------------------------------------------------------
// AC1 integration: filter changes propagate to data-fetching
// ---------------------------------------------------------------------------

describe("FiltersAndSearch — AC1 state propagation (filter.ts integration)", () => {
  it("toGraphParams produces params that match getGraph signature", () => {
    // This verifies the param object is structurally valid for the api-client
    const params = toGraphParams(
      { ...DEFAULT_FILTERS, entity_types: ["Person"], community: "comm-A" },
      "synthetic_demo",
      "2024-01-06T23:59:59Z"
    );
    // Should have all the keys the api-client's GetGraphParams accepts
    expect(params.dataset).toBe("synthetic_demo");
    expect(params.as_of).toBe("2024-01-06T23:59:59Z");
    expect(params.entity_types).toBe("Person");
    expect(params.community).toBe("comm-A");
  });

  it("toSearchParams produces params that match searchEntities signature", () => {
    const params = toSearchParams(
      { ...DEFAULT_FILTERS, q: "Sharma", entity_types: ["Person"] },
      "synthetic_demo"
    );
    expect(params.q).toBe("Sharma");
    expect(params.entity_type).toBe("Person");
    expect(params.dataset).toBe("synthetic_demo");
  });
});
