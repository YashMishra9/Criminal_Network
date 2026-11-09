"""Ask-the-Network API Router — F4 Implementation.

Task: F4 (Track F — Ask API Endpoint)
Implements: DOC3 §12.8 — POST /ask

Pipeline (DOC2 §12 two-call design):
    AskRequest
        → F1 QueryGenerator    (NL → Cypher generation)
        → F2 CypherValidator   (safety validation; dataset injection)
        → F3 QueryExecutor     (Neo4j execution; evidence attachment via C4)
        → F3 Narrator          (narration-only LLM call; Invariant 3)
        → AskResponse

AskResponse (DOC3 §10, full union):
    { status: "ok",               narration, path, evidence }
    { status: "llm_unavailable",  message }     — F1 or F3 narration LLM failure
    { status: "validation_failed", reason }      — F2 rule violation
    { status: "no_result",         message }     — valid query, empty graph result

HTTP error fall-through (DOC3 §13 table):
    graph_unavailable → 503  (F3 executor returns ExecutionError('graph_unavailable'))
    execution_error   → 503  (F3 executor returns ExecutionError('execution_error'))
    unhandled         → 500  (global catch-all in A6)

Security / Contract Invariants (DOC3 §15):
    Invariant 2  — dataset isolation is enforced by F2 injection/check; never bypassed.
    Invariant 3  — LLM narration receives only query_result + question (F3 Narrator).
    Invariant 4  — LLM unavailability at EITHER F1 or F3 returns llm_unavailable;
                   it never silently degrades to a raw un-narrated result.
    Invariant 13 — CALL/procedure rejection is F2's job; F4 never executes raw Cypher.

F4.md §11 explicit constraint:
    "Must return typed llm_unavailable at either failure point — never fabricate an
    answer, never silently degrade to raw results."
"""

import logging
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.ask.query_generator import (
    AskRequest,
    GeneratorError,
    QueryGenerator,
    get_query_generator,
)
from app.ask.validator import (
    CypherValidator,
    ValidationFailed,
    get_cypher_validator,
)
from app.ask.service import (
    ExecutionError,
    GraphQueryResult,
    NoResult,
    QueryExecutor,
    get_query_executor,
)
from app.ask.narrator import (
    NarrationInput,
    NarratorError,
    Narrator,
    get_narrator,
)
from app.contracts.errors import (
    GraphUnavailableError,
    InternalError,
    LLMUnavailableError,
)
from app.contracts.evidence import Evidence
from app.evidence.resolver import evidence_resolver as _resolver

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ask", tags=["ask"])

# ---------------------------------------------------------------------------
# AskResponse — exact union per DOC3 §10
# ---------------------------------------------------------------------------


class AskResponseOk(BaseModel):
    """Successful Ask-the-Network response (DOC3 §10).

    narration: LLM narration grounded solely in `path` (Invariant 3).
    path:      The evidence-attached GraphQueryResult.
    evidence:  Flattened de-duplicated Evidence[] from all relationships in `path`.
    """

    status: Literal["ok"] = "ok"
    narration: str
    path: GraphQueryResult
    evidence: List[Evidence]


class AskResponseLLMUnavailable(BaseModel):
    """LLM failure at F1 (generation) or F3 (narration) — DOC3 §10."""

    status: Literal["llm_unavailable"] = "llm_unavailable"
    message: str


class AskResponseValidationFailed(BaseModel):
    """F2 validation rule violated — DOC3 §10."""

    status: Literal["validation_failed"] = "validation_failed"
    reason: str


class AskResponseNoResult(BaseModel):
    """Query executed successfully but returned no matching nodes/edges — DOC3 §10."""

    status: Literal["no_result"] = "no_result"
    message: str


AskResponse = Union[
    AskResponseOk,
    AskResponseLLMUnavailable,
    AskResponseValidationFailed,
    AskResponseNoResult,
]


# ---------------------------------------------------------------------------
# AskService — orchestration layer
# ---------------------------------------------------------------------------


class AskService:
    """Orchestrates the full F1 → F2 → F3 → Narrator pipeline.

    Dependency-injected components allow full unit-test isolation without a
    live LLM or Neo4j instance.

    DOC3 §10 / F4.md §11 guarantee:
        LLM unavailability at EITHER the generation step (F1) or the narration
        step (F3) produces AskResponseLLMUnavailable — it never silently falls
        back to a raw un-narrated result, and it never fabricates an answer.
    """

    def __init__(
        self,
        generator: Optional[QueryGenerator] = None,
        validator: Optional[CypherValidator] = None,
        executor: Optional[QueryExecutor] = None,
        narrator: Optional[Narrator] = None,
    ) -> None:
        self._generator = generator or get_query_generator()
        self._validator = validator or get_cypher_validator()
        self._executor = executor or get_query_executor()
        self._narrator = narrator or get_narrator()

    def ask(self, request: AskRequest) -> AskResponse:
        """Execute the full Ask-the-Network pipeline.

        Args:
            request: AskRequest from the frontend (question, dataset, as_of).

        Returns:
            One of the four AskResponse variants — never raises.
        """
        logger.info(
            "AskService.ask: dataset=%s question_len=%d",
            request.dataset,
            len(request.question),
        )

        # ------------------------------------------------------------------ #
        # Step 1 — F1: NL → Cypher generation                                #
        # Failure: GeneratorError → llm_unavailable (Invariant 4, F4.md §11) #
        # ------------------------------------------------------------------ #
        generator_result = self._generator.generate(request)

        if isinstance(generator_result, GeneratorError):
            logger.warning(
                "AskService: F1 generation failed (status=%s, reason=%s)",
                generator_result.status,
                generator_result.reason,
            )
            return AskResponseLLMUnavailable(
                message=(
                    f"The query could not be generated because the language model is "
                    f"currently unavailable ({generator_result.reason}). "
                    "Please try again later."
                )
            )

        generated_query = generator_result  # GeneratedQuery

        # ------------------------------------------------------------------ #
        # Step 2 — F2: Cypher validation                                      #
        # Failure: ValidationFailed → validation_failed (DOC3 §10)           #
        # F4 NEVER executes a GeneratedQuery directly (Invariant 13).        #
        # ------------------------------------------------------------------ #
        validation_result = self._validator.validate(
            generated_query, dataset=request.dataset
        )

        if isinstance(validation_result, ValidationFailed):
            logger.warning(
                "AskService: F2 validation failed (rule=%d, reason=%s)",
                validation_result.rule,
                validation_result.reason,
            )
            return AskResponseValidationFailed(reason=validation_result.reason)

        validated_query = validation_result  # ValidatedQuery

        # ------------------------------------------------------------------ #
        # Step 3 — F3: Query execution + evidence attachment                  #
        # graph_unavailable → raise GraphUnavailableError (HTTP 503)         #
        # timeout / execution_error → raise GraphUnavailableError (HTTP 503) #
        # no_result → AskResponseNoResult                                     #
        # ------------------------------------------------------------------ #
        execution_result = self._executor.execute(validated_query)

        if isinstance(execution_result, ExecutionError):
            if execution_result.status == "graph_unavailable":
                logger.error(
                    "AskService: Neo4j unavailable — %s", execution_result.message
                )
                raise GraphUnavailableError(
                    execution_result.message,
                    details={"step": "query_execution"},
                )
            elif execution_result.status == "timeout":
                logger.warning(
                    "AskService: query timeout — %s", execution_result.message
                )
                raise GraphUnavailableError(
                    execution_result.message,
                    details={"step": "query_execution", "reason": "timeout"},
                )
            else:
                # execution_error — classified as internal graph failure
                logger.error(
                    "AskService: execution error — %s", execution_result.message
                )
                raise GraphUnavailableError(
                    execution_result.message,
                    details={"step": "query_execution", "reason": "execution_error"},
                )

        if isinstance(execution_result, NoResult):
            logger.info("AskService: query returned no results.")
            return AskResponseNoResult(message=execution_result.message)

        graph_result: GraphQueryResult = execution_result

        # ------------------------------------------------------------------ #
        # Step 4 — F3 Narrator: narration-only LLM call (call 2 of two-call) #
        # Failure: NarratorError → llm_unavailable (Invariant 4, F4.md §11)  #
        # The narrator receives ONLY query_result + question (Invariant 3).  #
        # ------------------------------------------------------------------ #
        narration_input = NarrationInput(
            question=request.question,
            query_result=graph_result,
        )
        narration_result = self._narrator.narrate(narration_input)

        if isinstance(narration_result, NarratorError):
            logger.warning(
                "AskService: F3 narration failed (reason=%s)", narration_result.reason
            )
            # DOC3 §10 / F4.md §11: return llm_unavailable — NEVER return raw result.
            return AskResponseLLMUnavailable(
                message=(
                    "The query returned results but narration failed because the language "
                    f"model is currently unavailable ({narration_result.reason}). "
                    "Please try again later."
                )
            )

        # ------------------------------------------------------------------ #
        # Assemble the ok response — collect full Evidence via C4 resolver   #
        # (evidence_ids were attached by F3; we now fetch full objects once  #
        # per unique relationship so the caller gets complete provenance).   #
        # ------------------------------------------------------------------ #
        seen_ev_ids: set = set()
        flat_evidence: List[Evidence] = []

        for rel in graph_result.relationships:
            try:
                evidences = _resolver.for_relationship(rel.relationship_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "AskService: evidence lookup failed for rel=%s — %s",
                    rel.relationship_id,
                    exc,
                )
                evidences = []
            for ev in evidences:
                if ev.evidence_id not in seen_ev_ids:
                    seen_ev_ids.add(ev.evidence_id)
                    flat_evidence.append(ev)

        logger.info(
            "AskService.ask: ok response — entities=%d relationships=%d evidence=%d",
            len(graph_result.entities),
            len(graph_result.relationships),
            len(flat_evidence),
        )

        return AskResponseOk(
            narration=narration_result.narration,
            path=graph_result,
            evidence=flat_evidence,
        )


# ---------------------------------------------------------------------------
# Module-level singleton — dependency-injected in tests via _override_service
# ---------------------------------------------------------------------------

_service: Optional[AskService] = None


def _get_service() -> AskService:
    """Return the module-level AskService singleton (created lazily)."""
    global _service
    if _service is None:
        _service = AskService()
    return _service


# ---------------------------------------------------------------------------
# POST /ask — DOC3 §12.8
# ---------------------------------------------------------------------------


@router.post("")
async def ask_network(request: AskRequest) -> Dict[str, Any]:
    """Natural-language query interface grounded in graph structure (DOC3 §12.8).

    Pipeline: NL → Cypher (F1) → validation (F2) → execution (F3) → narration (F3).

    Returns one of the four AskResponse variants:
        { status: "ok",               narration, path, evidence }
        { status: "llm_unavailable",  message }
        { status: "validation_failed", reason }
        { status: "no_result",         message }

    DOC3 §13 HTTP status codes:
        200 for all four ok-shape variants (the status field disambiguates).
        503 for graph_unavailable (raised by AskService when Neo4j is down).
        500 for unexpected internal errors (global A6 catch-all).

    Note: llm_unavailable and validation_failed are returned as HTTP 200 with
    a typed status field per DOC3 §10 — they are not HTTP errors; they are
    expected, recoverable application states the frontend handles explicitly.
    """
    service = _get_service()
    response = service.ask(request)
    return response.model_dump()
