/**
 * tests/NetworkView.test.tsx — E2 component tests (E2.md §13)
 *
 * Covers: render, node/edge selection callbacks, entity-type filtering,
 * relationship-type filtering, and shortest-path highlight.
 *
 * Cytoscape.js is browser-only and cannot run in jsdom — it is mocked below
 * with a minimal stub that records calls and exposes tap event handlers so
 * tests can simulate user interactions.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { CanonicalEntity, Relationship } from "../lib/types";

// ---------------------------------------------------------------------------
// Cytoscape mock — must be declared before the component import
// ---------------------------------------------------------------------------

type TapHandler = (evt: { target: unknown }) => void;

interface MockElement {
  data: Record<string, string>;
  classes: Set<string>;
}

interface MockCy {
  _elements: MockElement[];
  on: ReturnType<typeof vi.fn>;
  elements: ReturnType<typeof vi.fn>;
  nodes: ReturnType<typeof vi.fn>;
  edges: ReturnType<typeof vi.fn>;
  add: ReturnType<typeof vi.fn>;
  layout: ReturnType<typeof vi.fn>;
  getElementById: ReturnType<typeof vi.fn>;
  destroy: ReturnType<typeof vi.fn>;
  fireTap: (selector: "node" | "edge", id: string) => void;
}

let mockCyInstance: MockCy;

vi.mock("cytoscape", () => ({
  default: vi.fn((opts: { elements: { data: Record<string, string> }[] }) => {
    const store: MockElement[] = (opts.elements ?? []).map((el) => ({
      data: el.data,
      classes: new Set<string>(),
    }));

    const tapHandlers: Record<string, TapHandler[]> = {};

    const makeEl = (item: MockElement) => ({
      data: (k: string) => item.data[k],
      hasClass: (c: string) => item.classes.has(c),
      addClass: (c: string) => item.classes.add(c),
      removeClass: (c: string) => item.classes.delete(c),
      source: () => ({ hasClass: () => false }),
      target: () => ({ hasClass: () => false }),
    });

    const makeCollection = (items: MockElement[]) => ({
      forEach: (fn: (el: ReturnType<typeof makeEl>) => void) =>
        items.forEach((item) => fn(makeEl(item))),
      removeClass: (c: string) => items.forEach((item) => item.classes.delete(c)),
      addClass: (c: string) => items.forEach((item) => item.classes.add(c)),
      remove: vi.fn(() => { store.length = 0; }),
      unselect: vi.fn(),
    });

    const cy: MockCy = {
      _elements: store,
      on: vi.fn((event: string, selectorOrHandler: string | TapHandler, handler?: TapHandler) => {
        const key = handler ? `${event}:${selectorOrHandler as string}` : event;
        const fn = (handler ?? selectorOrHandler) as TapHandler;
        tapHandlers[key] = tapHandlers[key] ?? [];
        tapHandlers[key].push(fn);
      }),
      elements: vi.fn(() => makeCollection(store)),
      nodes: vi.fn(() => makeCollection(store.filter((e) => !e.data.source))),
      edges: vi.fn(() => makeCollection(store.filter((e) => !!e.data.source))),
      add: vi.fn((els: { data: Record<string, string> }[]) =>
        els.forEach((el) => store.push({ data: el.data, classes: new Set() }))
      ),
      layout: vi.fn(() => ({ run: vi.fn() })),
      getElementById: vi.fn((id: string) => {
        const item = store.find((e) => e.data.id === id);
        return { addClass: (c: string) => item?.classes.add(c) };
      }),
      destroy: vi.fn(),
      fireTap: (selector: "node" | "edge", id: string) => {
        (tapHandlers[`tap:${selector}`] ?? []).forEach((h) =>
          h({ target: { id: () => id } })
        );
      },
    };

    mockCyInstance = cy;
    return cy;
  }),
}));

// Static import — must come after vi.mock so the mock is in place
import NetworkView from "../components/NetworkView/NetworkView";
import type { NetworkViewProps } from "../components/NetworkView/NetworkView";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ENTITIES: CanonicalEntity[] = [
  {
    entity_id: "ent-001", entity_type: "Person", dataset: "synthetic_demo",
    display_name: "Rahul Sharma", attributes: {}, resolved_from: [],
    resolution_method: "exact_match", created_at: "2024-01-10T08:00:00Z", updated_at: "2024-01-10T08:00:00Z",
  },
  {
    entity_id: "ent-002", entity_type: "Phone", dataset: "synthetic_demo",
    display_name: "+919876543210", attributes: {}, resolved_from: [],
    resolution_method: "exact_match", created_at: "2024-01-10T08:00:00Z", updated_at: "2024-01-10T08:00:00Z",
  },
  {
    entity_id: "ent-003", entity_type: "Organization", dataset: "synthetic_demo",
    display_name: "Apex Trading Co.", attributes: {}, resolved_from: [],
    resolution_method: "exact_match", created_at: "2024-01-10T08:00:00Z", updated_at: "2024-01-10T08:00:00Z",
  },
];

const RELATIONSHIPS: Relationship[] = [
  {
    relationship_id: "rel-001", relationship_type: "CALLED",
    from_entity_id: "ent-001", to_entity_id: "ent-002",
    dataset: "synthetic_demo", attributes: {}, valid_from: "2024-01-06T10:00:00Z",
    valid_to: null, evidence_ids: ["ev-001"], created_at: "2024-01-10T08:00:00Z", updated_at: "2024-01-10T08:00:00Z",
  },
  {
    relationship_id: "rel-002", relationship_type: "WORKS_FOR",
    from_entity_id: "ent-001", to_entity_id: "ent-003",
    dataset: "synthetic_demo", attributes: {}, valid_from: "2024-01-06T10:00:00Z",
    valid_to: null, evidence_ids: ["ev-002"], created_at: "2024-01-10T08:00:00Z", updated_at: "2024-01-10T08:00:00Z",
  },
];

function renderNetworkView(props: Partial<NetworkViewProps> = {}) {
  return render(
    <NetworkView entities={ENTITIES} relationships={RELATIONSHIPS} {...props} />
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("NetworkView — render", () => {
  it("renders the container div with data-testid='network-view'", () => {
    renderNetworkView();
    expect(screen.getByTestId("network-view")).toBeInTheDocument();
  });

  it("initialises a Cytoscape instance on mount", async () => {
    const cytoscape = await import("cytoscape");
    const spy = vi.mocked(cytoscape.default);
    spy.mockClear();
    renderNetworkView();
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("passes entities and relationships as elements to Cytoscape", async () => {
    const cytoscape = await import("cytoscape");
    const spy = vi.mocked(cytoscape.default);
    spy.mockClear();
    renderNetworkView();
    const callArg = spy.mock.calls[0][0] as { elements: { data: Record<string, string> }[] };
    const ids = callArg.elements.map((el) => el.data.id);
    expect(ids).toContain("ent-001");
    expect(ids).toContain("ent-002");
    expect(ids).toContain("rel-001");
  });

  it("container has minimum height style", () => {
    renderNetworkView();
    expect(screen.getByTestId("network-view")).toHaveStyle({ minHeight: "400px" });
  });
});

describe("NetworkView — selection callbacks", () => {
  it("calls onSelectEntity with entity id when a node is tapped", () => {
    const onSelectEntity = vi.fn();
    renderNetworkView({ onSelectEntity });
    mockCyInstance.fireTap("node", "ent-001");
    expect(onSelectEntity).toHaveBeenCalledWith("ent-001");
  });

  it("calls onSelectRelationship with relationship id when an edge is tapped", () => {
    const onSelectRelationship = vi.fn();
    renderNetworkView({ onSelectRelationship });
    mockCyInstance.fireTap("edge", "rel-001");
    expect(onSelectRelationship).toHaveBeenCalledWith("rel-001");
  });

  it("does not throw when callbacks are not provided and a node is tapped", () => {
    renderNetworkView();
    expect(() => mockCyInstance.fireTap("node", "ent-001")).not.toThrow();
  });
});

describe("NetworkView — entity-type filtering", () => {
  it("applies .hidden class to nodes not in entityTypeFilter", () => {
    renderNetworkView({ entityTypeFilter: new Set(["Person"]) });
    const phoneNode = mockCyInstance._elements.find((e) => e.data.id === "ent-002");
    const personNode = mockCyInstance._elements.find((e) => e.data.id === "ent-001");
    expect(phoneNode?.classes.has("hidden")).toBe(true);
    expect(personNode?.classes.has("hidden")).toBe(false);
  });

  it("shows all nodes when entityTypeFilter is empty", () => {
    renderNetworkView({ entityTypeFilter: new Set() });
    const hidden = mockCyInstance._elements.filter((e) => e.classes.has("hidden"));
    expect(hidden.length).toBe(0);
  });
});

describe("NetworkView — relationship-type filtering", () => {
  it("applies .hidden class to edges not in relationshipTypeFilter", () => {
    renderNetworkView({ relationshipTypeFilter: new Set(["CALLED"]) });
    const worksForEdge = mockCyInstance._elements.find((e) => e.data.id === "rel-002");
    const calledEdge = mockCyInstance._elements.find((e) => e.data.id === "rel-001");
    expect(worksForEdge?.classes.has("hidden")).toBe(true);
    expect(calledEdge?.classes.has("hidden")).toBe(false);
  });
});

describe("NetworkView — shortest-path highlight", () => {
  it("adds .path-highlight class to nodes in highlightPath", () => {
    renderNetworkView({ highlightPath: ["ent-001", "ent-002"] });
    const node1 = mockCyInstance._elements.find((e) => e.data.id === "ent-001");
    const node2 = mockCyInstance._elements.find((e) => e.data.id === "ent-002");
    expect(node1?.classes.has("path-highlight")).toBe(true);
    expect(node2?.classes.has("path-highlight")).toBe(true);
  });

  it("does not add .path-highlight when highlightPath has fewer than 2 nodes", () => {
    renderNetworkView({ highlightPath: ["ent-001"] });
    const highlighted = mockCyInstance._elements.filter((e) => e.classes.has("path-highlight"));
    expect(highlighted.length).toBe(0);
  });

  it("does not add .path-highlight when highlightPath is empty (default)", () => {
    renderNetworkView();
    const highlighted = mockCyInstance._elements.filter((e) => e.classes.has("path-highlight"));
    expect(highlighted.length).toBe(0);
  });
});
