"use client";

/**
 * components/AnalyticsPanel/AnalyticsPanel.tsx
 *
 * Analytics summary + pattern/finding display (E4, DOC1 W3, DOC3 §12.5–12.6).
 *
 * Contracts:
 *   §12.5  GET /analytics  → AnalyticsResult (centrality, communities)
 *   §12.6  GET /patterns   → { findings: Finding[] }
 *   §1.8   Every Finding MUST display Finding.disclaimer verbatim — Contract Invariant 5.
 *   §9.4   Every Finding rendered here MUST have a reachable evidence affordance.
 *
 * Phase 0: data comes from mock mode; real-wiring post-D5 (Sync 3).
 *
 * CRITICAL — Contract Invariant 5 (DOC3 §15):
 *   "Every flagged pattern carries the investigative-lead disclaimer, unmodified,
 *    every time it is displayed or returned."
 *   The disclaimer is rendered verbatim from Finding.disclaimer — it is NEVER
 *   reworded, omitted, or conditionally shown (E4.md §11, §17).
 */

import { useEffect, useState } from "react";
import type { AnalyticsResult, Finding, Evidence } from "../../lib/types";
import { getAnalytics, getPatterns, getEvidence } from "../../lib/api-client";
import EvidencePanel from "../EvidencePanel/EvidencePanel";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface AnalyticsPanelProps {
  /**
   * Current as_of value (ISO-8601) from the Timeline slider, or null for the
   * full current graph. Changing this prop triggers re-fetches of both
   * /analytics and /patterns (E4.md §10).
   */
  asOf: string | null;
  dataset?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AnalyticsPanel({
  asOf,
  dataset = "synthetic_demo",
}: AnalyticsPanelProps) {
  const [analytics, setAnalytics] = useState<AnalyticsResult | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Which finding's evidence is expanded (null = none)
  const [expandedEvidenceFor, setExpandedEvidenceFor] = useState<string | null>(
    null
  );

  // Re-fetch whenever asOf or dataset changes (E4.md §10)
  useEffect(() => {
    setLoading(true);
    setError(null);
    setExpandedEvidenceFor(null);

    Promise.all([
      getAnalytics({ dataset, as_of: asOf ?? undefined }),
      getPatterns({ dataset, as_of: asOf ?? undefined }),
    ])
      .then(([analyticsData, patternsData]) => {
        setAnalytics(analyticsData);
        setFindings(patternsData.findings);
      })
      .catch(() => setError("Failed to load analytics data."))
      .finally(() => setLoading(false));
  }, [asOf, dataset]);

  const toggleEvidence = (findingId: string) => {
    setExpandedEvidenceFor((prev) =>
      prev === findingId ? null : findingId
    );
  };

  // ---------------------------------------------------------------------------
  // Community summary helpers
  // ---------------------------------------------------------------------------

  const communityMap: Record<string, string[]> = {};
  if (analytics) {
    for (const { entity_id, community_id } of analytics.communities) {
      if (!communityMap[community_id]) communityMap[community_id] = [];
      communityMap[community_id].push(entity_id);
    }
  }
  const communityIds = Object.keys(communityMap).sort();

  // Top-5 by betweenness centrality
  const topByBetweenness = analytics
    ? [...analytics.centrality]
        .sort((a, b) => b.betweenness - a.betweenness)
        .slice(0, 5)
    : [];

  // ---------------------------------------------------------------------------
  // Loading / error states
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div data-testid="analytics-panel" className="bg-gray-800 rounded-lg p-4 text-slate-400 text-sm">
        Loading analytics…
      </div>
    );
  }

  if (error) {
    return (
      <div data-testid="analytics-panel" className="bg-gray-800 rounded-lg p-4 text-red-400 text-sm">
        {error}
      </div>
    );
  }

  return (
    <div data-testid="analytics-panel" className="bg-gray-800 rounded-lg p-4 text-sm text-slate-200 space-y-5">
      {/* ------------------------------------------------------------------ */}
      {/* Header                                                               */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-slate-100">Analytics &amp; Patterns</h2>
        {asOf && (
          <span
            data-testid="analytics-as-of-badge"
            className="text-xs font-mono px-2 py-0.5 rounded bg-blue-900 text-blue-200"
          >
            as_of {asOf.slice(0, 10)}
          </span>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Centrality — top entities by betweenness                            */}
      {/* ------------------------------------------------------------------ */}
      {analytics && topByBetweenness.length > 0 && (
        <section data-testid="centrality-section">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">
            Key Entities (Betweenness Centrality)
          </h3>
          <ul className="space-y-1" data-testid="centrality-list">
            {topByBetweenness.map((row, idx) => (
              <li
                key={row.entity_id}
                data-testid="centrality-item"
                className="flex items-center gap-2 text-xs"
              >
                <span className="text-slate-500 w-5 text-right shrink-0">
                  {idx + 1}.
                </span>
                <span className="font-mono text-slate-300 flex-1 truncate">
                  {row.entity_id}
                </span>
                <span className="text-slate-400 shrink-0">
                  btw:{" "}
                  <span className="text-slate-200 font-mono">
                    {row.betweenness.toFixed(2)}
                  </span>
                </span>
                <span className="text-slate-400 shrink-0">
                  pr:{" "}
                  <span className="text-slate-200 font-mono">
                    {row.pagerank.toFixed(2)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Communities                                                          */}
      {/* ------------------------------------------------------------------ */}
      {analytics && communityIds.length > 0 && (
        <section data-testid="communities-section">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">
            Communities ({communityIds.length})
          </h3>
          <ul className="space-y-1" data-testid="community-list">
            {communityIds.map((cid) => (
              <li
                key={cid}
                data-testid="community-item"
                className="flex items-center gap-2 text-xs"
              >
                <span
                  className="font-mono px-1.5 py-0.5 rounded text-xs bg-purple-900 text-purple-200"
                >
                  {cid}
                </span>
                <span className="text-slate-400">
                  {communityMap[cid].length} member
                  {communityMap[cid].length !== 1 ? "s" : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Findings / Pattern detection                                         */}
      {/*                                                                      */}
      {/* Contract Invariant 5 (DOC3 §15, E4.md §11):                        */}
      {/*   The disclaimer MUST be visible alongside every rendered Finding.  */}
      {/*   It is rendered verbatim from Finding.disclaimer; it must NEVER be */}
      {/*   omitted, reworded, or conditionally hidden.                       */}
      {/* ------------------------------------------------------------------ */}
      <section data-testid="findings-section">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">
          Investigative Leads ({findings.length})
        </h3>

        {findings.length === 0 ? (
          <p className="text-slate-500 italic text-xs">
            No flagged patterns for this time window.
          </p>
        ) : (
          <ul className="space-y-3" data-testid="findings-list">
            {findings.map((finding) => (
              <li
                key={finding.finding_id}
                data-testid="finding-item"
                className="border border-gray-700 rounded p-3 space-y-2"
              >
                {/* Rule badge + explanation */}
                <div className="flex items-start gap-2">
                  <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-orange-900 text-orange-200 shrink-0">
                    {finding.rule_name}
                  </span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  {finding.explanation}
                </p>

                {/* Triggering values */}
                {Object.keys(finding.triggering_values).length > 0 && (
                  <dl className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
                    {Object.entries(finding.triggering_values).map(([k, v]) => (
                      <div key={k} className="flex gap-1">
                        <dt className="text-slate-500">{k}:</dt>
                        <dd className="text-slate-300 font-mono">{String(v)}</dd>
                      </div>
                    ))}
                  </dl>
                )}

                {/* View evidence affordance — DOC3 §9.4 */}
                <button
                  data-testid="finding-view-evidence-button"
                  onClick={() => toggleEvidence(finding.finding_id)}
                  className="text-xs text-blue-400 hover:text-blue-200"
                  aria-expanded={expandedEvidenceFor === finding.finding_id}
                >
                  {expandedEvidenceFor === finding.finding_id
                    ? "Hide evidence"
                    : "View evidence"}
                </button>

                {/* Inline evidence panel (DOC3 §9.4) */}
                {expandedEvidenceFor === finding.finding_id && (
                  <EvidencePanel
                    findingId={finding.finding_id}
                    onClose={() => setExpandedEvidenceFor(null)}
                  />
                )}

                {/* -------------------------------------------------------- */}
                {/* Contract Invariant 5 — disclaimer, ALWAYS present,       */}
                {/* rendered verbatim from Finding.disclaimer, unconditional. */}
                {/* -------------------------------------------------------- */}
                <p
                  data-testid="finding-disclaimer"
                  className="text-xs text-slate-500 italic border-t border-gray-700 pt-2 mt-1"
                >
                  {finding.disclaimer}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
