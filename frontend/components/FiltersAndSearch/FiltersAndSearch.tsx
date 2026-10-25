"use client";

/**
 * components/FiltersAndSearch/FiltersAndSearch.tsx
 *
 * Entity-type / relationship-type / date / source / community / pattern
 * filters and free-text search (E5, DOC1 FR26, DOC3 §12.1, §12.4).
 *
 * Contracts:
 *   §12.1  GET /entities/search?q=&dataset=&entity_type=
 *   §12.4  GET /graph?entity_types=&relationship_types=&community=&pattern=
 *
 * This is a **controlled component** — it does not own its state.
 * The parent (app/page.tsx) owns a `FilterState` and passes:
 *   - `filters`      — current state (read)
 *   - `onFiltersChange` — called whenever any filter changes
 *
 * The parent is responsible for re-fetching /graph, /analytics, /patterns
 * whenever `filters` changes (E5.md §11: filter/search state must propagate
 * to NetworkView, Timeline, and AnalyticsPanel).
 *
 * Phase 0: mock mode — all API calls return fixtures regardless of filter
 * params. Real filtering applies at Sync 2/3 against live C6/D5 endpoints.
 *
 * Constraint (E5.md §17):
 *   Only types from lib/types.ts are used — no contract types are redefined.
 */

import type { FilterState } from "../../state/filters";
import { DEFAULT_FILTERS, isDefaultFilters } from "../../state/filters";
import type { EntityType, RelationshipType } from "../../lib/types";

// ---------------------------------------------------------------------------
// Constants — entity/relationship type options (closed enums from DOC3 §1.3)
// ---------------------------------------------------------------------------

const ENTITY_TYPES: EntityType[] = [
  "Person",
  "Phone",
  "Vehicle",
  "Location",
  "Organization",
  "BankAccount",
  "Transaction",
  "Event",
];

const RELATIONSHIP_TYPES: RelationshipType[] = [
  "CALLED",
  "OWNS",
  "USED",
  "TRANSFERRED",
  "VISITED",
  "MET",
  "WORKS_FOR",
  "ASSOCIATED_WITH",
  "MENTIONED_IN",
  "PART_OF",
];

// Source types are non-exhaustive per DOC3 §2.2 — offer the common ones
const SOURCE_TYPES: string[] = [
  "FIR",
  "police_report",
  "CDR",
  "transaction",
  "vehicle_registry",
  "surveillance",
  "social_media",
  "criminal_history",
  "org_registry",
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface FiltersAndSearchProps {
  /** Current active filters — owned by the parent. */
  filters: FilterState;

  /** Called when any filter changes — parent updates state and re-fetches. */
  onFiltersChange: (next: FilterState) => void;

  /**
   * Available community IDs for the community filter dropdown.
   * Derived from the current AnalyticsResult.communities by the parent.
   */
  availableCommunities?: string[];

  /**
   * Available pattern rule names for the pattern filter dropdown.
   * Derived from the current Finding[] by the parent.
   */
  availablePatterns?: { rule_id: string; rule_name: string }[];

  /** Loading flag from parent — disables inputs while data is in flight. */
  loading?: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toggleArrayItem<T>(arr: T[], item: T): T[] {
  return arr.includes(item) ? arr.filter((x) => x !== item) : [...arr, item];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function FiltersAndSearch({
  filters,
  onFiltersChange,
  availableCommunities = [],
  availablePatterns = [],
  loading = false,
}: FiltersAndSearchProps) {
  const anyActive = !isDefaultFilters(filters);

  const update = (patch: Partial<FilterState>) =>
    onFiltersChange({ ...filters, ...patch });

  const clearAll = () => onFiltersChange({ ...DEFAULT_FILTERS });

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div
      data-testid="filters-and-search"
      className="bg-gray-800 rounded-lg p-4 space-y-4 text-sm text-slate-200"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-slate-100">Filters &amp; Search</h2>
        {anyActive && (
          <button
            data-testid="filters-clear-all"
            onClick={clearAll}
            disabled={loading}
            className="text-xs text-blue-400 hover:text-blue-200 disabled:opacity-40"
            aria-label="Clear all filters"
          >
            Clear all
          </button>
        )}
      </div>

      {/* Search bar */}
      <div>
        <label
          htmlFor="filter-search-q"
          className="block text-xs text-slate-400 mb-1"
        >
          Search entities
        </label>
        <input
          id="filter-search-q"
          data-testid="filter-search-input"
          type="search"
          value={filters.q}
          onChange={(e) => update({ q: e.target.value })}
          placeholder="Name, ID, type…"
          disabled={loading}
          aria-label="Search entities by name or ID"
          className={[
            "w-full rounded bg-gray-700 border border-gray-600 px-3 py-1.5 text-sm",
            "text-slate-200 placeholder-slate-500 outline-none",
            "focus:border-blue-500 focus:ring-1 focus:ring-blue-500",
            "disabled:opacity-40 disabled:cursor-not-allowed",
          ].join(" ")}
        />
      </div>

      {/* Entity type filter — checkbox group */}
      <fieldset>
        <legend className="text-xs text-slate-400 mb-2 font-medium">
          Entity types
        </legend>
        <div
          data-testid="entity-type-filter"
          className="flex flex-wrap gap-1.5"
        >
          {ENTITY_TYPES.map((type) => {
            const active = filters.entity_types.includes(type);
            return (
              <button
                key={type}
                data-testid={`entity-type-toggle-${type}`}
                onClick={() =>
                  update({
                    entity_types: toggleArrayItem(filters.entity_types, type),
                  })
                }
                disabled={loading}
                aria-pressed={active}
                className={[
                  "text-xs px-2 py-0.5 rounded border transition-colors",
                  "disabled:opacity-40 disabled:cursor-not-allowed",
                  active
                    ? "bg-blue-600 border-blue-500 text-white"
                    : "bg-gray-700 border-gray-600 text-slate-300 hover:border-blue-500",
                ].join(" ")}
              >
                {type}
              </button>
            );
          })}
        </div>
      </fieldset>

      {/* Relationship type filter — checkbox group */}
      <fieldset>
        <legend className="text-xs text-slate-400 mb-2 font-medium">
          Relationship types
        </legend>
        <div
          data-testid="relationship-type-filter"
          className="flex flex-wrap gap-1.5"
        >
          {RELATIONSHIP_TYPES.map((type) => {
            const active = filters.relationship_types.includes(type);
            return (
              <button
                key={type}
                data-testid={`rel-type-toggle-${type}`}
                onClick={() =>
                  update({
                    relationship_types: toggleArrayItem(
                      filters.relationship_types,
                      type
                    ),
                  })
                }
                disabled={loading}
                aria-pressed={active}
                className={[
                  "text-xs px-2 py-0.5 rounded border font-mono transition-colors",
                  "disabled:opacity-40 disabled:cursor-not-allowed",
                  active
                    ? "bg-purple-700 border-purple-500 text-white"
                    : "bg-gray-700 border-gray-600 text-slate-300 hover:border-purple-500",
                ].join(" ")}
              >
                {type}
              </button>
            );
          })}
        </div>
      </fieldset>

      {/* Source type filter — select dropdown */}
      <div>
        <label
          htmlFor="filter-source-type"
          className="block text-xs text-slate-400 mb-1"
        >
          Source type
        </label>
        <select
          id="filter-source-type"
          data-testid="filter-source-type"
          value={filters.source_type}
          onChange={(e) => update({ source_type: e.target.value })}
          disabled={loading}
          aria-label="Filter by source type"
          className={[
            "w-full rounded bg-gray-700 border border-gray-600 px-2 py-1.5 text-sm",
            "text-slate-200 outline-none",
            "focus:border-blue-500 focus:ring-1 focus:ring-blue-500",
            "disabled:opacity-40 disabled:cursor-not-allowed",
          ].join(" ")}
        >
          <option value="">All sources</option>
          {SOURCE_TYPES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {/* Community filter — select dropdown (populated from analytics) */}
      {availableCommunities.length > 0 && (
        <div>
          <label
            htmlFor="filter-community"
            className="block text-xs text-slate-400 mb-1"
          >
            Community
          </label>
          <select
            id="filter-community"
            data-testid="filter-community"
            value={filters.community}
            onChange={(e) => update({ community: e.target.value })}
            disabled={loading}
            aria-label="Filter by community"
            className={[
              "w-full rounded bg-gray-700 border border-gray-600 px-2 py-1.5 text-sm",
              "text-slate-200 outline-none",
              "focus:border-blue-500 focus:ring-1 focus:ring-blue-500",
              "disabled:opacity-40 disabled:cursor-not-allowed",
            ].join(" ")}
          >
            <option value="">All communities</option>
            {availableCommunities.map((cid) => (
              <option key={cid} value={cid}>
                {cid}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Pattern filter — select dropdown (populated from findings) */}
      {availablePatterns.length > 0 && (
        <div>
          <label
            htmlFor="filter-pattern"
            className="block text-xs text-slate-400 mb-1"
          >
            Pattern
          </label>
          <select
            id="filter-pattern"
            data-testid="filter-pattern"
            value={filters.pattern}
            onChange={(e) => update({ pattern: e.target.value })}
            disabled={loading}
            aria-label="Filter by flagged pattern"
            className={[
              "w-full rounded bg-gray-700 border border-gray-600 px-2 py-1.5 text-sm",
              "text-slate-200 outline-none",
              "focus:border-blue-500 focus:ring-1 focus:ring-blue-500",
              "disabled:opacity-40 disabled:cursor-not-allowed",
            ].join(" ")}
          >
            <option value="">All patterns</option>
            {availablePatterns.map((p) => (
              <option key={p.rule_id} value={p.rule_id}>
                {p.rule_name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Active filters summary */}
      {anyActive && (
        <div
          data-testid="active-filters-summary"
          className="text-xs text-slate-400 italic border-t border-gray-700 pt-2"
        >
          Active filters:{" "}
          {[
            filters.q && `search: "${filters.q}"`,
            filters.entity_types.length > 0 &&
              `types: ${filters.entity_types.join(", ")}`,
            filters.relationship_types.length > 0 &&
              `rels: ${filters.relationship_types.join(", ")}`,
            filters.source_type && `source: ${filters.source_type}`,
            filters.community && `community: ${filters.community}`,
            filters.pattern && `pattern: ${filters.pattern}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </div>
      )}
    </div>
  );
}
