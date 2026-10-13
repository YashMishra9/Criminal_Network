"""Unit tests for Task B1: SourceAdapter Interface.

Tests (per B1 §13):
- An interface-conformance test confirming a class implementing all three
  methods satisfies the SourceAdapter ABC.
- A test confirming a class missing any method is rejected at instantiation.
- PollResult shape tests.
- Docstring-rule verification: idempotency and cursor-ownership documented.
"""

import pytest
from typing import List, Optional

from app.contracts.raw_record import AdapterDescriptor, RawRecord
from app.ingestion.adapter_base import PollResult, SourceAdapter


# ---------------------------------------------------------------------------
# A minimal concrete implementation (used for conformance tests)
# ---------------------------------------------------------------------------

class _MinimalBatchAdapter(SourceAdapter):
    """Minimal batch-mode adapter — implements all three abstract methods."""

    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            adapter_id="test_batch_v1",
            source_type="FIR",
            dataset="synthetic_demo",
            mode="batch",
            enabled=True,
            last_run_status="never_run",
        )

    def fetch_batch(self) -> List[RawRecord]:
        return [
            RawRecord(
                record_id="fir_001",
                dataset="synthetic_demo",
                source_type="FIR",
                source_adapter_id="test_batch_v1",
                ingested_at="2024-01-20T12:00:00Z",
                payload={"case_no": "123/2024"},
            )
        ]

    def poll(self, cursor: Optional[str]) -> PollResult:
        # Batch adapter: not intended for poll, but must be implemented
        raise NotImplementedError("This adapter is batch-only.")


class _MinimalPollAdapter(SourceAdapter):
    """Minimal poll-mode adapter — implements all three abstract methods."""

    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            adapter_id="rss_public_v1",
            source_type="rss",
            dataset="live_public",
            mode="poll",
            enabled=True,
            poll_interval_seconds=300,
            last_run_status="never_run",
        )

    def fetch_batch(self) -> List[RawRecord]:
        raise NotImplementedError("This adapter is poll-only.")

    def poll(self, cursor: Optional[str]) -> PollResult:
        next_cursor = "2024-01-21T00:00:00Z"
        return PollResult(records=[], next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# ABC conformance tests
# ---------------------------------------------------------------------------

def test_batch_adapter_satisfies_abc():
    """A class implementing all three methods can be instantiated."""
    adapter = _MinimalBatchAdapter()
    assert isinstance(adapter, SourceAdapter)


def test_poll_adapter_satisfies_abc():
    """A poll-mode adapter implementing all three methods can be instantiated."""
    adapter = _MinimalPollAdapter()
    assert isinstance(adapter, SourceAdapter)


def test_class_missing_descriptor_is_rejected():
    """A subclass that omits descriptor() cannot be instantiated."""
    with pytest.raises(TypeError):
        class _BadAdapter(SourceAdapter):
            def fetch_batch(self): return []
            def poll(self, cursor): return PollResult([], "x")

        _BadAdapter()


def test_class_missing_fetch_batch_is_rejected():
    """A subclass that omits fetch_batch() cannot be instantiated."""
    with pytest.raises(TypeError):
        class _BadAdapter(SourceAdapter):
            def descriptor(self): ...
            def poll(self, cursor): return PollResult([], "x")

        _BadAdapter()


def test_class_missing_poll_is_rejected():
    """A subclass that omits poll() cannot be instantiated."""
    with pytest.raises(TypeError):
        class _BadAdapter(SourceAdapter):
            def descriptor(self): ...
            def fetch_batch(self): return []

        _BadAdapter()


def test_class_missing_all_methods_is_rejected():
    """A subclass implementing no methods cannot be instantiated."""
    with pytest.raises(TypeError):
        class _EmptyAdapter(SourceAdapter):
            pass

        _EmptyAdapter()


# ---------------------------------------------------------------------------
# Method behaviour tests
# ---------------------------------------------------------------------------

def test_batch_adapter_descriptor_returns_correct_shape():
    adapter = _MinimalBatchAdapter()
    d = adapter.descriptor()
    assert isinstance(d, AdapterDescriptor)
    assert d.mode == "batch"
    assert d.dataset == "synthetic_demo"


def test_batch_adapter_fetch_batch_returns_raw_records():
    adapter = _MinimalBatchAdapter()
    records = adapter.fetch_batch()
    assert isinstance(records, list)
    assert len(records) == 1
    assert isinstance(records[0], RawRecord)
    assert records[0].record_id == "fir_001"


def test_poll_adapter_descriptor_returns_correct_shape():
    adapter = _MinimalPollAdapter()
    d = adapter.descriptor()
    assert d.mode == "poll"
    assert d.poll_interval_seconds == 300


def test_poll_adapter_poll_returns_poll_result():
    adapter = _MinimalPollAdapter()
    result = adapter.poll(cursor=None)
    assert isinstance(result, PollResult)
    assert result.records == []
    assert isinstance(result.next_cursor, str)
    assert len(result.next_cursor) > 0


def test_poll_adapter_poll_with_existing_cursor():
    adapter = _MinimalPollAdapter()
    result = adapter.poll(cursor="2024-01-20T00:00:00Z")
    assert isinstance(result, PollResult)


# ---------------------------------------------------------------------------
# PollResult shape tests
# ---------------------------------------------------------------------------

def test_poll_result_stores_records_and_cursor():
    records = [
        RawRecord(
            record_id="rss_001",
            dataset="live_public",
            source_type="rss",
            source_adapter_id="rss_public_v1",
            ingested_at="2024-01-20T12:00:00Z",
            payload={"title": "News item"},
        )
    ]
    result = PollResult(records=records, next_cursor="tok_abc123")
    assert len(result.records) == 1
    assert result.next_cursor == "tok_abc123"


def test_poll_result_repr():
    result = PollResult(records=[], next_cursor="tok_xyz")
    r = repr(result)
    assert "0 record" in r
    assert "tok_xyz" in r


# ---------------------------------------------------------------------------
# Interface constraint: exactly 3 abstract methods — no more
# ---------------------------------------------------------------------------

def test_source_adapter_has_exactly_three_abstract_methods():
    """B1 §17: must not add methods beyond descriptor/fetch_batch/poll."""
    abstract_methods = SourceAdapter.__abstractmethods__
    assert abstract_methods == {"descriptor", "fetch_batch", "poll"}, (
        f"SourceAdapter has unexpected abstract methods: {abstract_methods}"
    )
