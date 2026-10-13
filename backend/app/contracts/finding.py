"""DOC3 §1.8 — Finding (Pattern/Pattern Detection output)."""

from typing import Any, List, Literal

from pydantic import BaseModel

INVESTIGATIVE_LEAD_DISCLAIMER = (
    "This is an investigative lead, not evidence of wrongdoing."
)
"""Fixed literal disclaimer (DOC3 §1.8, Contract Invariant 5). Must appear
verbatim on every Finding — no component may omit or reword it."""


class Finding(BaseModel):
    """Output of Pattern Detection. Persisted as a Neo4j node.

    DOC3 §1.8.

    Invariant: evidence_ids must be non-empty (Contract Invariant 1).
    Invariant: disclaimer must equal INVESTIGATIVE_LEAD_DISCLAIMER verbatim
               (Contract Invariant 5).
    Invariant: finding_id is stable across re-detection of the same pattern
               instance, upserted by identity key
               (rule_id, dataset, subject_entity_ids, subject_relationship_ids)
               (Contract Invariant 15).
    """

    finding_id: str
    """Globally unique. Stable across re-detection runs (DOC3 §1.13, Invariant 15)."""

    dataset: str

    rule_id: str
    """Which rule produced this, e.g. 'bridge_entity_v1'."""

    rule_name: str
    """Human-readable, e.g. 'Bridge Entity'."""

    subject_entity_ids: List[str]
    """Entities involved."""

    subject_relationship_ids: List[str]
    """Relationships involved, if applicable."""

    explanation: str
    """Plain-language, specific to this instance (DOC3 §8)."""

    triggering_values: Any = {}
    """The actual numbers/thresholds that fired, e.g. {call_count: 17, threshold: 10}."""

    evidence_ids: List[str]
    """Required — non-empty (Contract Invariant 1)."""

    disclaimer: Literal[
        "This is an investigative lead, not evidence of wrongdoing."
    ] = INVESTIGATIVE_LEAD_DISCLAIMER
    """Fixed literal, always present (Contract Invariant 5)."""

    detected_at: str
    """ISO-8601."""
