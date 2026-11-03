/**
 * frontend/state/filters.ts
 *
 * Shared filter/search view-state for the Criminal Network dashboard (E5).
 *
 * This module defines the canonical FilterState shape that is:
 *   - Created in the page root (app/page.tsx)
 *   - Passed down to FiltersAndSearch (controlled component, drives state)
 *   - Consumed by getGraph, getAnalytics, getPatterns, searchEntities
 *     as query parameters (DOC3 §12.1, §12.4)
 *
 * Constraint (E5.md §17):
 *   Types must reuse lib/types.ts — do not duplicate/redefine backend contract types.
 *
 * DOC3 §12.4 graph filter params:
 *   dataset, as_of, entity_types, relationship_types, community, pattern
 *
 * DOC3 §12.1 search params:
 *   q, dataset, entity_type
 */

import type { EntityType, RelationshipType } from "../lib/types";

// ---------------------------------------------------------------------------
// FilterState — the single shared shape passed to every dependent component
// ---------------------------------------------------------------------------

export interface FilterState {
  /**
   * Free-text search query. Maps to GET /entities/search?q= (DOC3 §12.1).
   * Empty string means "no search filter".
   */
  q: string;

  /**
   * Entity type filter. Maps to GET /graph?entity_types= and
   * GET /entities/search?entity_type= (DOC3 §12.1, §12.4).
   * Empty array means "all types".
   */
  entity_types: EntityType[];

  /**
   * Relationship type filter. Maps to GET /graph?relationship_types=
   * (DOC3 §12.4). Empty array means "all types".
   */
  relationship_types: RelationshipType[];

  /**
   * Source type filter (e.g. "FIR", "CDR", "transaction").
   * Applied client-side to filter displayed entities/relationships by their
   * evidence source_type. NOT forwarded as a query parameter to the backend
   * graph API (DOC3 §12.4 does not define a source_type param). Empty string
   * means "all sources".
   */
  source_type: string;

  /**
   * Community filter. Maps to GET /graph?community= (DOC3 §12.4).
   * Empty string means "no community filter".
   */
  community: string;

  /**
   * Pattern/finding rule_id filter. Maps to GET /graph?pattern= (DOC3 §12.4).
   * Empty string means "no pattern filter".
   */
  pattern: string;
}

// ---------------------------------------------------------------------------
// DEFAULT_FILTERS — the "no filter applied" baseline
// ---------------------------------------------------------------------------

export const DEFAULT_FILTERS: FilterState = {
  q: "",
  entity_types: [],
  relationship_types: [],
  source_type: "",
  community: "",
  pattern: "",
};

// ---------------------------------------------------------------------------
// Helpers for converting FilterState → API query params
// ---------------------------------------------------------------------------

/**
 * Returns the GET /graph params object derived from the current FilterState.
 * Omits fields when they carry no useful value (empty string / empty array).
 */
export function toGraphParams(
  filters: FilterState,
  dataset = "synthetic_demo",
  asOf: string | null = null
): Record<string, string> {
  const params: Record<string, string> = { dataset };
  if (asOf) params.as_of = asOf;
  if (filters.entity_types.length > 0)
    params.entity_types = filters.entity_types.join(",");
  if (filters.relationship_types.length > 0)
    params.relationship_types = filters.relationship_types.join(",");
  if (filters.community) params.community = filters.community;
  if (filters.pattern) params.pattern = filters.pattern;
  return params;
}

/**
 * Returns the GET /entities/search params derived from the current FilterState.
 */
export function toSearchParams(
  filters: FilterState,
  dataset = "synthetic_demo"
): Record<string, string> {
  const params: Record<string, string> = { dataset };
  if (filters.q) params.q = filters.q;
  if (filters.entity_types.length === 1)
    params.entity_type = filters.entity_types[0];
  return params;
}

/**
 * Returns true if no filters are active (same as DEFAULT_FILTERS).
 */
export function isDefaultFilters(filters: FilterState): boolean {
  return (
    filters.q === "" &&
    filters.entity_types.length === 0 &&
    filters.relationship_types.length === 0 &&
    filters.source_type === "" &&
    filters.community === "" &&
    filters.pattern === ""
  );
}
