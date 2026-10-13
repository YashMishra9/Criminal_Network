"""DOC3 §1.7 — ResolutionDecision."""

from typing import List, Literal, Optional

from pydantic import BaseModel

from app.contracts.entity import ResolutionMethod


class ResolutionDecision(BaseModel):
    """Records why mentions were (or were not) merged into a canonical entity.

    DOC3 §1.7. Persisted as a Neo4j node; satisfies FR10 (inspectable resolution)
    and is the canonical provenance mechanism for every CanonicalEntity (DOC3 §2.5).
    """

    decision_id: str
    """Globally unique (DOC3 §1.13)."""

    entity_id: str
    """The resulting (or candidate) CanonicalEntity."""

    mention_ids: List[str]
    """Mentions considered together in this decision."""

    source_record_ids: List[str]
    """RawRecord.record_id for each entry in mention_ids, same order/length.
    This is what makes the entity → evidence path exact without needing to persist
    EntityMention as a graph node (DOC3 §1.7, §2.5)."""

    outcome: Literal["merged", "rejected"]

    method: ResolutionMethod

    matched_on: List[str]
    """e.g. ['phone_number', 'name_similarity>0.85']"""

    score: Optional[float] = None
    """Similarity/confidence score if applicable."""

    decided_at: str
    """ISO-8601."""
