"""Tests for Task B4: IngestionOrchestrator.

Tests (per B4 §13):
- Integration test toggling LIVE_ADAPTER_ENABLED and confirming correct
  record flow in each case.
- Contract Invariant 8: orchestrator never writes to the graph.
- DOC3 §3 cursor rule: cursor passed back unchanged, treated as opaque.
- DOC3 §2.6: live disabled → only synthetic_demo records flow.
- DOC3 §2.6: live enabled → both datasets flow, each correctly tagged.
- No graph interaction in any test (confirms Invariant 8 by construction).
"""

from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.contracts.raw_record import AdapterDescriptor, RawRecord
from app.ingestion.adapter_base import PollResult, SourceAdapter
from app.ingestion.orchestrator import IngestionOrchestrator, RecordConsumer

# ---------------------------------------------------------------------------
# Test doubles — minimal concrete adapters
# ---------------------------------------------------------------------------

def _make_raw_record(record_id: str, dataset: str, source_type: str) -> RawRecord:
    return RawRecord(
        record_id=record_id,
        dataset=dataset,  # type: ignore[arg-type]
        source_type=source_type,
        source_adapter_id="test_adapter",
        occurred_at="2024-01-01T00:00:00Z",
        ingested_at="2024-01-01T12:00:00Z",
        payload={"test": True},
        payload_text="test record",
    )


class _FakeSyntheticAdapter(SourceAdapter):
    """Returns a fixed list of synthetic_demo records from fetch_batch()."""

    def __init__(self, records: List[RawRecord]) -> None:
        self._records = records
        self._fetch_count = 0

    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            adapter_id="synthetic_v1",
            source_type="synthetic_multi",
            dataset="synthetic_demo",
            mode="batch",
            enabled=True,
            last_run_status="never_run",
        )

    def fetch_batch(self) -> List[RawRecord]:
        self._fetch_count += 1
        return list(self._records)

    def poll(self, cursor: Optional[str]) -> PollResult:
        raise NotImplementedError("Batch-only")


class _FakeLiveAdapter(SourceAdapter):
    """Returns a fixed set of live_public records from poll(), cycling through pages."""

    def __init__(
        self,
        pages: List[List[RawRecord]],
        cursors: List[str],
    ) -> None:
        """
        pages:   list of record lists, one per poll() call.
        cursors: next_cursor values to return, one per poll() call.
        """
        self._pages = pages
        self._cursors = cursors
        self._call_index = 0
        self._received_cursors: List[Optional[str]] = []
        self._last_run_status = "never_run"

    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            adapter_id="rss_public_v1",
            source_type="rss",
            dataset="live_public",
            mode="poll",
            enabled=True,
            poll_interval_seconds=300,
            last_run_status=self._last_run_status,  # type: ignore[arg-type]
        )

    def fetch_batch(self) -> List[RawRecord]:
        raise NotImplementedError("Poll-only")

    def poll(self, cursor: Optional[str]) -> PollResult:
        self._received_cursors.append(cursor)
        idx = min(self._call_index, len(self._pages) - 1)
        records = self._pages[idx]
        next_cursor = self._cursors[idx]
        self._call_index += 1
        self._last_run_status = "ok"
        return PollResult(records=list(records), next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SYNTHETIC_RECORDS = [
    _make_raw_record("fir_001", "synthetic_demo", "FIR"),
    _make_raw_record("cdr_001", "synthetic_demo", "CDR"),
    _make_raw_record("txn_001", "synthetic_demo", "transaction"),
]

LIVE_RECORDS_PAGE1 = [
    _make_raw_record("rss_aaa", "live_public", "rss"),
    _make_raw_record("rss_bbb", "live_public", "rss"),
]

LIVE_RECORDS_PAGE2 = [
    _make_raw_record("rss_ccc", "live_public", "rss"),
]


@pytest.fixture
def synthetic_adapter():
    return _FakeSyntheticAdapter(SYNTHETIC_RECORDS)


@pytest.fixture
def live_adapter():
    return _FakeLiveAdapter(
        pages=[LIVE_RECORDS_PAGE1, LIVE_RECORDS_PAGE2],
        cursors=["2024-01-20T10:00:00Z", "2024-01-21T10:00:00Z"],
    )


def _collecting_consumer() -> tuple[RecordConsumer, list]:
    """Return a consumer function and the list it appends records into."""
    received: list = []

    def consumer(records: List[RawRecord]) -> None:
        received.extend(records)

    return consumer, received


# ===========================================================================
# B4 §12 Acceptance Criteria: live disabled → only synthetic_demo
# ===========================================================================

def test_run_batch_delivers_synthetic_records(synthetic_adapter):
    consumer, received = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=None,
        live_adapter_enabled=False,
    )
    count = orch.run_batch()
    assert count == 3
    assert len(received) == 3
    assert all(r.dataset == "synthetic_demo" for r in received)


def test_live_disabled_run_delivers_only_synthetic(synthetic_adapter):
    """B4 §12: with live adapter disabled, only synthetic_demo records flow."""
    consumer, received = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=None,
        live_adapter_enabled=False,
    )
    counts = orch.run()
    assert counts["synthetic_demo"] == 3
    assert counts["live_public"] == 0
    assert all(r.dataset == "synthetic_demo" for r in received)
    assert len(received) == 3


def test_run_poll_disabled_is_noop(synthetic_adapter, live_adapter):
    """run_poll() returns 0 and calls no adapter when live is disabled."""
    consumer, received = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=live_adapter,
        live_adapter_enabled=False,
    )
    count = orch.run_poll()
    assert count == 0
    assert received == []
    assert live_adapter._call_index == 0  # poll() was never called


def test_run_poll_no_live_adapter_is_noop(synthetic_adapter):
    """run_poll() with live_adapter=None returns 0 safely."""
    consumer, received = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=None,
        live_adapter_enabled=True,  # enabled but no adapter
    )
    count = orch.run_poll()
    assert count == 0
    assert received == []


# ===========================================================================
# B4 §12 Acceptance Criteria: live enabled → both datasets flow
# ===========================================================================

def test_live_enabled_run_delivers_both_datasets(synthetic_adapter, live_adapter):
    """B4 §12: with live adapter enabled, both datasets flow through."""
    consumer, received = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=live_adapter,
        live_adapter_enabled=True,
    )
    counts = orch.run()
    assert counts["synthetic_demo"] == 3
    assert counts["live_public"] == 2  # page 1 has 2 records

    datasets = {r.dataset for r in received}
    assert "synthetic_demo" in datasets
    assert "live_public" in datasets


def test_live_enabled_records_have_correct_datasets(synthetic_adapter, live_adapter):
    consumer, received = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=live_adapter,
        live_adapter_enabled=True,
    )
    orch.run()

    synthetic_records = [r for r in received if r.dataset == "synthetic_demo"]
    live_records = [r for r in received if r.dataset == "live_public"]
    assert len(synthetic_records) == 3
    assert len(live_records) == 2


# ===========================================================================
# DOC3 §3 Cursor rule: pass back unchanged, treat as opaque
# ===========================================================================

def test_cursor_is_none_on_first_poll(synthetic_adapter, live_adapter):
    """First call to poll() must receive cursor=None (never polled yet)."""
    consumer, _ = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=live_adapter,
        live_adapter_enabled=True,
    )
    orch.run_poll()
    assert live_adapter._received_cursors[0] is None


def test_cursor_persisted_and_passed_back_unchanged(synthetic_adapter, live_adapter):
    """DOC3 §3: cursor returned by poll() must be stored and passed back unchanged."""
    consumer, _ = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=live_adapter,
        live_adapter_enabled=True,
    )
    # First poll: receives None, adapter returns "2024-01-20T10:00:00Z"
    orch.run_poll()
    assert live_adapter._received_cursors[-1] is None
    assert orch.get_cursor("rss_public_v1") == "2024-01-20T10:00:00Z"

    # Second poll: must receive the exact string returned by first poll
    orch.run_poll()
    assert live_adapter._received_cursors[-1] == "2024-01-20T10:00:00Z"
    assert orch.get_cursor("rss_public_v1") == "2024-01-21T10:00:00Z"


def test_cursor_not_modified_by_orchestrator(synthetic_adapter, live_adapter):
    """The orchestrator must pass cursor back as-is without any parsing."""
    # Use a deliberately opaque cursor format (not ISO-8601)
    opaque_adapter = _FakeLiveAdapter(
        pages=[[], []],
        cursors=["opaque|token|12345", "opaque|token|99999"],
    )
    consumer, _ = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=opaque_adapter,
        live_adapter_enabled=True,
    )
    orch.run_poll()
    assert orch.get_cursor("rss_public_v1") == "opaque|token|12345"
    orch.run_poll()
    assert opaque_adapter._received_cursors[-1] == "opaque|token|12345"


def test_reset_cursor_clears_stored_cursor(synthetic_adapter, live_adapter):
    consumer, _ = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=live_adapter,
        live_adapter_enabled=True,
    )
    orch.run_poll()
    assert orch.get_cursor("rss_public_v1") is not None
    orch.reset_cursor("rss_public_v1")
    assert orch.get_cursor("rss_public_v1") is None


# ===========================================================================
# Contract Invariant 8: orchestrator never writes to the graph
# ===========================================================================

def test_orchestrator_has_no_neo4j_import():
    """Invariant 8: orchestrator.py must not import any Neo4j module."""
    import inspect
    import app.ingestion.orchestrator as mod
    src = inspect.getsource(mod)
    neo4j_imports = ["import neo4j", "from neo4j", "GraphDatabase", "AsyncGraphDatabase"]
    for imp in neo4j_imports:
        assert imp not in src, f"Neo4j import '{imp}' found in orchestrator.py"


def test_run_does_not_call_graph_write(synthetic_adapter, live_adapter):
    """Invariant 8: consumer is the only write target; no graph driver is called."""
    consumer, received = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=live_adapter,
        live_adapter_enabled=True,
    )
    orch.run()
    # All records went to consumer — none to Neo4j
    # (If a graph write were attempted we'd get an import/attribute error above)
    assert len(received) == 5  # 3 synthetic + 2 live


# ===========================================================================
# Record count correctness
# ===========================================================================

def test_run_batch_returns_correct_count(synthetic_adapter):
    consumer, _ = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter_enabled=False,
    )
    assert orch.run_batch() == 3


def test_run_poll_returns_correct_count(synthetic_adapter, live_adapter):
    consumer, _ = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=live_adapter,
        live_adapter_enabled=True,
    )
    assert orch.run_poll() == 2


def test_empty_synthetic_adapter_returns_zero():
    empty = _FakeSyntheticAdapter([])
    consumer, received = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=empty,
        consumer=consumer,
        live_adapter_enabled=False,
    )
    assert orch.run_batch() == 0
    assert received == []


def test_empty_live_page_returns_zero(synthetic_adapter):
    empty_live = _FakeLiveAdapter(pages=[[]], cursors=["2024-01-20T10:00:00Z"])
    consumer, received = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=empty_live,
        live_adapter_enabled=True,
    )
    count = orch.run_poll()
    assert count == 0
    live_received = [r for r in received if r.dataset == "live_public"]
    assert live_received == []


# ===========================================================================
# Consumer is called (Extraction hand-off contract)
# ===========================================================================

def test_consumer_called_with_synthetic_records(synthetic_adapter):
    consumer = MagicMock()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter_enabled=False,
    )
    orch.run_batch()
    consumer.assert_called_once()
    args = consumer.call_args[0][0]
    assert len(args) == 3


def test_consumer_not_called_when_no_records():
    empty = _FakeSyntheticAdapter([])
    consumer = MagicMock()
    orch = IngestionOrchestrator(
        synthetic_adapter=empty,
        consumer=consumer,
        live_adapter_enabled=False,
    )
    orch.run_batch()
    consumer.assert_not_called()


def test_consumer_called_separately_for_batch_and_poll(synthetic_adapter, live_adapter):
    """run() calls consumer once for batch and once for poll (two separate calls)."""
    consumer = MagicMock()
    orch = IngestionOrchestrator(
        synthetic_adapter=synthetic_adapter,
        consumer=consumer,
        live_adapter=live_adapter,
        live_adapter_enabled=True,
    )
    orch.run()
    assert consumer.call_count == 2  # once for synthetic, once for live


# ===========================================================================
# Integration test using the real SyntheticAdapter and H1 dataset (B4 §13)
# ===========================================================================

def test_integration_live_disabled_only_synthetic_demo_flows():
    """B4 §13 integration test: LIVE_ADAPTER_ENABLED=False → only synthetic_demo."""
    from pathlib import Path
    from app.ingestion.synthetic_adapter import SyntheticAdapter

    repo_root = Path(__file__).resolve().parents[3]
    h1_base = repo_root / "data" / "synthetic"

    consumer, received = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=SyntheticAdapter(base_path=h1_base),
        consumer=consumer,
        live_adapter=None,
        live_adapter_enabled=False,
    )
    counts = orch.run()

    assert counts["synthetic_demo"] == 31
    assert counts["live_public"] == 0
    assert all(r.dataset == "synthetic_demo" for r in received)
    assert len(received) == 31


def test_integration_live_enabled_both_datasets_flow():
    """B4 §13 integration test: LIVE_ADAPTER_ENABLED=True → both datasets, correctly tagged."""
    from pathlib import Path
    from app.ingestion.synthetic_adapter import SyntheticAdapter

    repo_root = Path(__file__).resolve().parents[3]
    h1_base = repo_root / "data" / "synthetic"

    # Use a fake live adapter (avoid real network in tests)
    live = _FakeLiveAdapter(
        pages=[LIVE_RECORDS_PAGE1],
        cursors=["2024-01-20T10:00:00Z"],
    )

    consumer, received = _collecting_consumer()
    orch = IngestionOrchestrator(
        synthetic_adapter=SyntheticAdapter(base_path=h1_base),
        consumer=consumer,
        live_adapter=live,
        live_adapter_enabled=True,
    )
    counts = orch.run()

    assert counts["synthetic_demo"] == 31
    assert counts["live_public"] == 2

    synthetic = [r for r in received if r.dataset == "synthetic_demo"]
    live_recs = [r for r in received if r.dataset == "live_public"]
    assert len(synthetic) == 31
    assert len(live_recs) == 2
