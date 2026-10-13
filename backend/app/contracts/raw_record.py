"""DOC3 §1.1–§1.2 — RawRecord and AdapterDescriptor."""

from typing import Any, Literal, Optional

from pydantic import BaseModel


class RawRecord(BaseModel):
    """Normalized output of any Source Adapter; sole input to Entity Extraction.

    DOC3 §1.1.
    """

    record_id: str
    """Globally unique, stable, adapter-assigned. Unique within dataset (DOC3 §1.13)."""

    dataset: Literal["synthetic_demo", "live_public"]
    """Which dataset this record belongs to (DOC3 §2.1)."""

    source_type: str
    """e.g. 'FIR', 'CDR', 'transaction', 'vehicle_registry', 'surveillance',
    'social_media', 'rss', 'org_registry' (DOC3 §2.2)."""

    source_adapter_id: str
    """Which adapter produced this, e.g. 'synthetic_v1', 'rss_public_v1'."""

    occurred_at: Optional[str] = None
    """When the underlying event happened, if known (ISO-8601). May be null."""

    ingested_at: str
    """When the adapter fetched/emitted this record (ISO-8601). Always set."""

    payload: Any
    """Adapter-specific raw content (free-form; extraction reads this)."""

    payload_text: Optional[str] = None
    """Flattened text form of payload, for NLP/LLM convenience. May be null."""


class AdapterDescriptor(BaseModel):
    """Static description of a configured adapter. DOC3 §1.2."""

    adapter_id: str
    source_type: str
    dataset: Literal["synthetic_demo", "live_public"]
    mode: Literal["batch", "poll"]
    enabled: bool
    poll_interval_seconds: Optional[float] = None
    """Required when mode == 'poll'; null for batch adapters."""

    last_run_at: Optional[str] = None
    last_run_status: Literal["ok", "error", "never_run"] = "never_run"
    last_error: Optional[str] = None
