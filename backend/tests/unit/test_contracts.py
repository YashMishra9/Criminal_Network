"""Unit tests for Task A3: Shared Contract Types.

Tests:
1. All models instantiate with valid example data drawn from DOC3 §1.
2. Field names, types, and nullability match DOC3 §1 exactly.
3. CanonicalEntity and EntityMention reject 'Case' as an entity_type.
4. Note rejects more than one non-null 'about_*' field.
"""

import pytest
from pydantic import ValidationError

from app.contracts.raw_record import AdapterDescriptor, RawRecord
from app.contracts.mention import EntityMention, RelationshipMention
from app.contracts.entity import CanonicalEntity
from app.contracts.relationship import Relationship
from app.contracts.evidence import Evidence
from app.contracts.resolution import ResolutionDecision
from app.contracts.finding import Finding, INVESTIGATIVE_LEAD_DISCLAIMER
from app.contracts.case import Case, Note, EdgeRef
from app.contracts.analytics import AnalyticsResult, CentralityEntry, CommunityEntry, ShortestPathResult
from app.contracts.errors import ErrorDetail, ErrorResponse


# ---------------------------------------------------------------------------
# §1.1 RawRecord
# ---------------------------------------------------------------------------

def test_raw_record_valid():
    r = RawRecord(
        record_id="fir_001",
        dataset="synthetic_demo",
        source_type="FIR",
        source_adapter_id="synthetic_v1",
        occurred_at="2024-01-15T10:00:00Z",
        ingested_at="2024-01-20T12:00:00Z",
        payload={"case_no": "123/2024", "accused": "R. Sharma"},
        payload_text="FIR Case 123/2024. Accused: R. Sharma",
    )
    assert r.record_id == "fir_001"
    assert r.dataset == "synthetic_demo"
    assert r.occurred_at == "2024-01-15T10:00:00Z"


def test_raw_record_nullable_fields():
    r = RawRecord(
        record_id="cdr_001",
        dataset="synthetic_demo",
        source_type="CDR",
        source_adapter_id="synthetic_v1",
        ingested_at="2024-01-20T12:00:00Z",
        payload={},
    )
    assert r.occurred_at is None
    assert r.payload_text is None


def test_raw_record_invalid_dataset():
    with pytest.raises(ValidationError):
        RawRecord(
            record_id="x",
            dataset="invalid_dataset",
            source_type="FIR",
            source_adapter_id="synthetic_v1",
            ingested_at="2024-01-20T12:00:00Z",
            payload={},
        )


# ---------------------------------------------------------------------------
# §1.2 AdapterDescriptor
# ---------------------------------------------------------------------------

def test_adapter_descriptor_batch():
    d = AdapterDescriptor(
        adapter_id="synthetic_v1",
        source_type="synthetic",
        dataset="synthetic_demo",
        mode="batch",
        enabled=True,
        poll_interval_seconds=None,
        last_run_status="never_run",
    )
    assert d.mode == "batch"
    assert d.poll_interval_seconds is None
    assert d.last_run_at is None


def test_adapter_descriptor_poll():
    d = AdapterDescriptor(
        adapter_id="rss_public_v1",
        source_type="rss",
        dataset="live_public",
        mode="poll",
        enabled=False,
        poll_interval_seconds=300,
        last_run_status="never_run",
    )
    assert d.mode == "poll"
    assert d.poll_interval_seconds == 300


# ---------------------------------------------------------------------------
# §1.3 EntityMention and RelationshipMention
# ---------------------------------------------------------------------------

def test_entity_mention_valid():
    m = EntityMention(
        mention_id="m_001",
        record_id="fir_001",
        dataset="synthetic_demo",
        entity_type="Person",
        raw_text="R. Sharma",
        normalized_value="Rahul Sharma",
        attributes={"dob": "1985-05-10"},
        extraction_method="spacy",
        confidence=0.92,
    )
    assert m.entity_type == "Person"
    assert m.extraction_method == "spacy"


def test_entity_mention_rejects_case_entity_type():
    """Contract Invariant 16: 'Case' must NOT be a valid entity_type."""
    with pytest.raises(ValidationError):
        EntityMention(
            mention_id="m_002",
            record_id="fir_001",
            dataset="synthetic_demo",
            entity_type="Case",  # MUST be rejected
            raw_text="Case #123",
            extraction_method="regex",
        )


def test_entity_mention_allows_transaction():
    """'Transaction' must be a valid entity_type per DOC3 §1.4 decision."""
    m = EntityMention(
        mention_id="m_003",
        record_id="txn_001",
        dataset="synthetic_demo",
        entity_type="Transaction",
        raw_text="TXN-20240115-001",
        extraction_method="regex",
    )
    assert m.entity_type == "Transaction"


def test_relationship_mention_valid():
    rm = RelationshipMention(
        relationship_mention_id="rm_001",
        record_id="cdr_001",
        dataset="synthetic_demo",
        relationship_type="CALLED",
        from_mention_id="m_001",
        to_mention_id="m_002",
        occurred_at="2024-01-15T09:00:00Z",
        attributes={"duration_seconds": 340},
        extraction_method="regex",
    )
    assert rm.relationship_type == "CALLED"


def test_relationship_mention_nullable_occurred_at():
    rm = RelationshipMention(
        relationship_mention_id="rm_002",
        record_id="cdr_001",
        dataset="synthetic_demo",
        relationship_type="MET",
        from_mention_id="m_001",
        to_mention_id="m_002",
        extraction_method="spacy",
    )
    assert rm.occurred_at is None


# ---------------------------------------------------------------------------
# §1.4 CanonicalEntity
# ---------------------------------------------------------------------------

def test_canonical_entity_valid():
    e = CanonicalEntity(
        entity_id="ent_001",
        entity_type="Person",
        dataset="synthetic_demo",
        display_name="Rahul Sharma",
        attributes={"aliases": ["R. Sharma", "Rahul S."]},
        resolved_from=["m_001", "m_005"],
        resolution_method="fuzzy_match",
        created_at="2024-01-20T12:00:00Z",
        updated_at="2024-01-20T12:00:00Z",
    )
    assert e.entity_id == "ent_001"
    assert "m_001" in e.resolved_from


def test_canonical_entity_rejects_case():
    """Contract Invariant 16: 'Case' must NOT be a valid entity_type."""
    with pytest.raises(ValidationError):
        CanonicalEntity(
            entity_id="ent_002",
            entity_type="Case",  # MUST be rejected
            dataset="synthetic_demo",
            display_name="Case #123",
            resolved_from=[],
            resolution_method="exact_match",
            created_at="2024-01-20T12:00:00Z",
            updated_at="2024-01-20T12:00:00Z",
        )


def test_canonical_entity_allows_transaction():
    e = CanonicalEntity(
        entity_id="ent_003",
        entity_type="Transaction",
        dataset="synthetic_demo",
        display_name="TXN-20240115-001",
        attributes={"amount": 50000, "currency": "INR"},
        resolved_from=["m_010"],
        resolution_method="exact_match",
        created_at="2024-01-20T12:00:00Z",
        updated_at="2024-01-20T12:00:00Z",
    )
    assert e.entity_type == "Transaction"


# ---------------------------------------------------------------------------
# §1.5 Relationship
# ---------------------------------------------------------------------------

def test_relationship_valid():
    r = Relationship(
        relationship_id="rel_001",
        relationship_type="CALLED",
        from_entity_id="ent_001",
        to_entity_id="ent_002",
        dataset="synthetic_demo",
        attributes={"duration_seconds": 340},
        valid_from="2024-01-15T09:00:00Z",
        valid_to=None,
        evidence_ids=["ev_001"],
        created_at="2024-01-20T12:00:00Z",
        updated_at="2024-01-20T12:00:00Z",
    )
    assert r.relationship_id == "rel_001"
    assert len(r.evidence_ids) == 1


def test_relationship_nullable_valid_to():
    r = Relationship(
        relationship_id="rel_002",
        relationship_type="OWNS",
        from_entity_id="ent_001",
        to_entity_id="ent_003",
        dataset="synthetic_demo",
        valid_from="2024-01-15T09:00:00Z",
        evidence_ids=["ev_002"],
        created_at="2024-01-20T12:00:00Z",
        updated_at="2024-01-20T12:00:00Z",
    )
    assert r.valid_to is None


# ---------------------------------------------------------------------------
# §1.6 Evidence
# ---------------------------------------------------------------------------

def test_evidence_valid():
    e = Evidence(
        evidence_id="ev_001",
        dataset="synthetic_demo",
        source_id="fir_001",
        source_type="FIR",
        record_timestamp="2024-01-15T10:00:00Z",
        ingested_at="2024-01-20T12:00:00Z",
        snippet="R. Sharma was accused in FIR 123/2024",
        pointer={"file": "fir/fir_001.json"},
    )
    assert e.evidence_id == "ev_001"
    assert e.source_id == "fir_001"


def test_evidence_nullable_fields():
    e = Evidence(
        evidence_id="ev_002",
        dataset="synthetic_demo",
        source_id="cdr_001",
        source_type="CDR",
        ingested_at="2024-01-20T12:00:00Z",
    )
    assert e.record_timestamp is None
    assert e.snippet is None
    assert e.pointer is None


# ---------------------------------------------------------------------------
# §1.7 ResolutionDecision
# ---------------------------------------------------------------------------

def test_resolution_decision_valid():
    d = ResolutionDecision(
        decision_id="dec_001",
        entity_id="ent_001",
        mention_ids=["m_001", "m_005"],
        source_record_ids=["fir_001", "police_report_002"],
        outcome="merged",
        method="fuzzy_match",
        matched_on=["name_similarity>0.85", "shared_phone"],
        score=0.91,
        decided_at="2024-01-20T12:00:00Z",
    )
    assert d.outcome == "merged"
    assert len(d.source_record_ids) == len(d.mention_ids)


def test_resolution_decision_rejected():
    d = ResolutionDecision(
        decision_id="dec_002",
        entity_id="ent_010",
        mention_ids=["m_020"],
        source_record_ids=["cdr_099"],
        outcome="rejected",
        method="exact_match",
        matched_on=[],
        decided_at="2024-01-20T12:00:00Z",
    )
    assert d.outcome == "rejected"
    assert d.score is None


# ---------------------------------------------------------------------------
# §1.8 Finding
# ---------------------------------------------------------------------------

def test_finding_valid():
    f = Finding(
        finding_id="find_001",
        dataset="synthetic_demo",
        rule_id="frequency_rule_v1",
        rule_name="High Call Frequency",
        subject_entity_ids=["ent_001", "ent_002"],
        subject_relationship_ids=["rel_001"],
        explanation="17 calls between these two numbers over 4 days, exceeding the 10-call/7-day threshold.",
        triggering_values={"call_count": 17, "threshold": 10},
        evidence_ids=["ev_001", "ev_002"],
        disclaimer="This is an investigative lead, not evidence of wrongdoing.",
        detected_at="2024-01-20T12:00:00Z",
    )
    assert f.disclaimer == INVESTIGATIVE_LEAD_DISCLAIMER
    assert len(f.evidence_ids) > 0


def test_finding_disclaimer_must_be_exact_literal():
    """Contract Invariant 5: disclaimer must equal the exact fixed literal."""
    with pytest.raises(ValidationError):
        Finding(
            finding_id="find_002",
            dataset="synthetic_demo",
            rule_id="bridge_entity_v1",
            rule_name="Bridge Entity",
            subject_entity_ids=["ent_003"],
            subject_relationship_ids=[],
            explanation="ent_003 connects two otherwise-disconnected communities.",
            triggering_values={},
            evidence_ids=["ev_003"],
            disclaimer="This is a lead.",  # MUST be rejected — not the exact literal
            detected_at="2024-01-20T12:00:00Z",
        )


# ---------------------------------------------------------------------------
# §1.9 Case
# ---------------------------------------------------------------------------

def test_case_valid():
    c = Case(
        case_id="case_001",
        title="Operation Falcon",
        status="open",
        dataset="synthetic_demo",
        created_at="2024-01-20T12:00:00Z",
        updated_at="2024-01-20T12:00:00Z",
    )
    assert c.status == "open"


def test_case_invalid_status():
    with pytest.raises(ValidationError):
        Case(
            case_id="case_002",
            title="Test",
            status="archived",  # MUST be rejected
            dataset="synthetic_demo",
            created_at="2024-01-20T12:00:00Z",
            updated_at="2024-01-20T12:00:00Z",
        )


# ---------------------------------------------------------------------------
# §1.10 Note
# ---------------------------------------------------------------------------

def test_note_general():
    n = Note(
        note_id="note_001",
        case_id="case_001",
        text="Sharma appears to be the central node in the network.",
        created_at="2024-01-21T09:00:00Z",
    )
    assert n.about_entity_id is None
    assert n.about_edge_ref_id is None


def test_note_about_entity():
    n = Note(
        note_id="note_002",
        case_id="case_001",
        text="Key suspect.",
        about_entity_id="ent_001",
        created_at="2024-01-21T09:00:00Z",
    )
    assert n.about_entity_id == "ent_001"


def test_note_rejects_multiple_about_fields():
    """DOC3 §1.10 invariant: at most one about_* field non-null."""
    with pytest.raises(ValidationError):
        Note(
            note_id="note_003",
            case_id="case_001",
            text="Ambiguous note.",
            about_entity_id="ent_001",
            about_evidence_id="ev_001",  # second non-null — MUST be rejected
            created_at="2024-01-21T09:00:00Z",
        )


# ---------------------------------------------------------------------------
# §1.11 EdgeRef
# ---------------------------------------------------------------------------

def test_edge_ref_valid():
    er = EdgeRef(
        edge_ref_id="er_001",
        relationship_id="rel_001",
        from_entity_id="ent_001",
        to_entity_id="ent_002",
        relationship_type="CALLED",
        created_at="2024-01-20T12:00:00Z",
    )
    assert er.relationship_id == "rel_001"


# ---------------------------------------------------------------------------
# §1.12 AnalyticsResult and ShortestPathResult
# ---------------------------------------------------------------------------

def test_analytics_result_valid():
    ar = AnalyticsResult(
        computed_at="2024-01-20T13:00:00Z",
        dataset="synthetic_demo",
        as_of=None,
        centrality=[
            CentralityEntry(entity_id="ent_001", degree=5.0, betweenness=0.42, pagerank=0.18),
        ],
        communities=[
            CommunityEntry(entity_id="ent_001", community_id="comm_1"),
        ],
    )
    assert ar.as_of is None
    assert ar.centrality[0].entity_id == "ent_001"


def test_shortest_path_result_found():
    sp = ShortestPathResult(
        found=True,
        path_entity_ids=["ent_001", "ent_003", "ent_002"],
        path_relationship_ids=["rel_010", "rel_011"],
    )
    assert sp.found is True


def test_shortest_path_result_not_found():
    sp = ShortestPathResult(found=False, path_entity_ids=[], path_relationship_ids=[])
    assert sp.found is False


# ---------------------------------------------------------------------------
# §13 ErrorResponse
# ---------------------------------------------------------------------------

def test_error_response_valid():
    er = ErrorResponse(
        error=ErrorDetail(type="not_found", message="Entity not found.", details=None)
    )
    assert er.error.type == "not_found"


def test_error_response_all_types():
    """Verify all six error.type values from DOC3 §13 are accepted."""
    valid_types = [
        "not_found",
        "validation_error",
        "llm_unavailable",
        "dataset_isolation_violation",
        "graph_unavailable",
        "internal_error",
    ]
    for t in valid_types:
        er = ErrorResponse(error=ErrorDetail(type=t, message="msg"))
        assert er.error.type == t


def test_error_response_invalid_type():
    with pytest.raises(ValidationError):
        ErrorResponse(error=ErrorDetail(type="unknown_type", message="msg"))
