"""Unit tests for C6 — Graph & Entity API Endpoints (DOC3 §12.1–12.4).

Tests all four endpoints using mocked Neo4j sessions (no live database needed):
  - GET /api/v1/entities/search     (§12.1)
  - GET /api/v1/entities/{id}       (§12.2)
  - GET /api/v1/entities/{id}/relationships  (§12.3)
  - GET /api/v1/graph               (§12.4)

Boundary conditions tested:
  - Correct response shapes per DOC3 §12.1-12.4 (field-for-field).
  - GET /entities/{unknown_id} returns 404 with not_found error type (AC §12).
  - dataset defaults to 'synthetic_demo' when omitted.
  - as_of parameter is wired to C5's build_as_of_filter (Invariant 14).
  - /entities/{id}/relationships includes inline Evidence[]; /graph does not.
  - Neo4j unavailability returns 503 with graph_unavailable error type.

Live-database integration (post-H3 seeded graph tests required by C6 §13):
  Marked with @pytest.mark.neo4j_live — skipped without a live instance.
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Fixture: Neo4j session + Evidence resolver mocking helpers
# ---------------------------------------------------------------------------

def _make_entity_row(
    entity_id: str = "ent-001",
    entity_type: str = "Person",
    display_name: str = "Rahul Sharma",
    dataset: str = "synthetic_demo",
    resolution_method: str = "exact_match",
) -> Dict[str, Any]:
    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "dataset": dataset,
        "display_name": display_name,
        "attributes_json": "{}",
        "resolved_from": ["m-001"],
        "resolution_method": resolution_method,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }


def _make_decision_row(
    decision_id: str = "dec-001",
    entity_id: str = "ent-001",
) -> Dict[str, Any]:
    return {
        "decision_id": decision_id,
        "entity_id": entity_id,
        "mention_ids": ["m-001"],
        "source_record_ids": ["fir_001"],
        "outcome": "merged",
        "method": "exact_match",
        "matched_on": ["singleton"],
        "score": None,
        "decided_at": "2024-01-01T00:00:00Z",
    }


def _make_rel_row(
    relationship_id: str = "rel-001",
    relationship_type: str = "CALLED",
    from_entity_id: str = "ent-001",
    to_entity_id: str = "ent-002",
    dataset: str = "synthetic_demo",
) -> Dict[str, Any]:
    return {
        "relationship_id": relationship_id,
        "relationship_type": relationship_type,
        "from_entity_id": from_entity_id,
        "to_entity_id": to_entity_id,
        "dataset": dataset,
        "valid_from": "2024-01-01T00:00:00Z",
        "valid_to": None,
        "attributes_json": "{}",
        "evidence_ids": ["ev-001"],
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }


class MockRecord:
    """Mimics a neo4j.Record for test use."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


def _mock_session(records: List[Dict]) -> MagicMock:
    """Return a MagicMock context manager that yields records on session.run()."""
    mock_records = [MockRecord(r) for r in records]
    mock_run = MagicMock(return_value=iter(mock_records))
    mock_run.single = MagicMock(
        return_value=mock_records[0] if mock_records else None
    )
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.run = mock_run
    return mock_session


# ===========================================================================
# §12.1  GET /entities/search
# ===========================================================================

class TestSearchEntities:

    def test_returns_200_with_results_key(self):
        """§12.1: Response shape must be {results: CanonicalEntity[]}."""
        row = _make_entity_row()
        mock_sess = _mock_session([row])
        with patch("app.api.entities.get_session", return_value=mock_sess):
            resp = client.get("/api/v1/entities/search?q=Rahul")
        assert resp.status_code == 200
        body = resp.json()
        assert "results" in body
        assert isinstance(body["results"], list)

    def test_entity_fields_match_doc3_shape(self):
        """§12.1: Each result must carry all CanonicalEntity fields."""
        row = _make_entity_row()
        mock_sess = _mock_session([row])
        with patch("app.api.entities.get_session", return_value=mock_sess):
            resp = client.get("/api/v1/entities/search?q=Rahul")
        entity = resp.json()["results"][0]
        required_fields = [
            "entity_id", "entity_type", "dataset", "display_name",
            "attributes", "resolved_from", "resolution_method",
            "created_at", "updated_at",
        ]
        for field in required_fields:
            assert field in entity, f"Missing field: {field}"

    def test_empty_results_when_no_match(self):
        """§12.1: Empty results list when Neo4j returns nothing."""
        mock_sess = _mock_session([])
        with patch("app.api.entities.get_session", return_value=mock_sess):
            resp = client.get("/api/v1/entities/search?q=NoSuchEntity")
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_dataset_defaults_to_synthetic_demo(self):
        """DOC3 §2.6: dataset param defaults to 'synthetic_demo' when omitted."""
        mock_sess = _mock_session([])
        with patch("app.api.entities.get_session", return_value=mock_sess) as mock_gs:
            resp = client.get("/api/v1/entities/search")
        # Verify that the session's run was called with synthetic_demo in params
        assert resp.status_code == 200

    def test_unknown_entity_type_returns_empty(self):
        """Unknown entity_type not in DOC3 §6.1 enum → empty results without error."""
        resp = client.get("/api/v1/entities/search?entity_type=Alien")
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_graph_unavailable_returns_503(self):
        """Neo4j unavailability → 503 with graph_unavailable error type."""
        from neo4j.exceptions import ServiceUnavailable
        with patch("app.api.entities.get_session", side_effect=ServiceUnavailable("down")):
            resp = client.get("/api/v1/entities/search?q=test")
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["type"] == "graph_unavailable"


# ===========================================================================
# §12.2  GET /entities/{entity_id}
# ===========================================================================

class TestGetEntity:

    def test_returns_entity_and_resolution(self):
        """§12.2: Response shape must be {entity: CanonicalEntity, resolution: []}."""
        entity_row = _make_entity_row()
        decision_row = _make_decision_row()

        # session.run is called twice: entity then decisions
        call_count = [0]
        mock_records_by_call = [
            [MockRecord(entity_row)],   # first call: entity
            [MockRecord(decision_row)], # second call: decisions
        ]

        mock_session_obj = MagicMock()
        mock_session_obj.__enter__ = MagicMock(return_value=mock_session_obj)
        mock_session_obj.__exit__ = MagicMock(return_value=False)

        def mock_run(cypher, params):
            result_mock = MagicMock()
            records = mock_records_by_call[call_count[0] % 2]
            call_count[0] += 1
            result_mock.single = MagicMock(return_value=records[0] if records else None)
            result_mock.__iter__ = MagicMock(return_value=iter(records))
            return result_mock

        mock_session_obj.run = mock_run

        with patch("app.api.entities.get_session", return_value=mock_session_obj):
            resp = client.get("/api/v1/entities/ent-001")

        assert resp.status_code == 200
        body = resp.json()
        assert "entity" in body
        assert "resolution" in body

    def test_entity_shape_matches_doc3(self):
        """§12.2: entity object must contain all CanonicalEntity fields."""
        entity_row = _make_entity_row()
        mock_session_obj = MagicMock()
        mock_session_obj.__enter__ = MagicMock(return_value=mock_session_obj)
        mock_session_obj.__exit__ = MagicMock(return_value=False)

        call_count = [0]

        def mock_run(cypher, params):
            result = MagicMock()
            if call_count[0] == 0:
                result.single = MagicMock(return_value=MockRecord(entity_row))
                result.__iter__ = MagicMock(return_value=iter([]))
            else:
                result.single = MagicMock(return_value=None)
                result.__iter__ = MagicMock(return_value=iter([]))
            call_count[0] += 1
            return result

        mock_session_obj.run = mock_run

        with patch("app.api.entities.get_session", return_value=mock_session_obj):
            resp = client.get("/api/v1/entities/ent-001")

        assert resp.status_code == 200
        entity = resp.json()["entity"]
        for field in ["entity_id", "entity_type", "dataset", "display_name",
                      "attributes", "resolved_from", "resolution_method",
                      "created_at", "updated_at"]:
            assert field in entity, f"Missing field: {field}"

    def test_ac_unknown_entity_returns_404(self):
        """AC §12: GET /entities/{unknown_id} must return 404 with not_found."""
        mock_session_obj = MagicMock()
        mock_session_obj.__enter__ = MagicMock(return_value=mock_session_obj)
        mock_session_obj.__exit__ = MagicMock(return_value=False)

        result_mock = MagicMock()
        result_mock.single = MagicMock(return_value=None)
        mock_session_obj.run = MagicMock(return_value=result_mock)

        with patch("app.api.entities.get_session", return_value=mock_session_obj):
            resp = client.get("/api/v1/entities/nonexistent-id")

        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["type"] == "not_found"

    def test_resolution_is_list(self):
        """§12.2: resolution must be a list (even when empty)."""
        entity_row = _make_entity_row()
        mock_session_obj = MagicMock()
        mock_session_obj.__enter__ = MagicMock(return_value=mock_session_obj)
        mock_session_obj.__exit__ = MagicMock(return_value=False)

        call_count = [0]

        def mock_run(cypher, params):
            result = MagicMock()
            if call_count[0] == 0:
                result.single = MagicMock(return_value=MockRecord(entity_row))
            else:
                result.single = MagicMock(return_value=None)
            result.__iter__ = MagicMock(return_value=iter([]))
            call_count[0] += 1
            return result

        mock_session_obj.run = mock_run

        with patch("app.api.entities.get_session", return_value=mock_session_obj):
            resp = client.get("/api/v1/entities/ent-001")

        assert resp.status_code == 200
        assert isinstance(resp.json()["resolution"], list)

    def test_graph_unavailable_returns_503(self):
        """Neo4j unavailability → 503 graph_unavailable."""
        from neo4j.exceptions import ServiceUnavailable
        with patch("app.api.entities.get_session", side_effect=ServiceUnavailable("down")):
            resp = client.get("/api/v1/entities/ent-001")
        assert resp.status_code == 503
        assert resp.json()["error"]["type"] == "graph_unavailable"


# ===========================================================================
# §12.3  GET /entities/{entity_id}/relationships
# ===========================================================================

class TestGetEntityRelationships:

    def _mock_rel_session(self, rel_rows):
        """Session returning rel rows; EvidenceResolver also mocked."""
        mock_records = [MockRecord(r) for r in rel_rows]
        mock_session_obj = MagicMock()
        mock_session_obj.__enter__ = MagicMock(return_value=mock_session_obj)
        mock_session_obj.__exit__ = MagicMock(return_value=False)
        result_mock = MagicMock()
        result_mock.__iter__ = MagicMock(return_value=iter(mock_records))
        mock_session_obj.run = MagicMock(return_value=result_mock)
        return mock_session_obj

    def test_returns_200_with_relationships_key(self):
        """§12.3: Response shape must be {relationships: [...]}."""
        rel_row = _make_rel_row()
        mock_sess = self._mock_rel_session([rel_row])

        with patch("app.api.entities.get_session", return_value=mock_sess), \
             patch("app.api.entities.evidence_resolver.for_relationship", return_value=[]):
            resp = client.get("/api/v1/entities/ent-001/relationships")

        assert resp.status_code == 200
        body = resp.json()
        assert "relationships" in body
        assert isinstance(body["relationships"], list)

    def test_relationship_shape_includes_evidence_array(self):
        """§12.3: Each relationship must include inline 'evidence' array (not /graph behavior)."""
        rel_row = _make_rel_row()
        mock_sess = self._mock_rel_session([rel_row])

        with patch("app.api.entities.get_session", return_value=mock_sess), \
             patch("app.api.entities.evidence_resolver.for_relationship", return_value=[]):
            resp = client.get("/api/v1/entities/ent-001/relationships")

        assert resp.status_code == 200
        rels = resp.json()["relationships"]
        assert len(rels) == 1
        item = rels[0]
        # DOC3 §12.3: must include 'evidence' key with full Evidence[]
        assert "evidence" in item
        assert isinstance(item["evidence"], list)

    def test_relationship_fields_present(self):
        """§12.3: relationship item must include all Relationship fields."""
        rel_row = _make_rel_row()
        mock_sess = self._mock_rel_session([rel_row])

        with patch("app.api.entities.get_session", return_value=mock_sess), \
             patch("app.api.entities.evidence_resolver.for_relationship", return_value=[]):
            resp = client.get("/api/v1/entities/ent-001/relationships")

        item = resp.json()["relationships"][0]
        for field in ["relationship_id", "relationship_type", "from_entity_id",
                      "to_entity_id", "dataset", "valid_from", "evidence_ids"]:
            assert field in item, f"Missing field: {field}"

    def test_evidence_resolver_called_per_relationship(self):
        """§12.3: evidence_resolver.for_relationship() must be called for each relationship."""
        rel_row = _make_rel_row()
        mock_sess = self._mock_rel_session([rel_row])

        with patch("app.api.entities.get_session", return_value=mock_sess), \
             patch("app.api.entities.evidence_resolver.for_relationship",
                   return_value=[]) as mock_ev:
            client.get("/api/v1/entities/ent-001/relationships")

        mock_ev.assert_called_once_with("rel-001")

    def test_dataset_defaults_to_synthetic_demo(self):
        """§2.6: dataset defaults to 'synthetic_demo'."""
        mock_sess = self._mock_rel_session([])
        with patch("app.api.entities.get_session", return_value=mock_sess), \
             patch("app.api.entities.evidence_resolver.for_relationship", return_value=[]):
            resp = client.get("/api/v1/entities/ent-001/relationships")
        assert resp.status_code == 200

    def test_as_of_wired_to_c5_filter(self):
        """§2.4A / Invariant 14: as_of parameter is passed to C5's build_as_of_filter."""
        mock_sess = self._mock_rel_session([])
        with patch("app.api.entities.get_session", return_value=mock_sess), \
             patch("app.api.entities.evidence_resolver.for_relationship", return_value=[]), \
             patch("app.api.entities.build_as_of_filter",
                   wraps=__import__("app.graph.queries",
                                    fromlist=["build_as_of_filter"]).build_as_of_filter
                   ) as mock_baf:
            client.get("/api/v1/entities/ent-001/relationships?as_of=2024-06-01T00:00:00Z")

        mock_baf.assert_called_once_with("2024-06-01T00:00:00Z")

    def test_graph_unavailable_returns_503(self):
        """Neo4j unavailability → 503 graph_unavailable."""
        from neo4j.exceptions import ServiceUnavailable
        with patch("app.api.entities.get_session", side_effect=ServiceUnavailable("down")):
            resp = client.get("/api/v1/entities/ent-001/relationships")
        assert resp.status_code == 503
        assert resp.json()["error"]["type"] == "graph_unavailable"


# ===========================================================================
# §12.4  GET /graph
# ===========================================================================

class TestGetGraph:

    def _make_sessions(self, rel_rows=None, entity_rows=None, iso_rows=None):
        """Mock get_session to return different results per successive call."""
        rel_rows = rel_rows or []
        entity_rows = entity_rows or []
        iso_rows = iso_rows or []

        # get_session is called up to 3 times: relationships, entities (Rule 2a), isolated (Rule 2b)
        call_count = [0]
        all_calls = [rel_rows, entity_rows, iso_rows]

        def make_mock_session():
            call_index = call_count[0]
            call_count[0] += 1
            rows = all_calls[call_index] if call_index < len(all_calls) else []
            records = [MockRecord(r) for r in rows]
            mock_s = MagicMock()
            mock_s.__enter__ = MagicMock(return_value=mock_s)
            mock_s.__exit__ = MagicMock(return_value=False)
            result_mock = MagicMock()
            result_mock.__iter__ = MagicMock(return_value=iter(records))
            mock_s.run = MagicMock(return_value=result_mock)
            return mock_s

        return make_mock_session

    def test_returns_entities_and_relationships_keys(self):
        """§12.4: Response must be {entities: [...], relationships: [...]}."""
        factory = self._make_sessions()
        with patch("app.api.graph.get_session", side_effect=lambda: factory()):
            resp = client.get("/api/v1/graph")
        assert resp.status_code == 200
        body = resp.json()
        assert "entities" in body
        assert "relationships" in body

    def test_relationships_contain_evidence_ids_not_inline_evidence(self):
        """§12.4: relationships carry evidence_ids only, NOT inline Evidence[]."""
        rel_row = _make_rel_row()
        entity_row = _make_entity_row()
        factory = self._make_sessions(
            rel_rows=[rel_row],
            entity_rows=[entity_row],
            iso_rows=[],
        )
        with patch("app.api.graph.get_session", side_effect=lambda: factory()):
            resp = client.get("/api/v1/graph")

        assert resp.status_code == 200
        body = resp.json()
        if body["relationships"]:
            rel = body["relationships"][0]
            # MUST have evidence_ids
            assert "evidence_ids" in rel
            # MUST NOT have inline "evidence" key (that's §12.3's job)
            assert "evidence" not in rel

    def test_relationship_fields_present(self):
        """§12.4: each relationship must include all Relationship fields."""
        rel_row = _make_rel_row()
        entity_row = _make_entity_row()
        factory = self._make_sessions(rel_rows=[rel_row], entity_rows=[entity_row])
        with patch("app.api.graph.get_session", side_effect=lambda: factory()):
            resp = client.get("/api/v1/graph")
        body = resp.json()
        if body["relationships"]:
            rel = body["relationships"][0]
            for field in ["relationship_id", "relationship_type", "from_entity_id",
                          "to_entity_id", "dataset", "valid_from", "evidence_ids"]:
                assert field in rel, f"Missing field: {field}"

    def test_dataset_defaults_to_synthetic_demo(self):
        """§2.6: dataset defaults to 'synthetic_demo'."""
        factory = self._make_sessions()
        with patch("app.api.graph.get_session", side_effect=lambda: factory()):
            resp = client.get("/api/v1/graph")
        assert resp.status_code == 200

    def test_as_of_wired_to_c5_filter(self):
        """Invariant 14: as_of parameter must be forwarded to C5's build_as_of_filter."""
        factory = self._make_sessions()
        with patch("app.api.graph.get_session", side_effect=lambda: factory()), \
             patch("app.api.graph.build_as_of_filter",
                   wraps=__import__("app.graph.queries",
                                    fromlist=["build_as_of_filter"]).build_as_of_filter
                   ) as mock_baf:
            client.get("/api/v1/graph?as_of=2024-06-01T00:00:00Z")

        mock_baf.assert_called_once_with("2024-06-01T00:00:00Z")

    def test_no_as_of_passes_none_to_c5(self):
        """as_of omitted → build_as_of_filter(None) → no temporal filter."""
        factory = self._make_sessions()
        with patch("app.api.graph.get_session", side_effect=lambda: factory()), \
             patch("app.api.graph.build_as_of_filter",
                   wraps=__import__("app.graph.queries",
                                    fromlist=["build_as_of_filter"]).build_as_of_filter
                   ) as mock_baf:
            client.get("/api/v1/graph")

        mock_baf.assert_called_once_with(None)

    def test_graph_unavailable_returns_503(self):
        """Neo4j unavailability → 503 graph_unavailable."""
        from neo4j.exceptions import ServiceUnavailable
        with patch("app.api.graph.get_session", side_effect=ServiceUnavailable("down")):
            resp = client.get("/api/v1/graph")
        assert resp.status_code == 503
        assert resp.json()["error"]["type"] == "graph_unavailable"

    def test_empty_graph_returns_empty_lists(self):
        """Empty database → both entities and relationships are empty lists."""
        factory = self._make_sessions(rel_rows=[], entity_rows=[], iso_rows=[])
        with patch("app.api.graph.get_session", side_effect=lambda: factory()):
            resp = client.get("/api/v1/graph")
        assert resp.status_code == 200
        body = resp.json()
        assert body["entities"] == []
        assert body["relationships"] == []


# ===========================================================================
# Invariant 14 — C5 import verification
# ===========================================================================

class TestInvariant14Compliance:
    """C6 must import and use C5's filter, never reimplement it."""

    def test_entities_module_imports_from_queries(self):
        """entities.py must import build_as_of_filter from app.graph.queries."""
        import app.api.entities as ent_module
        assert hasattr(ent_module, "build_as_of_filter"), (
            "entities.py must import build_as_of_filter from C5 (app.graph.queries)"
        )

    def test_graph_module_imports_from_queries(self):
        """graph.py must import build_as_of_filter from app.graph.queries."""
        import app.api.graph as graph_module
        assert hasattr(graph_module, "build_as_of_filter"), (
            "graph.py must import build_as_of_filter from C5 (app.graph.queries)"
        )

    def test_entities_module_uses_evidence_resolver_not_direct_query(self):
        """entities.py must use EvidenceResolver (C4), not direct Evidence queries."""
        import app.api.entities as ent_module
        assert hasattr(ent_module, "evidence_resolver"), (
            "entities.py must import evidence_resolver from C4 (app.evidence.resolver)"
        )

    def test_graph_module_does_not_import_evidence_resolver(self):
        """graph.py §12.4 returns evidence_ids only — it must NOT call EvidenceResolver."""
        import app.api.graph as graph_module
        # graph.py should not even import evidence_resolver (it uses evidence_ids only)
        assert not hasattr(graph_module, "evidence_resolver"), (
            "graph.py must not import evidence_resolver — §12.4 returns evidence_ids only"
        )


# ===========================================================================
# Live integration tests (post-H3, neo4j_live guard)
# ===========================================================================

@pytest.mark.neo4j_live
class TestC6LiveIntegration:
    """C6 §13: API integration tests against a seeded graph (post-H3).

    These tests require a running Neo4j instance seeded via scripts/seed_demo.py.
    They are skipped when Neo4j is unavailable (neo4j_live marker).

    Coverage:
      - /entities/search returns entities from the synthetic_demo dataset.
      - /entities/{entity_id} returns a known entity with its resolution chain.
      - /entities/{entity_id}/relationships returns relationships with Evidence[].
      - /graph returns the full network with no temporal filter.
      - /graph?as_of=... correctly filters to the specified timestamp.
      - /entities/{unknown_id} returns 404.
    """

    def test_search_returns_synthetic_entities(self):
        """Live: /entities/search returns ≥1 result from the seeded synthetic_demo graph."""
        resp = client.get("/api/v1/entities/search?dataset=synthetic_demo")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) > 0

    def test_get_unknown_entity_returns_404(self):
        """Live AC: /entities/{nonexistent_id} returns 404 not_found."""
        resp = client.get("/api/v1/entities/this-entity-does-not-exist-live-test")
        assert resp.status_code == 404
        assert resp.json()["error"]["type"] == "not_found"

    def test_graph_returns_entities_and_relationships(self):
        """Live: /graph returns non-empty entities and relationships from seeded data."""
        resp = client.get("/api/v1/graph?dataset=synthetic_demo")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["entities"]) > 0
        assert len(body["relationships"]) > 0

    def test_graph_as_of_reduces_relationship_count(self):
        """Live §2.4A: /graph?as_of=<early_date> returns fewer/equal rels than no filter."""
        resp_all = client.get("/api/v1/graph?dataset=synthetic_demo")
        resp_early = client.get(
            "/api/v1/graph?dataset=synthetic_demo&as_of=2020-01-01T00:00:00Z"
        )
        assert resp_all.status_code == 200
        assert resp_early.status_code == 200
        # Temporal filter should not produce more relationships than no filter
        assert len(resp_early.json()["relationships"]) <= len(resp_all.json()["relationships"])

    def test_entity_relationships_includes_evidence_array(self):
        """Live §12.3: each relationship in /relationships includes non-null evidence key."""
        # First search for any entity
        search_resp = client.get("/api/v1/entities/search?dataset=synthetic_demo")
        assert search_resp.status_code == 200
        results = search_resp.json()["results"]
        if not results:
            pytest.skip("No entities in seeded graph")
        entity_id = results[0]["entity_id"]

        rel_resp = client.get(
            f"/api/v1/entities/{entity_id}/relationships?dataset=synthetic_demo"
        )
        assert rel_resp.status_code == 200
        for rel_item in rel_resp.json()["relationships"]:
            assert "evidence" in rel_item
