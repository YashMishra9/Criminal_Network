"""DOC3 §1.9–§1.11 — Case, Note, EdgeRef (Case Workspace types)."""

from typing import Literal, Optional

from pydantic import BaseModel, model_validator


class Case(BaseModel):
    """An investigation case created by the investigator.

    DOC3 §1.9.
    Never produced by Extraction or Resolution (Contract Invariant 16).
    Created only via CaseWorkspace.create_case().
    """

    case_id: str
    """Globally unique (DOC3 §1.13)."""

    title: str

    status: Literal["open", "closed"]

    dataset: str
    """The dataset scope this case was created within."""

    created_at: str
    """ISO-8601."""

    updated_at: str
    """ISO-8601."""


class Note(BaseModel):
    """A timestamped note attached to a case, optionally scoped to a specific item.

    DOC3 §1.10.

    Invariant: at most one of about_entity_id / about_edge_ref_id / about_evidence_id
    is non-null at a time (DOC3 §1.10).
    """

    note_id: str
    """Globally unique (DOC3 §1.13)."""

    case_id: str

    text: str

    about_entity_id: Optional[str] = None
    about_edge_ref_id: Optional[str] = None
    about_evidence_id: Optional[str] = None

    created_at: str
    """ISO-8601."""

    @model_validator(mode="after")
    def validate_at_most_one_about(self) -> "Note":
        """Enforce DOC3 §1.10 invariant: at most one 'about_*' field is non-null."""
        about_fields = [
            self.about_entity_id,
            self.about_edge_ref_id,
            self.about_evidence_id,
        ]
        non_null = sum(1 for v in about_fields if v is not None)
        if non_null > 1:
            raise ValueError(
                "At most one of about_entity_id, about_edge_ref_id, about_evidence_id "
                "may be non-null (DOC3 §1.10)."
            )
        return self


class EdgeRef(BaseModel):
    """Pointer node standing in for a Relationship wherever something needs to
    reference an edge as if it were a node.

    DOC3 §1.11.

    Invariant: exactly one EdgeRef exists per Relationship (Contract Invariant 12).
    Created once by the Graph Write Layer at relationship-creation time.
    """

    edge_ref_id: str
    """Globally unique (DOC3 §1.13)."""

    relationship_id: str
    """The Relationship this points to."""

    from_entity_id: str
    """Denormalized for display convenience."""

    to_entity_id: str

    relationship_type: str

    created_at: str
    """ISO-8601."""
