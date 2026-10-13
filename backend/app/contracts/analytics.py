"""DOC3 §1.12 — AnalyticsResult and ShortestPathResult."""

from typing import List, Optional

from pydantic import BaseModel


class CentralityEntry(BaseModel):
    """Per-entity centrality scores (DOC3 §1.12)."""

    entity_id: str
    degree: float
    betweenness: float
    pagerank: float


class CommunityEntry(BaseModel):
    """Per-entity community assignment (DOC3 §1.12)."""

    entity_id: str
    community_id: str


class AnalyticsResult(BaseModel):
    """Output of the Analytics Service.

    DOC3 §1.12.
    """

    computed_at: str
    """ISO-8601."""

    dataset: str

    as_of: Optional[str] = None
    """If computed over a temporal-filtered snapshot (DOC3 §2.4A); null = full current graph."""

    centrality: List[CentralityEntry]
    communities: List[CommunityEntry]


class ShortestPathResult(BaseModel):
    """Result of a shortest-path analytics request.

    DOC3 §7 (returned alongside AnalyticsResult when 'shortest_path' is requested).
    """

    found: bool
    path_entity_ids: List[str]
    """Ordered entity IDs along the path."""

    path_relationship_ids: List[str]
    """Ordered relationship IDs along the path."""
