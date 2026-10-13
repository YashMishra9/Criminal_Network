"""DOC3 §1.6 — Evidence."""

from typing import Any, Optional

from pydantic import BaseModel


class Evidence(BaseModel):
    """Provenance record linking a graph claim to its source record.

    DOC3 §1.6.
    """

    evidence_id: str
    """Globally unique. Same (source_id, dataset) pair always resolves to the
    same evidence_id on repeated writes (idempotent) — DOC3 §1.13."""

    dataset: str

    source_id: str
    """== RawRecord.record_id this was derived from."""

    source_type: str

    record_timestamp: Optional[str] = None
    """== RawRecord.occurred_at. May be null."""

    ingested_at: str
    """== RawRecord.ingested_at."""

    snippet: Optional[str] = None
    """Short human-readable excerpt, if applicable."""

    pointer: Optional[Any] = None
    """Adapter-specific pointer back to full original record. May be null."""
