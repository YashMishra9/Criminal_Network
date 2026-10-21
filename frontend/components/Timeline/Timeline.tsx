"use client";

/**
 * components/Timeline/Timeline.tsx
 *
 * Network Time Machine slider (E4, DOC1 W4, DOC3 §2.4A, §12.4).
 *
 * Contracts:
 *   §12.4  GET /graph?as_of=   — re-queried when slider moves
 *   §12.5  GET /analytics?as_of=
 *   §12.6  GET /patterns?as_of=
 *   §2.4A  as_of semantics: relationship-level filter; entity visibility derived from it
 *
 * Phase 0: mock mode — api-client returns fixture data regardless of as_of.
 * Real-wiring: live C6/D5 endpoints apply as_of filtering at query time (Sync 3).
 *
 * The slider maps a discrete integer position to a concrete ISO-8601 date
 * derived from the earliest and latest relationship valid_from values in the
 * current dataset. The caller receives the chosen as_of string so it can drive
 * re-fetches at the page level.
 */

import { useCallback } from "react";
import type { Relationship } from "../../lib/types";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface TimelineProps {
  /**
   * All relationships currently known — used to compute the earliest/latest
   * date bounds for the slider. May be empty (slider is disabled).
   */
  relationships: Relationship[];

  /**
   * The currently active as_of ISO-8601 string, or null for "full current
   * graph" (no temporal filter applied).
   */
  asOf: string | null;

  /**
   * Called whenever the slider position changes, with the new as_of value
   * (ISO-8601 datetime string at end-of-day UTC) or null when the slider is
   * dragged all the way to the right (meaning "show full graph / no filter").
   *
   * The parent is responsible for re-fetching GET /graph, /analytics, and
   * /patterns with the new as_of value (E4.md §10).
   */
  onAsOfChange: (asOf: string | null) => void;

  /** Loading state from the parent — disables the slider while data is in flight. */
  loading?: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns YYYY-MM-DD from an ISO-8601 string (date part only, UTC). */
function isoDatePart(iso: string): string {
  return iso.slice(0, 10);
}

/** Converts a YYYY-MM-DD string to a Unix timestamp (ms) for arithmetic. */
function dateToMs(dateStr: string): number {
  return new Date(dateStr + "T00:00:00Z").getTime();
}

/** Converts a Unix timestamp (ms) to a YYYY-MM-DD string (UTC). */
function msToDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/**
 * Derives the [minDate, maxDate] bounds from the provided relationships.
 * Uses valid_from as the temporal anchor (DOC3 §2.4 / §6.6).
 * Returns null when no relationships are available (disabled state).
 */
function computeBounds(
  relationships: Relationship[]
): { minDate: string; maxDate: string } | null {
  if (relationships.length === 0) return null;
  const dates = relationships
    .map((r) => isoDatePart(r.valid_from))
    .filter(Boolean)
    .sort();
  if (dates.length === 0) return null;
  return { minDate: dates[0], maxDate: dates[dates.length - 1] };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Number of discrete steps the slider offers between minDate and maxDate.
 * 100 steps gives day-level granularity for a ~3-month span — sufficient for
 * the prototype per DOC1 §4 W4 / §10 assumption (day-level granularity).
 */
const SLIDER_STEPS = 100;

export default function Timeline({
  relationships,
  asOf,
  onAsOfChange,
  loading = false,
}: TimelineProps) {
  const bounds = computeBounds(relationships);
  const disabled = loading || !bounds;

  /**
   * Derives the current slider integer position (0–SLIDER_STEPS) from
   * the asOf prop.  SLIDER_STEPS means "no filter" (full current graph).
   */
  const currentPosition = useCallback((): number => {
    if (!bounds || asOf === null) return SLIDER_STEPS;
    const minMs = dateToMs(bounds.minDate);
    const maxMs = dateToMs(bounds.maxDate);
    if (maxMs === minMs) return 0;
    const targetMs = dateToMs(asOf.slice(0, 10));
    const ratio = (targetMs - minMs) / (maxMs - minMs);
    return Math.round(Math.min(1, Math.max(0, ratio)) * (SLIDER_STEPS - 1));
  }, [bounds, asOf]);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (!bounds) return;
      const pos = Number(e.target.value);
      if (pos >= SLIDER_STEPS) {
        // All the way right → remove temporal filter (full graph)
        onAsOfChange(null);
        return;
      }
      const minMs = dateToMs(bounds.minDate);
      const maxMs = dateToMs(bounds.maxDate);
      const ratio = pos / (SLIDER_STEPS - 1);
      const targetMs = minMs + ratio * (maxMs - minMs);
      // End-of-day UTC so the chosen date is fully included
      onAsOfChange(msToDate(targetMs) + "T23:59:59Z");
    },
    [bounds, onAsOfChange]
  );

  // Human-readable label for the current as_of value shown above the slider
  const label: string = asOf
    ? `Showing network as of ${isoDatePart(asOf)}`
    : "Showing full current graph";

  return (
    <div data-testid="timeline" className="bg-gray-800 rounded-lg p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-100">
          Network Time Machine
        </h2>
        {asOf && (
          <button
            data-testid="timeline-reset"
            onClick={() => onAsOfChange(null)}
            disabled={disabled}
            className="text-xs text-blue-400 hover:text-blue-200 disabled:opacity-40"
            aria-label="Reset timeline to full current graph"
          >
            Reset
          </button>
        )}
      </div>

      {/* Current label */}
      <p
        data-testid="timeline-label"
        className="text-xs text-slate-400 font-mono"
      >
        {label}
      </p>

      {/* Slider */}
      <div className="flex items-center gap-3">
        {bounds && (
          <span className="text-xs text-slate-500 shrink-0 font-mono">
            {bounds.minDate}
          </span>
        )}
        <input
          data-testid="timeline-slider"
          type="range"
          min={0}
          max={SLIDER_STEPS}
          step={1}
          value={currentPosition()}
          onChange={handleChange}
          disabled={disabled}
          aria-label="Timeline slider — adjust network as_of date"
          aria-valuetext={label}
          className={[
            "flex-1 h-2 rounded-full appearance-none cursor-pointer",
            "bg-gray-600 accent-blue-500",
            "disabled:opacity-40 disabled:cursor-not-allowed",
          ].join(" ")}
        />
        {bounds && (
          <span className="text-xs text-slate-500 shrink-0 font-mono">
            {bounds.maxDate}
          </span>
        )}
      </div>

      {/* Fallback helper text when no relationships */}
      {!bounds && (
        <p className="text-xs text-slate-500 italic">
          {loading ? "Loading relationships…" : "No relationships available."}
        </p>
      )}
    </div>
  );
}
