"use client";

/**
 * components/AskTheNetwork/AskTheNetwork.tsx
 *
 * Chat-style NL question input for the Ask-the-Network feature (E6).
 *
 * Contracts:
 *   POST /ask → AskResponse (DOC3 §12.8 / §10)
 *
 * AskResponse is a discriminated union with four variants (DOC3 §10, types.ts):
 *   "ok"               — narration + path + evidence (success)
 *   "llm_unavailable"  — LLM is down; must be surfaced honestly (E6.md §17,
 *                        Contract Invariant 4 — LLM unavailability never blocks
 *                        core functionality but must be disclosed, not hidden)
 *   "validation_failed"— generated Cypher failed validation; show reason
 *   "no_result"        — query executed, no graph data matched
 *
 * CRITICAL (E6.md §17 / DOC3 §15 Invariant 3):
 *   "llm_unavailable" MUST be displayed as a distinct, labelled degraded state.
 *   It must NEVER be rendered as an empty answer, a generic error, or
 *   "no result" — the user must be able to tell the LLM was unavailable.
 *
 * CRITICAL (E6.md §17 / DOC3 §15 Invariant 3):
 *   The LLM never originates factual claims reaching the user.
 *   Narration is displayed verbatim but sourced only from query_result —
 *   the component never fabricates or summarises beyond what the server returns.
 *
 * Phase 0: mock mode returns MOCK_ASK_RESPONSE_OK.
 * The component also exposes a mock-variant override via `mockResponseStatus`
 * prop so all four states can be tested in isolation (test-only).
 */

import { useState } from "react";
import type { AskRequest, AskResponse, Evidence } from "../../lib/types";
import { ask } from "../../lib/api-client";
import EvidencePanel from "../EvidencePanel/EvidencePanel";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface AskTheNetworkProps {
  /** Active dataset — passed through to AskRequest (DOC3 §10). */
  dataset?: string;
  /** Active as_of from the Timeline slider — passed through to AskRequest. */
  asOf?: string | null;
  /**
   * TEST-ONLY: override which mock AskResponse variant the component renders.
   * In production, the server determines the variant. Ignored in real mode.
   * This lets all four variants be exercised in unit tests without re-mocking
   * the entire api-client.
   */
  _testMockStatus?: AskResponse["status"] | null;
}

// ---------------------------------------------------------------------------
// Sub-renderers — one per AskResponse variant
// ---------------------------------------------------------------------------

/** "ok" — success: narration + path summary + evidence */
function OkResult({
  response,
}: {
  response: Extract<AskResponse, { status: "ok" }>;
}) {
  const [showEvidence, setShowEvidence] = useState(false);
  const entityCount = response.path.entities.length;
  const relCount = response.path.relationships.length;

  return (
    <div data-testid="ask-result-ok" className="space-y-3">
      {/* Narration */}
      <div className="rounded-lg bg-gray-700 p-3 text-sm text-slate-200 leading-relaxed">
        <p className="text-xs text-slate-400 uppercase tracking-wide font-semibold mb-1">
          Network Answer
        </p>
        <p data-testid="ask-narration">{response.narration}</p>
      </div>

      {/* Path summary */}
      <div className="text-xs text-slate-400 flex gap-4">
        <span>
          <span className="text-slate-200 font-mono">{entityCount}</span>{" "}
          {entityCount === 1 ? "entity" : "entities"}
        </span>
        <span>
          <span className="text-slate-200 font-mono">{relCount}</span>{" "}
          {relCount === 1 ? "relationship" : "relationships"}
        </span>
        <span>
          <span className="text-slate-200 font-mono">
            {response.evidence.length}
          </span>{" "}
          evidence item{response.evidence.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Evidence affordance — DOC3 §9.4 */}
      {response.evidence.length > 0 && (
        <>
          <button
            data-testid="ask-view-evidence-button"
            onClick={() => setShowEvidence((v) => !v)}
            className="text-xs text-blue-400 hover:text-blue-200"
            aria-expanded={showEvidence}
          >
            {showEvidence ? "Hide evidence" : "View evidence"}
          </button>
          {showEvidence && (
            <EvidencePanel
              evidence={response.evidence}
              onClose={() => setShowEvidence(false)}
            />
          )}
        </>
      )}
    </div>
  );
}

/**
 * "llm_unavailable" — MUST be displayed distinctly and honestly.
 * Contract Invariant 4: LLM unavailability never blocks core functionality
 * but must be disclosed, not hidden or disguised as "no result".
 */
function LlmUnavailableResult({
  response,
}: {
  response: Extract<AskResponse, { status: "llm_unavailable" }>;
}) {
  return (
    <div
      data-testid="ask-result-llm-unavailable"
      className="rounded-lg border border-yellow-700 bg-yellow-950 p-3 space-y-1"
      role="alert"
      aria-live="assertive"
    >
      <p className="text-xs font-semibold text-yellow-400 uppercase tracking-wide">
        AI Assistant Unavailable
      </p>
      <p className="text-sm text-yellow-200">{response.message}</p>
      <p className="text-xs text-yellow-600 italic">
        The graph is still available — explore entities and relationships
        directly using the panels above.
      </p>
    </div>
  );
}

/**
 * "validation_failed" — query was generated but failed safety/schema validation.
 * Must show the reason explicitly per E6.md §17.
 */
function ValidationFailedResult({
  response,
}: {
  response: Extract<AskResponse, { status: "validation_failed" }>;
}) {
  return (
    <div
      data-testid="ask-result-validation-failed"
      className="rounded-lg border border-red-800 bg-red-950 p-3 space-y-1"
      role="alert"
    >
      <p className="text-xs font-semibold text-red-400 uppercase tracking-wide">
        Query Validation Failed
      </p>
      <p className="text-sm text-red-200" data-testid="ask-validation-reason">
        {response.reason}
      </p>
      <p className="text-xs text-red-600 italic">
        Try rephrasing your question to avoid restricted operations.
      </p>
    </div>
  );
}

/**
 * "no_result" — query ran but the graph returned no matching data.
 * Distinct from llm_unavailable and validation_failed.
 */
function NoResultResult({
  response,
}: {
  response: Extract<AskResponse, { status: "no_result" }>;
}) {
  return (
    <div
      data-testid="ask-result-no-result"
      className="rounded-lg border border-gray-600 bg-gray-900 p-3 space-y-1"
    >
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
        No Result
      </p>
      <p className="text-sm text-slate-300">{response.message}</p>
      <p className="text-xs text-slate-500 italic">
        Try broadening your question or adjusting filters.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AskTheNetwork({
  dataset = "synthetic_demo",
  asOf = null,
  _testMockStatus = null,
}: AskTheNetworkProps) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;

    setLoading(true);
    setResponse(null);
    setError(null);

    try {
      const req: AskRequest = {
        question: trimmed,
        dataset,
        as_of: asOf,
      };
      let result = await ask(req);

      // TEST-ONLY: swap mock response to the requested variant so all four
      // states can be exercised in unit tests without re-mocking api-client.
      if (_testMockStatus && _testMockStatus !== result.status) {
        const { MOCK_ASK_RESPONSE_LLM_UNAVAILABLE,
                MOCK_ASK_RESPONSE_VALIDATION_FAILED,
                MOCK_ASK_RESPONSE_NO_RESULT,
                MOCK_ASK_RESPONSE_OK } = await import("../../lib/mock-data");
        if (_testMockStatus === "llm_unavailable") result = MOCK_ASK_RESPONSE_LLM_UNAVAILABLE;
        else if (_testMockStatus === "validation_failed") result = MOCK_ASK_RESPONSE_VALIDATION_FAILED;
        else if (_testMockStatus === "no_result") result = MOCK_ASK_RESPONSE_NO_RESULT;
        else if (_testMockStatus === "ok") result = MOCK_ASK_RESPONSE_OK;
      }

      setResponse(result);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "An unexpected error occurred."
      );
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setQuestion("");
    setResponse(null);
    setError(null);
  };

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div
      data-testid="ask-the-network"
      className="bg-gray-800 rounded-lg p-4 space-y-4 text-sm text-slate-200"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-slate-100">Ask the Network</h2>
        {response && (
          <button
            data-testid="ask-clear-button"
            onClick={handleClear}
            className="text-xs text-slate-400 hover:text-slate-200"
            aria-label="Clear question and result"
          >
            Clear
          </button>
        )}
      </div>

      {/* Question form */}
      <form onSubmit={handleSubmit} className="flex gap-2" role="search">
        <input
          id="ask-question-input"
          data-testid="ask-question-input"
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about the network…"
          disabled={loading}
          aria-label="Ask a question about the criminal network"
          className={[
            "flex-1 rounded bg-gray-700 border border-gray-600 px-3 py-2",
            "text-sm text-slate-200 placeholder-slate-500 outline-none",
            "focus:border-blue-500 focus:ring-1 focus:ring-blue-500",
            "disabled:opacity-40 disabled:cursor-not-allowed",
          ].join(" ")}
        />
        <button
          data-testid="ask-submit-button"
          type="submit"
          disabled={loading || !question.trim()}
          className={[
            "px-4 py-2 rounded text-sm font-medium transition-colors",
            "bg-blue-600 text-white hover:bg-blue-500",
            "disabled:opacity-40 disabled:cursor-not-allowed",
          ].join(" ")}
          aria-label="Submit question to Ask the Network"
        >
          {loading ? "Asking…" : "Ask"}
        </button>
      </form>

      {/* Loading state */}
      {loading && (
        <p
          data-testid="ask-loading"
          className="text-slate-400 text-xs italic animate-pulse"
        >
          Analysing the network…
        </p>
      )}

      {/* Network/API error (distinct from AskResponse error states) */}
      {error && (
        <div
          data-testid="ask-error"
          className="rounded-lg border border-red-800 bg-red-950 p-3 text-sm text-red-300"
          role="alert"
        >
          {error}
        </div>
      )}

      {/* Response — discriminated union, each variant rendered distinctly */}
      {response && !loading && (
        <div data-testid="ask-response-container">
          {response.status === "ok" && <OkResult response={response} />}
          {response.status === "llm_unavailable" && (
            <LlmUnavailableResult response={response} />
          )}
          {response.status === "validation_failed" && (
            <ValidationFailedResult response={response} />
          )}
          {response.status === "no_result" && (
            <NoResultResult response={response} />
          )}
        </div>
      )}

      {/* Hint when no question has been submitted yet */}
      {!response && !loading && !error && (
        <p className="text-xs text-slate-500 italic">
          Example: "Who does Rahul Sharma call most frequently?"
        </p>
      )}
    </div>
  );
}
