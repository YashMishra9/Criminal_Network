"""DOC3 §1.5 — Relationship (graph edge)."""

from typing import Any, List, Optional

from pydantic import BaseModel

from app.contracts.mention import RelationshipType


class Relationship(BaseModel):
    """The resolved, graph-level relationship — maps to a Neo4j relationship.

    DOC3 §1.5.

    Invariant: evidence_ids must be non-empty before this is written to the graph
    or returned by any API (DOC3 §15, Contract Invariant 1).
    """

    relationship_id: str
    """Globally unique (DOC3 §1.13)."""

    relationship_type: RelationshipType

    from_entity_id: str
    to_entity_id: str

    dataset: str

    attributes: Any = {}

    valid_from: str
    """Required — earliest known occurrence (ISO-8601). Derived from occurred_at,
    falling back to ingested_at with attributes.timestamp_is_fallback=true (DOC3 §2.4)."""

    valid_to: Optional[str] = None
    """Null if open-ended / not applicable."""

    evidence_ids: List[str]
    """Evidence.evidence_id[] — at least one required (DOC3 §15 Invariant 1)."""

    created_at: str
    updated_at: str
