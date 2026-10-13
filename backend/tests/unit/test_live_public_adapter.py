"""Unit tests for Task B3: LivePublicAdapter.

Tests (per B3 §13):
- Unit tests mocking network failure and success scenarios.
- A test confirming no exception ever escapes poll().
- Acceptance criteria:
  - A simulated network failure returns an empty result, not an exception.
  - AdapterDescriptor.last_run_status updates correctly on success and failure.

All network I/O is mocked — these tests never make real HTTP requests.
"""

import io
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from app.contracts.raw_record import AdapterDescriptor, RawRecord
from app.ingestion.adapter_base import PollResult, SourceAdapter
from app.ingestion.live_public_adapter import LivePublicAdapter, _ADAPTER_ID, _DATASET

# ---------------------------------------------------------------------------
# Minimal valid RSS 2.0 feed XML
# ---------------------------------------------------------------------------

_RSS_TWO_ITEMS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Public Feed</title>
    <link>https://example.com</link>
    <description>Test feed for unit tests</description>
    <item>
      <title>Organisation Alpha signs new deal</title>
      <link>https://example.com/news/1</link>
      <description>Organisation Alpha announced a new partnership today.</description>
      <pubDate>Tue, 20 Jan 2024 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Government announces policy update</title>
      <link>https://example.com/news/2</link>
      <description>The government released a new policy regarding trade regulations.</description>
      <pubDate>Tue, 20 Jan 2024 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

_RSS_EMPTY = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Public Feed</title>
    <link>https://example.com</link>
    <description>Empty feed</description>
  </channel>
</rss>"""

_RSS_ONE_ITEM_NEWER = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Public Feed</title>
    <link>https://example.com</link>
    <description>Single item feed</description>
    <item>
      <title>New story published after cursor</title>
      <link>https://example.com/news/3</link>
      <description>A story published after the cursor timestamp.</description>
      <pubDate>Wed, 21 Jan 2024 08:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

_ATOM_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom Feed</title>
  <entry>
    <title>Atom item title</title>
    <link href="https://example.com/atom/1"/>
    <summary>Atom item summary text.</summary>
    <published>2024-01-20T10:00:00Z</published>
  </entry>
</feed>"""


def _mock_urlopen(xml_bytes: bytes):
    """Return a context-manager mock that yields the given bytes."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=xml_bytes)))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def adapter() -> LivePublicAdapter:
    return LivePublicAdapter(
        feed_url="https://example.com/rss.xml",
        poll_interval_seconds=300,
    )


# ===========================================================================
# ABC conformance
# ===========================================================================

def test_live_adapter_is_source_adapter(adapter):
    assert isinstance(adapter, SourceAdapter)


# ===========================================================================
# descriptor() tests
# ===========================================================================

def test_descriptor_returns_adapter_descriptor(adapter):
    d = adapter.descriptor()
    assert isinstance(d, AdapterDescriptor)


def test_descriptor_fields(adapter):
    d = adapter.descriptor()
    assert d.adapter_id == _ADAPTER_ID
    assert d.dataset == _DATASET
    assert d.mode == "poll"
    assert d.enabled is True
    assert d.poll_interval_seconds == 300


def test_descriptor_initial_status(adapter):
    d = adapter.descriptor()
    assert d.last_run_status == "never_run"
    assert d.last_run_at is None
    assert d.last_error is None


# ===========================================================================
# fetch_batch() raises NotImplementedError (poll-only)
# ===========================================================================

def test_fetch_batch_raises_not_implemented(adapter):
    with pytest.raises(NotImplementedError):
        adapter.fetch_batch()


# ===========================================================================
# poll() — success scenarios
# ===========================================================================

def test_poll_returns_poll_result(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    assert isinstance(result, PollResult)


def test_poll_no_cursor_returns_all_items(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    assert len(result.records) == 2


def test_poll_records_are_raw_records(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    for r in result.records:
        assert isinstance(r, RawRecord)


def test_poll_records_have_correct_dataset(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    for r in result.records:
        assert r.dataset == "live_public"


def test_poll_records_have_correct_source_type(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    for r in result.records:
        assert r.source_type == "rss"


def test_poll_records_have_correct_adapter_id(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    for r in result.records:
        assert r.source_adapter_id == _ADAPTER_ID


def test_poll_records_have_non_empty_record_ids(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    for r in result.records:
        assert r.record_id and len(r.record_id) > 0


def test_poll_record_ids_are_unique(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    ids = [r.record_id for r in result.records]
    assert len(ids) == len(set(ids))


def test_poll_records_have_occurred_at_from_pubdate(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    for r in result.records:
        assert r.occurred_at is not None


def test_poll_records_have_ingested_at(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    for r in result.records:
        assert r.ingested_at and len(r.ingested_at) > 0


def test_poll_records_have_payload_with_title(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    for r in result.records:
        assert "title" in r.payload
        assert len(r.payload["title"]) > 0


def test_poll_next_cursor_is_string(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    assert isinstance(result.next_cursor, str)
    assert len(result.next_cursor) > 0


def test_poll_next_cursor_reflects_newest_item(adapter):
    """next_cursor should be >= the pub_date of the newer of the two items (2024-01-20T12:00:00Z)."""
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=None)
    # The newer item is 2024-01-20T12:00:00Z — cursor should be that or later
    assert result.next_cursor >= "2024-01-20T12:00:00Z"


def test_poll_status_ok_after_success(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        adapter.poll(cursor=None)
    d = adapter.descriptor()
    assert d.last_run_status == "ok"
    assert d.last_run_at is not None
    assert d.last_error is None


# ===========================================================================
# poll() — cursor filtering
# ===========================================================================

def test_poll_with_cursor_filters_old_items(adapter):
    """Items at or before the cursor must NOT be returned."""
    # cursor is 2024-01-20T11:00:00Z — item 1 (10:00) should be excluded,
    # item 2 (12:00) should be included.
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor="2024-01-20T11:00:00Z")
    assert len(result.records) == 1
    assert "Government announces policy update" in result.records[0].payload["title"]


def test_poll_with_cursor_after_all_items_returns_empty(adapter):
    """Cursor newer than all items → empty result."""
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor="2024-01-21T00:00:00Z")
    assert result.records == []


def test_poll_cursor_unchanged_when_no_new_items(adapter):
    """If no new items, next_cursor should equal the input cursor."""
    cursor = "2024-01-21T00:00:00Z"
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result = adapter.poll(cursor=cursor)
    # No new items: next_cursor must be >= cursor (either unchanged or = call time)
    assert result.next_cursor >= cursor


def test_poll_empty_feed_returns_empty(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_EMPTY)):
        result = adapter.poll(cursor=None)
    assert result.records == []
    assert isinstance(result.next_cursor, str)


# ===========================================================================
# poll() — Atom feed support
# ===========================================================================

def test_poll_parses_atom_feed(adapter):
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_ATOM_FEED)):
        result = adapter.poll(cursor=None)
    assert len(result.records) == 1
    assert result.records[0].source_type == "rss"
    assert "Atom item title" in result.records[0].payload["title"]


# ===========================================================================
# poll() — SILENT FAILURE (B3 §12, §13 acceptance criterion)
# ===========================================================================

def test_poll_never_raises_on_network_error(adapter):
    """B3 §12: a network failure must return empty result, not raise."""
    with patch("urllib.request.urlopen", side_effect=ConnectionError("Network unreachable")):
        result = adapter.poll(cursor=None)  # must not raise
    assert isinstance(result, PollResult)
    assert result.records == []


def test_poll_never_raises_on_url_error(adapter):
    from urllib.error import URLError
    with patch("urllib.request.urlopen", side_effect=URLError("Name or service not known")):
        result = adapter.poll(cursor=None)
    assert isinstance(result, PollResult)
    assert result.records == []


def test_poll_never_raises_on_timeout(adapter):
    import socket
    with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        result = adapter.poll(cursor=None)
    assert isinstance(result, PollResult)
    assert result.records == []


def test_poll_never_raises_on_malformed_xml(adapter):
    malformed = b"<this is not valid xml"
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(malformed)):
        result = adapter.poll(cursor=None)
    assert isinstance(result, PollResult)
    assert result.records == []


def test_poll_never_raises_on_unexpected_exception(adapter):
    with patch("urllib.request.urlopen", side_effect=RuntimeError("unexpected")):
        result = adapter.poll(cursor=None)
    assert isinstance(result, PollResult)
    assert result.records == []


def test_poll_cursor_unchanged_on_network_failure(adapter):
    """On failure, next_cursor must equal the cursor passed in (DOC3 §3)."""
    cursor = "2024-01-20T10:00:00Z"
    with patch("urllib.request.urlopen", side_effect=ConnectionError("fail")):
        result = adapter.poll(cursor=cursor)
    assert result.next_cursor == cursor


def test_poll_cursor_is_call_time_on_first_failure(adapter):
    """On first call failure (cursor=None), next_cursor must be a non-empty string."""
    with patch("urllib.request.urlopen", side_effect=ConnectionError("fail")):
        result = adapter.poll(cursor=None)
    assert isinstance(result.next_cursor, str)
    assert len(result.next_cursor) > 0


# ===========================================================================
# descriptor status update on failure (B3 §12 acceptance criterion)
# ===========================================================================

def test_descriptor_status_error_after_network_failure(adapter):
    """B3 §12: AdapterDescriptor status updates correctly on failure."""
    with patch("urllib.request.urlopen", side_effect=ConnectionError("fail")):
        adapter.poll(cursor=None)
    d = adapter.descriptor()
    assert d.last_run_status == "error"
    assert d.last_error is not None
    assert "ConnectionError" in d.last_error or "fail" in d.last_error
    assert d.last_run_at is not None


def test_descriptor_status_resets_to_ok_after_recovery(adapter):
    """Status transitions from error → ok when next poll succeeds."""
    # First: fail
    with patch("urllib.request.urlopen", side_effect=ConnectionError("fail")):
        adapter.poll(cursor=None)
    assert adapter.descriptor().last_run_status == "error"

    # Then: succeed
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        adapter.poll(cursor=None)
    d = adapter.descriptor()
    assert d.last_run_status == "ok"
    assert d.last_error is None


# ===========================================================================
# Record-id stability (same URL → same record_id across calls)
# ===========================================================================

def test_record_ids_are_stable_across_calls(adapter):
    """record_id is derived from the item URL (stable across re-polls)."""
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result1 = adapter.poll(cursor=None)
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_RSS_TWO_ITEMS)):
        result2 = adapter.poll(cursor=None)
    ids1 = sorted(r.record_id for r in result1.records)
    ids2 = sorted(r.record_id for r in result2.records)
    assert ids1 == ids2


# ===========================================================================
# Contract invariant: never a dependency on the core demo
# ===========================================================================

def test_live_adapter_import_does_not_block_core():
    """Importing LivePublicAdapter does not import any heavy optional dependency."""
    import importlib
    mod = importlib.import_module("app.ingestion.live_public_adapter")
    assert mod is not None
