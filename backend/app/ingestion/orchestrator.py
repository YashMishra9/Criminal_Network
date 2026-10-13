"""Ingestion Orchestrator — DOC3 §3, DOC3 §2.6, B4.

Task B4: Coordinates calling configured adapters (respecting
LIVE_ADAPTER_ENABLED), persists poll cursors, and hands off normalized
RawRecord objects to a downstream consumer (Extraction).

Contract Invariants enforced here:
  Invariant 8: Source adapters never write directly to the graph. All
    RawRecord objects produced by adapters are passed to the caller-supplied
    consumer callback (Extraction). The orchestrator never touches Neo4j.
  Invariant 2 / DOC3 §2.6: When LIVE_ADAPTER_ENABLED=False only
    synthetic_demo records flow through. When True, both datasets flow,
    each correctly tagged by their adapter.

DOC3 §3 cursor rule:
  The orchestrator persists whatever next_cursor it receives from poll()
  and passes it back unchanged on the next call. It never interprets the
  cursor's internal format.

Design (DOC2 §6.3, §6.4):
  - In-process only — no message queue, no worker process, no infrastructure.
  - The consumer is an injected callable (type: RecordConsumer). This keeps
    the orchestrator decoupled from Extraction's implementation and fully
    testable in isolation.
  - Cursor state is held in-memory. Persistence across restarts is out of scope
    for the prototype (the live adapter is optional/non-demo-critical).
"""

import logging
from typing import Callable, Dict, List, Optional

from app.contracts.raw_record import RawRecord
from app.ingestion.adapter_base import SourceAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

# The downstream consumer of ingested records.
# Extraction will implement this signature (B5 onwards).
# For now, any callable that accepts a list of RawRecords satisfies it.
RecordConsumer = Callable[[List[RawRecord]], None]


# ---------------------------------------------------------------------------
# IngestionOrchestrator
# ---------------------------------------------------------------------------

class IngestionOrchestrator:
    """Coordinates adapter calls, cursor persistence, and record hand-off.

    Usage:
        orchestrator = IngestionOrchestrator(
            synthetic_adapter=SyntheticAdapter(),
            live_adapter=LivePublicAdapter(...),   # or None
            live_adapter_enabled=config.LIVE_ADAPTER_ENABLED,
            consumer=extraction_pipeline.process,
        )
        orchestrator.run_batch()    # synthetic only (or both if enabled)
        orchestrator.run_poll()     # poll live adapter (no-op if disabled)

    The orchestrator holds no Neo4j connection and performs no graph writes
    (Contract Invariant 8). All records are handed to ``consumer``.
    """

    def __init__(
        self,
        synthetic_adapter: SourceAdapter,
        consumer: RecordConsumer,
        live_adapter: Optional[SourceAdapter] = None,
        live_adapter_enabled: bool = False,
    ) -> None:
        """Initialise the orchestrator.

        Args:
            synthetic_adapter:    The B2 SyntheticAdapter instance.
            consumer:             Callable that receives List[RawRecord].
                                  This is where Extraction plugs in.
            live_adapter:         The B3 LivePublicAdapter instance, or None.
            live_adapter_enabled: Mirror of config.LIVE_ADAPTER_ENABLED.
                                  When False the live adapter is never called.
        """
        self._synthetic = synthetic_adapter
        self._live = live_adapter
        self._live_enabled = live_adapter_enabled
        self._consumer = consumer

        # In-memory cursor store (DOC3 §3 — opaque string per adapter_id)
        self._cursors: Dict[str, Optional[str]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_batch(self) -> int:
        """Run fetch_batch() on the synthetic adapter and hand records to consumer.

        Always runs regardless of LIVE_ADAPTER_ENABLED (the synthetic adapter
        is the guaranteed demo path — DOC1 NFR3, Contract Invariant 7).

        Returns:
            Total number of RawRecord objects passed to the consumer.
        """
        logger.info("IngestionOrchestrator: running batch ingestion (synthetic).")

        records = self._synthetic.fetch_batch()
        total = len(records)
        logger.info("Synthetic adapter produced %d record(s).", total)

        if records:
            self._consumer(records)

        self._update_descriptor_log(self._synthetic, "batch", total)
        return total

    def run_poll(self) -> int:
        """Run poll() on the live adapter (if enabled) and hand records to consumer.

        When LIVE_ADAPTER_ENABLED is False this is a no-op (returns 0).

        DOC3 §3 cursor rule: the cursor returned by poll() is stored as-is
        and passed back unchanged on the next call. Its internal format is
        never inspected.

        Returns:
            Number of new RawRecord objects passed to the consumer, or 0 if
            the live adapter is disabled, unconfigured, or returned nothing.
        """
        if not self._live_enabled:
            logger.debug(
                "IngestionOrchestrator.run_poll(): live adapter disabled "
                "(LIVE_ADAPTER_ENABLED=False). Skipping."
            )
            return 0

        if self._live is None:
            logger.warning(
                "IngestionOrchestrator.run_poll(): live adapter is enabled "
                "but no live adapter instance was provided. Skipping."
            )
            return 0

        adapter_id = self._live.descriptor().adapter_id
        cursor = self._cursors.get(adapter_id)

        logger.info(
            "IngestionOrchestrator: polling live adapter '%s' (cursor=%r).",
            adapter_id,
            cursor,
        )

        # poll() is guaranteed to never raise (DOC3 §3 / B3 contract)
        result = self._live.poll(cursor)

        # Persist cursor unchanged (DOC3 §3 — opaque, never interpreted)
        self._cursors[adapter_id] = result.next_cursor
        logger.debug(
            "Cursor for '%s' updated: %r → %r", adapter_id, cursor, result.next_cursor
        )

        total = len(result.records)
        if result.records:
            self._consumer(result.records)

        self._update_descriptor_log(self._live, "poll", total)
        return total

    def run(self) -> Dict[str, int]:
        """Run all adapters in the correct order.

        Runs the synthetic adapter first (always), then the live adapter (only
        when enabled). Returns record counts per dataset.

        Returns:
            dict with keys 'synthetic_demo' and 'live_public', each mapping
            to the number of records handed to the consumer.
        """
        counts: Dict[str, int] = {
            "synthetic_demo": self.run_batch(),
            "live_public": self.run_poll(),
        }
        logger.info(
            "IngestionOrchestrator.run() complete: %s", counts
        )
        return counts

    def get_cursor(self, adapter_id: str) -> Optional[str]:
        """Return the stored cursor for an adapter, or None if never polled.

        Exposed for testing and for the ingestion status endpoint.
        """
        return self._cursors.get(adapter_id)

    def reset_cursor(self, adapter_id: str) -> None:
        """Clear the stored cursor for an adapter (forces full re-poll next time).

        Should only be called intentionally (e.g., when the live adapter feed
        is reconfigured and historical cursor is invalid).
        """
        self._cursors.pop(adapter_id, None)
        logger.info("Cursor for adapter '%s' reset.", adapter_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _update_descriptor_log(
        adapter: SourceAdapter, mode: str, count: int
    ) -> None:
        """Log the adapter's current descriptor status after a run."""
        try:
            d = adapter.descriptor()
            logger.info(
                "Adapter '%s' (%s) last_run_status=%s records=%d last_error=%r",
                d.adapter_id,
                mode,
                d.last_run_status,
                count,
                d.last_error,
            )
        except Exception:  # noqa: BLE001
            pass  # descriptor logging is informational only
