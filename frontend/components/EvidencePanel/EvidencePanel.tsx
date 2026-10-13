"use client";

/**
 * components/EvidencePanel/EvidencePanel.tsx
 *
 * Evidence chain view for any relationship or finding (E3, DOC3 §9.4, §12.7).
 *
 * Props accept either a pre-loaded Evidence[] (when the caller already has
 * inline evidence from §12.3) or a relationship_id/finding_id to fetch via
 * §12.7.  In Phase 0 both paths use mock data.
 */

import { useEffect, useState } from "react";
import type { Evidence } from "../../lib/types";
import { getEvidence } from "../../lib/api-client";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface EvidencePanelProps {
  /** Pre-loaded evidence (e.g. from §12.3 inline evidence). */
  evidence?: Evidence[];
  /** Fetch evidence for this relationship (§12.7). */
  relationshipId?: string;
  /** Fetch evidence for this finding (§12.7). */
  findingId?: string;
  onClose?: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function EvidencePanel({
  evidence: evidenceProp,
  relationshipId,
  findingId,
  onClose,
}: EvidencePanelProps) {
  const [evidence, setEvidence] = useState<Evidence[]>(evidenceProp ?? []);
  const [loading, setLoading] = useState(!evidenceProp);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (evidenceProp) {
      setEvidence(evidenceProp);
      setLoading(false);
      return;
    }
    if (!relationshipId && !findingId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    getEvidence({ relationship_id: relationshipId, finding_id: findingId })
      .then((res) => setEvidence(res.evidence))
      .catch(() => setError("Failed to load evidence."))
      .finally(() => setLoading(false));
  }, [evidenceProp, relationshipId, findingId]);

  return (
    <div data-testid="evidence-panel" className="bg-gray-800 rounded-lg p-4 text-sm text-slate-200">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-slate-100">Evidence</h3>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close evidence panel"
            className="text-slate-400 hover:text-slate-100 text-xs"
          >
            ✕
          </button>
        )}
      </div>

      {loading && <p className="text-slate-400">Loading evidence…</p>}
      {error && <p className="text-red-400">{error}</p>}

      {!loading && !error && evidence.length === 0 && (
        <p className="text-slate-400 italic">No evidence records found.</p>
      )}

      {!loading && !error && evidence.length > 0 && (
        <ul className="space-y-3" data-testid="evidence-list">
          {evidence.map((ev) => (
            <li
              key={ev.evidence_id}
              data-testid="evidence-item"
              className="border border-gray-700 rounded p-3 space-y-1"
            >
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono bg-gray-700 px-1.5 py-0.5 rounded text-slate-300">
                  {ev.source_type}
                </span>
                <span className="text-xs text-slate-400">{ev.source_id}</span>
              </div>
              {ev.snippet && (
                <p className="text-slate-300 text-xs leading-relaxed">
                  &ldquo;{ev.snippet}&rdquo;
                </p>
              )}
              {ev.record_timestamp && (
                <p className="text-slate-500 text-xs">
                  {new Date(ev.record_timestamp).toLocaleString()}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
