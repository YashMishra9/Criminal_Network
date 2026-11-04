"""F3 — Narrator: LLM Narration over Graph Query Results.

Task: F3 (Track F — Ask-the-Network)
Depends on: F3 service.py (GraphQueryResult), A5 (LLMClient)

Objective (F3.md §3):
    Perform the second LLM call in the two-call design (DOC2 §12):
    the narration call receives ONLY the graph query result and the original
    question — no direct graph or tool access.

DOC3 §15 Invariant 3 (binding):
    The LLM NEVER originates a factual claim reaching the user.
    All facts presented in the narration must be grounded in `query_result`.
    The narration prompt is constructed exclusively from `query_result` and
    the original `question`.  No other context is injected.

DOC3 §15 Invariant 4 (binding):
    LLM unavailability MUST NOT block core functionality.
    When the narration LLM call fails, the caller receives a typed
    NarratorError so that F4 / the Ask API endpoint can still return the
    raw GraphQueryResult to the user (without narration) rather than a 5xx.

DOC2 §12 — two-call design:
    Call 1 (generation): query_generator.py — F1
    Call 2 (narration):  this module — F3

Disclaimer (DOC1 §14 / DOC3 §10):
    Every narrated response MUST include the exact string:
        "This is an investigative lead, not evidence of wrongdoing."
    The narrator appends this at the end of every narration it produces.

F3.md §12 — acceptance criteria (code-review verifiable):
    The narration prompt is constructed from query_result and question ONLY.
    No independent graph/tool access is given to the LLM.
    Verified in test_f3_narrator.py::test_narrator_input_isolation.
"""

import json
import logging
from typing import List, Literal, Optional, Union

from pydantic import BaseModel

from app.ask.service import GraphQueryResult
from app.llm.client import LLMClient, LLMResultOk, get_llm_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Disclaimer — must appear verbatim in every narration (DOC1 §14 / DOC3 §10)
# ---------------------------------------------------------------------------

DISCLAIMER = "This is an investigative lead, not evidence of wrongdoing."


# ---------------------------------------------------------------------------
# Input / Output types (DOC3 §10)
# ---------------------------------------------------------------------------


class NarrationInput(BaseModel):
    """Input to the narration call — only question + query_result (Invariant 3)."""

    question: str
    query_result: GraphQueryResult


class NarrationOutput(BaseModel):
    """Narrated, evidence-grounded response from the LLM."""

    narration: str
    """Natural-language summary grounded solely in query_result.
    Always ends with DISCLAIMER."""


class NarratorError(BaseModel):
    """Typed failure returned when the narration LLM call is unavailable.

    DOC3 §15 Invariant 4: callers must NOT raise an exception when narration
    fails — they should surface the raw GraphQueryResult without narration.
    """

    status: Literal["narration_unavailable"] = "narration_unavailable"
    reason: str


NarrationResult = Union[NarrationOutput, NarratorError]


# ---------------------------------------------------------------------------
# Prompt construction — the ONLY place the narration context is assembled
# ---------------------------------------------------------------------------


def _build_narration_prompt(narration_input: NarrationInput) -> tuple[str, dict]:
    """Build the narration prompt and context from NarrationInput ONLY.

    DOC3 §15 Invariant 3 verification point:
        - `prompt` is derived solely from narration_input.question.
        - `context` is derived solely from narration_input.query_result.
        - No other data source is referenced here.

    Returns:
        (prompt_str, context_dict) — both safe to pass to LLMClient.generate().
    """
    qr = narration_input.query_result
    question = narration_input.question

    # Serialize the query result to a structured, readable context block.
    # This is the ONLY factual context the LLM receives.
    entity_summaries: List[str] = []
    for ent in qr.entities:
        entity_summaries.append(
            f"  - [{ent.entity_type}] {ent.display_name} (id={ent.entity_id})"
        )

    relationship_summaries: List[str] = []
    for rel in qr.relationships:
        relationship_summaries.append(
            f"  - {rel.from_entity_id} --[{rel.relationship_type}]--> {rel.to_entity_id} "
            f"(valid_from={rel.valid_from}, evidence_ids={rel.evidence_ids})"
        )

    path_summaries: List[str] = []
    for i, path in enumerate(qr.paths):
        path_summaries.append(
            f"  - Path {i + 1}: entities={path.get('entity_ids', [])}, "
            f"relationships={path.get('relationship_ids', [])}"
        )

    context = {
        "instruction": (
            "You are a criminal-network investigative assistant. "
            "Summarise the query result below in plain English to answer the investigator's question. "
            "Use ONLY the facts in 'query_result'. "
            "Do NOT infer, speculate, or add any information not present in the data. "
            f"Always end your response with the exact sentence: \"{DISCLAIMER}\""
        ),
        "query_result": {
            "entities": entity_summaries,
            "relationships": relationship_summaries,
            "paths": path_summaries,
        },
    }

    prompt = (
        f"Investigator's question: {question}\n\n"
        "Please narrate the findings above, grounded strictly in the provided query result."
    )

    return prompt, context


# ---------------------------------------------------------------------------
# Narrator
# ---------------------------------------------------------------------------


class Narrator:
    """Perform the narration LLM call (call 2 of the two-call design).

    The narration LLM call receives ONLY query_result and question — no graph
    or tool access (DOC3 §15 Invariant 3).  LLM unavailability returns a typed
    NarratorError rather than raising, preserving the ability to return raw
    results (DOC3 §15 Invariant 4).

    Usage::

        narrator = Narrator()
        narration_input = NarrationInput(question=question, query_result=result)
        result = narrator.narrate(narration_input)
        if isinstance(result, NarrationOutput):
            print(result.narration)
        else:
            # NarratorError — surface raw graph result without narration
            pass
    """

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        """
        Args:
            llm_client: LLMClient to use.  Defaults to get_llm_client().
                        Inject a mock in tests to avoid real LLM calls.
        """
        self._llm = llm_client or get_llm_client()

    def narrate(self, narration_input: NarrationInput) -> NarrationResult:
        """Narrate a GraphQueryResult.

        Args:
            narration_input: NarrationInput containing ONLY the question and
                             the evidence-attached GraphQueryResult.

        Returns:
            NarrationOutput — LLM narration with disclaimer appended.
            NarratorError   — LLM is unavailable; caller should degrade gracefully.

        DOC3 §15 Invariant 3: the narration prompt is constructed from
        narration_input ONLY — see _build_narration_prompt().
        """
        prompt, context = _build_narration_prompt(narration_input)

        logger.info(
            "Narrator.narrate: question_len=%d entities=%d relationships=%d",
            len(narration_input.question),
            len(narration_input.query_result.entities),
            len(narration_input.query_result.relationships),
        )

        try:
            llm_result = self._llm.generate(
                prompt=prompt,
                context=context,
                options={},
            )
        except Exception as exc:  # noqa: BLE001
            # LLM client contract: generate() should not raise, but we guard anyway.
            logger.error("Narrator: unexpected error from LLMClient.generate — %s", exc)
            return NarratorError(
                reason=f"Narration LLM call failed unexpectedly: {type(exc).__name__}"
            )

        if not isinstance(llm_result, LLMResultOk):
            logger.warning(
                "Narrator: LLM unavailable (status=%s, reason=%s)",
                llm_result.status,
                getattr(llm_result, "reason", "unknown"),
            )
            return NarratorError(
                reason=(
                    f"Narration LLM is currently unavailable "
                    f"(status={llm_result.status}). "
                    "Raw query results are still available."
                )
            )

        narration = llm_result.text.strip()

        # Ensure the mandatory disclaimer is present (DOC1 §14)
        if DISCLAIMER not in narration:
            narration = f"{narration}\n\n{DISCLAIMER}"

        logger.info("Narrator: narration produced (len=%d)", len(narration))
        return NarrationOutput(narration=narration)


# ---------------------------------------------------------------------------
# Module-level convenience factory
# ---------------------------------------------------------------------------


def get_narrator(llm_client: Optional[LLMClient] = None) -> Narrator:
    """Return a Narrator, optionally with a custom LLMClient.

    Tests inject a mock LLMClient to avoid real LLM calls.
    Production code uses the default (config-resolved provider).
    """
    return Narrator(llm_client=llm_client)

