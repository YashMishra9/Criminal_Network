"use client";

/**
 * app/page.tsx — Criminal Network Analysis dashboard shell (E1).
 *
 * Client Component: data is fetched at runtime, not at build time.
 * This matches the DOC2 §4 SPA architecture and ensures mock mode works
 * correctly without requiring env vars to be set during `next build`.
 *
 * E2 — NetworkView (Cytoscape.js graph visualisation)
 * E3 — EntityPanel / EvidencePanel (entity detail + evidence chain)
 * E4 — Timeline (Network Time Machine) + AnalyticsPanel (analytics + findings)
 * E5 — FiltersAndSearch (entity/rel/source/community/pattern filters + search)
 *      Filter state is owned here and propagated to every dependent component
 *      (E5.md §11): NetworkView, Timeline, and AnalyticsPanel all re-query
 *      with the active filters when they change.
 */

import { useEffect, useState, useCallback } from "react";
import {
  getGraph,
  getPatterns,
  getAnalytics,
  searchEntities,
  isMockMode,
} from "../lib/api-client";
import type {
  CanonicalEntity,
  Relationship,
  Finding,
  AnalyticsResult,
} from "../lib/types";
import Timeline from "../components/Timeline/Timeline";
import AnalyticsPanel from "../components/AnalyticsPanel/AnalyticsPanel";
import FiltersAndSearch from "../components/FiltersAndSearch/FiltersAndSearch";
import AskTheNetwork from "../components/AskTheNetwork/AskTheNetwork";
import CaseWorkspace from "../components/CaseWorkspace/CaseWorkspace";
import {
  DEFAULT_FILTERS,
  type FilterState,
  toGraphParams,
  toSearchParams,
} from "../state/filters";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DashboardData {
  entities: CanonicalEntity[];
  relationships: Relationship[];
  findings: Finding[];
  analytics: AnalyticsResult | null;
}

const DATASET = "synthetic_demo";

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);

  // E4: as_of state from the Timeline slider
  const [asOf, setAsOf] = useState<string | null>(null);

  // E5: shared filter/search state — owned here, propagated to all dependents
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);

  /**
   * Fetch graph data (entities + relationships + analytics summary) when
   * either asOf or filters change.  Analytics and Patterns are additionally
   * managed inside AnalyticsPanel (which re-fetches when its `asOf` prop
   * changes), but we also keep a summary copy here for the stats display.
   *
   * When a search query is active we call searchEntities to get the filtered
   * entity list; otherwise we call getGraph.
   */
  const fetchData = useCallback(
    (currentAsOf: string | null, currentFilters: FilterState) => {
      setGraphLoading(true);

      const graphParams = toGraphParams(currentFilters, DATASET, currentAsOf);
      const searchParams = toSearchParams(currentFilters, DATASET);

      Promise.all([
        // Entities: use searchEntities when q or entity_type filter is active
        currentFilters.q || currentFilters.entity_types.length === 1
          ? searchEntities(searchParams).then((r) => r.results)
          : getGraph(graphParams).then((r) => r.entities),
        getGraph(graphParams).then((r) => r.relationships),
        getPatterns({ dataset: DATASET, as_of: currentAsOf ?? undefined }),
        getAnalytics({ dataset: DATASET, as_of: currentAsOf ?? undefined }),
      ])
        .then(([entities, relationships, patternsData, analyticsData]) => {
          setData({
            entities,
            relationships,
            findings: patternsData.findings,
            analytics: analyticsData,
          });
          setError(null);
        })
        .catch((err: unknown) => {
          setError(err instanceof Error ? err.message : "Failed to load data");
        })
        .finally(() => setGraphLoading(false));
    },
    []
  );

  // Initial load
  useEffect(() => {
    fetchData(null, DEFAULT_FILTERS);
  }, [fetchData]);

  /** E4: Timeline change — update as_of and re-fetch */
  const handleAsOfChange = useCallback(
    (newAsOf: string | null) => {
      setAsOf(newAsOf);
      fetchData(newAsOf, filters);
    },
    [fetchData, filters]
  );

  /** E5: Filter change — update filters and re-fetch all dependents */
  const handleFiltersChange = useCallback(
    (newFilters: FilterState) => {
      setFilters(newFilters);
      fetchData(asOf, newFilters);
    },
    [fetchData, asOf]
  );

  // -------------------------------------------------------------------------
  // Derived values for community/pattern filter dropdowns
  // -------------------------------------------------------------------------

  const availableCommunities: string[] = data?.analytics
    ? [...new Set(data.analytics.communities.map((c) => c.community_id))].sort()
    : [];

  const availablePatterns: { rule_id: string; rule_name: string }[] =
    data?.findings
      ? [
          ...new Map(
            data.findings.map((f) => [f.rule_id, { rule_id: f.rule_id, rule_name: f.rule_name }])
          ).values(),
        ]
      : [];

  const communityCount = data?.analytics
    ? new Set(data.analytics.communities.map((c) => c.community_id)).size
    : 0;

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  if (error) {
    return (
      <main className="p-6">
        <p className="text-red-400">Error: {error}</p>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="p-6">
        <p className="text-gray-400">Loading…</p>
      </main>
    );
  }

  return (
    <main className="p-6 space-y-8">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">
          Criminal Network Analysis
        </h1>
        <p className="text-sm text-gray-400 mt-1">
          Dataset: <span className="font-mono">{DATASET}</span>
          {isMockMode() && (
            <span className="ml-2 px-2 py-0.5 rounded bg-yellow-800 text-yellow-200 text-xs">
              MOCK MODE
            </span>
          )}
        </p>
      </header>

      {/* E5 — FiltersAndSearch (wired into shared state — propagates to all panels) */}
      <section
        aria-label="Filters and Search"
        data-testid="filters-section"
      >
        <FiltersAndSearch
          filters={filters}
          onFiltersChange={handleFiltersChange}
          availableCommunities={availableCommunities}
          availablePatterns={availablePatterns}
          loading={graphLoading}
        />
      </section>

      {/* E6 — AskTheNetwork (chat-style NL query, all four AskResponse variants) */}
      <section
        aria-label="Ask the Network"
        data-testid="ask-section"
      >
        <AskTheNetwork asOf={asOf} dataset={DATASET} />
      </section>

      {/* Network summary stats */}
      <section aria-label="Network summary">
        <h2 className="text-lg font-semibold mb-3">Network</h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard label="Entities" value={data.entities.length} />
          <StatCard label="Relationships" value={data.relationships.length} />
          <StatCard label="Findings" value={data.findings.length} />
          <StatCard label="Communities" value={communityCount} />
        </div>
      </section>

      {/* E4 — Timeline (Network Time Machine) */}
      <section
        aria-label="Network Time Machine"
        data-testid="timeline-section"
      >
        <Timeline
          relationships={data.relationships}
          asOf={asOf}
          onAsOfChange={handleAsOfChange}
          loading={graphLoading}
        />
      </section>

      {/* Entity list — filtered by FiltersAndSearch */}
      <section aria-label="Entities">
        <h2 className="text-lg font-semibold mb-3">
          Entities
          {data.entities.length > 0 && (
            <span className="ml-2 text-sm font-normal text-gray-400">
              ({data.entities.length})
            </span>
          )}
        </h2>
        {data.entities.length === 0 ? (
          <p className="text-slate-500 italic text-sm">
            No entities match the current filters.
          </p>
        ) : (
          <ul className="space-y-2" data-testid="entity-list">
            {data.entities.map((entity) => (
              <li
                key={entity.entity_id}
                data-testid="entity-list-item"
                className="flex items-center gap-3 rounded-lg bg-gray-800 px-4 py-2"
              >
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-gray-700 text-gray-300">
                  {entity.entity_type}
                </span>
                <span className="font-medium">{entity.display_name}</span>
                <span className="ml-auto text-xs text-gray-500 font-mono">
                  {entity.entity_id}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* E4 — AnalyticsPanel (analytics + findings) */}
      <section
        aria-label="Analytics and Investigative Leads"
        data-testid="analytics-section"
      >
        <AnalyticsPanel asOf={asOf} dataset={DATASET} />
      </section>

      {/* E7 — CaseWorkspace (case creation, associations, notes, summary) */}
      <section
        aria-label="Case Workspace"
        data-testid="case-workspace-section"
      >
        <CaseWorkspace dataset={DATASET} />
      </section>
    </main>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-gray-800 px-4 py-3">
      <p className="text-2xl font-bold">{value}</p>
      <p className="text-sm text-gray-400">{label}</p>
    </div>
  );
}
