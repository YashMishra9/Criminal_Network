"""Unit tests for Task B5: Entity/Relationship Extraction (spaCy + regex).

Tests (per B5 §13):
  - Unit tests per source_type fixture, verifying correct entity/relationship
    extraction and provenance field propagation (record_id, dataset).
  - Acceptance criteria (B5 §12): given fixture RawRecords, produces valid
    mentions with correct record_id/dataset propagation for every source type.
  - Contract Invariant 4: full pipeline works with LLM entirely disabled.
  - Contract Invariant 16: 'Case' never appears as entity_type.
  - DOC3 §4: entity_type values match exactly the §1.3 enum.
  - DOC3 §4: relationship mentions only reference mention_ids within the
    same ExtractionResult.
"""

from typing import Any, Dict, List, Optional

import pytest

from app.contracts.mention import EntityMention, RelationshipMention
from app.contracts.raw_record import RawRecord
from app.extraction.extractor import ExtractionResult, Extractor
from app.extraction.regex_extractor import RegexExtractor
from app.extraction.spacy_extractor import SpacyExtractor

# ---------------------------------------------------------------------------
# Valid DOC3 §1.3 entity types (Case is excluded per Invariant 16)
# ---------------------------------------------------------------------------
VALID_ENTITY_TYPES = {
    "Person", "Phone", "Vehicle", "Location",
    "Organization", "BankAccount", "Transaction", "Event",
}

VALID_RELATIONSHIP_TYPES = {
    "CALLED", "OWNS", "USED", "TRANSFERRED", "VISITED",
    "MET", "WORKS_FOR", "ASSOCIATED_WITH", "MENTIONED_IN", "PART_OF",
}

VALID_EXTRACTION_METHODS = {"spacy", "regex", "llm"}


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_record(
    record_id: str,
    source_type: str,
    payload: Dict[str, Any],
    payload_text: str,
    dataset: str = "synthetic_demo",
    occurred_at: str = "2024-01-01T00:00:00Z",
) -> RawRecord:
    return RawRecord(
        record_id=record_id,
        dataset=dataset,
        source_type=source_type,
        source_adapter_id="synthetic_v1",
        occurred_at=occurred_at,
        ingested_at="2024-01-01T12:00:00Z",
        payload=payload,
        payload_text=payload_text,
    )


# ---------------------------------------------------------------------------
# Per-source-type fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cdr_record():
    return _make_record(
        "cdr_001", "CDR",
        payload={
            "caller": "9876543210",
            "callee": "9988776655",
            "duration_seconds": 145,
            "call_type": "voice",
        },
        payload_text="CDR call from 9876543210 to 9988776655 duration 145s voice",
    )


@pytest.fixture
def transaction_record():
    return _make_record(
        "txn_001", "transaction",
        payload={
            "from_account": "SBI-CORP-9012",
            "to_account": "SBI-SAVE-5678",
            "from_account_holder": "Khanna Enterprises Pvt Ltd",
            "to_account_holder": "Priya Mehta",
            "amount": 800000,
            "currency": "INR",
            "transaction_type": "NEFT",
        },
        payload_text="NEFT transfer INR 800000 from SBI-CORP-9012 (Khanna Enterprises Pvt Ltd) to SBI-SAVE-5678 (Priya Mehta)",
    )


@pytest.fixture
def vehicle_record():
    return _make_record(
        "veh_001", "vehicle_registry",
        payload={
            "registration_number": "MH-01-AB-1234",
            "registered_owner": "Rahul Sharma",
            "make": "Honda",
            "model": "City",
            "color": "White",
        },
        payload_text="Vehicle MH-01-AB-1234 registered to Rahul Sharma Honda City White",
    )


@pytest.fixture
def fir_record():
    return _make_record(
        "fir_001", "FIR",
        payload={
            "fir_number": "FIR/2024/001",
            "accused": [
                {"name": "Rahul Sharma", "alias": "R. Sharma"},
                {"name": "Priya Mehta", "alias": None},
            ],
            "organizations_involved": ["Khanna Enterprises Pvt Ltd"],
            "complainant_name": "Anita Verma",
        },
        payload_text="FIR filed against Rahul Sharma and Priya Mehta related to Khanna Enterprises Pvt Ltd. Complainant: Anita Verma.",
    )


@pytest.fixture
def police_report_record():
    return _make_record(
        "pr_001", "police_report",
        payload={
            "report_number": "PR/AE/2024/012",
            "suspects": [{"name": "R. Sharma"}, {"name": "Priya M."}],
            "organizations_involved": ["Khanna Enterprises Pvt Ltd"],
            "known_associates": [{"name": "D. Khanna"}],
        },
        payload_text="Police report: suspects R. Sharma, Priya M. associated with Khanna Enterprises Pvt Ltd. Known associate D. Khanna.",
    )


@pytest.fixture
def surveillance_record():
    return _make_record(
        "surv_001", "surveillance",
        payload={
            "observation_id": "surv_001",
            "persons_observed": [
                {"name": "R. Sharma"},
                {"name": "D. Khanna"},
            ],
            "location": "Hotel Sunrise, Bandra, Mumbai",
            "vehicles_observed": ["MH-01-AB-1234"],
        },
        payload_text="Surveillance: R. Sharma and D. Khanna observed at Hotel Sunrise Bandra Mumbai. Vehicle MH-01-AB-1234 present.",
    )


@pytest.fixture
def social_media_record():
    return _make_record(
        "sm_001", "social_media",
        payload={
            "platform": "LinkedIn",
            "account_name": "khanna_enterprises",
            "display_name": "Khanna Enterprises Pvt Ltd",
            "post_text": "We signed an MoU with Global Trading FZE today.",
        },
        payload_text="Khanna Enterprises Pvt Ltd signed an MoU with Global Trading FZE.",
    )


@pytest.fixture
def rss_record():
    return _make_record(
        "rss_abc123", "rss",
        payload={
            "title": "Government announces new trade policy",
            "link": "https://example.com/news/1",
            "description": "The Finance Minister announced a new policy today.",
        },
        payload_text="Government announces new trade policy. The Finance Minister announced a new policy today.",
        dataset="live_public",
    )


@pytest.fixture
def extractor():
    return Extractor(llm_extractor=None)


@pytest.fixture
def regex():
    return RegexExtractor()


# ===========================================================================
# DOC3 §4 provenance invariant helpers
# ===========================================================================

def _assert_provenance(entities: List[EntityMention], record: RawRecord) -> None:
    """Every mention must carry record_id and dataset from the input record."""
    for em in entities:
        assert em.record_id == record.record_id, (
            f"Mention {em.mention_id}: record_id={em.record_id!r} != {record.record_id!r}"
        )
        assert em.dataset == record.dataset, (
            f"Mention {em.mention_id}: dataset={em.dataset!r} != {record.dataset!r}"
        )


def _assert_rel_provenance(rels: List[RelationshipMention], record: RawRecord) -> None:
    for rm in rels:
        assert rm.record_id == record.record_id
        assert rm.dataset == record.dataset


def _assert_rel_mention_ids_exist(rels: List[RelationshipMention], entities: List[EntityMention]) -> None:
    """DOC3 §4: relationship mentions may only reference mention_ids in same ExtractionResult."""
    mention_ids = {em.mention_id for em in entities}
    for rm in rels:
        assert rm.from_mention_id in mention_ids, (
            f"from_mention_id {rm.from_mention_id!r} not in entities"
        )
        assert rm.to_mention_id in mention_ids, (
            f"to_mention_id {rm.to_mention_id!r} not in entities"
        )


def _assert_no_case_entity_type(entities: List[EntityMention]) -> None:
    """Contract Invariant 16: 'Case' must never appear as entity_type."""
    for em in entities:
        assert em.entity_type != "Case", (
            f"Invariant 16 violated: entity_type='Case' on mention {em.mention_id}"
        )


def _assert_valid_entity_types(entities: List[EntityMention]) -> None:
    for em in entities:
        assert em.entity_type in VALID_ENTITY_TYPES, (
            f"Invalid entity_type '{em.entity_type}' on mention {em.mention_id}"
        )


def _assert_valid_rel_types(rels: List[RelationshipMention]) -> None:
    for rm in rels:
        assert rm.relationship_type in VALID_RELATIONSHIP_TYPES, (
            f"Invalid relationship_type '{rm.relationship_type}'"
        )


# ===========================================================================
# ExtractionResult shape
# ===========================================================================

def test_extraction_result_has_correct_record_id(extractor, cdr_record):
    result = extractor.extract_one(cdr_record)
    assert isinstance(result, ExtractionResult)
    assert result.record_id == cdr_record.record_id


def test_extraction_result_has_lists(extractor, cdr_record):
    result = extractor.extract_one(cdr_record)
    assert isinstance(result.entities, list)
    assert isinstance(result.relationships, list)


# ===========================================================================
# CDR source type
# ===========================================================================

def test_cdr_extracts_two_phone_mentions(regex, cdr_record):
    entities, _ = regex.extract(cdr_record)
    phones = [e for e in entities if e.entity_type == "Phone"]
    assert len(phones) >= 2


def test_cdr_extracts_called_relationship(regex, cdr_record):
    entities, rels = regex.extract(cdr_record)
    called = [r for r in rels if r.relationship_type == "CALLED"]
    assert len(called) == 1


def test_cdr_called_rel_has_correct_attributes(regex, cdr_record):
    _, rels = regex.extract(cdr_record)
    rel = next(r for r in rels if r.relationship_type == "CALLED")
    assert rel.attributes.get("duration_seconds") == 145


def test_cdr_phone_normalized_values(regex, cdr_record):
    entities, _ = regex.extract(cdr_record)
    phones = [e for e in entities if e.entity_type == "Phone"]
    normalized = {e.normalized_value for e in phones}
    assert "9876543210" in normalized
    assert "9988776655" in normalized


def test_cdr_provenance(regex, cdr_record):
    entities, rels = regex.extract(cdr_record)
    _assert_provenance(entities, cdr_record)
    _assert_rel_provenance(rels, cdr_record)
    _assert_rel_mention_ids_exist(rels, entities)


# ===========================================================================
# Transaction source type
# ===========================================================================

def test_transaction_extracts_transaction_mention(regex, transaction_record):
    entities, _ = regex.extract(transaction_record)
    txn = [e for e in entities if e.entity_type == "Transaction"]
    assert len(txn) == 1
    assert txn[0].normalized_value == transaction_record.record_id


def test_transaction_extracts_bank_accounts(regex, transaction_record):
    entities, _ = regex.extract(transaction_record)
    accounts = [e for e in entities if e.entity_type == "BankAccount"]
    assert len(accounts) == 2
    raw_values = {e.raw_text for e in accounts}
    assert "SBI-CORP-9012" in raw_values
    assert "SBI-SAVE-5678" in raw_values


def test_transaction_extracts_transferred_relationship(regex, transaction_record):
    entities, rels = regex.extract(transaction_record)
    transferred = [r for r in rels if r.relationship_type == "TRANSFERRED"]
    assert len(transferred) == 1
    rel = transferred[0]
    assert rel.attributes.get("amount") == 800000
    assert rel.attributes.get("currency") == "INR"


def test_transaction_provenance(regex, transaction_record):
    entities, rels = regex.extract(transaction_record)
    _assert_provenance(entities, transaction_record)
    _assert_rel_provenance(rels, transaction_record)
    _assert_rel_mention_ids_exist(rels, entities)


# ===========================================================================
# Vehicle registry source type
# ===========================================================================

def test_vehicle_extracts_vehicle_mention(regex, vehicle_record):
    entities, _ = regex.extract(vehicle_record)
    vehicles = [e for e in entities if e.entity_type == "Vehicle"]
    assert len(vehicles) == 1
    assert "MH01AB1234" in vehicles[0].normalized_value


def test_vehicle_extracts_owner_person(regex, vehicle_record):
    entities, _ = regex.extract(vehicle_record)
    persons = [e for e in entities if e.entity_type == "Person"]
    assert len(persons) == 1
    assert persons[0].raw_text == "Rahul Sharma"


def test_vehicle_extracts_owns_relationship(regex, vehicle_record):
    entities, rels = regex.extract(vehicle_record)
    owns = [r for r in rels if r.relationship_type == "OWNS"]
    assert len(owns) == 1


def test_vehicle_provenance(regex, vehicle_record):
    entities, rels = regex.extract(vehicle_record)
    _assert_provenance(entities, vehicle_record)
    _assert_rel_provenance(rels, vehicle_record)
    _assert_rel_mention_ids_exist(rels, entities)


# ===========================================================================
# FIR source type
# ===========================================================================

def test_fir_extracts_accused_persons(regex, fir_record):
    entities, _ = regex.extract(fir_record)
    persons = [e for e in entities if e.entity_type == "Person"]
    names = {e.raw_text for e in persons}
    assert "Rahul Sharma" in names
    assert "Priya Mehta" in names


def test_fir_extracts_organization(regex, fir_record):
    entities, _ = regex.extract(fir_record)
    orgs = [e for e in entities if e.entity_type == "Organization"]
    assert any("Khanna Enterprises" in e.raw_text for e in orgs)


def test_fir_extracts_works_for_relationship(regex, fir_record):
    entities, rels = regex.extract(fir_record)
    works_for = [r for r in rels if r.relationship_type == "WORKS_FOR"]
    assert len(works_for) >= 1


def test_fir_provenance(regex, fir_record):
    entities, rels = regex.extract(fir_record)
    _assert_provenance(entities, fir_record)
    _assert_rel_provenance(rels, fir_record)
    _assert_rel_mention_ids_exist(rels, entities)


# ===========================================================================
# Police report source type
# ===========================================================================

def test_police_report_extracts_suspects(regex, police_report_record):
    entities, _ = regex.extract(police_report_record)
    persons = [e for e in entities if e.entity_type == "Person"]
    names = {e.raw_text for e in persons}
    assert "R. Sharma" in names or "Priya M." in names


def test_police_report_extracts_organization(regex, police_report_record):
    entities, _ = regex.extract(police_report_record)
    orgs = [e for e in entities if e.entity_type == "Organization"]
    assert len(orgs) >= 1


def test_police_report_provenance(regex, police_report_record):
    entities, rels = regex.extract(police_report_record)
    _assert_provenance(entities, police_report_record)
    _assert_rel_mention_ids_exist(rels, entities)


# ===========================================================================
# Surveillance source type
# ===========================================================================

def test_surveillance_extracts_persons(regex, surveillance_record):
    entities, _ = regex.extract(surveillance_record)
    persons = [e for e in entities if e.entity_type == "Person"]
    assert len(persons) >= 2


def test_surveillance_extracts_location(regex, surveillance_record):
    entities, _ = regex.extract(surveillance_record)
    locs = [e for e in entities if e.entity_type == "Location"]
    assert len(locs) >= 1
    assert "Hotel Sunrise" in locs[0].raw_text


def test_surveillance_extracts_visited_relationship(regex, surveillance_record):
    entities, rels = regex.extract(surveillance_record)
    visited = [r for r in rels if r.relationship_type == "VISITED"]
    assert len(visited) >= 1


def test_surveillance_extracts_met_relationship(regex, surveillance_record):
    entities, rels = regex.extract(surveillance_record)
    met = [r for r in rels if r.relationship_type == "MET"]
    assert len(met) >= 1  # 2 persons → 1 MET edge


def test_surveillance_provenance(regex, surveillance_record):
    entities, rels = regex.extract(surveillance_record)
    _assert_provenance(entities, surveillance_record)
    _assert_rel_provenance(rels, surveillance_record)
    _assert_rel_mention_ids_exist(rels, entities)


# ===========================================================================
# Social media source type
# ===========================================================================

def test_social_media_extracts_org(regex, social_media_record):
    entities, _ = regex.extract(social_media_record)
    orgs = [e for e in entities if e.entity_type == "Organization"]
    assert len(orgs) >= 1
    assert "Khanna Enterprises" in orgs[0].raw_text


def test_social_media_provenance(regex, social_media_record):
    entities, rels = regex.extract(social_media_record)
    _assert_provenance(entities, social_media_record)


# ===========================================================================
# Live_public dataset propagation (RSS)
# ===========================================================================

def test_live_public_dataset_propagated(extractor, rss_record):
    result = extractor.extract_one(rss_record)
    for em in result.entities:
        assert em.dataset == "live_public", f"Expected live_public, got {em.dataset!r}"


# ===========================================================================
# Contract Invariants (all source types)
# ===========================================================================

@pytest.mark.parametrize("fixture_name", [
    "cdr_record", "transaction_record", "vehicle_record",
    "fir_record", "police_report_record", "surveillance_record",
    "social_media_record",
])
def test_no_case_entity_type(fixture_name, request, regex):
    record = request.getfixturevalue(fixture_name)
    entities, _ = regex.extract(record)
    _assert_no_case_entity_type(entities)


@pytest.mark.parametrize("fixture_name", [
    "cdr_record", "transaction_record", "vehicle_record",
    "fir_record", "police_report_record", "surveillance_record",
    "social_media_record",
])
def test_valid_entity_types(fixture_name, request, regex):
    record = request.getfixturevalue(fixture_name)
    entities, _ = regex.extract(record)
    _assert_valid_entity_types(entities)


@pytest.mark.parametrize("fixture_name", [
    "cdr_record", "transaction_record", "vehicle_record",
    "fir_record", "surveillance_record",
])
def test_valid_relationship_types(fixture_name, request, regex):
    record = request.getfixturevalue(fixture_name)
    _, rels = regex.extract(record)
    _assert_valid_rel_types(rels)


@pytest.mark.parametrize("fixture_name", [
    "cdr_record", "transaction_record", "vehicle_record",
    "fir_record", "police_report_record", "surveillance_record",
    "social_media_record",
])
def test_all_mentions_have_extraction_method(fixture_name, request, regex):
    record = request.getfixturevalue(fixture_name)
    entities, rels = regex.extract(record)
    for em in entities:
        assert em.extraction_method in VALID_EXTRACTION_METHODS
    for rm in rels:
        assert rm.extraction_method in VALID_EXTRACTION_METHODS


# ===========================================================================
# Contract Invariant 4: pipeline works without LLM
# ===========================================================================

def test_extractor_works_without_llm(extractor, fir_record):
    """Contract Invariant 4: no LLM needed for core extraction."""
    assert extractor._llm is None
    result = extractor.extract_one(fir_record)
    assert isinstance(result, ExtractionResult)
    assert len(result.entities) > 0


def test_extractor_llm_failure_does_not_block(fir_record):
    """If LLM extractor raises, extraction still completes and returns results."""
    class _FailingLLM:
        def extract(self, record, existing):
            raise RuntimeError("LLM unavailable")

    extractor = Extractor(llm_extractor=_FailingLLM())
    result = extractor.extract_one(fir_record)  # must not raise
    assert isinstance(result, ExtractionResult)
    assert len(result.entities) > 0  # regex path still produced results


# ===========================================================================
# spaCy extractor — graceful degradation
# ===========================================================================

def test_spacy_extractor_returns_list(fir_record):
    """SpacyExtractor always returns a list — never raises."""
    spacy_ext = SpacyExtractor()
    entities, rels = spacy_ext.extract(fir_record)
    assert isinstance(entities, list)
    assert isinstance(rels, list)  # always empty for spaCy


def test_spacy_extraction_method_tag(fir_record):
    """All spaCy mentions must be tagged extraction_method='spacy'."""
    spacy_ext = SpacyExtractor()
    entities, _ = spacy_ext.extract(fir_record)
    for em in entities:
        assert em.extraction_method == "spacy"


def test_spacy_provenance_propagated(fir_record):
    """SpacyExtractor must propagate record_id and dataset from the input record."""
    spacy_ext = SpacyExtractor()
    entities, _ = spacy_ext.extract(fir_record)
    _assert_provenance(entities, fir_record)


def test_spacy_no_case_entity_type(fir_record):
    spacy_ext = SpacyExtractor()
    entities, _ = spacy_ext.extract(fir_record)
    _assert_no_case_entity_type(entities)


def test_spacy_empty_payload_text_returns_empty():
    record = _make_record("empty_001", "FIR", {}, "")
    spacy_ext = SpacyExtractor()
    entities, rels = spacy_ext.extract(record)
    assert entities == []
    assert rels == []


# ===========================================================================
# Extractor.extract_batch
# ===========================================================================

def test_extract_batch_returns_one_result_per_record(extractor, cdr_record, vehicle_record):
    results = extractor.extract_batch([cdr_record, vehicle_record])
    assert len(results) == 2
    record_ids = {r.record_id for r in results}
    assert cdr_record.record_id in record_ids
    assert vehicle_record.record_id in record_ids


def test_extract_batch_empty_list(extractor):
    results = extractor.extract_batch([])
    assert results == []


# ===========================================================================
# Deduplication: regex + spaCy don't double-produce the same entity
# ===========================================================================

def test_deduplication_prevents_duplicate_entity_types(extractor, fir_record):
    """If regex and spaCy both find 'Rahul Sharma' as Person, only one is kept."""
    result = extractor.extract_one(fir_record)
    # Collect (entity_type, raw_text.lower()) tuples
    keys = [(e.entity_type, e.raw_text.lower()) for e in result.entities]
    assert len(keys) == len(set(keys)), (
        f"Duplicate (entity_type, raw_text) found: {keys}"
    )


# ===========================================================================
# Full-pipeline integration against H1 dataset
# ===========================================================================

def test_full_pipeline_on_h1_synthetic_dataset():
    """Integration: run Extractor over all 31 H1 records; verify no crash and provenance."""
    from pathlib import Path
    from app.ingestion.synthetic_adapter import SyntheticAdapter

    repo_root = Path(__file__).resolve().parents[3]
    adapter = SyntheticAdapter(base_path=repo_root / "data" / "synthetic")
    records = adapter.fetch_batch()
    assert len(records) == 31

    extractor = Extractor(llm_extractor=None)
    results = extractor.extract_batch(records)

    assert len(results) == 31

    total_entities = sum(len(r.entities) for r in results)
    total_rels = sum(len(r.relationships) for r in results)
    assert total_entities > 0
    assert total_rels > 0

    for result in results:
        record = next(rec for rec in records if rec.record_id == result.record_id)
        _assert_provenance(result.entities, record)
        _assert_rel_provenance(result.relationships, record)
        _assert_rel_mention_ids_exist(result.relationships, result.entities)
        _assert_no_case_entity_type(result.entities)
        _assert_valid_entity_types(result.entities)
        _assert_valid_rel_types(result.relationships)
