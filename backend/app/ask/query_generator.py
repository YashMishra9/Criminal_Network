"""F1 — Cypher Query Generator.

Task: F1 (Track F — Ask-the-Network)
Depends on: A5 (LLMClient, app.llm.client)

Objective (F1.md §3):
    Build the schema-constrained prompt and call LLMClient to produce a
    GeneratedQuery, per DOC3 §10.

DOC3 §10 — Ask-the-Network contract:
    Input:   AskRequest  {question, dataset, as_of}
    Output:  GeneratedQuery {cypher, parameters, generated_by: 'llm'}

    On LLM unavailability the generator returns a typed failure signal
    (GeneratorError) for the caller (F3/F4) to map to an AskResponse —
    this module does NOT decide the final AskResponse shape.

DOC2 §12 — two-call design:
    This is call-1 (generation only).  Call-2 (narration) is F4.
    Keeping them separate structurally prevents the LLM from being the
    origin of any factual claim reaching the user (DOC3 §15 Invariant 3).

DOC3 §10 validation requirements:
    Validation is F2's responsibility.  This module only generates; it does
    NOT execute or validate the produced Cypher.

DOC3 §15 Invariant 13:
    CALL / any procedure invocation must be rejected by the validator (F2).
    The prompt in this module instructs the LLM to avoid CALL, but enforcement
    is F2's job.

Constraint (F1.md §17):
    This task does NOT execute queries.  Execution belongs to F3.
"""

import logging
from typing import Literal, Optional, Union
from pydantic import BaseModel

from app.llm.client import LLMClient, get_llm_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DOC3 §10 schema constants — node labels and relationship types the prompt
# must be constrained to (DOC3 §6.1 / §6.2).
# ---------------------------------------------------------------------------

# CanonicalEntity node labels (§6.1, first table)
_ENTITY_LABELS: list[str] = [
    "Person",
    "Phone",
    "Vehicle",
    "Location",
    "Organization",
    "BankAccount",
    "Transaction",
    "Event",
]

# Structural / workspace / provenance node labels (§6.1, second table)
# Included so the LLM knows they exist but should not be queried as entities.
_STRUCTURAL_LABELS: list[str] = [
    "Case",
    "Evidence",
    "Note",
    "EdgeRef",
    "ResolutionDecision",
    "Finding",
]

# Domain relationship types permitted in domain queries (§6.2)
_RELATIONSHIP_TYPES: list[str] = [
    "CALLED",
    "OWNS",
    "USED",
    "TRANSFERRED",
    "VISITED",
    "MET",
    "WORKS_FOR",
    "ASSOCIATED_WITH",
    "MENTIONED_IN",
    "PART_OF",
    # Evidence / provenance edges (read-only queries may traverse these)
    "SUPPORTS",
    "INCLUDES_ENTITY",
    "INCLUDES_EDGE",
    "INCLUDES_EVIDENCE",
    "ABOUT",
    "RESOLVED_FROM",
    "BASED_ON",
    "CONCERNS",
]

# Permitted Cypher constructs (DOC3 §10 validation rule 3)
_PERMITTED_CONSTRUCTS: list[str] = [
    "MATCH",
    "OPTIONAL MATCH",
    "WHERE",
    "RETURN",
    "WITH",
    "ORDER BY",
    "LIMIT",
    "SKIP",
    "shortestPath()",
    "standard comparison / boolean / string predicate functions",
]

# ---------------------------------------------------------------------------
# Contract types — DOC3 §10
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    """NL question input (DOC3 §10)."""

    question: str
    dataset: str = "synthetic_demo"
    as_of: Optional[str] = None


class GeneratedQuery(BaseModel):
    """Schema-constrained Cypher produced by the LLM (DOC3 §10).

    Internal representation — never returned raw to the frontend.
    """

    cypher: str
    parameters: dict
    generated_by: Literal["llm"] = "llm"


class GeneratorError(BaseModel):
    """Typed failure returned when the LLM is unavailable.

    The caller (F3/F4) maps this to an AskResponse with status
    'llm_unavailable' (DOC3 §10, DOC2 §12A).
    """

    status: Literal["llm_unavailable"] = "llm_unavailable"
    reason: str  # forwards LLMResultUnavailable.reason for logging/debugging


GeneratorResult = Union[GeneratedQuery, GeneratorError]


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_schema_section() -> str:
    """Return the schema block that constrains the LLM to DOC3 §6 labels."""
    entity_list = "\n".join(f"  - {label}" for label in _ENTITY_LABELS)
    rel_list = "\n".join(f"  - {rel}" for rel in _RELATIONSHIP_TYPES)
    constructs = "\n".join(f"  - {c}" for c in _PERMITTED_CONSTRUCTS)
    return f"""\
=== Graph Schema (DOC3 §6) ===

Node labels you may reference (CanonicalEntity types):
{entity_list}

All nodes and relationships carry a `dataset` property.
You MUST filter every matched node/relationship by `dataset = $dataset`.

Relationship types you may use:
{rel_list}

Permitted Cypher constructs ONLY:
{constructs}

FORBIDDEN (never use, these will be rejected before execution):
  - CREATE, MERGE, SET, DELETE, REMOVE  (write operations)
  - CALL or any procedure invocation (e.g. apoc.*, gds.*)
  - Any construct not listed under "Permitted Cypher constructs" above
"""


def _build_prompt(request: AskRequest) -> str:
    """Construct the schema-constrained generation prompt."""
    schema_section = _build_schema_section()

    as_of_instruction = (
        f"The query must also filter by `valid_from <= '{request.as_of}'` "
        f"and (`valid_to IS NULL OR valid_to >= '{request.as_of}'`) on every "
        f"domain relationship (DOC3 §2.4A / §6.6)."
        if request.as_of
        else "No temporal filter is requested; do not add as_of constraints."
    )

    return f"""\
You are a Cypher query generator for a criminal network analysis system backed
by Neo4j.  Your sole job is to translate the investigator's natural-language
question into a single, valid, read-only Cypher query.

{schema_section}

Dataset scope (MANDATORY):
  The query MUST include `dataset = $dataset` on every node and relationship
  pattern it matches — cross-dataset leakage is a hard contract violation.

Temporal scope:
  {as_of_instruction}

Output format (STRICT):
  Respond with ONLY the Cypher query — no explanation, no markdown fences,
  no preamble.  The response is parsed directly as Cypher.

Parameters available to the query:
  $dataset  — string, the scoped dataset (already set to "{request.dataset}")
  $as_of    — ISO-8601 string or null

Investigator's question:
  {request.question}
"""


# ---------------------------------------------------------------------------
# Query generator — public interface (F1)
# ---------------------------------------------------------------------------


class QueryGenerator:
    """Schema-constrained NL → Cypher generator (DOC3 §10, F1).

    Usage::

        generator = QueryGenerator()
        result = generator.generate(AskRequest(question="...", dataset="synthetic_demo"))
        if isinstance(result, GeneratedQuery):
            # pass to F2 (validator) then F3 (executor)
            cypher = result.cypher
        else:
            # LLM unavailable — surface AskResponse(status="llm_unavailable")
            ...
    """

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        """
        Args:
            llm_client: Optional override for testing.  When None, the default
                        LLMClient from A5 is used (provider resolved from config).
        """
        self._llm_client = llm_client or get_llm_client()

    def generate(self, request: AskRequest) -> GeneratorResult:
        """Translate a natural-language question to a GeneratedQuery.

        Args:
            request: AskRequest with question, dataset, and optional as_of.

        Returns:
            GeneratedQuery on success.
            GeneratorError if the LLM is unavailable (maps to
            AskResponse status='llm_unavailable' in F4).

        DOC3 §10 contract:
            - The prompt includes DOC3 §6 node/relationship labels and a
              mandatory dataset-scoping instruction.
            - generated_by is always 'llm'.
            - This method does NOT validate or execute the query (F2/F3).
        """
        prompt = _build_prompt(request)
        context = {
            "schema": _build_schema_section(),
            "dataset": request.dataset,
            "as_of": request.as_of,
        }

        logger.info(
            "QueryGenerator.generate: dataset=%s as_of=%s question_len=%d",
            request.dataset,
            request.as_of,
            len(request.question),
        )

        result = self._llm_client.generate(prompt=prompt, context=context)

        if result.status == "ok":
            cypher = result.text.strip()
            logger.debug("QueryGenerator produced Cypher (%d chars)", len(cypher))
            return GeneratedQuery(
                cypher=cypher,
                parameters={"dataset": request.dataset, "as_of": request.as_of},
                generated_by="llm",
            )

        # LLM unavailable — return a typed failure for F3/F4 to handle
        logger.warning(
            "QueryGenerator: LLM unavailable, reason=%s", result.reason
        )
        return GeneratorError(reason=result.reason)


# ---------------------------------------------------------------------------
# Module-level convenience factory
# ---------------------------------------------------------------------------


def get_query_generator(llm_client: Optional[LLMClient] = None) -> QueryGenerator:
    """Return a QueryGenerator using the default (or supplied) LLMClient."""
    return QueryGenerator(llm_client=llm_client)
