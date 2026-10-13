"""DOC3 §1.3 — EntityMention and RelationshipMention."""

from typing import Any, Literal, Optional

from pydantic import BaseModel

# Closed enum: entity types that can appear in a mention or as a CanonicalEntity.
# NOTE: "Case" is explicitly excluded per DOC3 Round-2 correction, Contract Invariant 16.
# "Transaction" is included as a first-class entity per DOC3 §1.4 decision.
EntityType = Literal[
    "Person",
    "Phone",
    "Vehicle",
    "Location",
    "Organization",
    "BankAccount",
    "Transaction",
    "Event",
]

RelationshipType = Literal[
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
]

ExtractionMethod = Literal["spacy", "regex", "llm"]


class EntityMention(BaseModel):
    """A single occurrence of an entity in one record — not yet resolved.

    DOC3 §1.3.
    """

    mention_id: str
    """Globally unique (DOC3 §1.13). Assigned by Extraction."""

    record_id: str
    """The RawRecord this mention came from."""

    dataset: str
    """Inherited from the record."""

    entity_type: EntityType
    """Must NOT include 'Case' (Contract Invariant 16)."""

    raw_text: str
    """The literal text/value extracted (e.g. 'R. Sharma', '98XXXXXXXX')."""

    normalized_value: Optional[str] = None
    """Extractor's best-effort normalization (e.g. E.164 phone). May be null."""

    attributes: Any = {}
    """Type-specific extra fields (e.g. {plate_state: 'MH'} for Vehicle)."""

    extraction_method: ExtractionMethod

    confidence: Optional[float] = None
    """0.0–1.0 if the method produces one; null if not applicable."""


class RelationshipMention(BaseModel):
    """A candidate relationship extracted from a single record.

    DOC3 §1.3.
    """

    relationship_mention_id: str
    """Globally unique."""

    record_id: str
    dataset: str

    relationship_type: RelationshipType

    from_mention_id: str
    """References EntityMention.mention_id within the same ExtractionResult."""

    to_mention_id: str
    """References EntityMention.mention_id within the same ExtractionResult."""

    occurred_at: Optional[str] = None
    """Event time if the record specifies it; else null (falls back to record.occurred_at)."""

    attributes: Any = {}
    """e.g. {duration_seconds: 340} for CALLED, {amount: 5000, currency: 'INR'} for TRANSFERRED."""

    extraction_method: ExtractionMethod
