"use client";

/**
 * app/page.tsx — Criminal Network Analysis dashboard shell (E1).
 *
 * Client Component: data is fetched at runtime, not at build time.
 * This matches the DOC2 §4 SPA architecture and ensures mock mode works
 * correctly without requiring env vars to be set during `next build`.
 *
 * E2–E7 will replace the placeholder sections with real components.
 */

import { useEffect, useState } from "react";
import { getGraph, getPatterns, getAnalytics, isMockMode } from "../lib/api-client";
import type { CanonicalEntity, Relationship, Finding, AnalyticsResult } from "../lib/types";

interface DashboardData {
  entities: CanonicalEntity[];
  relationships: Relationship[];
  findings: Finding[];
  analytics: AnalyticsResult | null;
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      getGraph({ dataset: "synthetic_demo" }),
      getPatterns({ dataset: "synthetic_demo" }),
      getAnalytics({ dataset: "synthetic_demo" }),
    ])
      .then(([graphData, patternsData, analyticsData]) => {
        setData({
          entities: graphData.entities,
          relationships: graphData.relationships,
          findings: patternsData.findings,
          analytics: analyticsData,
        });
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load data");
      });
  }, []);

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
          Dataset: <span className="font-mono">synthetic_demo</span>
          {isMockMode() && (
            <span className="ml-2 px-2 py-0.5 rounded bg-yellow-800 text-yellow-200 text-xs">
              MOCK MODE
            </span>
          )}
        </p>
      </header>

      {/* Network summary — placeholder for E2 NetworkView */}
      <section aria-label="Network summary">
        <h2 className="text-lg font-semibold mb-3">Network</h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard label="Entities" value={data.entities.length} />
          <StatCard label="Relationships" value={data.relationships.length} />
          <StatCard label="Findings" value={data.findings.length} />
          <StatCard label="Communities" value={communityCount} />
        </div>
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

      {/* Findings — placeholder for E4 AnalyticsPanel */}
      <section aria-label="Investigative leads">
        <h2 className="text-lg font-semibold mb-3">Investigative Leads</h2>
        <ul className="space-y-3">
          {data.findings.map((finding) => (
            <li
              key={finding.finding_id}
              className="rounded-lg bg-gray-800 px-4 py-3 space-y-1"
            >
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-orange-900 text-orange-200">
                  {finding.rule_name}
                </span>
              </div>
              <p className="text-sm">{finding.explanation}</p>
              {/* Contract Invariant 5: disclaimer always present, unmodified */}
              <p className="text-xs text-gray-400 italic">{finding.disclaimer}</p>
            </li>
          ))}
        </ul>
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
