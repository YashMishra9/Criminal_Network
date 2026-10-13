"""Unit tests for Task B8: Incremental Entity Resolution (best-effort).

Tests (per B8 §13):
  - Unit tests with synthetic live-like fixtures covering both match and no-match cases.
  - Acceptance criteria (B8 §12):
      * A live mention with no match creates a new entity without error.
      * A live mention matching an existing entity updates resolved_from
        and produces a ResolutionDecision.
  - Dataset isolation: mention.dataset != dataset raises ValueError.
  - best-effort label: documented in tests (NOT claimed to be correctness-guaranteed).
  - source_record_ids parallel to mention_ids (DOC3 §1.7).

IMPORTANT: B8 is BEST-EFFORT ONLY (DOC1 FR11). Tests confirm functional
correctness for the defined cases but do NOT assert exhaustive correctness.
"""

from typing import List, Optional

import pytest

from app.contracts.entity import CanonicalEntity
from app.contracts.mention import EntityMention
from app.contracts.resolution import ResolutionDecision
from app.resolution.resolver import IncrementalResolver, IncrementalResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mention(
    mention_id: str,
    entity_type: str,
    raw_text: str,
    record_id: str = "live_rec_001",
    dataset: str = "live_public",
    normalized_value: Optional[str] = None,
    attributes: Optional[dict] = None,
    extraction_method: str = "regex",
) -> EntityMention:
    return EntityMention(
        mention_id=mention_id,
        record_id=record_id,
        dataset=dataset,
        entity_type=entity_type,  # type: ignore[arg-type]
        raw_text=raw_text,
        normalized_value=normalized_value,
        attributes=attributes or {},
        extraction_method=extraction_method,  # type: ignore[arg-type]
        confidence=None,
    )


def _make_entity(
    entity_id: str,
    entity_type: str,
    display_name: str,
    dataset: str = "live_public",
    resolved_from: Optional[List[str]] = None,
) -> CanonicalEntity:
    return CanonicalEntity(
        entity_id=entity_id,
        entity_type=entity_type,  # type: ignore[arg-type]
        dataset=dataset,
        display_name=display_name,
        attributes={},
        resolved_from=resolved_from or ["orig_mention_001"],
        resolution_method="exact_match",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )


# ===========================================================================
# B8 §12 Acceptance Criteria: no-match case
# ===========================================================================

def test_no_match_creates_new_entity():
    """B8 §12: a live mention with no match creates a new entity without error."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Phone", "7777777777", normalized_value="7777777777")
    existing = [_make_entity("ent_001", "Phone", "+919876543210", resolved_from=["m_orig"])]

    result = resolver.resolve_one(mention, existing, dataset="live_public")

    assert isinstance(result, IncrementalResult)
    assert result.is_new_entity is True
    assert result.updated_entity is None
    assert result.entity is not None
    assert result.entity.entity_type == "Phone"
    assert mention.mention_id in result.entity.resolved_from


def test_no_match_decision_has_singleton_marker():
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Phone", "7777777777", normalized_value="7777777777")
    result = resolver.resolve_one(mention, [], dataset="live_public")
    assert "singleton_new_entity" in result.decision.matched_on


def test_no_match_empty_existing_set_creates_new_entity():
    """Empty existing set → always creates a new entity."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_001", "Person", "John Doe")
    result = resolver.resolve_one(mention, [], dataset="live_public")
    assert result.is_new_entity
    assert result.entity.display_name == "John Doe"


def test_no_match_different_entity_type_ignored():
    """Existing entities of a different entity_type must be skipped."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Person", "Rahul Sharma")
    existing = [
        # Same phone normalized value but different entity_type
        _make_entity("ent_001", "Phone", "9876543210"),
    ]
    result = resolver.resolve_one(mention, existing, dataset="live_public")
    assert result.is_new_entity  # Different type → no match


# ===========================================================================
# B8 §12 Acceptance Criteria: match case
# ===========================================================================

def test_matching_phone_updates_existing_entity():
    """B8 §12: live mention matching existing entity updates resolved_from."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Phone", "9876543210", normalized_value="9876543210")
    existing = [_make_entity("ent_001", "Phone", "9876543210", resolved_from=["m_orig"])]

    result = resolver.resolve_one(mention, existing, dataset="live_public")

    assert result.is_new_entity is False
    assert result.updated_entity is not None
    assert "m_new" in result.updated_entity.resolved_from
    assert "m_orig" in result.updated_entity.resolved_from  # original still present
    assert result.entity.entity_id == "ent_001"  # same entity id


def test_matching_person_name_updates_existing_entity():
    """Person name abbreviation match → attaches mention to existing entity."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Person", "R. Sharma", record_id="live_rec_002")
    existing = [_make_entity("ent_person", "Person", "Rahul Sharma", resolved_from=["m_orig"])]

    result = resolver.resolve_one(mention, existing, dataset="live_public")

    assert result.is_new_entity is False
    assert "m_new" in result.updated_entity.resolved_from


def test_matching_org_prefix_updates_existing():
    """Org prefix match → attaches to existing entity."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Organization", "Khanna Enterprises")
    existing = [_make_entity("ent_org", "Organization", "Khanna Enterprises Pvt Ltd")]

    result = resolver.resolve_one(mention, existing, dataset="live_public")

    assert result.is_new_entity is False
    assert "m_new" in result.updated_entity.resolved_from


def test_matching_vehicle_updates_existing():
    """Vehicle plate match → attaches to existing entity."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Vehicle", "MH-01-AB-1234", normalized_value="MH01AB1234")
    existing = [_make_entity("ent_veh", "Vehicle", "MH-01-AB-1234")]

    result = resolver.resolve_one(mention, existing, dataset="live_public")

    assert result.is_new_entity is False


def test_match_result_decision_has_matched_on():
    """On a match, decision.matched_on is non-empty."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Phone", "9876543210", normalized_value="9876543210")
    existing = [_make_entity("ent_001", "Phone", "9876543210")]
    result = resolver.resolve_one(mention, existing, dataset="live_public")
    assert result.decision.matched_on
    assert len(result.decision.matched_on) > 0


def test_first_match_is_used_best_effort():
    """When multiple entities could match, the first one found is used (best-effort)."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Person", "Rahul Sharma")
    # Two entities that both match
    existing = [
        _make_entity("ent_A", "Person", "Rahul Sharma", resolved_from=["mA"]),
        _make_entity("ent_B", "Person", "R. Sharma", resolved_from=["mB"]),
    ]
    result = resolver.resolve_one(mention, existing, dataset="live_public")
    assert result.is_new_entity is False
    # Must match ent_A (the first one in the list)
    assert result.entity.entity_id == "ent_A"


# ===========================================================================
# DOC3 §1.7: source_record_ids parallel to mention_ids
# ===========================================================================

def test_decision_source_record_ids_parallel_to_mention_ids_on_match():
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Phone", "9876543210", normalized_value="9876543210", record_id="live_r_001")
    existing = [_make_entity("ent_001", "Phone", "9876543210")]
    result = resolver.resolve_one(mention, existing, dataset="live_public")
    assert len(result.decision.mention_ids) == len(result.decision.source_record_ids)


def test_decision_source_record_ids_parallel_on_new_entity():
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Phone", "0000000000", normalized_value="0000000000", record_id="live_r_002")
    result = resolver.resolve_one(mention, [], dataset="live_public")
    assert len(result.decision.mention_ids) == len(result.decision.source_record_ids)
    assert result.decision.source_record_ids[0] == "live_r_002"


def test_decision_mention_ids_contains_new_mention_id():
    resolver = IncrementalResolver()
    mention = _make_mention("m_xyz", "Phone", "9876543210", normalized_value="9876543210")
    existing = [_make_entity("ent_001", "Phone", "9876543210")]
    result = resolver.resolve_one(mention, existing, dataset="live_public")
    assert "m_xyz" in result.decision.mention_ids


# ===========================================================================
# Dataset isolation
# ===========================================================================

def test_dataset_isolation_raises_on_wrong_mention_dataset():
    """DOC3 §2.6: mention.dataset != dataset → ValueError."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Phone", "9876543210", dataset="synthetic_demo")
    with pytest.raises(ValueError, match="Dataset isolation"):
        resolver.resolve_one(mention, [], dataset="live_public")


def test_dataset_isolation_existing_entities_filtered_by_dataset():
    """Entities from a different dataset in the existing list are silently skipped."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Phone", "9876543210", normalized_value="9876543210", dataset="live_public")
    # Existing entity has same display_name but wrong dataset — must be skipped
    existing = [_make_entity("ent_001", "Phone", "9876543210", dataset="synthetic_demo")]
    result = resolver.resolve_one(mention, existing, dataset="live_public")
    # synthetic_demo entity should be skipped → new entity created
    assert result.is_new_entity


# ===========================================================================
# Output shape and ID uniqueness
# ===========================================================================

def test_new_entity_has_globally_unique_entity_id():
    """DOC3 §1.13: every new entity_id is globally unique (not reusing existing ids)."""
    resolver = IncrementalResolver()
    existing = [_make_entity("ent_001", "Phone", "+919876543210")]
    mention = _make_mention("m_new", "Phone", "8888888888", normalized_value="8888888888")
    result = resolver.resolve_one(mention, existing, dataset="live_public")
    assert result.entity.entity_id != "ent_001"


def test_decision_has_unique_decision_id():
    """DOC3 §1.13: decision_id is unique across two calls."""
    resolver = IncrementalResolver()
    m1 = _make_mention("m1", "Phone", "0000000000", normalized_value="0000000000")
    m2 = _make_mention("m2", "Phone", "1111111111", normalized_value="1111111111")
    r1 = resolver.resolve_one(m1, [], dataset="live_public")
    r2 = resolver.resolve_one(m2, [], dataset="live_public")
    assert r1.decision.decision_id != r2.decision.decision_id


def test_new_entity_dataset_equals_input_dataset():
    """New entity must carry the correct dataset value."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Person", "Jane Smith", dataset="live_public")
    result = resolver.resolve_one(mention, [], dataset="live_public")
    assert result.entity.dataset == "live_public"


def test_updated_entity_preserves_entity_id():
    """Updated entity must retain the same entity_id as the candidate."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Phone", "9876543210", normalized_value="9876543210")
    existing = [_make_entity("ent_FIXED", "Phone", "9876543210")]
    result = resolver.resolve_one(mention, existing, dataset="live_public")
    assert result.entity.entity_id == "ent_FIXED"


def test_updated_entity_updated_at_is_refreshed():
    """updated_at on the returned entity must be a fresh timestamp (not the original)."""
    resolver = IncrementalResolver()
    mention = _make_mention("m_new", "Phone", "9876543210", normalized_value="9876543210")
    existing = [_make_entity("ent_001", "Phone", "9876543210")]
    result = resolver.resolve_one(mention, existing, dataset="live_public")
    # Original was "2024-01-01T00:00:00Z"; updated_at should differ
    assert result.entity.updated_at != "2024-01-01T00:00:00Z"


def test_outcome_is_always_merged():
    """ResolutionDecision.outcome is always 'merged' (B8 never rejects — FR11)."""
    resolver = IncrementalResolver()
    # No-match case
    m1 = _make_mention("m1", "Person", "Unknown Person XYZ")
    r1 = resolver.resolve_one(m1, [], dataset="live_public")
    assert r1.decision.outcome == "merged"

    # Match case
    m2 = _make_mention("m2", "Phone", "9876543210", normalized_value="9876543210")
    r2 = resolver.resolve_one(m2, [_make_entity("ent_p", "Phone", "9876543210")], dataset="live_public")
    assert r2.decision.outcome == "merged"


# ===========================================================================
# Best-effort documentation (FR11)
# ===========================================================================

def test_incremental_resolver_is_marked_best_effort():
    """Confirm the resolver class docstring contains the best-effort disclaimer."""
    import inspect
    doc = inspect.getdoc(IncrementalResolver)
    assert "best-effort" in doc.lower() or "BEST-EFFORT" in doc, (
        "IncrementalResolver docstring must contain best-effort disclaimer (DOC1 FR11)"
    )


def test_incremental_result_is_marked_best_effort():
    """IncrementalResult must carry a best-effort annotation."""
    import inspect
    doc = inspect.getdoc(IncrementalResult)
    assert "best-effort" in (doc or "").lower() or "FR11" in (doc or ""), (
        "IncrementalResult docstring must reference best-effort / FR11"
    )
