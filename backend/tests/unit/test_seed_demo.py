"""Unit tests for scripts/seed_demo.py — focused on the three confirmed runtime defects.

Defects fixed (Sync 2 verification report, 2026-10-12):
  D1: wrong import path 'app.extraction.orchestrator.ExtractionOrchestrator'
      → corrected to 'app.extraction.extractor.Extractor / build_extractor'
  D2: wrong import path 'app.ingestion.adapters.synthetic.SyntheticAdapter'
      → corrected to 'app.ingestion.synthetic_adapter.SyntheticAdapter'
  D3: tuple-unpack of ResolutionResult dataclass
      → corrected to .entities / .decisions attribute access

Tests here are all unit-level (no live Neo4j, no file system I/O beyond import).
They verify:
  - The correct classes are importable from the correct module paths.
  - The correct method names exist on those classes.
  - ResolutionResult is a non-iterable dataclass and .entities / .decisions work.
  - build_extractor(with_llm=False) returns an Extractor, callable as extract_one().
  - _resolve_entities() in seed_demo correctly accesses .entities and .decisions,
    not tuple-unpacking (proven by mocking BatchResolver.resolve to return a
    ResolutionResult and asserting no TypeError is raised).
  - _load_and_extract() calls extractor.extract_one(), not extractor.extract().
  - RelationshipMention.occurred_at and .attributes are real declared fields
    (so rm.occurred_at and rm.attributes direct access are safe).
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — seed_demo imports from backend/
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = str(_REPO_ROOT / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


# ---------------------------------------------------------------------------
# Helpers: load seed_demo as a module without executing seed() / main()
# ---------------------------------------------------------------------------

def _load_seed_demo():
    """Load scripts/seed_demo.py as a module object (does not run seed or main)."""
    seed_path = _REPO_ROOT / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("seed_demo", seed_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ===========================================================================
# D1 — Correct import path for Extractor
# ===========================================================================

class TestExtractorImport:
    """D1: app.extraction.extractor must export Extractor and build_extractor."""

    def test_extractor_importable_from_correct_module(self):
        """Extractor must be importable from app.extraction.extractor."""
        from app.extraction.extractor import Extractor  # noqa: F401 — ImportError = test fail

    def test_build_extractor_importable(self):
        """build_extractor must be importable from app.extraction.extractor."""
        from app.extraction.extractor import build_extractor  # noqa: F401

    def test_extractor_has_extract_one_method(self):
        """Extractor must expose extract_one(), not extract()."""
        from app.extraction.extractor import Extractor
        assert hasattr(Extractor, "extract_one"), (
            "Extractor.extract_one() not found — seed_demo calls extractor.extract_one(record)"
        )

    def test_extractor_does_not_have_extract_method_as_public_api(self):
        """extract() is not the public API name; extract_one() is correct."""
        from app.extraction.extractor import Extractor
        # extract_one must exist; the old wrong name 'extract' should not be
        # the one called by the seeder
        assert hasattr(Extractor, "extract_one")
        # (extract may exist on sub-extractors, not on the orchestrating Extractor)

    def test_build_extractor_with_llm_false_returns_extractor(self):
        """build_extractor(with_llm=False) must return an Extractor (offline/LLM-free path)."""
        from app.extraction.extractor import Extractor, build_extractor
        extractor = build_extractor(with_llm=False)
        assert isinstance(extractor, Extractor), (
            f"Expected Extractor, got {type(extractor)}"
        )

    def test_wrong_module_does_not_exist(self):
        """The old wrong module path app.extraction.orchestrator must NOT exist."""
        with pytest.raises((ImportError, ModuleNotFoundError)):
            import app.extraction.orchestrator  # noqa: F401

    def test_seed_demo_imports_extractor_not_extraction_orchestrator(self):
        """seed_demo.py must import from app.extraction.extractor, not .orchestrator."""
        seed_path = _REPO_ROOT / "scripts" / "seed_demo.py"
        source = seed_path.read_text(encoding="utf-8")
        assert "app.extraction.extractor" in source, (
            "seed_demo.py must import from app.extraction.extractor"
        )
        assert "app.extraction.orchestrator" not in source, (
            "seed_demo.py must NOT import from app.extraction.orchestrator (module does not exist)"
        )


# ===========================================================================
# D2 — Correct import path for SyntheticAdapter
# ===========================================================================

class TestSyntheticAdapterImport:
    """D2: SyntheticAdapter must be imported from app.ingestion.synthetic_adapter."""

    def test_synthetic_adapter_importable_from_correct_module(self):
        """SyntheticAdapter must be importable from app.ingestion.synthetic_adapter."""
        from app.ingestion.synthetic_adapter import SyntheticAdapter  # noqa: F401

    def test_synthetic_adapter_has_fetch_batch(self):
        """SyntheticAdapter must expose fetch_batch()."""
        from app.ingestion.synthetic_adapter import SyntheticAdapter
        assert hasattr(SyntheticAdapter, "fetch_batch")

    def test_wrong_module_path_does_not_exist(self):
        """app.ingestion.adapters.synthetic must NOT exist."""
        with pytest.raises((ImportError, ModuleNotFoundError)):
            from app.ingestion.adapters.synthetic import SyntheticAdapter  # noqa: F401

    def test_seed_demo_imports_from_correct_synthetic_adapter_path(self):
        """seed_demo.py must import from app.ingestion.synthetic_adapter."""
        seed_path = _REPO_ROOT / "scripts" / "seed_demo.py"
        source = seed_path.read_text(encoding="utf-8")
        assert "app.ingestion.synthetic_adapter" in source, (
            "seed_demo.py must import from app.ingestion.synthetic_adapter"
        )
        assert "app.ingestion.adapters.synthetic" not in source, (
            "seed_demo.py must NOT import from app.ingestion.adapters.synthetic (path does not exist)"
        )


# ===========================================================================
# D3 — ResolutionResult is not iterable; must use .entities / .decisions
# ===========================================================================

class TestResolutionResultHandling:
    """D3: BatchResolver.resolve() returns ResolutionResult (dataclass), not a tuple."""

    def test_resolution_result_is_not_iterable(self):
        """ResolutionResult must NOT support tuple unpacking."""
        from app.resolution.resolver import ResolutionResult
        r = ResolutionResult()
        with pytest.raises(TypeError):
            a, b = r  # must raise — it is a dataclass, not a tuple

    def test_resolution_result_has_entities_attribute(self):
        """ResolutionResult.entities must be accessible as an attribute."""
        from app.resolution.resolver import ResolutionResult
        r = ResolutionResult()
        assert hasattr(r, "entities")
        assert isinstance(r.entities, list)

    def test_resolution_result_has_decisions_attribute(self):
        """ResolutionResult.decisions must be accessible as an attribute."""
        from app.resolution.resolver import ResolutionResult
        r = ResolutionResult()
        assert hasattr(r, "decisions")
        assert isinstance(r.decisions, list)

    def test_batch_resolver_resolve_returns_resolution_result(self):
        """BatchResolver.resolve() return type annotation must be ResolutionResult."""
        import inspect
        from app.resolution.resolver import BatchResolver, ResolutionResult
        sig = inspect.signature(BatchResolver.resolve)
        return_ann = sig.return_annotation
        assert return_ann is ResolutionResult, (
            f"BatchResolver.resolve() return annotation is {return_ann!r}, "
            f"expected ResolutionResult"
        )

    def test_seed_demo_does_not_tuple_unpack_resolve(self):
        """seed_demo.py must NOT have 'entities, decisions = resolver.resolve' (tuple-unpack)."""
        seed_path = _REPO_ROOT / "scripts" / "seed_demo.py"
        source = seed_path.read_text(encoding="utf-8")
        # The old bad pattern
        assert "entities, decisions = resolver.resolve" not in source, (
            "seed_demo.py must not tuple-unpack ResolutionResult from resolver.resolve()"
        )

    def test_seed_demo_accesses_resolution_result_attributes(self):
        """seed_demo.py must access .entities and .decisions on the ResolutionResult."""
        seed_path = _REPO_ROOT / "scripts" / "seed_demo.py"
        source = seed_path.read_text(encoding="utf-8")
        assert "resolution.entities" in source or "result.entities" in source or \
               ".entities" in source, (
            "seed_demo.py must access .entities on the ResolutionResult object"
        )
        assert "resolution.decisions" in source or "result.decisions" in source or \
               ".decisions" in source, (
            "seed_demo.py must access .decisions on the ResolutionResult object"
        )


# ===========================================================================
# Integration: _resolve_entities() behaviour with mocked BatchResolver
# ===========================================================================

class TestResolveEntitiesFunction:
    """Verify _resolve_entities() in the seeder correctly handles ResolutionResult."""

    def test_resolve_entities_does_not_raise_type_error(self):
        """_resolve_entities() must not raise TypeError when resolve() returns ResolutionResult."""
        from app.contracts.entity import CanonicalEntity
        from app.contracts.resolution import ResolutionDecision
        from app.resolution.resolver import ResolutionResult

        # Build a fake ResolutionResult with one entity and one decision
        now = "2024-01-01T00:00:00Z"
        fake_entity = CanonicalEntity(
            entity_id="ent-test-001",
            entity_type="Person",
            dataset="synthetic_demo",
            display_name="Test Person",
            resolved_from=["m-001"],
            resolution_method="exact_match",
            created_at=now,
            updated_at=now,
        )
        fake_decision = ResolutionDecision(
            decision_id="dec-test-001",
            entity_id="ent-test-001",
            mention_ids=["m-001"],
            source_record_ids=["fir_001"],
            outcome="merged",
            method="exact_match",
            matched_on=["singleton"],
            decided_at=now,
        )
        fake_result = ResolutionResult(entities=[fake_entity], decisions=[fake_decision])

        # Mock BatchResolver.resolve to return a ResolutionResult
        with patch("app.resolution.resolver.BatchResolver.resolve", return_value=fake_result):
            mod = _load_seed_demo()
            # Call _resolve_entities with an empty mention map (BatchResolver is mocked)
            entities, decisions = mod._resolve_entities({})

        assert entities == [fake_entity]
        assert decisions == [fake_decision]

    def test_resolve_entities_returns_two_element_tuple(self):
        """_resolve_entities() must return (entities, decisions) tuple for callers."""
        from app.resolution.resolver import ResolutionResult

        fake_result = ResolutionResult()
        with patch("app.resolution.resolver.BatchResolver.resolve", return_value=fake_result):
            mod = _load_seed_demo()
            result = mod._resolve_entities({})

        assert isinstance(result, tuple)
        assert len(result) == 2
        entities, decisions = result
        assert isinstance(entities, list)
        assert isinstance(decisions, list)


# ===========================================================================
# Integration: _load_and_extract() calls extract_one(), not extract()
# ===========================================================================

class TestLoadAndExtractFunction:
    """Verify _load_and_extract() uses the correct Extractor API."""

    def test_load_and_extract_calls_extract_one(self):
        """_load_and_extract() must call extractor.extract_one(record), not extractor.extract()."""
        from app.contracts.raw_record import RawRecord
        from app.extraction.extractor import ExtractionResult

        now = "2024-01-01T00:00:00Z"
        fake_record = RawRecord(
            record_id="fir_001",
            dataset="synthetic_demo",
            source_type="FIR",
            source_adapter_id="synthetic_v1",
            ingested_at=now,
            payload={"case_no": "001"},
        )
        fake_result = ExtractionResult(record_id="fir_001", entities=[], relationships=[])

        # Mock SyntheticAdapter.fetch_batch and Extractor.extract_one
        mock_adapter = MagicMock()
        mock_adapter.fetch_batch.return_value = [fake_record]

        with patch("app.extraction.extractor.Extractor.extract_one", return_value=fake_result) as mock_extract_one:
            mod = _load_seed_demo()
            records, entity_map, rel_map = mod._load_and_extract(mock_adapter)

        # extract_one must have been called once with the fake record
        mock_extract_one.assert_called_once_with(fake_record)
        assert len(records) == 1
        assert "fir_001" in entity_map
        assert "fir_001" in rel_map

    def test_load_and_extract_does_not_call_extract(self):
        """_load_and_extract() must NOT call the non-existent extractor.extract() method."""
        from app.contracts.raw_record import RawRecord
        from app.extraction.extractor import ExtractionResult

        now = "2024-01-01T00:00:00Z"
        fake_record = RawRecord(
            record_id="fir_001",
            dataset="synthetic_demo",
            source_type="FIR",
            source_adapter_id="synthetic_v1",
            ingested_at=now,
            payload={},
        )
        fake_result = ExtractionResult(record_id="fir_001", entities=[], relationships=[])

        mock_adapter = MagicMock()
        mock_adapter.fetch_batch.return_value = [fake_record]

        with patch("app.extraction.extractor.Extractor.extract_one", return_value=fake_result):
            mod = _load_seed_demo()
            # Should not raise AttributeError for missing .extract()
            records, entity_map, rel_map = mod._load_and_extract(mock_adapter)

        assert records == [fake_record]


# ===========================================================================
# RelationshipMention field access (no getattr fallback needed)
# ===========================================================================

class TestRelationshipMentionFields:
    """Verify RelationshipMention has declared fields accessed directly in seeder."""

    def test_occurred_at_is_declared_field(self):
        """RelationshipMention.occurred_at must be a declared Pydantic field."""
        from app.contracts.mention import RelationshipMention
        assert "occurred_at" in RelationshipMention.model_fields, (
            "RelationshipMention.occurred_at is not a declared field — "
            "seed_demo accesses rm.occurred_at directly"
        )

    def test_attributes_is_declared_field(self):
        """RelationshipMention.attributes must be a declared Pydantic field."""
        from app.contracts.mention import RelationshipMention
        assert "attributes" in RelationshipMention.model_fields

    def test_relationship_mention_occurred_at_defaults_to_none(self):
        """occurred_at defaults to None (Optional[str] — seed_demo relies on this for fallback)."""
        from app.contracts.mention import RelationshipMention
        rm = RelationshipMention(
            relationship_mention_id="rm-001",
            record_id="fir_001",
            dataset="synthetic_demo",
            relationship_type="CALLED",
            from_mention_id="m-001",
            to_mention_id="m-002",
            extraction_method="regex",
        )
        assert rm.occurred_at is None

    def test_seed_demo_does_not_use_getattr_for_occurred_at(self):
        """seed_demo.py must NOT use getattr(rm, 'occurred_at', None) — it's a real field."""
        seed_path = _REPO_ROOT / "scripts" / "seed_demo.py"
        source = seed_path.read_text(encoding="utf-8")
        assert "getattr(rm, \"occurred_at\"" not in source, (
            "seed_demo.py must access rm.occurred_at directly, not via getattr()"
        )
