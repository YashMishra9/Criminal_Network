"""Graph API Router — C6 implementation.

Implements DOC3 §12.4:
  GET /graph?dataset=&as_of=&entity_types=&relationship_types=&community=&pattern=
  → { entities: CanonicalEntity[], relationships: Relationship[] }

Contract rules (DOC3 §12.4):
  - relationships carry evidence_ids only, NOT full Evidence[] (performance,
    deliberate DOC3 §12.3 vs §12.4 distinction).
  - as_of filtering uses C5's shared build_as_of_filter() (Invariant 14).
  - dataset defaults to 'synthetic_demo' (DOC3 §2.6).
  - entity_types and relationship_types are comma-separated filter lists;
    unknown values silently match nothing (result is empty for that type).
  - community and pattern filter by the matching property on nodes, if present.
  - All errors go through A6's typed exception classes.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from neo4j.exceptions import AuthError, ServiceUnavailable

from app.contracts.entity import CanonicalEntity
from app.contracts.errors import GraphUnavailableError
from app.contracts.relationship import Relationship
from app.graph.connection import get_session
from app.graph.queries import build_as_of_filter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])

# ---------------------------------------------------------------------------
# Constants — DOC3 §6.1/§6.2 closed enums
# ---------------------------------------------------------------------------

_ALL_ENTITY_TYPES = [
    "Person", "Phone", "Vehicle", "Location", "Organization",
    "BankAccount", "Transaction", "Event",
]

_ALL_REL_TYPES = [
    "CALLED", "OWNS", "USED", "TRANSFERRED", "VISITED",
    "MET", "WORKS_FOR", "ASSOCIATED_WITH", "MENTIONED_IN", "PART_OF",
]

_ALLOWED_ENTITY_TYPES = frozenset(_ALL_ENTITY_TYPES)
_ALLOWED_REL_TYPES = frozenset(_ALL_REL_TYPES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_entity(record: Any) -> CanonicalEntity:
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
        resolved_from=list(record.get("resolved_from") or []),
        resolution_method=record["resolution_method"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def _row_to_relationship(record: Any) -> Relationship:
    attrs_raw = record.get("attributes_json")
    try:
        attributes = json.loads(attrs_raw) if attrs_raw else {}
    except (ValueError, TypeError):
        attributes = {}
    return Relationship(
        relationship_id=record["relationship_id"],
        relationship_type=record["relationship_type"],
        from_entity_id=record["from_entity_id"],
        to_entity_id=record["to_entity_id"],
        dataset=record["dataset"],
        attributes=attributes,
        valid_from=record["valid_from"],
        valid_to=record.get("valid_to"),
        evidence_ids=list(record.get("evidence_ids") or []),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def _parse_csv_param(value: Optional[str], allowed: frozenset) -> List[str]:
    """Parse a comma-separated query parameter, filtering to allowed values."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip() in allowed]


# ---------------------------------------------------------------------------
# §12.4  GET /graph
# ---------------------------------------------------------------------------

@router.get("")
async def get_graph(
    dataset: str = "synthetic_demo",
    as_of: Optional[str] = None,
    entity_types: Optional[str] = None,
    relationship_types: Optional[str] = None,
    community: Optional[str] = None,
    pattern: Optional[str] = None,
) -> Dict[str, Any]:
    """Get filtered graph snapshot for network visualization (DOC3 §12.4).

    Returns: { entities: CanonicalEntity[], relationships: Relationship[] }

    Relationships carry evidence_ids only (not full Evidence[]) per DOC3 §12.4.
    as_of filtering follows §2.4A exactly via C5's build_as_of_filter().

    Filtering:
      - entity_types: comma-separated list of entity type labels (e.g. "Person,Phone")
      - relationship_types: comma-separated list of relationship types
      - community: filter entities by community property value
      - pattern: filter entities by pattern property value (used by Pattern Detection)
    """
    # Build C5 as_of filter (Invariant 14)
    af = build_as_of_filter(as_of)

    # Parse and validate CSV filter params
    req_entity_types = _parse_csv_param(entity_types, _ALLOWED_ENTITY_TYPES)
    req_rel_types = _parse_csv_param(relationship_types, _ALLOWED_REL_TYPES)

    # Determine which relationship types to match
    active_rel_types = req_rel_types if req_rel_types else _ALL_REL_TYPES
    rel_union = "|".join(active_rel_types)

    # Determine which entity labels to match
    if req_entity_types:
        # Filter to specific labels using label union syntax (Cypher 4+)
        entity_label_filter = " OR ".join(
            f"n:{et}" for et in req_entity_types
        )
    else:
        # All entity types — match any node that has entity_id (avoids metadata nodes)
        entity_label_filter = None

    params: Dict[str, Any] = {"dataset": dataset}
    params.update(af.params)

    try:
        relationships: List[Relationship] = []
        rel_entity_ids: set = set()

        # ----------------------------------------------------------------
        # Step 1: Fetch all matching, temporally-visible relationships
        # ----------------------------------------------------------------
        rel_conditions = ["r.dataset = $dataset"]
        if af.is_active:
            rel_conditions.append(af.relationship_where)
        if req_rel_types:
            # Already filtered by Cypher type pattern
            pass

        rel_where = " AND ".join(rel_conditions)

        rel_cypher = f"""
        MATCH (from_n)-[r:{rel_union}]->(to_n)
        WHERE {rel_where}
        RETURN
            r.relationship_id       AS relationship_id,
            type(r)                 AS relationship_type,
            r.dataset               AS dataset,
            from_n.entity_id        AS from_entity_id,
            to_n.entity_id          AS to_entity_id,
            r.valid_from            AS valid_from,
            r.valid_to              AS valid_to,
            r.attributes_json       AS attributes_json,
            r.evidence_ids          AS evidence_ids,
            r.created_at            AS created_at,
            r.updated_at            AS updated_at
        ORDER BY r.valid_from
        """

        with get_session() as session:
            for record in session.run(rel_cypher, params):
                rel = _row_to_relationship(record)
                relationships.append(rel)
                rel_entity_ids.add(rel.from_entity_id)
                rel_entity_ids.add(rel.to_entity_id)

        # ----------------------------------------------------------------
        # Step 2: Fetch entities
        # DOC3 §2.4A Rule 2:
        #   (a) entities that participate in ≥1 visible relationship (rel_entity_ids)
        #   (b) isolated entities — zero relationships in the dataset (always shown)
        # Entity types are filtered by entity_types param if provided.
        # ----------------------------------------------------------------
        entities: List[CanonicalEntity] = []

        entity_params: Dict[str, Any] = {"dataset": dataset}

        if rel_entity_ids:
            entity_params["rel_entity_ids"] = list(rel_entity_ids)

        # Build extra filters
        extra_entity_conditions = []
        if community:
            extra_entity_conditions.append("n.community = $community")
            entity_params["community"] = community
        if pattern:
            extra_entity_conditions.append("n.pattern = $pattern")
            entity_params["pattern"] = pattern

        extra_where = (" AND " + " AND ".join(extra_entity_conditions)
                       if extra_entity_conditions else "")

        # Fetch visible entities from relationships (Rule 2a) —
        # only those that match the entity_types filter.
        if rel_entity_ids:
            if entity_label_filter:
                entity_cypher_a = f"""
                MATCH (n)
                WHERE ({entity_label_filter})
                  AND n.dataset = $dataset
                  AND n.entity_id IN $rel_entity_ids{extra_where}
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
                """
            else:
                entity_cypher_a = f"""
                MATCH (n)
                WHERE n.entity_id IS NOT NULL
                  AND n.dataset = $dataset
                  AND n.entity_id IN $rel_entity_ids{extra_where}
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
                """

            with get_session() as session:
                for record in session.run(entity_cypher_a, entity_params):
                    et = record.get("entity_type")
                    if et not in _ALLOWED_ENTITY_TYPES:
                        continue
                    entities.append(_row_to_entity(record))

        # Fetch isolated entities (Rule 2b) — only when no entity_types filter
        # constrains them (or when the filter includes their type).
        # An isolated entity has zero relationships in the dataset.
        if entity_label_filter:
            iso_label_match = f"MATCH (n)\n        WHERE ({entity_label_filter})"
        else:
            iso_label_match = "MATCH (n)\n        WHERE n.entity_id IS NOT NULL"

        isolated_rel_union = "|".join(_ALL_REL_TYPES)
        iso_cypher = f"""
        {iso_label_match}
          AND n.dataset = $dataset{extra_where}
          AND NOT EXISTS {{
              MATCH (n)-[:{isolated_rel_union}]-()
              WHERE true
          }}
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
        """

        iso_params: Dict[str, Any] = {"dataset": dataset}
        if community:
            iso_params["community"] = community
        if pattern:
            iso_params["pattern"] = pattern

        with get_session() as session:
            for record in session.run(iso_cypher, iso_params):
                et = record.get("entity_type")
                if et not in _ALLOWED_ENTITY_TYPES:
                    continue
                entities.append(_row_to_entity(record))

        return {
            "entities": entities,
            "relationships": relationships,
        }

    except (ServiceUnavailable, AuthError, OSError) as exc:
        logger.warning("Neo4j unavailable in get_graph: %s", exc)
        raise GraphUnavailableError(
            "Neo4j graph is unavailable. Try again later.",
            details={"original_error": str(exc)},
        ) from exc
