"use client";

/**
 * components/CaseWorkspace/CaseWorkspace.tsx
 *
 * Full Case Workspace flow (E7, DOC1 W6, DOC3 §11, §12.9).
 *
 * Flow:
 *   1. Create a case (POST /cases)
 *   2. Associate entities and relationships to the case (POST /cases/{id}/entities, /relationships)
 *   3. Add investigator notes (POST /cases/{id}/notes)
 *   4. Load a summary (GET /cases/{id}/summary → CaseSummaryResult)
 *   5. View the assembled case content (GET /cases/{id})
 *
 * Error handling requirements (E7.md §11, §17, DOC3 §13, Contract Invariant 11):
 *   - dataset_isolation_violation MUST be surfaced clearly — never silently swallowed.
 *   - CaseSummaryResult.status "llm_unavailable" MUST be displayed distinctly
 *     per DOC3 §11, exactly as AskTheNetwork surfaces its variant.
 *
 * Phase 0: mock mode — api-client returns MOCK_CASE / MOCK_NOTES / MOCK_EDGE_REF etc.
 * Real-wiring at Sync 3 against G3 endpoints; no signature changes required.
 *
 * Dataset isolation: the component only creates cases with DATASET prop value
 * and the backend enforces cross-dataset rejection per Contract Invariant 11.
 */

import { useState, useCallback } from "react";
import type {
  Case,
  CanonicalEntity,
  EdgeRef,
  Evidence,
  Note,
  CaseSummaryResult,
} from "../../lib/types";
import {
  createCase,
  getCase,
  addCaseEntity,
  addCaseRelationship,
  addCaseNote,
  getCaseSummary,
} from "../../lib/api-client";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface CaseWorkspaceProps {
  /** Dataset the workspace operates in. Must equal the entities' datasets. */
  dataset?: string;
  /**
   * Pre-selected entity IDs from the main NetworkView/EntityPanel — the
   * investigator can add them to the case with a single click.
   */
  selectedEntityId?: string | null;
  /**
   * Pre-selected relationship ID from the main NetworkView/EntityPanel.
   */
  selectedRelationshipId?: string | null;
}

// ---------------------------------------------------------------------------
// Internal types
// ---------------------------------------------------------------------------

interface CaseDetail {
  case: Case;
  entities: CanonicalEntity[];
  edge_refs: EdgeRef[];
  evidence: Evidence[];
  notes: Note[];
}

// ---------------------------------------------------------------------------
// Sub-renderers
// ---------------------------------------------------------------------------

/** Renders a dataset_isolation_violation or other API error clearly (E7.md §17). */
function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      data-testid="case-error-banner"
      role="alert"
      aria-live="assertive"
      className="rounded-lg border border-red-700 bg-red-950 p-3 text-sm text-red-200"
    >
      <p className="font-semibold text-red-400 text-xs uppercase tracking-wide mb-1">
        Error
      </p>
      <p>{message}</p>
    </div>
  );
}

/** Renders a dataset_isolation_violation specifically — must be visible and labelled. */
function IsolationViolationBanner({ message }: { message: string }) {
  return (
    <div
      data-testid="case-isolation-violation-banner"
      role="alert"
      aria-live="assertive"
      className="rounded-lg border border-orange-700 bg-orange-950 p-3 text-sm text-orange-200"
    >
      <p className="font-semibold text-orange-400 text-xs uppercase tracking-wide mb-1">
        Dataset Isolation Violation
      </p>
      <p>{message}</p>
      <p className="text-xs text-orange-600 italic mt-1">
        You can only associate items from the same dataset as this case (
        <span className="font-mono">{}</span>).
      </p>
    </div>
  );
}

/** CaseSummaryResult — "ok" variant */
function SummaryOk({
  result,
}: {
  result: Extract<CaseSummaryResult, { status: "ok" }>;
}) {
  return (
    <div
      data-testid="case-summary-ok"
      className="rounded-lg bg-gray-700 p-3 text-sm text-slate-200 space-y-1"
    >
      <p className="text-xs text-slate-400 uppercase tracking-wide font-semibold">
        AI Case Summary
      </p>
      <p data-testid="case-summary-text">{result.summary}</p>
      <p className="text-xs text-slate-500">
        Generated {new Date(result.generated_at).toLocaleString()}
      </p>
    </div>
  );
}

/**
 * CaseSummaryResult — "llm_unavailable" variant.
 * MUST be displayed distinctly — never hidden or shown as empty (DOC3 §11).
 */
function SummaryLlmUnavailable({
  result,
}: {
  result: Extract<CaseSummaryResult, { status: "llm_unavailable" }>;
}) {
  return (
    <div
      data-testid="case-summary-llm-unavailable"
      role="alert"
      aria-live="assertive"
      className="rounded-lg border border-yellow-700 bg-yellow-950 p-3 text-sm text-yellow-200 space-y-1"
    >
      <p className="text-xs font-semibold text-yellow-400 uppercase tracking-wide">
        AI Assistant Unavailable
      </p>
      <p>{result.message}</p>
      <p className="text-xs text-yellow-600 italic">
        The case data is still available below — you can review entities,
        relationships, and notes manually.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function CaseWorkspace({
  dataset = "synthetic_demo",
  selectedEntityId = null,
  selectedRelationshipId = null,
}: CaseWorkspaceProps) {
  // --- Creation form state ---
  const [titleInput, setTitleInput] = useState("");
  const [creating, setCreating] = useState(false);

  // --- Active case state ---
  const [activeCase, setActiveCase] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(false);

  // --- Note form state ---
  const [noteText, setNoteText] = useState("");
  const [addingNote, setAddingNote] = useState(false);

  // --- Summary state ---
  const [summary, setSummary] = useState<CaseSummaryResult | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  // --- Error state — tracks both general errors and isolation violations ---
  const [error, setError] = useState<string | null>(null);
  const [isolationError, setIsolationError] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Error parsing — identify dataset_isolation_violation from api error
  // ---------------------------------------------------------------------------

  const parseApiError = useCallback(
    (err: unknown): { isIsolation: boolean; message: string } => {
      if (err instanceof Error) {
        const e = err as Error & { errorBody?: { error?: { type?: string; message?: string } } };
        if (e.errorBody?.error?.type === "dataset_isolation_violation") {
          return {
            isIsolation: true,
            message:
              e.errorBody.error.message ??
              "Dataset isolation violation: items must share the case's dataset.",
          };
        }
        return { isIsolation: false, message: e.message };
      }
      return { isIsolation: false, message: "An unexpected error occurred." };
    },
    []
  );

  const handleError = useCallback(
    (err: unknown) => {
      const { isIsolation, message } = parseApiError(err);
      if (isIsolation) {
        setIsolationError(message);
        setError(null);
      } else {
        setError(message);
        setIsolationError(null);
      }
    },
    [parseApiError]
  );

  // ---------------------------------------------------------------------------
  // Case creation
  // ---------------------------------------------------------------------------

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const title = titleInput.trim();
    if (!title) return;
    setCreating(true);
    setError(null);
    setIsolationError(null);
    try {
      const newCase = await createCase(title, dataset);
      const detail = await getCase(newCase.case_id);
      setActiveCase(detail);
      setTitleInput("");
      setSummary(null);
    } catch (err) {
      handleError(err);
    } finally {
      setCreating(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Reload case (refresh entity/edge/evidence/note lists)
  // ---------------------------------------------------------------------------

  const reloadCase = useCallback(async (caseId: string) => {
    setLoading(true);
    try {
      const detail = await getCase(caseId);
      setActiveCase(detail);
    } catch (err) {
      handleError(err);
    } finally {
      setLoading(false);
    }
  }, [handleError]);

  // ---------------------------------------------------------------------------
  // Add entity
  // ---------------------------------------------------------------------------

  const handleAddEntity = async (entityId: string) => {
    if (!activeCase) return;
    setError(null);
    setIsolationError(null);
    try {
      await addCaseEntity(activeCase.case.case_id, entityId);
      await reloadCase(activeCase.case.case_id);
    } catch (err) {
      handleError(err);
    }
  };

  // ---------------------------------------------------------------------------
  // Add relationship
  // ---------------------------------------------------------------------------

  const handleAddRelationship = async (relationshipId: string) => {
    if (!activeCase) return;
    setError(null);
    setIsolationError(null);
    try {
      await addCaseRelationship(activeCase.case.case_id, relationshipId);
      await reloadCase(activeCase.case.case_id);
    } catch (err) {
      handleError(err);
    }
  };

  // ---------------------------------------------------------------------------
  // Add note
  // ---------------------------------------------------------------------------

  const handleAddNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeCase || !noteText.trim()) return;
    setAddingNote(true);
    setError(null);
    setIsolationError(null);
    try {
      await addCaseNote(activeCase.case.case_id, noteText.trim());
      setNoteText("");
      await reloadCase(activeCase.case.case_id);
    } catch (err) {
      handleError(err);
    } finally {
      setAddingNote(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Generate summary
  // ---------------------------------------------------------------------------

  const handleGenerateSummary = async () => {
    if (!activeCase) return;
    setSummaryLoading(true);
    setError(null);
    setIsolationError(null);
    setSummary(null);
    try {
      const result = await getCaseSummary(activeCase.case.case_id);
      setSummary(result);
    } catch (err) {
      handleError(err);
    } finally {
      setSummaryLoading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      data-testid="case-workspace"
      className="bg-gray-800 rounded-lg p-4 space-y-4 text-sm text-slate-200"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-slate-100">Case Workspace</h2>
        {activeCase && (
          <span className="text-xs text-slate-400 font-mono">
            {activeCase.case.case_id}
          </span>
        )}
      </div>

      {/* Error banners — rendered prominently before the form */}
      {isolationError && (
        <IsolationViolationBanner message={isolationError} />
      )}
      {error && !isolationError && <ErrorBanner message={error} />}

      {/* --- Create case form (shown when no active case) --- */}
      {!activeCase && (
        <form
          data-testid="create-case-form"
          onSubmit={handleCreate}
          className="space-y-2"
        >
          <label
            htmlFor="case-title-input"
            className="block text-xs text-slate-400"
          >
            New case title
          </label>
          <div className="flex gap-2">
            <input
              id="case-title-input"
              data-testid="case-title-input"
              type="text"
              value={titleInput}
              onChange={(e) => setTitleInput(e.target.value)}
              placeholder="e.g. Operation Apex"
              disabled={creating}
              aria-label="Case title"
              className={[
                "flex-1 rounded bg-gray-700 border border-gray-600 px-3 py-1.5 text-sm",
                "text-slate-200 placeholder-slate-500 outline-none",
                "focus:border-blue-500 focus:ring-1 focus:ring-blue-500",
                "disabled:opacity-40 disabled:cursor-not-allowed",
              ].join(" ")}
            />
            <button
              data-testid="create-case-button"
              type="submit"
              disabled={creating || !titleInput.trim()}
              className={[
                "px-3 py-1.5 rounded text-sm font-medium transition-colors",
                "bg-blue-600 text-white hover:bg-blue-500",
                "disabled:opacity-40 disabled:cursor-not-allowed",
              ].join(" ")}
            >
              {creating ? "Creating…" : "Create Case"}
            </button>
          </div>
          <p className="text-xs text-slate-500">
            Dataset: <span className="font-mono">{dataset}</span>
          </p>
        </form>
      )}

      {/* --- Active case view --- */}
      {activeCase && (
        <div data-testid="active-case-view" className="space-y-4">
          {/* Case header */}
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="font-semibold text-slate-100" data-testid="case-title">
                {activeCase.case.title}
              </p>
              <p className="text-xs text-slate-400">
                Status:{" "}
                <span
                  className={
                    activeCase.case.status === "open"
                      ? "text-green-400"
                      : "text-slate-500"
                  }
                >
                  {activeCase.case.status}
                </span>
                {" · "}
                Dataset:{" "}
                <span className="font-mono">{activeCase.case.dataset}</span>
              </p>
            </div>
            <button
              data-testid="close-case-button"
              onClick={() => {
                setActiveCase(null);
                setSummary(null);
                setError(null);
                setIsolationError(null);
              }}
              className="text-xs text-slate-400 hover:text-slate-200 shrink-0"
              aria-label="Close case workspace"
            >
              Close
            </button>
          </div>

          {/* --- Add entity from selection --- */}
          {selectedEntityId && (
            <div className="flex items-center gap-2 rounded bg-gray-700 px-3 py-2">
              <span className="text-xs text-slate-400 flex-1">
                Selected entity:{" "}
                <span className="font-mono">{selectedEntityId}</span>
              </span>
              <button
                data-testid="add-entity-button"
                onClick={() => handleAddEntity(selectedEntityId)}
                disabled={loading}
                className="text-xs px-2 py-1 rounded bg-blue-700 hover:bg-blue-600 text-white disabled:opacity-40"
                aria-label="Add selected entity to case"
              >
                + Add to case
              </button>
            </div>
          )}

          {/* --- Add relationship from selection --- */}
          {selectedRelationshipId && (
            <div className="flex items-center gap-2 rounded bg-gray-700 px-3 py-2">
              <span className="text-xs text-slate-400 flex-1">
                Selected relationship:{" "}
                <span className="font-mono">{selectedRelationshipId}</span>
              </span>
              <button
                data-testid="add-relationship-button"
                onClick={() => handleAddRelationship(selectedRelationshipId)}
                disabled={loading}
                className="text-xs px-2 py-1 rounded bg-purple-700 hover:bg-purple-600 text-white disabled:opacity-40"
                aria-label="Add selected relationship to case"
              >
                + Add to case
              </button>
            </div>
          )}

          {/* --- Entities list --- */}
          <div>
            <p className="text-xs text-slate-400 font-medium mb-1">
              Entities ({activeCase.entities.length})
            </p>
            {activeCase.entities.length === 0 ? (
              <p className="text-xs text-slate-500 italic">
                No entities added yet.
              </p>
            ) : (
              <ul
                data-testid="case-entities-list"
                className="space-y-1"
              >
                {activeCase.entities.map((ent) => (
                  <li
                    key={ent.entity_id}
                    className="flex items-center gap-2 text-xs rounded bg-gray-700 px-2 py-1"
                    data-testid="case-entity-item"
                  >
                    <span className="text-gray-400 font-mono text-xs">
                      {ent.entity_type}
                    </span>
                    <span>{ent.display_name}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* --- Edge refs list --- */}
          <div>
            <p className="text-xs text-slate-400 font-medium mb-1">
              Relationships ({activeCase.edge_refs.length})
            </p>
            {activeCase.edge_refs.length === 0 ? (
              <p className="text-xs text-slate-500 italic">
                No relationships added yet.
              </p>
            ) : (
              <ul
                data-testid="case-edge-refs-list"
                className="space-y-1"
              >
                {activeCase.edge_refs.map((ref) => (
                  <li
                    key={ref.edge_ref_id}
                    className="text-xs rounded bg-gray-700 px-2 py-1 font-mono"
                    data-testid="case-edge-ref-item"
                  >
                    {ref.from_entity_id}{" "}
                    <span className="text-purple-400">{ref.relationship_type}</span>{" "}
                    {ref.to_entity_id}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* --- Notes list --- */}
          <div>
            <p className="text-xs text-slate-400 font-medium mb-1">
              Notes ({activeCase.notes.length})
            </p>
            {activeCase.notes.length === 0 ? (
              <p className="text-xs text-slate-500 italic">No notes yet.</p>
            ) : (
              <ul
                data-testid="case-notes-list"
                className="space-y-1"
              >
                {activeCase.notes.map((note) => (
                  <li
                    key={note.note_id}
                    className="text-xs rounded bg-gray-700 px-2 py-1.5"
                    data-testid="case-note-item"
                  >
                    {note.text}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* --- Add note form --- */}
          <form
            data-testid="add-note-form"
            onSubmit={handleAddNote}
            className="flex gap-2"
          >
            <input
              id="case-note-input"
              data-testid="case-note-input"
              type="text"
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="Add an investigator note…"
              disabled={addingNote}
              aria-label="Investigator note text"
              className={[
                "flex-1 rounded bg-gray-700 border border-gray-600 px-3 py-1.5 text-xs",
                "text-slate-200 placeholder-slate-500 outline-none",
                "focus:border-blue-500 focus:ring-1 focus:ring-blue-500",
                "disabled:opacity-40 disabled:cursor-not-allowed",
              ].join(" ")}
            />
            <button
              data-testid="add-note-button"
              type="submit"
              disabled={addingNote || !noteText.trim()}
              className="text-xs px-2 py-1.5 rounded bg-gray-600 hover:bg-gray-500 text-white disabled:opacity-40"
              aria-label="Add note to case"
            >
              {addingNote ? "Adding…" : "Add Note"}
            </button>
          </form>

          {/* --- Summary section --- */}
          <div className="border-t border-gray-700 pt-3 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs text-slate-400 font-medium">
                Case Summary
              </p>
              <button
                data-testid="generate-summary-button"
                onClick={handleGenerateSummary}
                disabled={summaryLoading}
                className={[
                  "text-xs px-2 py-1 rounded font-medium transition-colors",
                  "bg-indigo-700 hover:bg-indigo-600 text-white",
                  "disabled:opacity-40 disabled:cursor-not-allowed",
                ].join(" ")}
                aria-label="Generate AI case summary"
              >
                {summaryLoading ? "Generating…" : "Generate Summary"}
              </button>
            </div>

            {summaryLoading && (
              <p
                data-testid="summary-loading"
                className="text-xs text-slate-400 italic animate-pulse"
              >
                Generating summary…
              </p>
            )}

            {/* Both CaseSummaryResult variants rendered distinctly */}
            {summary && !summaryLoading && (
              <>
                {summary.status === "ok" && <SummaryOk result={summary} />}
                {summary.status === "llm_unavailable" && (
                  <SummaryLlmUnavailable result={summary} />
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
