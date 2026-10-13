"""Unit tests for Task B2: SyntheticAdapter.

Tests (per B2 §13):
- Unit tests reading actual H1 fixture files and asserting correct RawRecord
  shape and field population.
- An idempotency test: two consecutive fetch_batch() calls yield identical
  record_id sets.
- Coverage: all seven source types present in H1 are represented in output.
- Acceptance criteria: every bundled source type appears; idempotency holds.

These tests use the REAL H1 dataset at data/synthetic/ (not mocks), since
B2's definition of done is "the full synthetic dataset ingests without error".
A separate set of isolation tests uses a temporary fixture directory.
"""

import json
import tempfile
from pathlib import Path
from typing import List

import pytest

from app.contracts.raw_record import AdapterDescriptor, RawRecord
from app.ingestion.adapter_base import SourceAdapter
from app.ingestion.synthetic_adapter import (
    SyntheticAdapter,
    _ADAPTER_ID,
    _DATASET,
    _SOURCE_TYPE_MAP,
)

# ---------------------------------------------------------------------------
# Resolve H1 dataset path (relative to this file → repo_root/data/synthetic)
# tests/unit/test_synthetic_adapter.py → backend/tests/unit/
# repo_root is 3 levels up from backend/
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_H1_BASE = _REPO_ROOT / "data" / "synthetic"


# ===========================================================================
# Fixtures — real H1 dataset
# ===========================================================================

@pytest.fixture(scope="module")
def adapter() -> SyntheticAdapter:
    """SyntheticAdapter pointed at the real H1 dataset."""
    return SyntheticAdapter(base_path=_H1_BASE)


@pytest.fixture(scope="module")
def records(adapter: SyntheticAdapter) -> List[RawRecord]:
    """Full batch of records from the real H1 dataset."""
    return adapter.fetch_batch()


# ===========================================================================
# ABC conformance
# ===========================================================================

def test_synthetic_adapter_is_source_adapter(adapter):
    """SyntheticAdapter must satisfy the B1 SourceAdapter ABC."""
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
    assert d.mode == "batch"
    assert d.enabled is True
    assert d.poll_interval_seconds is None


def test_descriptor_status_updates_after_fetch(adapter, records):
    """After fetch_batch(), descriptor.last_run_status must be 'ok'."""
    d = adapter.descriptor()
    assert d.last_run_status == "ok"
    assert d.last_run_at is not None
    assert d.last_error is None


# ===========================================================================
# fetch_batch() — RawRecord shape
# ===========================================================================

def test_fetch_batch_returns_list(records):
    assert isinstance(records, list)


def test_fetch_batch_returns_nonempty(records):
    assert len(records) > 0, "fetch_batch() returned no records from H1 dataset"


def test_all_records_are_raw_record_instances(records):
    for r in records:
        assert isinstance(r, RawRecord), f"Non-RawRecord found: {type(r)}"


def test_all_records_have_correct_dataset(records):
    for r in records:
        assert r.dataset == _DATASET, f"Wrong dataset on {r.record_id}: {r.dataset}"


def test_all_records_have_correct_adapter_id(records):
    for r in records:
        assert r.source_adapter_id == _ADAPTER_ID, (
            f"Wrong adapter_id on {r.record_id}: {r.source_adapter_id}"
        )


def test_all_records_have_non_empty_record_id(records):
    for r in records:
        assert r.record_id and len(r.record_id) > 0, "Empty record_id found"


def test_all_record_ids_are_unique(records):
    ids = [r.record_id for r in records]
    assert len(ids) == len(set(ids)), (
        f"Duplicate record_ids: {[x for x in ids if ids.count(x) > 1]}"
    )


def test_all_records_have_ingested_at(records):
    """ingested_at must be set on every record (DOC3 §1.1)."""
    for r in records:
        assert r.ingested_at and len(r.ingested_at) > 0, (
            f"Missing ingested_at on {r.record_id}"
        )


def test_all_records_have_occurred_at(records):
    """All H1 records explicitly set occurred_at (they are never null in H1)."""
    for r in records:
        assert r.occurred_at is not None, (
            f"occurred_at is null on {r.record_id} — H1 dataset should always set this"
        )


def test_all_records_have_payload(records):
    for r in records:
        assert r.payload is not None, f"None payload on {r.record_id}"


def test_all_records_have_payload_text(records):
    """H1 files all include payload_text for NLP/LLM convenience."""
    for r in records:
        assert r.payload_text is not None and len(r.payload_text) > 0, (
            f"Missing payload_text on {r.record_id}"
        )


def test_all_records_have_valid_source_type(records):
    """source_type must be one of the mapped DOC3 §2.2 values."""
    valid_types = set(_SOURCE_TYPE_MAP.values())
    for r in records:
        assert r.source_type in valid_types, (
            f"Unexpected source_type '{r.source_type}' on {r.record_id}"
        )


# ===========================================================================
# Coverage: every H1 source type is represented in output
# ===========================================================================

def test_all_source_types_represented(records):
    """B2 §12: every bundled source type must appear in fetch_batch() output."""
    found = {r.source_type for r in records}
    expected = set(_SOURCE_TYPE_MAP.values())
    missing = expected - found
    assert not missing, (
        f"Missing source types in fetch_batch() output: {missing}. "
        f"Found: {found}"
    )


def test_fir_records_present(records):
    fir_records = [r for r in records if r.source_type == "FIR"]
    assert len(fir_records) >= 3, f"Expected >=3 FIR records, got {len(fir_records)}"


def test_police_report_records_present(records):
    pr_records = [r for r in records if r.source_type == "police_report"]
    assert len(pr_records) >= 2, f"Expected >=2 police_report records, got {len(pr_records)}"


def test_cdr_records_present(records):
    cdr_records = [r for r in records if r.source_type == "CDR"]
    assert len(cdr_records) >= 10, f"Expected >=10 CDR records, got {len(cdr_records)}"


def test_transaction_records_present(records):
    txn_records = [r for r in records if r.source_type == "transaction"]
    assert len(txn_records) >= 6, f"Expected >=6 transaction records, got {len(txn_records)}"


def test_vehicle_records_present(records):
    veh_records = [r for r in records if r.source_type == "vehicle_registry"]
    assert len(veh_records) >= 3, f"Expected >=3 vehicle_registry records, got {len(veh_records)}"


def test_surveillance_records_present(records):
    surv_records = [r for r in records if r.source_type == "surveillance"]
    assert len(surv_records) >= 4, f"Expected >=4 surveillance records, got {len(surv_records)}"


def test_social_media_records_present(records):
    sm_records = [r for r in records if r.source_type == "social_media"]
    assert len(sm_records) >= 3, f"Expected >=3 social_media records, got {len(sm_records)}"


def test_total_record_count_matches_h1(records):
    """H1 created exactly 31 records — verify full ingestion."""
    assert len(records) == 31, (
        f"Expected 31 records (per H1 README), got {len(records)}"
    )


# ===========================================================================
# Idempotency test (B2 §12, §13)
# ===========================================================================

def test_fetch_batch_is_idempotent():
    """Two consecutive calls yield identical record_id sets (B2 §12 acceptance criterion)."""
    adapter = SyntheticAdapter(base_path=_H1_BASE)
    batch1 = adapter.fetch_batch()
    batch2 = adapter.fetch_batch()

    ids1 = sorted(r.record_id for r in batch1)
    ids2 = sorted(r.record_id for r in batch2)

    assert ids1 == ids2, "fetch_batch() is not idempotent — record_id sets differ"
    assert len(ids1) == len(ids2), "Batch sizes differ between calls"


def test_idempotent_payloads():
    """Payloads are structurally identical across two calls (same files, same data)."""
    adapter = SyntheticAdapter(base_path=_H1_BASE)
    batch1 = {r.record_id: r.payload for r in adapter.fetch_batch()}
    batch2 = {r.record_id: r.payload for r in adapter.fetch_batch()}

    assert batch1.keys() == batch2.keys()
    for rid in batch1:
        assert batch1[rid] == batch2[rid], f"Payload mismatch for {rid} across two calls"


# ===========================================================================
# Spot-check specific records from H1 for correct field mapping
# ===========================================================================

def test_fir_001_payload_correct(records):
    r = next((r for r in records if r.record_id == "fir_001"), None)
    assert r is not None, "fir_001 not found in batch output"
    assert r.source_type == "FIR"
    assert r.dataset == "synthetic_demo"
    assert "fir_number" in r.payload
    assert r.payload["fir_number"] == "FIR/2024/001"
    assert r.occurred_at == "2024-01-20T10:00:00Z"


def test_cdr_001_payload_correct(records):
    r = next((r for r in records if r.record_id == "cdr_001"), None)
    assert r is not None, "cdr_001 not found in batch output"
    assert r.source_type == "CDR"
    assert r.payload["caller"] == "9876543210"
    assert r.payload["callee"] == "9988776655"
    assert r.occurred_at == "2024-01-05T09:12:00Z"


def test_txn_006_payload_correct(records):
    r = next((r for r in records if r.record_id == "txn_006"), None)
    assert r is not None, "txn_006 not found in batch output"
    assert r.source_type == "transaction"
    assert r.payload["from_account"] == "HDFC-PRIV-1234"
    assert r.payload["to_account_holder"] == "Global Trading FZE"


def test_veh_002_payload_correct(records):
    r = next((r for r in records if r.record_id == "veh_002"), None)
    assert r is not None, "veh_002 not found"
    assert r.source_type == "vehicle_registry"
    assert r.payload["registration_number"] == "DL-05-CD-5678"
    assert r.payload["registered_owner"] == "R. Patel"  # intentional alias


def test_surv_001_payload_correct(records):
    r = next((r for r in records if r.record_id == "surv_001"), None)
    assert r is not None, "surv_001 not found"
    assert r.source_type == "surveillance"
    assert "Hotel Sunrise" in r.payload["location"]


# ===========================================================================
# Offline / no-network guarantee (Contract Invariant 7)
# ===========================================================================

def test_no_network_import_in_adapter():
    """SyntheticAdapter must not import network-dependent libraries."""
    import inspect
    import app.ingestion.synthetic_adapter as mod
    src = inspect.getsource(mod)
    # These imports would indicate a network dependency
    network_imports = ["import requests", "import httpx", "import urllib.request", "import aiohttp"]
    for imp in network_imports:
        assert imp not in src, f"Network import '{imp}' found in synthetic_adapter.py"


# ===========================================================================
# poll() raises NotImplementedError (batch-only)
# ===========================================================================

def test_poll_raises_not_implemented(adapter):
    with pytest.raises(NotImplementedError):
        adapter.poll(cursor=None)


def test_poll_with_cursor_raises_not_implemented(adapter):
    with pytest.raises(NotImplementedError):
        adapter.poll(cursor="2024-01-01T00:00:00Z")


# ===========================================================================
# Error handling — missing base_path
# ===========================================================================

def test_missing_base_path_raises_file_not_found():
    bad_adapter = SyntheticAdapter(base_path=Path("/nonexistent/path/to/data"))
    with pytest.raises(FileNotFoundError):
        bad_adapter.fetch_batch()


def test_missing_base_path_sets_error_status():
    bad_adapter = SyntheticAdapter(base_path=Path("/nonexistent/path/to/data"))
    try:
        bad_adapter.fetch_batch()
    except FileNotFoundError:
        pass
    d = bad_adapter.descriptor()
    assert d.last_run_status == "error"
    assert d.last_error is not None


# ===========================================================================
# Isolation tests using temp directory (verify file-format handling)
# ===========================================================================

@pytest.fixture
def temp_dataset(tmp_path: Path) -> Path:
    """Create a minimal temporary dataset matching H1's file formats."""
    # Single-record file (like fir/)
    fir_dir = tmp_path / "fir"
    fir_dir.mkdir()
    (fir_dir / "fir_test_001.json").write_text(json.dumps({
        "record_id": "fir_test_001",
        "occurred_at": "2024-06-01T10:00:00Z",
        "payload": {"fir_number": "FIR/TEST/001", "description": "Test FIR"},
        "payload_text": "Test FIR 001",
    }), encoding="utf-8")

    # Array-format file (like cdr/)
    cdr_dir = tmp_path / "cdr"
    cdr_dir.mkdir()
    (cdr_dir / "records.json").write_text(json.dumps([
        {
            "record_id": "cdr_test_001",
            "occurred_at": "2024-06-01T08:00:00Z",
            "payload": {"caller": "1111111111", "callee": "2222222222", "duration_seconds": 100},
            "payload_text": "CDR caller 1111111111 callee 2222222222 duration 100s",
        },
        {
            "record_id": "cdr_test_002",
            "occurred_at": "2024-06-02T09:00:00Z",
            "payload": {"caller": "2222222222", "callee": "1111111111", "duration_seconds": 200},
            "payload_text": "CDR caller 2222222222 callee 1111111111 duration 200s",
        },
    ]), encoding="utf-8")

    return tmp_path


def test_single_record_file_parsed(temp_dataset):
    adapter = SyntheticAdapter(base_path=temp_dataset)
    records = adapter.fetch_batch()
    fir_records = [r for r in records if r.record_id == "fir_test_001"]
    assert len(fir_records) == 1
    assert fir_records[0].source_type == "FIR"


def test_array_record_file_parsed(temp_dataset):
    adapter = SyntheticAdapter(base_path=temp_dataset)
    records = adapter.fetch_batch()
    cdr_records = [r for r in records if r.source_type == "CDR"]
    assert len(cdr_records) == 2
    assert {r.record_id for r in cdr_records} == {"cdr_test_001", "cdr_test_002"}


def test_unknown_folder_is_skipped(temp_dataset):
    """Directories not in _SOURCE_TYPE_MAP must be silently ignored."""
    unknown_dir = temp_dataset / "unknown_source"
    unknown_dir.mkdir()
    (unknown_dir / "records.json").write_text(
        json.dumps([{"record_id": "unk_001", "payload": {}, "payload_text": "x", "occurred_at": "2024-01-01T00:00:00Z"}]),
        encoding="utf-8"
    )
    adapter = SyntheticAdapter(base_path=temp_dataset)
    records = adapter.fetch_batch()
    ids = {r.record_id for r in records}
    assert "unk_001" not in ids, "Record from unknown folder should not be ingested"
