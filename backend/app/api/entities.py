"""Entities API Router — C6 implementation.

Implements DOC3 §12.1–§12.3:
  GET /entities/search?q=&dataset=&entity_type=   → {results: CanonicalEntity[]}
  GET /entities/{entity_id}                        → {entity: CanonicalEntity,
                                                       resolution: ResolutionDecision[]}
                                                      or 404
  GET /entities/{entity_id}/relationships?dataset=&as_of=
                                                   → {relationships: (Relationship &
                                                       {evidence: Evidence[]})[]}

Contract rules (DOC3 §11–§12):
  - dataset defaults to 'synthetic_demo' when omitted (DOC3 §2.6).
  - as_of filtering uses C5's shared implementation (Invariant 14).
  - /entities/{id}/relationships includes full inline Evidence[] per
    relationship (DOC3 §12.3 — deliberately different from /graph §12.4).
  - All errors go through A6's typed exception classes.
  - If Neo4j is unreachable, GraphUnavailableError is raised (HTTP 503).
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from neo4j.exceptions import AuthError, ServiceUnavailable

from app.contracts.entity import CanonicalEntity
from app.contracts.errors import GraphUnavailableError, NotFoundError
from app.contracts.relationship import Relationship
from app.contracts.resolution import ResolutionDecision
from app.evidence.resolver import evidence_resolver
from app.graph.connection import get_session
from app.graph.queries import build_as_of_filter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/entities", tags=["entities"])

# ---------------------------------------------------------------------------
# Helpers — row → contract object
# ---------------------------------------------------------------------------

_ALLOWED_ENTITY_TYPES = frozenset([
    "Person", "Phone", "Vehicle", "Location", "Organization",
    "BankAccount", "Transaction", "Event",
])

_ALLOWED_RESOLUTION_METHODS = frozenset([
    "exact_match", "fuzzy_match", "shared_attribute",
    "embedding_similarity", "manual",
])


def _row_to_entity(record: Any) -> CanonicalEntity:
    """Convert a Neo4j record row to a CanonicalEntity."""
    resolved_from = record.get("resolved_from") or []
    attrs_raw = record.get("attributes_json")
    try:
        attributes = json.loads(attrs_raw) if attrs_raw else {}
    except (ValueError, TypeError):
        attributes = {}
    return CanonicalEntity(
        entity_id=record["entity_id"],
        entity_type=record["entity_type"],
        dataset=record["dataset"],
        display_name=record["display_name"],
        attributes=attributes,
        resolved_from=list(resolved_from),
        resolution_method=record["resolution_method"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def _row_to_decision(record: Any) -> ResolutionDecision:
    """Convert a Neo4j record row to a ResolutionDecision."""
    return ResolutionDecision(
        decision_id=record["decision_id"],
        entity_id=record["entity_id"],
        mention_ids=list(record.get("mention_ids") or []),
        source_record_ids=list(record.get("source_record_ids") or []),
        outcome=record["outcome"],
        method=record["method"],
        matched_on=list(record.get("matched_on") or []),
        score=record.get("score"),
        decided_at=record["decided_at"],
    )


def _row_to_relationship(record: Any) -> Relationship:
    """Convert a Neo4j record row to a Relationship."""
    attrs_raw = record.get("attributes_json")
    try:
        attributes = json.loads(attrs_raw) if attrs_raw else {}
    except (ValueError, TypeError):
        attributes = {}
    evidence_ids = list(record.get("evidence_ids") or [])
    return Relationship(
        relationship_id=record["relationship_id"],
        relationship_type=record["relationship_type"],
        from_entity_id=record["from_entity_id"],
        to_entity_id=record["to_entity_id"],
        dataset=record["dataset"],
        attributes=attributes,
        valid_from=record["valid_from"],
        valid_to=record.get("valid_to"),
        evidence_ids=evidence_ids,
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


# ---------------------------------------------------------------------------
# §12.1  GET /entities/search
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_entities(
    q: Optional[str] = None,
    dataset: str = "synthetic_demo",
    entity_type: Optional[str] = None,
) -> Dict[str, List[CanonicalEntity]]:
    """Search entities by text, dataset, and entity_type (DOC3 §12.1).

    Returns: { results: CanonicalEntity[] }

    Matching strategy (case-insensitive contains on display_name):
      - If q is provided: WHERE toLower(n.display_name) CONTAINS toLower($q)
      - entity_type is an exact match filter when provided.
    """
    # Validate entity_type against the closed enum if provided
    if entity_type and entity_type not in _ALLOWED_ENTITY_TYPES:
        # Return empty result; unknown type has no nodes
        return {"results": []}

    # Build the Cypher query
    conditions = ["n.dataset = $dataset"]
    params: Dict[str, Any] = {"dataset": dataset}

    if q:
        conditions.append("toLower(n.display_name) CONTAINS toLower($q)")
        params["q"] = q

    where_clause = " AND ".join(conditions)

    if entity_type:
        # Use the label directly for performance (C1 schema has per-label indexes)
        cypher = f"""
        MATCH (n:{entity_type})
        WHERE {where_clause}
        RETURN
            n.entity_id        AS entity_id,
            '{entity_type}'    AS entity_type,
            n.dataset          AS dataset,
            n.display_name     AS display_name,
            n.attributes_json  AS attributes_json,
            n.resolved_from    AS resolved_from,
            n.resolution_method AS resolution_method,
            n.created_at       AS created_at,
            n.updated_at       AS updated_at
        ORDER BY n.display_name
        LIMIT 200
        """
    else:
        cypher = f"""
        MATCH (n)
        WHERE n.entity_id IS NOT NULL AND {where_clause}
        RETURN
            n.entity_id         AS entity_id,
            n.entity_type       AS entity_type,
            n.dataset           AS dataset,
            n.display_name      AS display_name,
            n.attributes_json   AS attributes_json,
            n.resolved_from     AS resolved_from,
            n.resolution_method AS resolution_method,
            n.created_at        AS created_at,
            n.updated_at        AS updated_at
        ORDER BY n.display_name
        LIMIT 200
        """

    try:
        results = []
        with get_session() as session:
            for record in session.run(cypher, params):
                et = record.get("entity_type") or entity_type
                if et not in _ALLOWED_ENTITY_TYPES:
                    continue
                results.append(_row_to_entity(record))
        return {"results": results}
    except (ServiceUnavailable, AuthError, OSError) as exc:
        logger.warning("Neo4j unavailable in search_entities: %s", exc)
        raise GraphUnavailableError(
            "Neo4j graph is unavailable. Try again later.",
            details={"original_error": str(exc)},
        ) from exc


# ---------------------------------------------------------------------------
# §12.2  GET /entities/{entity_id}
# ---------------------------------------------------------------------------

@router.get("/{entity_id}")
async def get_entity(
    entity_id: str,
) -> Dict[str, Any]:
    """Get entity details and resolution decisions (DOC3 §12.2).

    Returns: { entity: CanonicalEntity, resolution: ResolutionDecision[] }
    or 404 (not_found) when entity_id does not exist.
    """
    # Fetch the entity node (any label — entity_id is globally unique)
    entity_cypher = """
    MATCH (n {entity_id: $entity_id})
    WHERE n.dataset IS NOT NULL AND n.display_name IS NOT NULL
    RETURN
        n.entity_id         AS entity_id,
        n.entity_type       AS entity_type,
        n.dataset           AS dataset,
        n.display_name      AS display_name,
        n.attributes_json   AS attributes_json,
        n.resolved_from     AS resolved_from,
        n.resolution_method AS resolution_method,
        n.created_at        AS created_at,
        n.updated_at        AS updated_at
    LIMIT 1
    """

    # Fetch all ResolutionDecision nodes for this entity
    decision_cypher = """
    MATCH (rd:ResolutionDecision {entity_id: $entity_id})
    RETURN
        rd.decision_id       AS decision_id,
        rd.entity_id         AS entity_id,
        rd.mention_ids       AS mention_ids,
        rd.source_record_ids AS source_record_ids,
        rd.outcome           AS outcome,
        rd.method            AS method,
        rd.matched_on        AS matched_on,
        rd.score             AS score,
        rd.decided_at        AS decided_at
    ORDER BY rd.decided_at
    """

    try:
        entity = None
        decisions = []
        with get_session() as session:
            record = session.run(entity_cypher, {"entity_id": entity_id}).single()
            if record is None:
                raise NotFoundError(
                    f"Entity '{entity_id}' not found.",
                    details={"entity_id": entity_id},
                )
            et = record.get("entity_type")
            if et not in _ALLOWED_ENTITY_TYPES:
                raise NotFoundError(
                    f"Entity '{entity_id}' not found.",
                    details={"entity_id": entity_id},
                )
            entity = _row_to_entity(record)

            for dec_record in session.run(decision_cypher, {"entity_id": entity_id}):
                decisions.append(_row_to_decision(dec_record))

        return {"entity": entity, "resolution": decisions}

    except NotFoundError:
        raise
    except (ServiceUnavailable, AuthError, OSError) as exc:
        logger.warning("Neo4j unavailable in get_entity(%s): %s", entity_id, exc)
        raise GraphUnavailableError(
            "Neo4j graph is unavailable. Try again later.",
            details={"original_error": str(exc)},
        ) from exc


# ---------------------------------------------------------------------------
# §12.3  GET /entities/{entity_id}/relationships
# ---------------------------------------------------------------------------

# All domain relationship types from DOC3 §6.2 / mention.py RelationshipType
_DOMAIN_REL_TYPES = [
    "CALLED", "OWNS", "USED", "TRANSFERRED", "VISITED",
    "MET", "WORKS_FOR", "ASSOCIATED_WITH", "MENTIONED_IN", "PART_OF",
]
_DOMAIN_REL_UNION = "|".join(_DOMAIN_REL_TYPES)


@router.get("/{entity_id}/relationships")
async def get_entity_relationships(
    entity_id: str,
    dataset: str = "synthetic_demo",
    as_of: Optional[str] = None,
) -> Dict[str, List[Dict]]:
    """Get entity relationships with inline Evidence[] (DOC3 §12.3).

    Returns: { relationships: (Relationship & {evidence: Evidence[]})[] }

    The full inline Evidence[] is included per DOC3 §12.3 (this is deliberately
    different from /graph §12.4, which includes only evidence_ids for performance).

    as_of filtering uses C5's shared implementation (Invariant 14).
    """
    # Build C5 as_of filter
    af = build_as_of_filter(as_of)

    # Match outgoing and incoming domain relationships for this entity
    cypher_parts = [
        f"MATCH (n {{entity_id: $entity_id}})-[r:{_DOMAIN_REL_UNION}]-(other)",
        "WHERE r.dataset = $dataset",
    ]
    if af.is_active:
        cypher_parts.append(f"  AND {af.relationship_where}")

    cypher_parts.append("""
    RETURN
        r.relationship_id   AS relationship_id,
        type(r)             AS relationship_type,
        r.dataset           AS dataset,
        startNode(r).entity_id AS from_entity_id,
        endNode(r).entity_id   AS to_entity_id,
        r.valid_from        AS valid_from,
        r.valid_to          AS valid_to,
        r.attributes_json   AS attributes_json,
        r.evidence_ids      AS evidence_ids,
        r.created_at        AS created_at,
        r.updated_at        AS updated_at
    ORDER BY r.valid_from
    """)

    cypher = "\n".join(cypher_parts)
    params: Dict[str, Any] = {"entity_id": entity_id, "dataset": dataset}
    params.update(af.params)

    try:
        items = []
        with get_session() as session:
            for record in session.run(cypher, params):
                rel = _row_to_relationship(record)
                # DOC3 §12.3: include full Evidence[] inline via C4 EvidenceResolver
                evidence_list = evidence_resolver.for_relationship(rel.relationship_id)
                item = rel.model_dump()
                item["evidence"] = [ev.model_dump() for ev in evidence_list]
                items.append(item)

        return {"relationships": items}

    except (ServiceUnavailable, AuthError, OSError) as exc:
        logger.warning(
            "Neo4j unavailable in get_entity_relationships(%s): %s", entity_id, exc
        )
        raise GraphUnavailableError(
            "Neo4j graph is unavailable. Try again later.",
            details={"original_error": str(exc)},
        ) from exc
