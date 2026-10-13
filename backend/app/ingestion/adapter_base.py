"""SourceAdapter Interface — DOC3 §3.

Task B1: Defines the abstract base class every ingestion adapter must implement.
This is the seam that keeps ingestion source-agnostic (DOC2 §6).

Exactly three methods are defined — no more (B1 §17 constraint):
  descriptor()    -> AdapterDescriptor
  fetch_batch()   -> list[RawRecord]       (adapters with mode == 'batch')
  poll(cursor)    -> PollResult            (adapters with mode == 'poll')

B2 (SyntheticAdapter) and B3 (LivePublicAdapter) must implement this interface
without modifying it.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.contracts.raw_record import AdapterDescriptor, RawRecord


class PollResult:
    """Return type of SourceAdapter.poll().

    Attributes:
        records:     New records since the given cursor. May be empty if nothing
                     is new — this is not an error condition (DOC3 §3).
        next_cursor: Opaque string the Ingestion Orchestrator must persist and
                     pass back unchanged on the next poll() call. The adapter
                     owns the cursor format entirely; no other component may
                     interpret its internal structure (DOC3 §3 cursor rule).
    """

    __slots__ = ("records", "next_cursor")

    def __init__(self, records: List[RawRecord], next_cursor: str) -> None:
        self.records = records
        self.next_cursor = next_cursor

    def __repr__(self) -> str:
        return (
            f"PollResult(records={len(self.records)} record(s), "
            f"next_cursor={self.next_cursor!r})"
        )


class SourceAdapter(ABC):
    """Abstract base class for all Source Adapters.

    DOC3 §3: "Every adapter (synthetic or live) implements this interface.
    This is the seam that keeps ingestion source-agnostic per DOC2 §6."

    Exactly three methods must be implemented — no more, no less (B1 §17):

    descriptor()
        Return the static metadata for this adapter.  Must always succeed;
        no network calls are made.

    fetch_batch()
        **Required when mode == 'batch' (synthetic_demo dataset only).**
        Returns ALL available records in one synchronous call.

        Idempotency requirement (DOC3 §3):
            Calling fetch_batch() again must return records with the same
            record_id values (unchanged content) unless the underlying
            synthetic dataset files themselves changed.  Downstream components
            that write to Neo4j rely on this to make upserts safe.

        Error behavior (DOC3 §3):
            A broken synthetic adapter is a build-blocking defect, not a
            runtime-degradation case.  Implementations should log clearly and
            raise rather than silently returning an empty list, so the failure
            is immediately visible.

    poll(cursor)
        **Required when mode == 'poll' (live_public dataset only).**
        Returns only records new since the given cursor.

        Cursor ownership rule (DOC3 §3):
            Cursors are opaque strings owned entirely by the adapter (e.g., a
            timestamp or an API-provided pagination token).  The Ingestion
            Orchestrator persists next_cursor and passes it back unchanged on
            the next call.  No other component interprets the cursor format.

        Error behavior (DOC3 §3 §6.3):
            Implementations MUST catch all network/parsing errors internally
            and return PollResult(records=[], next_cursor=<unchanged>) rather
            than raising.  A failed poll is silent to the pipeline — logged,
            not propagated.  The orchestrator must not treat an empty result as
            an error.

        Status tracking (DOC3 §3):
            Every call (success or failure) must update the adapter's internal
            last_run_status / last_error so the ingestion status endpoint can
            report state without the adapter throwing across the boundary.
    """

    @abstractmethod
    def descriptor(self) -> AdapterDescriptor:
        """Return the static AdapterDescriptor for this adapter.

        Must always succeed — no I/O or network calls.
        """
        ...

    @abstractmethod
    def fetch_batch(self) -> List[RawRecord]:
        """Return all available records (batch mode only).

        See class docstring for idempotency and error-behavior requirements.
        Raises:
            NotImplementedError: if the adapter mode is not 'batch'.
        """
        ...

    @abstractmethod
    def poll(self, cursor: Optional[str]) -> PollResult:
        """Return new records since cursor (poll mode only).

        Args:
            cursor: The opaque cursor returned by the previous poll() call,
                    or None for the first call (return all records available).

        Returns:
            PollResult with zero or more records and the next cursor value.

        See class docstring for cursor ownership, error-behavior, and status
        tracking requirements.

        Raises:
            NotImplementedError: if the adapter mode is not 'poll'.
        """
        ...
