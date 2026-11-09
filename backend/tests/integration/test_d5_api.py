from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from app.api import analytics as analytics_api
from app.api import patterns as patterns_api
from app.contracts.analytics import AnalyticsResult, ShortestPathResult
from app.contracts.entity import CanonicalEntity
from app.contracts.errors import GraphUnavailableError
from app.contracts.relationship import Relationship
from app.main import app
from app.patterns.engine import PatternDetectionEngine

client = TestClient(app)


def _entity(entity_id: str, dataset="synthetic_demo"):
    now = "2024-01-01T00:00:00Z"
    return CanonicalEntity(
        entity_id=entity_id,
        entity_type="Person",
        dataset=dataset,
        display_name=entity_id,
        attributes={},
        resolved_from=[],
        resolution_method="manual",
        created_at=now,
        updated_at=now,
    )


def _relationship(relationship_id: str, source: str, target: str, dataset="synthetic_demo"):
    now = "2024-01-01T00:00:00Z"
    return Relationship(
        relationship_id=relationship_id,
        relationship_type="CALLED",
        from_entity_id=source,
        to_entity_id=target,
        dataset=dataset,
        attributes={},
        valid_from=now,
        valid_to=None,
        evidence_ids=[f"evidence-{relationship_id}"],
        created_at=now,
        updated_at=now,
    )


def _analytics_result(dataset="synthetic_demo", as_of=None):
    return AnalyticsResult(
        computed_at="2024-01-01T00:00:00Z",
        dataset=dataset,
        as_of=as_of,
        centrality=[],
        communities=[],
    )


def _finding_row(
    finding_id="finding-1",
    dataset="synthetic_demo",
    subject_entity_ids=None,
    subject_relationship_ids=None,
):
    return {
        "finding_id": finding_id,
        "dataset": dataset,
        "rule_id": "fixture_rule_v1",
        "rule_name": "Fixture Rule",
        "subject_entity_ids": subject_entity_ids or ["entity-a"],
        "subject_relationship_ids": subject_relationship_ids or [],
        "explanation": "A specific fixture-backed lead.",
        "triggering_values_json": '{"count": 2}',
        "evidence_ids": ["evidence-1"],
        "disclaimer": "This is an investigative lead, not evidence of wrongdoing.",
        "detected_at": "2024-01-01T00:00:00Z",
    }


def _patch_findings_session(monkeypatch, rows):
    calls = []

    class FakeSession:
        def run(self, query, params):
            calls.append((query, params))
            return rows

    @contextmanager
    def fake_get_session():
        yield FakeSession()

    monkeypatch.setattr(patterns_api, "get_session", fake_get_session)
    return calls


def test_analytics_defaults_to_four_non_shortest_algorithms(monkeypatch):
    snapshot = {
        "entities": [_entity("entity-a"), _entity("entity-b")],
        "relationships": [_relationship("rel-1", "entity-a", "entity-b")],
    }
    graph_call = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(analytics_api, "get_graph_snapshot", graph_call)
    calls = []

    def fake_compute(request, *, relationships, nodes):
        calls.append((request, relationships, nodes))
        return _analytics_result(request.dataset, request.as_of), None

    monkeypatch.setattr(analytics_api._analytics_service, "compute", fake_compute)

    response = client.get("/api/v1/analytics")

    assert response.status_code == 200
    assert set(response.json()) == {"computed_at", "dataset", "as_of", "centrality", "communities"}
    request, relationships, nodes = calls[0]
    assert request.dataset == "synthetic_demo"
    assert request.algorithms == ["degree", "betweenness", "pagerank", "community"]
    assert relationships == snapshot["relationships"]
    assert nodes == ["entity-a", "entity-b"]
    graph_call.assert_awaited_once_with(dataset="synthetic_demo", as_of=None)


def test_analytics_passes_selected_algorithms_and_as_of_to_d1(monkeypatch):
    cutoff = "2024-01-01T00:00:00Z"
    monkeypatch.setattr(
        analytics_api,
        "get_graph_snapshot",
        AsyncMock(return_value={"entities": [], "relationships": []}),
    )
    calls = []

    def fake_compute(request, *, relationships, nodes):
        calls.append(request)
        return _analytics_result(request.dataset, request.as_of), None

    monkeypatch.setattr(analytics_api._analytics_service, "compute", fake_compute)

    response = client.get(
        "/api/v1/analytics",
        params={"dataset": "live_public", "as_of": cutoff, "algorithms": "community,degree"},
    )

    assert response.status_code == 200
    assert calls[0].dataset == "live_public"
    assert calls[0].as_of == cutoff
    assert calls[0].algorithms == ["community", "degree"]


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"algorithms": "shortest_path"}, "supports only"),
        ({"algorithms": "degree,unknown"}, "supports only"),
        ({"algorithms": "degree,,community"}, "comma-separated"),
        ({"dataset": "combined"}, "dataset must"),
        ({"as_of": "not-a-date"}, "ISO-8601"),
    ],
)
def test_analytics_rejects_invalid_query_parameters(monkeypatch, params, message):
    graph_call = AsyncMock()
    monkeypatch.setattr(analytics_api, "get_graph_snapshot", graph_call)

    response = client.get("/api/v1/analytics", params=params)

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "validation_error"
    assert message in response.json()["error"]["message"]
    graph_call.assert_not_awaited()


def test_shortest_path_uses_d1_parameter_names_and_existing_result(monkeypatch):
    snapshot = {
        "entities": [_entity("source"), _entity("target")],
        "relationships": [_relationship("rel-1", "source", "target")],
    }
    graph_call = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(analytics_api, "get_graph_snapshot", graph_call)
    path_result = ShortestPathResult(
        found=True,
        path_entity_ids=["source", "target"],
        path_relationship_ids=["rel-1"],
    )
    calls = []

    def fake_compute(request, *, relationships, nodes):
        calls.append((request, relationships, nodes))
        return _analytics_result(request.dataset, request.as_of), path_result

    monkeypatch.setattr(analytics_api._analytics_service, "compute", fake_compute)
    cutoff = "2024-01-01T00:00:00Z"

    response = client.get(
        "/api/v1/analytics/shortest-path",
        params={
            "dataset": "synthetic_demo",
            "as_of": cutoff,
            "shortest_path_from": "source",
            "shortest_path_to": "target",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "found": True,
        "path_entity_ids": ["source", "target"],
        "path_relationship_ids": ["rel-1"],
    }
    request, relationships, nodes = calls[0]
    assert request.algorithms == ["shortest_path"]
    assert request.shortest_path_from == "source"
    assert request.shortest_path_to == "target"
    assert request.as_of == cutoff
    assert relationships == snapshot["relationships"]
    assert nodes == ["source", "target"]
    graph_call.assert_awaited_once_with(dataset="synthetic_demo", as_of=cutoff)


def test_shortest_path_requires_both_endpoint_ids(monkeypatch):
    graph_call = AsyncMock()
    monkeypatch.setattr(analytics_api, "get_graph_snapshot", graph_call)

    response = client.get(
        "/api/v1/analytics/shortest-path",
        params={"shortest_path_from": "source"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "validation_error"
    graph_call.assert_not_awaited()


def test_shortest_path_returns_not_found_shape_when_no_path(monkeypatch):
    monkeypatch.setattr(
        analytics_api,
        "get_graph_snapshot",
        AsyncMock(return_value={"entities": [], "relationships": []}),
    )

    def fake_compute(request, *, relationships, nodes):
        return _analytics_result(request.dataset, request.as_of), ShortestPathResult(
            found=False,
            path_entity_ids=[],
            path_relationship_ids=[],
        )

    monkeypatch.setattr(analytics_api._analytics_service, "compute", fake_compute)

    response = client.get(
        "/api/v1/analytics/shortest-path",
        params={"shortest_path_from": "missing-a", "shortest_path_to": "missing-b"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "found": False,
        "path_entity_ids": [],
        "path_relationship_ids": [],
    }


def test_analytics_graph_unavailable_uses_doc3_error_envelope(monkeypatch):
    async def unavailable_graph(*, dataset, as_of):
        raise GraphUnavailableError("Neo4j unavailable")

    monkeypatch.setattr(analytics_api, "get_graph_snapshot", unavailable_graph)

    response = client.get("/api/v1/analytics")

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "graph_unavailable"


def test_patterns_reads_findings_twice_without_running_detection(monkeypatch):
    rows = [_finding_row()]
    calls = _patch_findings_session(monkeypatch, rows)
    detection_run = MagicMock(side_effect=AssertionError("GET /patterns must be read-only"))
    monkeypatch.setattr(PatternDetectionEngine, "run", detection_run)

    first = client.get("/api/v1/patterns")
    second = client.get("/api/v1/patterns")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    finding = first.json()["findings"][0]
    assert finding["evidence_ids"] == ["evidence-1"]
    assert finding["disclaimer"] == "This is an investigative lead, not evidence of wrongdoing."
    assert len(calls) == 2
    assert all(params == {"dataset": "synthetic_demo"} for _, params in calls)
    assert all(
        not any(token in query.upper() for token in ("CREATE", "MERGE", "DELETE", " SET "))
        for query, _ in calls
    )
    detection_run.assert_not_called()


def test_patterns_filters_every_subject_by_as_of_graph_visibility(monkeypatch):
    rows = [
        _finding_row("visible", subject_entity_ids=["entity-visible"], subject_relationship_ids=["rel-visible"]),
        _finding_row("hidden-rel", subject_entity_ids=["entity-visible"], subject_relationship_ids=["rel-hidden"]),
        _finding_row("hidden-entity", subject_entity_ids=["entity-hidden"], subject_relationship_ids=[]),
    ]
    calls = _patch_findings_session(monkeypatch, rows)
    cutoff = "2024-01-01T00:00:00Z"

    async def visible_snapshot(*, dataset, as_of):
        assert dataset == "synthetic_demo"
        assert as_of == cutoff
        return {
            "entities": [_entity("entity-visible")],
            "relationships": [_relationship("rel-visible", "entity-visible", "entity-b")],
        }

    monkeypatch.setattr(patterns_api, "get_graph_snapshot", visible_snapshot)

    response = client.get("/api/v1/patterns", params={"as_of": cutoff})

    assert response.status_code == 200
    assert [finding["finding_id"] for finding in response.json()["findings"]] == ["visible"]
    assert calls[0][1] == {"dataset": "synthetic_demo"}


def test_patterns_rejects_invalid_dataset_and_as_of_before_reading(monkeypatch):
    calls = _patch_findings_session(monkeypatch, [])
    graph_call = AsyncMock()
    monkeypatch.setattr(patterns_api, "get_graph_snapshot", graph_call)

    bad_dataset = client.get("/api/v1/patterns", params={"dataset": "combined"})
    bad_as_of = client.get("/api/v1/patterns", params={"as_of": "invalid"})

    assert bad_dataset.status_code == bad_as_of.status_code == 400
    assert all(response.json()["error"]["type"] == "validation_error" for response in (bad_dataset, bad_as_of))
    assert calls == []
    graph_call.assert_not_awaited()


def test_patterns_rejects_cross_dataset_stored_finding(monkeypatch):
    _patch_findings_session(monkeypatch, [_finding_row(dataset="live_public")])

    response = client.get("/api/v1/patterns", params={"dataset": "synthetic_demo"})

    assert response.status_code == 500
    assert response.json()["error"]["type"] == "internal_error"


def test_patterns_rejects_stored_finding_without_evidence(monkeypatch):
    row = _finding_row()
    row["evidence_ids"] = []
    _patch_findings_session(monkeypatch, [row])

    response = client.get("/api/v1/patterns")

    assert response.status_code == 500
    assert response.json()["error"]["type"] == "internal_error"


def test_patterns_graph_unavailable_uses_doc3_error_envelope(monkeypatch):
    @contextmanager
    def failed_session():
        raise ServiceUnavailable("graph down")
        yield

    monkeypatch.setattr(patterns_api, "get_session", failed_session)

    response = client.get("/api/v1/patterns")

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "graph_unavailable"
