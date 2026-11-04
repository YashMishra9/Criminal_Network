"""F3 — Query Executor: Execution and Evidence Attachment.

Task: F3 (Track F — Ask-the-Network)
Depends on: F2 (ValidatedQuery), C4 (EvidenceResolver)

Objective (F3.md §3):
    Execute validated queries against Neo4j, attach evidence via the C4
    EvidenceResolver (DOC3 §9.1), then pass the result to the Narrator (F3
    second step, implemented in narrator.py) for LLM narration.

DOC3 §10 — GraphQueryResult:
    entities:      CanonicalEntity[]
    relationships: Relationship[]    ← evidence_ids must be populated
    paths:         {entity_ids: str[], relationship_ids: str[]}[]

DOC3 §15 Invariant 1:
    Every Relationship in GraphQueryResult.relationships MUST have non-empty
    evidence_ids before being returned to the caller.

DOC3 §15 Invariant 3:
    The LLM never originates a factual claim — narration is built solely from
    the query_result.  This module is responsible for constructing that result
    accurately.

Security model (F3.md §17, DOC3 §10):
    - Only a ValidatedQuery (from F2) is accepted.  This module refuses to
      execute a raw GeneratedQuery (type guard enforced at runtime).
    - query.parameters are passed through to Neo4j WITHOUT modification —
      the dataset filter injected / verified by F2 must not be stripped.
    - No credentials or internal Neo4j errors are surfaced to callers.
    - Sessions are always closed (try/finally).

Execution timeout:
    ValidatedQuery.timeout_ms is enforced by passing it to the Neo4j session's
    query timeout.  A neo4j.exceptions.ClientError whose code contains
    "TransactionTimedOut", or a concurrent.futures.TimeoutError from the
    session wrapper, maps to ExecutionError(status='timeout').

Dataset isolation:
    F2 has already injected the dataset filter into the Cypher and verified the
    parameters dict contains {"dataset": <value>}.  F3 passes parameters as-is
    and does NOT strip or modify them.

Resource cleanup:
    The existing `get_session()` context manager in app.graph.connection closes
    the session in its finally block.  This module wraps individual query
    execution in an additional try/except so that errors are caught before the
    with-block exits.
"""

import logging
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel

from app.ask.validator import ValidatedQuery
from app.contracts.entity import CanonicalEntity
from app.contracts.relationship import Relationship
from app.evidence.resolver import EvidenceResolver, evidence_resolver as _default_resolver
from app.graph.connection import get_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class GraphQueryResult(BaseModel):
    """The evidence-attached result of a validated Cypher query.

    DOC3 §10:
        entities:      list of CanonicalEntity nodes returned by the query.
        relationships: list of Relationship edges with evidence_ids populated.
        paths:         list of {entity_ids, relationship_ids} path descriptors.

    Invariant (DOC3 §15 Invariant 1):
        Every Relationship.evidence_ids is non-empty.  Relationships without
        evidence in the graph are logged at WARNING level and excluded from the
        result rather than returned with an empty evidence_ids list.
    """

    entities: List[CanonicalEntity]
    relationships: List[Relationship]
    paths: List[Dict[str, List[str]]]


class NoResult(BaseModel):
    """Returned when the query executed successfully but found no matching rows."""

    status: Literal["no_result"] = "no_result"
    message: str = "The query returned no results for the given parameters."


class ExecutionError(BaseModel):
    """Returned for all execution-side failures — never raises to the caller.

    status values:
        'graph_unavailable' — Neo4j is unreachable or authentication failed.
        'timeout'           — Query exceeded ValidatedQuery.timeout_ms.
        'execution_error'   — Any other Neo4j-side error.

    The `message` field contains only a safe, generic description — internal
    details (stack traces, credentials) are logged at ERROR/WARNING level but
    never included here (DOC3 §10 security rule).
    """

    status: Literal["graph_unavailable", "timeout", "execution_error"]
    message: str


ExecutorResult = Union[GraphQueryResult, NoResult, ExecutionError]


# ---------------------------------------------------------------------------
# Internal helpers — Neo4j record → contract type conversion
# ---------------------------------------------------------------------------


def _record_to_entity(record: Any) -> Optional[CanonicalEntity]:
    """Convert a Neo4j record or node map to a CanonicalEntity.

    Returns None if the record is missing required fields so callers can
    filter rather than raise.
    """
    try:
        # Support both Neo4j Node objects (dict-like) and plain dicts
        data: Dict[str, Any] = dict(record) if not isinstance(record, dict) else record
        return CanonicalEntity(
            entity_id=data["entity_id"],
            entity_type=data["entity_type"],
            dataset=data["dataset"],
            display_name=data.get("display_name", ""),
            attributes=data.get("attributes") or {},
            resolved_from=list(data.get("resolved_from") or []),
            resolution_method=data.get("resolution_method", "exact_match"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("_record_to_entity: skipping malformed record — %s", exc)
        return None


def _record_to_relationship(record: Any) -> Optional[Relationship]:
    """Convert a Neo4j record or relationship map to a Relationship (evidence_ids=[]).

    Evidence IDs are populated by the caller via EvidenceResolver after this
    conversion, so the initial list is empty — this is intentional.
    """
    try:
        data: Dict[str, Any] = dict(record) if not isinstance(record, dict) else record
        return Relationship(
            relationship_id=data["relationship_id"],
            relationship_type=data["relationship_type"],
            from_entity_id=data["from_entity_id"],
            to_entity_id=data["to_entity_id"],
            dataset=data["dataset"],
            attributes=data.get("attributes") or {},
            valid_from=data.get("valid_from", ""),
            valid_to=data.get("valid_to"),
            evidence_ids=list(data.get("evidence_ids") or []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("_record_to_relationship: skipping malformed record — %s", exc)
        return None


def _attach_evidence(
    relationships: List[Relationship],
    resolver: EvidenceResolver,
) -> List[Relationship]:
    """Populate evidence_ids on each Relationship via the C4 EvidenceResolver.

    DOC3 §10: "every Relationship in GraphQueryResult.relationships has its
    evidence_ids populated via the Evidence/Provenance Resolver before
    narration."

    Relationships for which the resolver returns no evidence are EXCLUDED from
    the result with a WARNING — DOC3 §15 Invariant 1 forbids returning
    Relationships with empty evidence_ids.
    """
    result: List[Relationship] = []
    for rel in relationships:
        try:
            evidences = resolver.for_relationship(rel.relationship_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "_attach_evidence: resolver error for relationship_id=%s — %s",
                rel.relationship_id,
                exc,
            )
            evidences = []

        evidence_ids = [ev.evidence_id for ev in evidences]
        if not evidence_ids:
            logger.warning(
                "_attach_evidence: relationship_id=%s has no evidence — excluded "
                "from result (DOC3 §15 Invariant 1).",
                rel.relationship_id,
            )
            continue

        # Return a new Relationship with populated evidence_ids (Pydantic models
        # are immutable by default — use model_copy to avoid mutation).
        result.append(rel.model_copy(update={"evidence_ids": evidence_ids}))

    return result


# ---------------------------------------------------------------------------
# QueryExecutor
# ---------------------------------------------------------------------------


class QueryExecutor:
    """Execute a ValidatedQuery against Neo4j and return an evidence-attached result.

    This is the ONLY component in Track F that touches Neo4j directly (all
    access goes through the C-track `get_session()` context manager).

    Usage::

        executor = QueryExecutor()
        result = executor.execute(validated_query)
        if isinstance(result, GraphQueryResult):
            # pass to Narrator
            pass
        elif isinstance(result, NoResult):
            # surface as AskResponse(status='no_result')
            pass
        else:
            # ExecutionError — surface as AskResponse(status=result.status)
            pass

    Security:
        Only a ValidatedQuery instance is accepted.  Passing any other type
        raises TypeError immediately (never reaches Neo4j).
    """

    def __init__(
        self,
        resolver: Optional[EvidenceResolver] = None,
    ) -> None:
        """
        Args:
            resolver: EvidenceResolver to use.  Defaults to the module-level
                      singleton from app.evidence.resolver.  Injected in tests.
        """
        self._resolver = resolver or _default_resolver

    def execute(self, query: ValidatedQuery) -> ExecutorResult:
        """Execute the validated query and return an evidence-attached result.

        Args:
            query: A ValidatedQuery from F2.  Must NOT be a raw GeneratedQuery.

        Returns:
            GraphQueryResult — successful execution with evidence attached.
            NoResult         — query ran but returned no rows.
            ExecutionError   — Neo4j unavailable, timed out, or errored.

        Raises:
            TypeError — if `query` is not a ValidatedQuery instance.
        """
        # Runtime type guard — F3 never executes a raw GeneratedQuery.
        if not isinstance(query, ValidatedQuery):
            raise TypeError(
                f"QueryExecutor.execute requires a ValidatedQuery (from F2), "
                f"got {type(query).__name__!r}. "
                "Raw GeneratedQuery instances must first pass through "
                "CypherValidator.validate() (F2)."
            )

        logger.info(
            "QueryExecutor.execute: dataset=%s timeout_ms=%d cypher_len=%d",
            query.parameters.get("dataset", "<unknown>"),
            query.timeout_ms,
            len(query.cypher),
        )

        try:
            raw_entities, raw_relationships, paths = self._run_query(query)
        except _GraphUnavailableError:
            return ExecutionError(
                status="graph_unavailable",
                message="The graph database is currently unavailable. Please try again later.",
            )
        except _TimeoutError:
            return ExecutionError(
                status="timeout",
                message=(
                    f"Query execution exceeded the {query.timeout_ms} ms timeout. "
                    "Try a more specific question or a smaller time range."
                ),
            )
        except _ExecutionFailedError as exc:
            return ExecutionError(
                status="execution_error",
                message=str(exc),
            )

        if not raw_entities and not raw_relationships:
            logger.info("QueryExecutor: query returned no rows.")
            return NoResult()

        # Convert Neo4j records to contract types
        entities: List[CanonicalEntity] = [
            e for e in (_record_to_entity(r) for r in raw_entities) if e is not None
        ]
        relationships_raw: List[Relationship] = [
            r for r in (_record_to_relationship(r) for r in raw_relationships) if r is not None
        ]

        # Attach evidence — this is the C4 integration point (DOC3 §10)
        relationships = _attach_evidence(relationships_raw, self._resolver)

        result = GraphQueryResult(
            entities=entities,
            relationships=relationships,
            paths=paths,
        )
        logger.info(
            "QueryExecutor: result entities=%d relationships=%d paths=%d",
            len(result.entities),
            len(result.relationships),
            len(result.paths),
        )
        return result

    # ------------------------------------------------------------------
    # Private: raw Neo4j execution
    # ------------------------------------------------------------------

    def _run_query(
        self, query: ValidatedQuery
    ) -> tuple[List[Any], List[Any], List[Dict[str, List[str]]]]:
        """Run the Cypher query against Neo4j and return raw row data.

        Returns a 3-tuple: (entity_records, relationship_records, paths).

        Callers translate domain-specific Neo4j exceptions into F3 sentinel
        exceptions (_GraphUnavailableError, _TimeoutError, _ExecutionFailedError).
        """
        import neo4j.exceptions as neo4j_exc  # lazy — not a hard requirement at module load

        entity_rows: List[Any] = []
        rel_rows: List[Any] = []
        path_rows: List[Dict[str, List[str]]] = []

        try:
            with get_session() as session:
                # Neo4j Python driver supports query timeout via the
                # `timeout` parameter of session.run() (in seconds).
                timeout_seconds = query.timeout_ms / 1000.0
                result = session.run(
                    query.cypher,
                    query.parameters,
                    timeout=timeout_seconds,
                )
                records = list(result)  # consume inside the session context

            for record in records:
                rec_dict = dict(record)

                # Support queries that return nodes bound to 'entity'/'e'/'n'
                for key in ("entity", "e", "n"):
                    if key in rec_dict and rec_dict[key] is not None:
                        node = rec_dict[key]
                        entity_rows.append(
                            {k: node.get(k) for k in node.keys()} if hasattr(node, "keys") else node
                        )
                        break

                # Support queries that return relationships bound to 'rel'/'r'
                for key in ("rel", "r", "relationship"):
                    if key in rec_dict and rec_dict[key] is not None:
                        rel = rec_dict[key]
                        rel_rows.append(
                            {k: rel.get(k) for k in rel.keys()} if hasattr(rel, "keys") else rel
                        )
                        break

                # Support path objects
                if "path" in rec_dict and rec_dict["path"] is not None:
                    path_obj = rec_dict["path"]
                    try:
                        entity_ids = [str(n["entity_id"]) for n in path_obj.nodes if "entity_id" in n]
                        rel_ids = [str(r["relationship_id"]) for r in path_obj.relationships if "relationship_id" in r]
                        path_rows.append({"entity_ids": entity_ids, "relationship_ids": rel_ids})
                    except Exception:  # noqa: BLE001
                        pass  # malformed path — skip silently

        except (neo4j_exc.ServiceUnavailable, neo4j_exc.AuthError) as exc:
            logger.error("QueryExecutor: Neo4j unavailable — %s", exc)
            raise _GraphUnavailableError() from exc

        except neo4j_exc.ClientError as exc:
            # Timeout-related ClientError codes from the Neo4j driver
            code = getattr(exc, "code", "") or ""
            msg = str(exc).lower()
            if "timedout" in code.lower() or "timeout" in msg or "timed out" in msg:
                logger.warning("QueryExecutor: query timed out — %s", exc)
                raise _TimeoutError() from exc
            logger.error("QueryExecutor: Neo4j client error — %s", exc)
            raise _ExecutionFailedError("Query execution failed due to a database error.") from exc

        except Exception as exc:  # noqa: BLE001
            # Catch-all: map unknown errors to execution_error without leaking details
            msg_lower = str(exc).lower()
            if "timeout" in msg_lower or "timed out" in msg_lower:
                logger.warning("QueryExecutor: query timed out (generic) — %s", exc)
                raise _TimeoutError() from exc
            logger.error("QueryExecutor: unexpected error during execution — %s", exc)
            raise _ExecutionFailedError("An unexpected error occurred during query execution.") from exc

        return entity_rows, rel_rows, path_rows


# ---------------------------------------------------------------------------
# Internal sentinel exceptions — not exported
# ---------------------------------------------------------------------------


class _GraphUnavailableError(Exception):
    """Neo4j is unreachable or authentication failed."""


class _TimeoutError(Exception):
    """Query exceeded its configured timeout."""


class _ExecutionFailedError(Exception):
    """Any other Neo4j execution failure — message is safe to surface."""

    def __str__(self) -> str:
        return self.args[0] if self.args else "Query execution failed."


# ---------------------------------------------------------------------------
# Module-level convenience factory
# ---------------------------------------------------------------------------


def get_query_executor(resolver: Optional[EvidenceResolver] = None) -> QueryExecutor:
    """Return a QueryExecutor, optionally with a custom EvidenceResolver.

    Tests inject a mock resolver to avoid real Neo4j / graph calls.
    Production code uses the default (module-level singleton).
    """
    return QueryExecutor(resolver=resolver)

