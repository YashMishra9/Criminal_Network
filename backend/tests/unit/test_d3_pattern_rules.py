from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app.contracts.analytics import AnalyticsResult
from app.contracts.evidence import Evidence
from app.contracts.finding import INVESTIGATIVE_LEAD_DISCLAIMER
from app.patterns.rules import bridge_entity_rule, temporal_convergence_rule
from app.patterns.rules.bridge_entity_rule import BridgeEntityRule
from app.patterns.rules.temporal_convergence_rule import TemporalConvergenceRule


class FakeResolver:
    def __init__(self, *, relationship_evidence=None, entity_evidence=None, error=None):
        self.relationship_evidence = relationship_evidence or {}
        self.entity_evidence = entity_evidence or {}
        self.error = error
        self.relationship_calls = []
        self.entity_calls = []

    def for_relationship(self, relationship_id):
        self.relationship_calls.append(relationship_id)
        if self.error:
            raise self.error
        return self.relationship_evidence.get(relationship_id, [])

    def for_entity(self, entity_id):
        self.entity_calls.append(entity_id)
        if self.error:
            raise self.error
        return self.entity_evidence.get(entity_id, [])


def _evidence(evidence_id, dataset="synthetic_demo"):
    return Evidence(
        evidence_id=evidence_id,
        dataset=dataset,
        source_id=f"record-{evidence_id}",
        source_type="CDR",
        ingested_at="2024-01-01T00:00:00Z",
    )


def _session_patch(monkeypatch, module, rows):
    captured = {}

    class FakeSession:
        def run(self, query, params):
            captured["query"] = query
            captured["params"] = params
            return rows

    @contextmanager
    def fake_get_session():
        yield FakeSession()

    monkeypatch.setattr(module, "get_session", fake_get_session)
    return captured


def _bridge_rows():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index, leaf in enumerate(("leaf-a", "leaf-b", "leaf-c", "leaf-d")):
        rows.append(
            {
                "relationship_id": f"rel-{index}",
                "dataset": "synthetic_demo",
                "relationship_type": "CALLED",
                "valid_from": (start + timedelta(hours=index)).isoformat().replace("+00:00", "Z"),
                "valid_to": None,
                "from_entity_id": "bridge",
                "to_entity_id": leaf,
            }
        )
    return rows


def _temporal_rows(*, dataset="synthetic_demo"):
    start = datetime(2024, 2, 1, tzinfo=timezone.utc)
    edges = [("a", "b", 0), ("b", "c", 2), ("c", "d", 8), ("x", "y", 60)]
    return [
        {
            "relationship_id": f"rel-{index}",
            "dataset": dataset,
            "relationship_type": "MET" if index == 2 else "CALLED",
            "valid_from": (start + timedelta(hours=offset)).isoformat().replace("+00:00", "Z"),
            "from_entity_id": source,
            "to_entity_id": target,
        }
        for index, (source, target, offset) in enumerate(edges)
    ]


def test_bridge_rule_uses_d1_metrics_and_resolves_evidence(monkeypatch):
    rows = _bridge_rows()
    resolver = FakeResolver(
        entity_evidence={"bridge": [_evidence("entity-evidence")]},
        relationship_evidence={
            row["relationship_id"]: [_evidence(f"evidence-{index}")]
            for index, row in enumerate(rows)
        },
    )
    captured = _session_patch(monkeypatch, bridge_entity_rule, rows)

    findings = BridgeEntityRule(resolver=resolver).evaluate("synthetic_demo", None)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "bridge_entity_v1"
    assert finding.subject_entity_ids == ["bridge"]
    assert finding.subject_relationship_ids == [row["relationship_id"] for row in rows]
    assert finding.triggering_values["betweenness"] == 1.0
    assert finding.triggering_values["community_id"] == "community_0"
    assert "betweenness centrality 1.000" in finding.explanation
    assert finding.evidence_ids == ["entity-evidence", "evidence-0", "evidence-1", "evidence-2", "evidence-3"]
    assert finding.disclaimer == INVESTIGATIVE_LEAD_DISCLAIMER
    assert captured["params"] == {"dataset": "synthetic_demo"}
    assert "r.dataset = $dataset" in captured["query"]


def test_bridge_rule_reuses_c5_as_of_filter_and_passes_scope_to_d1(monkeypatch):
    rows = _bridge_rows()
    resolver = FakeResolver(
        entity_evidence={"bridge": [_evidence("entity-evidence")]},
        relationship_evidence={
            row["relationship_id"]: [_evidence(f"evidence-{index}")]
            for index, row in enumerate(rows)
        },
    )
    captured = _session_patch(monkeypatch, bridge_entity_rule, rows)
    cutoff = "2024-01-02T00:00:00Z"

    BridgeEntityRule(resolver=resolver).evaluate("synthetic_demo", cutoff)

    assert captured["params"] == {"dataset": "synthetic_demo", "as_of": cutoff}
    assert "r.valid_from <= $as_of" in captured["query"]
    assert "r.valid_to >= $as_of" in captured["query"]


def test_bridge_rule_returns_empty_for_graph_without_bridge(monkeypatch):
    _session_patch(monkeypatch, bridge_entity_rule, [])
    resolver = FakeResolver()

    assert BridgeEntityRule(resolver=resolver).evaluate("synthetic_demo", None) == []
    assert resolver.entity_calls == []


def test_bridge_rule_does_not_flag_triangle_nodes(monkeypatch):
    rows = _bridge_rows()[:3]
    triangle_edges = [("a", "b"), ("b", "c"), ("c", "a")]
    for row, (from_id, to_id) in zip(rows, triangle_edges):
        row["from_entity_id"] = from_id
        row["to_entity_id"] = to_id
    _session_patch(monkeypatch, bridge_entity_rule, rows)
    resolver = FakeResolver()

    assert BridgeEntityRule(resolver=resolver).evaluate("synthetic_demo", None) == []
    assert resolver.entity_calls == []


def test_bridge_rule_rejects_analytics_from_wrong_scope(monkeypatch):
    class WrongScopeAnalytics:
        def compute(self, request, *, relationships):
            assert relationships
            return (
                AnalyticsResult(
                    computed_at="2024-01-01T00:00:00Z",
                    dataset="live_public",
                    as_of=request.as_of,
                    centrality=[],
                    communities=[],
                ),
                None,
            )

    _session_patch(monkeypatch, bridge_entity_rule, _bridge_rows())

    with pytest.raises(ValueError, match="different dataset or as_of"):
        BridgeEntityRule(analytics_service=WrongScopeAnalytics()).evaluate("synthetic_demo", None)


def test_bridge_rule_requires_entity_and_relationship_evidence(monkeypatch):
    _session_patch(monkeypatch, bridge_entity_rule, _bridge_rows())

    with pytest.raises(RuntimeError, match="No evidence resolved"):
        BridgeEntityRule(resolver=FakeResolver()).evaluate("synthetic_demo", None)


def test_bridge_rule_rejects_invalid_scope_before_query(monkeypatch):
    captured = _session_patch(monkeypatch, bridge_entity_rule, [])

    with pytest.raises(ValueError):
        BridgeEntityRule().evaluate("synthetic_demo", "invalid-date")
    assert captured == {}


def test_temporal_convergence_finds_close_connected_relationships(monkeypatch):
    rows = _temporal_rows()
    resolver = FakeResolver(
        relationship_evidence={
            row["relationship_id"]: [_evidence(f"evidence-{index}")]
            for index, row in enumerate(rows[:3])
        }
    )
    captured = _session_patch(monkeypatch, temporal_convergence_rule, rows)

    findings = TemporalConvergenceRule(resolver).evaluate("synthetic_demo", None)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "temporal_convergence_v1"
    assert finding.subject_entity_ids == ["a", "b", "c", "d"]
    assert finding.subject_relationship_ids == ["rel-0", "rel-1", "rel-2"]
    assert finding.triggering_values["relationship_count"] == 3
    assert finding.triggering_values["entity_count"] == 4
    assert finding.triggering_values["window_hours"] == 24
    assert finding.triggering_values["relationship_types"] == ["CALLED", "MET"]
    assert "3 relationships among 4 entities" in finding.explanation
    assert finding.evidence_ids == ["evidence-0", "evidence-1", "evidence-2"]
    assert finding.disclaimer == INVESTIGATIVE_LEAD_DISCLAIMER
    assert captured["params"] == {"dataset": "synthetic_demo"}


def test_temporal_convergence_reuses_c5_as_of_filter(monkeypatch):
    captured = _session_patch(monkeypatch, temporal_convergence_rule, [])
    cutoff = "2024-02-01T12:00:00Z"

    assert TemporalConvergenceRule().evaluate("synthetic_demo", cutoff) == []

    assert captured["params"] == {"dataset": "synthetic_demo", "as_of": cutoff}
    assert "r.valid_from <= $as_of" in captured["query"]
    assert "r.valid_to >= $as_of" in captured["query"]


def test_temporal_convergence_returns_empty_below_minimum(monkeypatch):
    rows = _temporal_rows()[:2]
    resolver = FakeResolver()
    _session_patch(monkeypatch, temporal_convergence_rule, rows)

    assert TemporalConvergenceRule(resolver).evaluate("synthetic_demo", None) == []
    assert resolver.relationship_calls == []


def test_temporal_convergence_handles_empty_graph(monkeypatch):
    _session_patch(monkeypatch, temporal_convergence_rule, [])

    assert TemporalConvergenceRule().evaluate("synthetic_demo", None) == []


@pytest.mark.parametrize(
    ("dataset", "as_of"),
    [("combined", None), ("synthetic_demo", "invalid-date")],
)
def test_temporal_convergence_rejects_invalid_scope(monkeypatch, dataset, as_of):
    captured = _session_patch(monkeypatch, temporal_convergence_rule, [])

    with pytest.raises(ValueError):
        TemporalConvergenceRule().evaluate(dataset, as_of)
    assert captured == {}


def test_temporal_convergence_rejects_cross_dataset_rows(monkeypatch):
    rows = _temporal_rows(dataset="live_public")
    _session_patch(monkeypatch, temporal_convergence_rule, rows)

    with pytest.raises(ValueError, match="different dataset"):
        TemporalConvergenceRule().evaluate("synthetic_demo", None)


def test_temporal_convergence_rejects_malformed_timestamps(monkeypatch):
    rows = _temporal_rows()[:3]
    rows[0]["valid_from"] = "not-a-date"
    _session_patch(monkeypatch, temporal_convergence_rule, rows)

    with pytest.raises(ValueError, match="ISO-8601"):
        TemporalConvergenceRule().evaluate("synthetic_demo", None)


def test_temporal_convergence_fails_closed_when_evidence_is_missing(monkeypatch):
    _session_patch(monkeypatch, temporal_convergence_rule, _temporal_rows()[:3])

    with pytest.raises(RuntimeError, match="No evidence resolved"):
        TemporalConvergenceRule(FakeResolver()).evaluate("synthetic_demo", None)


def test_temporal_convergence_propagates_resolver_errors(monkeypatch):
    _session_patch(monkeypatch, temporal_convergence_rule, _temporal_rows()[:3])

    with pytest.raises(RuntimeError, match="resolver unavailable"):
        TemporalConvergenceRule(FakeResolver(error=RuntimeError("resolver unavailable"))).evaluate(
            "synthetic_demo", None
        )
