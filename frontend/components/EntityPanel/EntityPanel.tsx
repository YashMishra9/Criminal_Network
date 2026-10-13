"use client";

/**
 * components/EntityPanel/EntityPanel.tsx
 *
 * Entity detail + resolution rationale + connected relationships (E3).
 *
 * Contracts:
 *   §12.2  GET /entities/{id}  → { entity: CanonicalEntity, resolution: ResolutionDecision[] }
 *   §12.3  GET /entities/{id}/relationships → { relationships: (Relationship & { evidence: Evidence[] })[] }
 *   §9.4   Every relationship rendered here MUST have a working "view evidence" affordance.
 *
 * Phase 0: all data comes from mock mode.
 * Real-wiring: swap api-client mock flag for live C6 endpoints (Sync 2/3).
 */

import { useEffect, useState } from "react";
import type {
  CanonicalEntity,
  ResolutionDecision,
  RelationshipWithEvidence,
  Evidence,
} from "../../lib/types";
import { getEntity, getEntityRelationships } from "../../lib/api-client";
import EvidencePanel from "../EvidencePanel/EvidencePanel";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface EntityPanelProps {
  entityId: string;
  onClose?: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function EntityPanel({ entityId, onClose }: EntityPanelProps) {
  const [entity, setEntity] = useState<CanonicalEntity | null>(null);
  const [resolution, setResolution] = useState<ResolutionDecision[]>([]);
  const [relationships, setRelationships] = useState<RelationshipWithEvidence[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Which relationship's evidence is currently expanded (null = none)
  const [expandedEvidenceFor, setExpandedEvidenceFor] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setExpandedEvidenceFor(null);

    Promise.all([
      getEntity(entityId),
      getEntityRelationships(entityId),
    ])
      .then(([entityRes, relRes]) => {
        setEntity(entityRes.entity);
        setResolution(entityRes.resolution);
        setRelationships(relRes.relationships);
      })
      .catch(() => setError("Failed to load entity details."))
      .finally(() => setLoading(false));
  }, [entityId]);

  const toggleEvidence = (relationshipId: string) => {
    setExpandedEvidenceFor((prev) =>
      prev === relationshipId ? null : relationshipId
    );
  };

  if (loading) {
    return (
      <div data-testid="entity-panel" className="bg-gray-800 rounded-lg p-4 text-slate-400 text-sm">
        Loading…
      </div>
    );
  }

  if (error || !entity) {
    return (
      <div data-testid="entity-panel" className="bg-gray-800 rounded-lg p-4 text-red-400 text-sm">
        {error ?? "Entity not found."}
      </div>
    );
  }

  return (
    <div data-testid="entity-panel" className="bg-gray-800 rounded-lg p-4 text-sm text-slate-200 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="font-semibold text-slate-100 text-base">{entity.display_name}</h2>
          <span className="text-xs text-slate-400">{entity.entity_type} · {entity.dataset}</span>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close entity panel"
            className="text-slate-400 hover:text-slate-100 text-xs ml-2"
          >
            ✕
          </button>
        )}
      </div>

      {/* Attributes */}
      {Object.keys(entity.attributes).length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-1">
            Attributes
          </h3>
          <dl className="space-y-0.5">
            {Object.entries(entity.attributes).map(([k, v]) => (
              <div key={k} className="flex gap-2 text-xs">
                <dt className="text-slate-400 shrink-0">{k}:</dt>
                <dd className="text-slate-300">{String(v)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {/* Resolution rationale */}
      {resolution.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-1">
            Resolution Rationale
          </h3>
          <ul className="space-y-2" data-testid="resolution-list">
            {resolution.map((d) => (
              <li key={d.decision_id} className="border border-gray-700 rounded p-2 text-xs space-y-0.5">
                <div className="flex gap-2">
                  <span className="text-slate-400">Method:</span>
                  <span className="text-slate-300">{d.method}</span>
                </div>
                <div className="flex gap-2">
                  <span className="text-slate-400">Outcome:</span>
                  <span className={d.outcome === "merged" ? "text-green-400" : "text-red-400"}>
                    {d.outcome}
                  </span>
                </div>
                {d.matched_on.length > 0 && (
                  <div className="flex gap-2">
                    <span className="text-slate-400">Matched on:</span>
                    <span className="text-slate-300">{d.matched_on.join(", ")}</span>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Relationships — every one MUST have a "view evidence" affordance (DOC3 §9.4) */}
      <section>
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-1">
          Relationships
        </h3>
        {relationships.length === 0 ? (
          <p className="text-slate-500 italic text-xs">No relationships found.</p>
        ) : (
          <ul className="space-y-2" data-testid="relationship-list">
            {relationships.map((rel) => (
              <li
                key={rel.relationship_id}
                data-testid="relationship-item"
                className="border border-gray-700 rounded p-2 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div className="text-xs space-y-0.5">
                    <span className="font-mono text-blue-300">{rel.relationship_type}</span>
                    <div className="text-slate-400">
                      {rel.from_entity_id} → {rel.to_entity_id}
                    </div>
                  </div>
                  {/* DOC3 §9.4 — evidence affordance: required on every relationship */}
                  <button
                    data-testid="view-evidence-button"
                    onClick={() => toggleEvidence(rel.relationship_id)}
                    className="text-xs text-blue-400 hover:text-blue-200 shrink-0 ml-2"
                    aria-expanded={expandedEvidenceFor === rel.relationship_id}
                  >
                    {expandedEvidenceFor === rel.relationship_id
                      ? "Hide evidence"
                      : "View evidence"}
                  </button>
                </div>

                {/* Inline evidence panel — uses pre-loaded §12.3 evidence */}
                {expandedEvidenceFor === rel.relationship_id && (
                  <EvidencePanel
                    evidence={rel.evidence}
                    onClose={() => setExpandedEvidenceFor(null)}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
