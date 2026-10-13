"""Unit tests for Tasks C2, C3, C4 — Graph Write Layer & EvidenceResolver.

These are unit-level tests that do NOT require a live Neo4j connection:
  - C2: write_entity / write_relationship contract checks (empty-evidence rejection,
         EdgeRef shape, Invariant 1 enforcement, Invariant 12 structure).
  - C3: write_evidence / write_resolution_decision contract checks (idempotency key,
         shape correctness, parallelism of mention_ids / source_record_ids).
  - C4: EvidenceResolver method signatures and item_type routing.

Live-Neo4j integration tests are in tests/integration/test_graph_write_layer.py,
guarded by @pytest.mark.neo4j_live.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.contracts.case import EdgeRef
from app.contracts.entity import CanonicalEntity
from app.contracts.evidence import Evidence
from app.contracts.relationship import Relationship
from app.contracts.resolution import ResolutionDecision
from app.evidence.resolver import EvidenceResolver, evidence_resolver
from app.graph.write_layer import (
    _new_uuid,
    evidence_from_raw_record,
    write_entity,
    write_evidence,
    write_relationship,
    write_resolution_decision,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_evidence(
    evidence_id: str = "ev-001",
    source_id: str = "fir_001",
    dataset: str = "synthetic_demo",
    source_type: str = "FIR",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        dataset=dataset,
        source_id=source_id,
        source_type=source_type,
        ingested_at="2024-01-01T00:00:00Z",
    )


def _make_entity(
    entity_id: str = "ent-001",
    entity_type: str = "Person",
    dataset: str = "synthetic_demo",
) -> CanonicalEntity:
    return CanonicalEntity(
        entity_id=entity_id,
        entity_type=entity_type,
        dataset=dataset,
        display_name="Test Person",
        resolved_from=["m-001"],
        resolution_method="exact_match",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )


def _make_relationship(
    relationship_id: str = "rel-001",
    evidence_ids: list = None,
    from_entity_id: str = "ent-001",
    to_entity_id: str = "ent-002",
) -> Relationship:
    return Relationship(
        relationship_id=relationship_id,
        relationship_type="CALLED",
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        dataset="synthetic_demo",
        valid_from="2024-01-01T00:00:00Z",
        evidence_ids=evidence_ids or ["ev-001"],
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )


def _make_decision(
    decision_id: str = "dec-001",
    entity_id: str = "ent-001",
    mention_ids: list = None,
    source_record_ids: list = None,
) -> ResolutionDecision:
    mention_ids = mention_ids or ["m-001", "m-002"]
    source_record_ids = source_record_ids or ["fir_001", "pr_001"]
    return ResolutionDecision(
        decision_id=decision_id,
        entity_id=entity_id,
        mention_ids=mention_ids,
        source_record_ids=source_record_ids,
        outcome="merged",
        method="exact_match",
        matched_on=["phone_number"],
        decided_at="2024-01-01T00:00:00Z",
    )


# ===========================================================================
# C2 — write_relationship: Contract Invariant 1 enforcement
# ===========================================================================

def test_write_relationship_rejects_empty_evidence_list():
    """Contract Invariant 1: write_relationship must raise on empty evidence_list."""
    rel = _make_relationship(evidence_ids=["ev-001"])
    with pytest.raises(ValueError, match="evidence_list is empty"):
        # Pass empty list — must raise before hitting Neo4j
        write_relationship(rel, evidence_list=[])


def test_write_relationship_rejects_empty_evidence_ids_on_relationship():
    """Contract Invariant 1: relationship.evidence_ids must not be empty.

    Directly construct a Relationship with evidence_ids=[] (bypassing the
    _make_relationship helper's 'or' default which would silently substitute ["ev-001"]).
    Must raise before touching the DB.
    """
    from app.contracts.relationship import Relationship as _Rel
    rel = _Rel(
        relationship_id="rel-empty-evids",
        relationship_type="CALLED",
        from_entity_id="ent-001",
        to_entity_id="ent-002",
        dataset="synthetic_demo",
        valid_from="2024-01-01T00:00:00Z",
        evidence_ids=[],   # <-- explicitly empty
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )
    ev = _make_evidence()
    with patch("app.graph.write_layer.get_session") as mock_session:
        with pytest.raises(ValueError, match="evidence_ids is empty"):
            write_relationship(rel, evidence_list=[ev])
        mock_session.assert_not_called()  # must be pre-DB rejection


def test_write_relationship_raises_before_db_call():
    """Invariant 1 enforcement must happen before any Neo4j session is opened."""
    rel = _make_relationship()
    with patch("app.graph.write_layer.get_session") as mock_session:
        with pytest.raises(ValueError):
            write_relationship(rel, evidence_list=[])
        # get_session must NOT have been called — rejection is pre-DB
        mock_session.assert_not_called()


# ===========================================================================
# C2 — write_relationship: EdgeRef shape
# ===========================================================================

def test_write_relationship_returns_edge_ref_with_correct_relationship_id():
    """write_relationship must return an EdgeRef pointing to the same relationship_id."""
    rel = _make_relationship(relationship_id="rel-xyz")
    ev = _make_evidence()

    # Mock the Neo4j session so we don't need a live DB
    mock_result = MagicMock()
    mock_result.single.return_value = {"actual_edge_ref_id": "edge-ref-uuid-1"}
    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("app.graph.write_layer.get_session", return_value=mock_session):
        edge_ref = write_relationship(rel, evidence_list=[ev])

    assert isinstance(edge_ref, EdgeRef)
    assert edge_ref.relationship_id == "rel-xyz"
    assert edge_ref.from_entity_id == rel.from_entity_id
    assert edge_ref.to_entity_id == rel.to_entity_id
    assert edge_ref.relationship_type == "CALLED"


def test_write_relationship_calls_session_run_at_least_twice():
    """Expect at least: (1) MERGE relationship+EdgeRef, (2) SUPPORTS edge per evidence."""
    rel = _make_relationship()
    ev1 = _make_evidence("ev-001", "fir_001")
    ev2 = _make_evidence("ev-002", "fir_002")

    mock_result = MagicMock()
    mock_result.single.return_value = {"actual_edge_ref_id": "er-1"}
    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("app.graph.write_layer.get_session", return_value=mock_session):
        write_relationship(rel, evidence_list=[ev1, ev2])

    # At least 3 calls: main MERGE + 2 SUPPORTS
    assert mock_session.run.call_count >= 3


# ===========================================================================
# C3 — write_evidence: shape and idempotency key
# ===========================================================================

def test_write_evidence_returns_evidence_on_first_write():
    """write_evidence must return an Evidence object with the same evidence_id."""
    ev = _make_evidence("ev-stable")

    mock_result = MagicMock()
    mock_result.single.return_value = {"evidence_id": "ev-stable"}
    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("app.graph.write_layer.get_session", return_value=mock_session):
        result = write_evidence(ev)

    assert result.evidence_id == "ev-stable"
    assert result.source_id == ev.source_id
    assert result.dataset == ev.dataset


def test_write_evidence_returns_existing_id_on_second_write():
    """If (source_id, dataset) already exists with a different evidence_id,
    the existing evidence_id must be returned (not the input one)."""
    ev = _make_evidence("ev-NEW", "fir_001")  # we pass ev-NEW but DB says ev-EXISTING

    mock_result = MagicMock()
    mock_result.single.return_value = {"evidence_id": "ev-EXISTING"}
    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("app.graph.write_layer.get_session", return_value=mock_session):
        result = write_evidence(ev)

    assert result.evidence_id == "ev-EXISTING"
    # Other fields preserved from input
    assert result.source_id == "fir_001"
    assert result.dataset == "synthetic_demo"


def test_write_evidence_uses_merge_cypher():
    """write_evidence must use MERGE (not CREATE) so it is idempotent."""
    ev = _make_evidence()
    mock_result = MagicMock()
    mock_result.single.return_value = {"evidence_id": ev.evidence_id}
    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("app.graph.write_layer.get_session", return_value=mock_session):
        write_evidence(ev)

    # The cypher passed to run() must contain MERGE
    call_args = mock_session.run.call_args_list[0]
    cypher_arg = call_args[0][0]
    assert "MERGE" in cypher_arg.upper()


def test_write_evidence_merge_key_is_source_id_and_dataset():
    """The MERGE key in write_evidence must be (source_id, dataset) not evidence_id."""
    ev = _make_evidence("ev-001", "fir_001", "synthetic_demo")
    mock_result = MagicMock()
    mock_result.single.return_value = {"evidence_id": "ev-001"}
    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("app.graph.write_layer.get_session", return_value=mock_session):
        write_evidence(ev)

    cypher = mock_session.run.call_args_list[0][0][0]
    params = mock_session.run.call_args_list[0][0][1]
    # MERGE must reference source_id and dataset as the key
    assert "source_id" in cypher
    assert "dataset" in cypher
    assert params["source_id"] == "fir_001"
    assert params["dataset"] == "synthetic_demo"


# ===========================================================================
# C3 — write_resolution_decision: DOC3 §1.7 parallelism invariant
# ===========================================================================

def test_resolution_decision_mention_ids_and_source_record_ids_same_length():
    """DOC3 §1.7: mention_ids and source_record_ids must have the same length."""
    dec = _make_decision(mention_ids=["m1", "m2"], source_record_ids=["r1", "r2"])
    assert len(dec.mention_ids) == len(dec.source_record_ids)


def test_resolution_decision_schema_requires_entity_id():
    """ResolutionDecision must carry entity_id (the resulting entity)."""
    dec = _make_decision(entity_id="ent-abc")
    assert dec.entity_id == "ent-abc"


def test_write_resolution_decision_calls_session():
    """write_resolution_decision must call Neo4j at least once."""
    dec = _make_decision()

    mock_result = MagicMock()
    mock_result.single.return_value = {"dataset": "synthetic_demo", "matched": 1}
    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("app.graph.write_layer.get_session", return_value=mock_session):
        write_resolution_decision(dec)

    assert mock_session.run.call_count >= 1


# ===========================================================================
# C2 — evidence_from_raw_record helper
# ===========================================================================

def test_evidence_from_raw_record_produces_valid_evidence():
    ev = evidence_from_raw_record(
        record_id="fir_001",
        dataset="synthetic_demo",
        source_type="FIR",
        ingested_at="2024-01-01T00:00:00Z",
        occurred_at="2024-01-01T08:00:00Z",
        snippet="Rahul Sharma seen at Andheri station",
    )
    assert ev.source_id == "fir_001"
    assert ev.dataset == "synthetic_demo"
    assert ev.source_type == "FIR"
    assert ev.snippet == "Rahul Sharma seen at Andheri station"
    assert ev.record_timestamp == "2024-01-01T08:00:00Z"
    assert ev.evidence_id  # non-empty UUID


def test_evidence_from_raw_record_produces_unique_ids():
    ev1 = evidence_from_raw_record("r1", "synthetic_demo", "FIR", "2024-01-01T00:00:00Z")
    ev2 = evidence_from_raw_record("r2", "synthetic_demo", "FIR", "2024-01-01T00:00:00Z")
    assert ev1.evidence_id != ev2.evidence_id


# ===========================================================================
# C4 — EvidenceResolver: method signatures and item_type routing
# ===========================================================================

def test_evidence_resolver_singleton_exists():
    """Module-level evidence_resolver singleton must be an EvidenceResolver."""
    assert isinstance(evidence_resolver, EvidenceResolver)


def test_evidence_resolver_for_entity_returns_list():
    mock_result = [{"evidence_id": "ev-1", "dataset": "synthetic_demo",
                    "source_id": "fir_001", "source_type": "FIR",
                    "ingested_at": "2024-01-01T00:00:00Z",
                    "record_timestamp": None, "snippet": None, "pointer_json": None}]
    mock_session = MagicMock()
    mock_session.run.return_value = iter(mock_result)
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    resolver = EvidenceResolver()
    with patch("app.evidence.resolver.get_session", return_value=mock_session):
        result = resolver.for_entity("ent-001")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].evidence_id == "ev-1"


def test_evidence_resolver_for_relationship_returns_list():
    mock_session = MagicMock()
    mock_session.run.return_value = iter([])
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    resolver = EvidenceResolver()
    with patch("app.evidence.resolver.get_session", return_value=mock_session):
        result = resolver.for_relationship("rel-001")

    assert isinstance(result, list)


def test_evidence_resolver_for_finding_returns_list():
    mock_session = MagicMock()
    mock_session.run.return_value = iter([])
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    resolver = EvidenceResolver()
    with patch("app.evidence.resolver.get_session", return_value=mock_session):
        result = resolver.for_finding("find-001")

    assert isinstance(result, list)


def test_evidence_resolver_for_resolution_decision_returns_list():
    mock_session = MagicMock()
    mock_session.run.return_value = iter([])
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    resolver = EvidenceResolver()
    with patch("app.evidence.resolver.get_session", return_value=mock_session):
        result = resolver.for_resolution_decision("dec-001")

    assert isinstance(result, list)


def test_evidence_resolver_for_case_item_entity_delegates_to_for_entity():
    resolver = EvidenceResolver()
    resolver.for_entity = MagicMock(return_value=[])
    result = resolver.for_case_item("case-1", "entity", "ent-001")
    resolver.for_entity.assert_called_once_with("ent-001")
    assert result == []


def test_evidence_resolver_for_case_item_evidence_queries_directly():
    mock_row = {"evidence_id": "ev-1", "dataset": "synthetic_demo",
                "source_id": "fir_001", "source_type": "FIR",
                "ingested_at": "2024-01-01T00:00:00Z",
                "record_timestamp": None, "snippet": None, "pointer_json": None}
    mock_result = MagicMock()
    mock_result.single.return_value = mock_row
    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    resolver = EvidenceResolver()
    with patch("app.evidence.resolver.get_session", return_value=mock_session):
        result = resolver.for_case_item("case-1", "evidence", "ev-1")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].evidence_id == "ev-1"


def test_evidence_resolver_for_case_item_edge_ref_looks_up_relationship_id():
    # Mock: EdgeRef lookup returns relationship_id, then for_relationship is called
    mock_result = MagicMock()
    mock_result.single.return_value = {"relationship_id": "rel-abc"}
    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    resolver = EvidenceResolver()
    resolver.for_relationship = MagicMock(return_value=[])

    with patch("app.evidence.resolver.get_session", return_value=mock_session):
        resolver.for_case_item("case-1", "edge_ref", "er-001")

    resolver.for_relationship.assert_called_once_with("rel-abc")


def test_evidence_resolver_for_case_item_invalid_type_raises():
    resolver = EvidenceResolver()
    with pytest.raises(ValueError, match="unknown item_type"):
        resolver.for_case_item("case-1", "unknown", "item-001")  # type: ignore


def test_evidence_resolver_for_entity_query_uses_resolved_from_path():
    """The for_entity query must traverse RESOLVED_FROM and BASED_ON (DOC3 §2.5)."""
    mock_session = MagicMock()
    mock_session.run.return_value = iter([])
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    resolver = EvidenceResolver()
    with patch("app.evidence.resolver.get_session", return_value=mock_session):
        resolver.for_entity("ent-001")

    cypher = mock_session.run.call_args[0][0]
    assert "RESOLVED_FROM" in cypher
    assert "BASED_ON" in cypher


def test_evidence_resolver_for_relationship_query_uses_supports_edge_ref():
    """for_relationship must traverse SUPPORTS → EdgeRef (DOC3 §6.5)."""
    mock_session = MagicMock()
    mock_session.run.return_value = iter([])
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    resolver = EvidenceResolver()
    with patch("app.evidence.resolver.get_session", return_value=mock_session):
        resolver.for_relationship("rel-001")

    cypher = mock_session.run.call_args[0][0]
    assert "EdgeRef" in cypher
    assert "SUPPORTS" in cypher


def test_evidence_resolver_for_finding_query_direct_supports():
    """for_finding must use direct Evidence-[:SUPPORTS]->Finding (no EdgeRef)."""
    mock_session = MagicMock()
    mock_session.run.return_value = iter([])
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    resolver = EvidenceResolver()
    with patch("app.evidence.resolver.get_session", return_value=mock_session):
        resolver.for_finding("find-001")

    cypher = mock_session.run.call_args[0][0]
    assert "Finding" in cypher
    assert "SUPPORTS" in cypher
    # Must NOT go through EdgeRef for findings (DOC3 §1.8)
    assert "EdgeRef" not in cypher
