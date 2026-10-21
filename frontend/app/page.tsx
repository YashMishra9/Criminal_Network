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
 */

import { useEffect, useState, useCallback } from "react";
import { getGraph, getPatterns, getAnalytics, isMockMode } from "../lib/api-client";
import type { CanonicalEntity, Relationship, Finding, AnalyticsResult } from "../lib/types";
import Timeline from "../components/Timeline/Timeline";
import AnalyticsPanel from "../components/AnalyticsPanel/AnalyticsPanel";

interface DashboardData {
  entities: CanonicalEntity[];
  relationships: Relationship[];
  findings: Finding[];
  analytics: AnalyticsResult | null;
}

const DATASET = "synthetic_demo";

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);

  // E4: as_of state drives Timeline slider and AnalyticsPanel re-fetches
  const [asOf, setAsOf] = useState<string | null>(null);

  /**
   * Fetch graph data (entities + relationships) when asOf changes.
   * Analytics and patterns are handled inside AnalyticsPanel (E4).
   */
  const fetchGraph = useCallback((currentAsOf: string | null) => {
    setGraphLoading(true);
    Promise.all([
      getGraph({ dataset: DATASET, as_of: currentAsOf ?? undefined }),
      getPatterns({ dataset: DATASET, as_of: currentAsOf ?? undefined }),
      getAnalytics({ dataset: DATASET, as_of: currentAsOf ?? undefined }),
    ])
      .then(([graphData, patternsData, analyticsData]) => {
        setData({
          entities: graphData.entities,
          relationships: graphData.relationships,
          findings: patternsData.findings,
          analytics: analyticsData,
        });
        setError(null);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load data");
      })
      .finally(() => setGraphLoading(false));
  }, []);

  // Initial load
  useEffect(() => {
    fetchGraph(null);
  }, [fetchGraph]);

  /** E4: called by Timeline when slider changes — re-fetches the whole graph at new as_of. */
  const handleAsOfChange = useCallback(
    (newAsOf: string | null) => {
      setAsOf(newAsOf);
      fetchGraph(newAsOf);
    },
    [fetchGraph]
  );

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

  const communityCount = data.analytics
    ? new Set(data.analytics.communities.map((c) => c.community_id)).size
    : 0;

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
      <section aria-label="Network Time Machine" data-testid="timeline-section">
        <Timeline
          relationships={data.relationships}
          asOf={asOf}
          onAsOfChange={handleAsOfChange}
          loading={graphLoading}
        />
      </section>

      {/* Entity list — placeholder for E3 EntityPanel */}
      <section aria-label="Entities">
        <h2 className="text-lg font-semibold mb-3">Entities</h2>
        <ul className="space-y-2">
          {data.entities.map((entity) => (
            <li
              key={entity.entity_id}
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
      </section>

      {/* E4 — AnalyticsPanel (analytics + findings) */}
      <section aria-label="Analytics and Investigative Leads" data-testid="analytics-section">
        <AnalyticsPanel asOf={asOf} dataset={DATASET} />
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
