"use client";

/**
 * components/NetworkView/NetworkView.tsx
 *
 * Interactive Cytoscape.js network canvas (E2, DOC1 FR25).
 * Consumes { entities, relationships } exactly per DOC3 §12.4.
 *
 * Features:
 *   - Pan, zoom (mouse wheel + pinch)
 *   - Node / edge click selection (fires onSelectEntity / onSelectRelationship)
 *   - Entity-type and relationship-type filtering (hides non-matching elements)
 *   - Shortest-path highlight between two selected nodes
 *
 * Phase 0: works entirely against mock data.
 * Real-wiring: swap the data prop for a live getGraph() call (E5 / Sync 2).
 */

import { useEffect, useRef, useCallback } from "react";
import type { CanonicalEntity, Relationship, EntityType, RelationshipType } from "../../lib/types";

// Cytoscape is a browser-only library — imported dynamically to avoid SSR issues.
// The component is already "use client" so this is safe.
import cytoscape from "cytoscape";

// ---------------------------------------------------------------------------
// Colour palette — one colour per EntityType
// ---------------------------------------------------------------------------

const ENTITY_COLOURS: Record<EntityType, string> = {
  Person:       "#60a5fa", // blue-400
  Phone:        "#34d399", // emerald-400
  Vehicle:      "#fbbf24", // amber-400
  Location:     "#a78bfa", // violet-400
  Organization: "#f87171", // red-400
  BankAccount:  "#fb923c", // orange-400
  Transaction:  "#e879f9", // fuchsia-400
  Event:        "#94a3b8", // slate-400
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface NetworkViewProps {
  entities: CanonicalEntity[];
  relationships: Relationship[];
  /** Active entity-type filters — empty set means "show all" */
  entityTypeFilter?: Set<EntityType>;
  /** Active relationship-type filters — empty set means "show all" */
  relationshipTypeFilter?: Set<RelationshipType>;
  /** IDs of entities forming the highlighted shortest path (ordered) */
  highlightPath?: string[];
  onSelectEntity?: (entityId: string) => void;
  onSelectRelationship?: (relationshipId: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function NetworkView({
  entities,
  relationships,
  entityTypeFilter = new Set(),
  relationshipTypeFilter = new Set(),
  highlightPath = [],
  onSelectEntity,
  onSelectRelationship,
}: NetworkViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);

  // Build Cytoscape elements from DOC3 §12.4 shapes
  const buildElements = useCallback((): cytoscape.ElementDefinition[] => {
    const nodes: cytoscape.ElementDefinition[] = entities.map((e) => ({
      data: {
        id: e.entity_id,
        label: e.display_name,
        entityType: e.entity_type,
        dataset: e.dataset,
      },
    }));

    const edges: cytoscape.ElementDefinition[] = relationships.map((r) => ({
      data: {
        id: r.relationship_id,
        source: r.from_entity_id,
        target: r.to_entity_id,
        label: r.relationship_type,
        relationshipType: r.relationship_type,
        dataset: r.dataset,
      },
    }));

    return [...nodes, ...edges];
  }, [entities, relationships]);

  // Initialise Cytoscape once on mount
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements: buildElements(),
      style: [
        {
          selector: "node",
          style: {
            "background-color": (ele: cytoscape.NodeSingular) =>
              ENTITY_COLOURS[ele.data("entityType") as EntityType] ?? "#94a3b8",
            label: "data(label)",
            color: "#f1f5f9",
            "font-size": "10px",
            "text-valign": "bottom",
            "text-margin-y": 4,
            width: 28,
            height: 28,
            "border-width": 0,
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-width": 3,
            "border-color": "#f8fafc",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#475569",
            "target-arrow-color": "#475569",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": "8px",
            color: "#94a3b8",
            "text-rotation": "autorotate",
          },
        },
        {
          selector: "edge:selected",
          style: {
            "line-color": "#60a5fa",
            "target-arrow-color": "#60a5fa",
            width: 2.5,
          },
        },
        {
          selector: ".hidden",
          style: { display: "none" },
        },
        {
          selector: ".path-highlight",
          style: {
            "background-color": "#facc15",
            "line-color": "#facc15",
            "target-arrow-color": "#facc15",
            width: 3,
            "border-width": 3,
            "border-color": "#facc15",
          },
        },
      ],
      layout: { name: "cose", animate: false },
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
    });

    // Selection events
    cy.on("tap", "node", (evt) => {
      onSelectEntity?.(evt.target.id());
    });
    cy.on("tap", "edge", (evt) => {
      onSelectRelationship?.(evt.target.id());
    });
    // Deselect on background tap
    cy.on("tap", (evt) => {
      if (evt.target === cy) {
        cy.elements().unselect();
      }
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // intentionally empty — cy is initialised once; data/filter changes handled below

  // Update elements when data changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().remove();
    cy.add(buildElements());
    cy.layout({ name: "cose", animate: false }).run();
  }, [buildElements]);

  // Apply entity-type and relationship-type filters
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.elements().removeClass("hidden");

    if (entityTypeFilter.size > 0) {
      cy.nodes().forEach((node) => {
        if (!entityTypeFilter.has(node.data("entityType") as EntityType)) {
          node.addClass("hidden");
        }
      });
    }

    if (relationshipTypeFilter.size > 0) {
      cy.edges().forEach((edge) => {
        if (!relationshipTypeFilter.has(edge.data("relationshipType") as RelationshipType)) {
          edge.addClass("hidden");
        }
      });
    }

    // Hide edges whose source or target is hidden
    cy.edges().forEach((edge) => {
      if (edge.source().hasClass("hidden") || edge.target().hasClass("hidden")) {
        edge.addClass("hidden");
      }
    });
  }, [entityTypeFilter, relationshipTypeFilter]);

  // Apply shortest-path highlight
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.elements().removeClass("path-highlight");

    if (highlightPath.length >= 2) {
      for (const id of highlightPath) {
        cy.getElementById(id).addClass("path-highlight");
      }
      // Highlight edges connecting consecutive path nodes
      for (let i = 0; i < highlightPath.length - 1; i++) {
        cy.edges(`[source = "${highlightPath[i]}"][target = "${highlightPath[i + 1]}"]`)
          .addClass("path-highlight");
        cy.edges(`[source = "${highlightPath[i + 1]}"][target = "${highlightPath[i]}"]`)
          .addClass("path-highlight");
      }
    }
  }, [highlightPath]);

  return (
    <div
      ref={containerRef}
      data-testid="network-view"
      className="w-full h-full bg-gray-900 rounded-lg"
      style={{ minHeight: "400px" }}
    />
  );
}
