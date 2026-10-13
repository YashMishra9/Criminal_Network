"""Unit tests for Task B6: LLM-Assisted Extraction.

Tests (per B6 §13):
  - Unit test: LLMClient returns {status: 'unavailable'} → pipeline still
    completes using only B5 results.
  - Unit test: LLM returns valid JSON → new EntityMention objects created
    with extraction_method='llm' and correct provenance.
  - Unit test: LLM returns malformed output → dropped silently, no crash.
  - Unit test: build_extractor(with_llm=True) correctly wires LLMExtractor.
  - Acceptance criteria (B6 §12): with LLM forced unavailable, extraction
    still completes for all records using only B5's results.
  - Contract Invariant 4: LLM availability never blocks core extraction.
"""

import json
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from app.contracts.mention import EntityMention, RelationshipMention
from app.contracts.raw_record import RawRecord
from app.extraction.extractor import Extractor, ExtractionResult, build_extractor
from app.extraction.llm_extractor import LLMExtractor
from app.llm.client import LLMClient, LLMResultOk, LLMResultUnavailable

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    record_id: str = "test_001",
    source_type: str = "FIR",
    payload: Optional[Dict[str, Any]] = None,
    payload_text: str = "Rahul Sharma and Priya Mehta were seen at Hotel Sunrise.",
    dataset: str = "synthetic_demo",
) -> RawRecord:
    return RawRecord(
        record_id=record_id,
        dataset=dataset,  # type: ignore[arg-type]
        source_type=source_type,
        source_adapter_id="test_v1",
        occurred_at="2024-01-20T10:00:00Z",
        ingested_at="2024-01-20T12:00:00Z",
        payload=payload or {"fir_number": "FIR/2024/001"},
        payload_text=payload_text,
    )


def _make_entity(
    mention_id: str,
    entity_type: str,
    raw_text: str,
    record_id: str = "test_001",
    dataset: str = "synthetic_demo",
    confidence: Optional[float] = 0.5,
) -> EntityMention:
    return EntityMention(
        mention_id=mention_id,
        record_id=record_id,
        dataset=dataset,
        entity_type=entity_type,  # type: ignore[arg-type]
        raw_text=raw_text,
        normalized_value=None,
        attributes={},
        extraction_method="regex",
        confidence=confidence,
    )


def _llm_client_ok(response_text: str) -> LLMClient:
    """Return an LLMClient mock that always returns LLMResultOk(text=response_text)."""
    mock_provider = MagicMock()
    mock_provider.call.return_value = response_text
    return LLMClient(provider=mock_provider)


def _llm_client_unavailable(reason: str = "provider_error") -> LLMClient:
    """Return an LLMClient mock that always returns LLMResultUnavailable."""
    mock_provider = MagicMock()
    mock_provider.call.side_effect = Exception("Simulated LLM failure")
    return LLMClient(provider=mock_provider)


# ===========================================================================
# B6 §12 Acceptance Criteria: LLM unavailable → B5 results unchanged
# ===========================================================================

def test_llm_unavailable_extraction_still_completes():
    """B6 §12: LLM unavailable → pipeline completes with B5-only results."""
    record = _make_record(
        payload={"accused": [{"name": "Rahul Sharma"}]},
        payload_text="Rahul Sharma met Priya Mehta at Hotel Blue Star.",
    )
    # Use the full Extractor with an unavailable LLM
    extractor = Extractor(llm_extractor=LLMExtractor(
        llm_client=_llm_client_unavailable()
    ))
    result = extractor.extract_one(record)

    assert isinstance(result, ExtractionResult)
    assert result.record_id == record.record_id
    # B5 regex found at least one person (Rahul Sharma from accused field)
    assert len(result.entities) > 0
    # No LLM mentions (since it was unavailable)
    llm_mentions = [e for e in result.entities if e.extraction_method == "llm"]
    assert llm_mentions == []


def test_llm_unavailable_does_not_raise():
    """Contract Invariant 4: LLM unavailability must never raise an exception."""
    record = _make_record()
    extractor = Extractor(llm_extractor=LLMExtractor(
        llm_client=_llm_client_unavailable()
    ))
    # Must not raise — any exception here is a test failure
    result = extractor.extract_one(record)
    assert result is not None


def test_llm_timeout_extraction_still_completes():
    """Timeout (one of the unavailable reasons) → graceful degradation."""
    mock_provider = MagicMock()
    mock_provider.call.side_effect = TimeoutError("LLM timed out")
    client = LLMClient(provider=mock_provider)
    extractor = Extractor(llm_extractor=LLMExtractor(llm_client=client))
    result = extractor.extract_one(_make_record())
    assert isinstance(result, ExtractionResult)


def test_llm_rate_limited_extraction_still_completes():
    """Rate limit → graceful degradation."""
    from app.llm.client import _RateLimitError
    mock_provider = MagicMock()
    mock_provider.call.side_effect = _RateLimitError("rate limited")
    client = LLMClient(provider=mock_provider)
    extractor = Extractor(llm_extractor=LLMExtractor(llm_client=client))
    result = extractor.extract_one(_make_record())
    assert isinstance(result, ExtractionResult)


# ===========================================================================
# LLMExtractor.extract() — success path
# ===========================================================================

def test_llm_adds_new_entity_mentions():
    """LLM returns valid JSON → new EntityMention with extraction_method='llm'."""
    record = _make_record(
        payload_text="Devendra Khanna from Khanna Enterprises Pvt Ltd met them."
    )
    # Low confidence so _needs_llm returns True
    existing = [_make_entity("m_001", "Person", "Rahul Sharma", confidence=0.5)]

    llm_response = json.dumps([
        {"entity_type": "Person", "raw_text": "Devendra Khanna"},
        {"entity_type": "Organization", "raw_text": "Khanna Enterprises Pvt Ltd"},
    ])
    extractor = LLMExtractor(llm_client=_llm_client_ok(llm_response))
    entities, rels = extractor.extract(record, existing)

    assert len(entities) == 2
    assert all(e.extraction_method == "llm" for e in entities)
    raw_texts = {e.raw_text for e in entities}
    assert "Devendra Khanna" in raw_texts
    assert "Khanna Enterprises Pvt Ltd" in raw_texts
    assert rels == []  # LLM never produces relationships directly


def test_llm_entity_carries_correct_record_id_and_dataset():
    """DOC3 §4 provenance: record_id and dataset must be propagated."""
    record = _make_record(record_id="fir_042", dataset="synthetic_demo")
    existing = [_make_entity("m_001", "Person", "Rahul Sharma", record_id="fir_042", confidence=0.5)]

    llm_response = json.dumps([{"entity_type": "Location", "raw_text": "Nariman Point"}])
    extractor = LLMExtractor(llm_client=_llm_client_ok(llm_response))
    entities, _ = extractor.extract(record, existing)

    assert len(entities) == 1
    assert entities[0].record_id == "fir_042"
    assert entities[0].dataset == "synthetic_demo"


def test_llm_entity_method_tag_is_llm():
    record = _make_record()
    existing = [_make_entity("m_001", "Person", "Someone", confidence=0.5)]
    llm_response = json.dumps([{"entity_type": "Event", "raw_text": "the meeting on Tuesday"}])
    extractor = LLMExtractor(llm_client=_llm_client_ok(llm_response))
    entities, _ = extractor.extract(record, existing)
    assert all(e.extraction_method == "llm" for e in entities)


# ===========================================================================
# LLM output validation — malformed / invalid inputs dropped silently
# ===========================================================================

def test_invalid_entity_type_dropped():
    """LLM returns unknown entity_type → silently dropped."""
    record = _make_record()
    existing = []
    llm_response = json.dumps([
        {"entity_type": "Case", "raw_text": "Case #001"},        # invalid — Contract Invariant 16
        {"entity_type": "Unknown", "raw_text": "something"},      # invalid — not in enum
        {"entity_type": "Person", "raw_text": "Valid Person"},    # valid
    ])
    extractor = LLMExtractor(llm_client=_llm_client_ok(llm_response))
    entities, _ = extractor.extract(record, existing)
    assert len(entities) == 1
    assert entities[0].raw_text == "Valid Person"
    # Confirm Case never appears
    assert all(e.entity_type != "Case" for e in entities)


def test_malformed_json_returns_empty():
    """LLM returns non-JSON → empty result, no crash."""
    record = _make_record()
    existing = []
    extractor = LLMExtractor(llm_client=_llm_client_ok("This is not JSON at all."))
    entities, rels = extractor.extract(record, existing)
    assert entities == []
    assert rels == []


def test_markdown_fenced_json_is_accepted():
    """LLM wraps output in markdown fences → still parsed correctly."""
    record = _make_record()
    existing = []
    fenced = "```json\n[{\"entity_type\": \"Person\", \"raw_text\": \"Anita Verma\"}]\n```"
    extractor = LLMExtractor(llm_client=_llm_client_ok(fenced))
    entities, _ = extractor.extract(record, existing)
    assert len(entities) == 1
    assert entities[0].raw_text == "Anita Verma"


def test_empty_array_response_returns_empty():
    record = _make_record()
    extractor = LLMExtractor(llm_client=_llm_client_ok("[]"))
    entities, rels = extractor.extract(record, [])
    assert entities == []
    assert rels == []


def test_llm_does_not_duplicate_existing_entities():
    """LLM output must not repeat entities already found by B5."""
    record = _make_record()
    existing = [_make_entity("m_001", "Person", "Rahul Sharma", confidence=0.5)]
    llm_response = json.dumps([
        {"entity_type": "Person", "raw_text": "Rahul Sharma"},    # duplicate — should be dropped
        {"entity_type": "Person", "raw_text": "Priya Mehta"},     # new — should be included
    ])
    extractor = LLMExtractor(llm_client=_llm_client_ok(llm_response))
    entities, _ = extractor.extract(record, existing)
    raw_texts = {e.raw_text for e in entities}
    assert "Rahul Sharma" not in raw_texts  # deduplicated
    assert "Priya Mehta" in raw_texts


def test_empty_raw_text_dropped():
    record = _make_record()
    llm_response = json.dumps([{"entity_type": "Person", "raw_text": ""}])
    extractor = LLMExtractor(llm_client=_llm_client_ok(llm_response))
    entities, _ = extractor.extract(record, [])
    assert entities == []


# ===========================================================================
# LLMExtractor._needs_llm heuristic
# ===========================================================================

def test_cdr_record_skips_llm():
    """CDR records are structured-only; the LLM heuristic should return False."""
    record = _make_record(source_type="CDR", payload_text="9876543210 9988776655 145s")
    extractor = LLMExtractor(llm_client=_llm_client_ok("[]"))
    # Confirm poll is not made (CDR is excluded)
    mock_provider = MagicMock()
    mock_provider.call.return_value = "[]"
    extractor._client = LLMClient(provider=mock_provider)
    extractor.extract(record, [])
    mock_provider.call.assert_not_called()


def test_short_text_skips_llm():
    """Short payload_text → LLM call skipped."""
    record = _make_record(payload_text="Hi")
    mock_provider = MagicMock()
    mock_provider.call.return_value = "[]"
    extractor = LLMExtractor(llm_client=LLMClient(provider=mock_provider))
    extractor.extract(record, [])
    mock_provider.call.assert_not_called()


def test_high_confidence_entities_skip_llm():
    """All existing entities have high confidence → LLM call skipped."""
    record = _make_record()
    existing = [
        _make_entity("m_001", "Person", "Rahul Sharma", confidence=0.95),
        _make_entity("m_002", "Organization", "Khanna Enterprises", confidence=0.90),
    ]
    mock_provider = MagicMock()
    mock_provider.call.return_value = "[]"
    extractor = LLMExtractor(llm_client=LLMClient(provider=mock_provider))
    extractor.extract(record, existing)
    mock_provider.call.assert_not_called()


def test_no_person_org_triggers_llm():
    """No Person or Org mentions → LLM is invoked."""
    record = _make_record()
    existing = [_make_entity("m_001", "Phone", "9876543210", confidence=0.99)]
    mock_provider = MagicMock()
    mock_provider.call.return_value = "[]"
    extractor = LLMExtractor(llm_client=LLMClient(provider=mock_provider))
    extractor.extract(record, existing)
    mock_provider.call.assert_called_once()


# ===========================================================================
# build_extractor() factory
# ===========================================================================

def test_build_extractor_no_llm_returns_b5_only():
    """build_extractor(with_llm=False) → Extractor with no LLM extractor."""
    extractor = build_extractor(with_llm=False)
    assert extractor._llm is None


def test_build_extractor_with_llm_true_wires_llm_extractor():
    """build_extractor(with_llm=True) → Extractor with LLMExtractor attached."""
    extractor = build_extractor(with_llm=True)
    assert extractor._llm is not None
    assert isinstance(extractor._llm, LLMExtractor)


def test_build_extractor_works_without_llm():
    """Factory with LLM disabled still produces correct extraction results."""
    from pathlib import Path
    from app.ingestion.synthetic_adapter import SyntheticAdapter

    repo_root = Path(__file__).resolve().parents[3]
    adapter = SyntheticAdapter(base_path=repo_root / "data" / "synthetic")
    records = adapter.fetch_batch()

    extractor = build_extractor(with_llm=False)
    results = extractor.extract_batch(records)
    assert len(results) == 31
    # No LLM mentions in B5-only mode
    llm_mentions = [
        e for r in results for e in r.entities if e.extraction_method == "llm"
    ]
    assert llm_mentions == []


# ===========================================================================
# Full pipeline: B5 + B6 (mock LLM) over real H1 records
# ===========================================================================

def test_full_pipeline_b5_b6_mock_llm_h1():
    """Integration: B5+B6 over H1 with mock LLM. All 31 records complete."""
    from pathlib import Path
    from app.ingestion.synthetic_adapter import SyntheticAdapter

    repo_root = Path(__file__).resolve().parents[3]
    adapter = SyntheticAdapter(base_path=repo_root / "data" / "synthetic")
    records = adapter.fetch_batch()

    # Mock LLM returns one new entity per call
    mock_provider = MagicMock()
    mock_provider.call.return_value = json.dumps([
        {"entity_type": "Event", "raw_text": "the meeting"}
    ])
    client = LLMClient(provider=mock_provider)
    extractor = Extractor(llm_extractor=LLMExtractor(llm_client=client))

    results = extractor.extract_batch(records)
    assert len(results) == 31

    # Verify provenance on all LLM-generated mentions
    for result in results:
        record = next(r for r in records if r.record_id == result.record_id)
        for em in result.entities:
            assert em.record_id == record.record_id
            assert em.dataset == record.dataset
            assert em.entity_type != "Case"  # Invariant 16
