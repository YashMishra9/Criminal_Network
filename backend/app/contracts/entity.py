"""DOC3 §1.4 — CanonicalEntity."""

from typing import Any, List, Literal

from pydantic import BaseModel

from app.contracts.mention import EntityType

ResolutionMethod = Literal[
    "exact_match",
    "fuzzy_match",
    "shared_attribute",
    "embedding_similarity",
    "manual",
]


class CanonicalEntity(BaseModel):
    """The resolved, graph-level entity — maps to a Neo4j node.

    DOC3 §1.4.
    """

    entity_id: str
    """Stable graph identity, generated at first resolution. Globally unique (DOC3 §1.13)."""

    entity_type: EntityType
    """Closed enum. 'Case' is explicitly excluded (Contract Invariant 16).
    'Transaction' is included as a first-class entity (DOC3 §1.4 decision)."""

    dataset: str
    """Resolution does not cross datasets by default (DOC3 §2.5)."""

    display_name: str
    """Best-representative value for UI."""

    attributes: Any = {}
    """Merged/canonical attributes."""

    resolved_from: List[str]
    """List of mention_id values folded into this entity (DOC3 §2.5 provenance path)."""

    resolution_method: ResolutionMethod

    created_at: str
    """ISO-8601."""

    updated_at: str
    """ISO-8601."""
