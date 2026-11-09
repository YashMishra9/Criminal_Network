from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app.contracts.evidence import Evidence
from app.contracts.finding import INVESTIGATIVE_LEAD_DISCLAIMER
from app.patterns.rules import frequency_rule, shared_attribute_rule
from app.patterns.rules.frequency_rule import FrequencyRule
from app.patterns.rules.shared_attribute_rule import SharedAttributeRule


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


def _call_rows(count=10, *, dataset="synthetic_demo"):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "relationship_id": f"rel-{index:02d}",
            "dataset": dataset,
            "valid_from": (start + timedelta(hours=12 * index)).isoformat().replace("+00:00", "Z"),
            "from_entity_id": "entity-a",
            "from_display_name": "Entity A",
            "to_entity_id": "entity-b",
            "to_display_name": "Entity B",
        }
        for index in range(count)
    ]


def test_frequency_rule_emits_specific_evidence_backed_finding(monkeypatch):
    rows = _call_rows(10)
    resolver = FakeResolver(
        relationship_evidence={row["relationship_id"]: [_evidence(f"ev-{index}")] for index, row in enumerate(rows)}
    )
    captured = _session_patch(monkeypatch, frequency_rule, rows)

    findings = FrequencyRule(resolver).evaluate("synthetic_demo", None)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "frequency_rule_v1"
    assert finding.subject_entity_ids == ["entity-a", "entity-b"]
    assert finding.subject_relationship_ids == [row["relationship_id"] for row in rows]
    assert finding.triggering_values["call_count"] == 10
    assert finding.triggering_values["threshold"] == 10
    assert finding.triggering_values["window_days"] == 7
    assert finding.evidence_ids == [f"ev-{index}" for index in range(10)]
    assert "10 calls between Entity A and Entity B" in finding.explanation
    assert finding.disclaimer == INVESTIGATIVE_LEAD_DISCLAIMER
    assert captured["params"] == {"dataset": "synthetic_demo"}
    assert "r.dataset = $dataset" in captured["query"]


def test_frequency_rule_reuses_c5_as_of_filter_and_dataset_scope(monkeypatch):
    rows = _call_rows(10)
    resolver = FakeResolver(
        relationship_evidence={row["relationship_id"]: [_evidence(f"ev-{index}")] for index, row in enumerate(rows)}
    )
    captured = _session_patch(monkeypatch, frequency_rule, rows)
    cutoff = "2024-01-08T00:00:00Z"

    FrequencyRule(resolver).evaluate("synthetic_demo", cutoff)

    assert captured["params"] == {"dataset": "synthetic_demo", "as_of": cutoff}
    assert "r.valid_from <= $as_of" in captured["query"]
    assert "r.valid_to >= $as_of" in captured["query"]


def test_frequency_rule_returns_empty_below_threshold(monkeypatch):
    resolver = FakeResolver()
    _session_patch(monkeypatch, frequency_rule, _call_rows(9))

    assert FrequencyRule(resolver).evaluate("synthetic_demo", None) == []
    assert resolver.relationship_calls == []


def test_frequency_rule_handles_empty_graph(monkeypatch):
    _session_patch(monkeypatch, frequency_rule, [])

    assert FrequencyRule().evaluate("synthetic_demo", None) == []


@pytest.mark.parametrize(
    ("dataset", "as_of"),
    [("combined", None), ("synthetic_demo", "not-a-date")],
)
def test_frequency_rule_rejects_invalid_scope_before_query(monkeypatch, dataset, as_of):
    captured = _session_patch(monkeypatch, frequency_rule, [])

    with pytest.raises(ValueError):
        FrequencyRule().evaluate(dataset, as_of)
    assert captured == {}


def test_frequency_rule_rejects_cross_dataset_rows(monkeypatch):
    rows = _call_rows(1, dataset="live_public")
    _session_patch(monkeypatch, frequency_rule, rows)

    with pytest.raises(ValueError, match="different dataset"):
        FrequencyRule().evaluate("synthetic_demo", None)


def test_frequency_rule_fails_closed_when_evidence_is_missing(monkeypatch):
    rows = _call_rows(10)
    _session_patch(monkeypatch, frequency_rule, rows)

    with pytest.raises(RuntimeError, match="No evidence resolved"):
        FrequencyRule(FakeResolver()).evaluate("synthetic_demo", None)


def test_frequency_rule_propagates_resolver_errors(monkeypatch):
    rows = _call_rows(10)
    _session_patch(monkeypatch, frequency_rule, rows)

    with pytest.raises(RuntimeError, match="resolver unavailable"):
        FrequencyRule(FakeResolver(error=RuntimeError("resolver unavailable"))).evaluate(
            "synthetic_demo", None
        )


def test_shared_attribute_rule_emits_finding_for_shared_identifier(monkeypatch):
    rows = [
        {
            "entity_id": "entity-a",
            "dataset": "synthetic_demo",
            "display_name": "Entity A",
            "attributes_json": json.dumps({"phone": "9876543210", "city": "Mumbai"}),
        },
        {
            "entity_id": "entity-b",
            "dataset": "synthetic_demo",
            "display_name": "Entity B",
            "attributes_json": json.dumps({"phone": " 9876543210 ", "account": "ACCT-2"}),
        },
        {
            "entity_id": "entity-c",
            "dataset": "synthetic_demo",
            "display_name": "Entity C",
            "attributes_json": json.dumps({"phone": "9123456789"}),
        },
    ]
    resolver = FakeResolver(
        entity_evidence={
            "entity-a": [_evidence("ev-a")],
            "entity-b": [_evidence("ev-b")],
        }
    )
    captured = _session_patch(monkeypatch, shared_attribute_rule, rows)

    findings = SharedAttributeRule(resolver).evaluate("synthetic_demo", None)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.subject_entity_ids == ["entity-a", "entity-b"]
    assert finding.subject_relationship_ids == []
    assert finding.triggering_values == {
        "attribute_name": "phone",
        "shared_value": "9876543210",
        "entity_count": 2,
    }
    assert finding.evidence_ids == ["ev-a", "ev-b"]
    assert "Entity A, Entity B" in finding.explanation
    assert finding.disclaimer == INVESTIGATIVE_LEAD_DISCLAIMER
    assert captured["params"] == {"dataset": "synthetic_demo"}
    assert "n.dataset = $dataset" in captured["query"]


def test_shared_attribute_rule_reuses_c5_entity_visibility_filter(monkeypatch):
    captured = _session_patch(monkeypatch, shared_attribute_rule, [])
    cutoff = "2024-01-08T00:00:00Z"

    assert SharedAttributeRule().evaluate("synthetic_demo", cutoff) == []

    assert captured["params"] == {"dataset": "synthetic_demo", "as_of": cutoff}
    assert "EXISTS { MATCH (n)-[r]->()" in captured["query"]
    assert "OR NOT EXISTS { MATCH (n)-[r]-() WHERE r.dataset = $dataset }" in captured["query"]


def test_shared_attribute_rule_handles_empty_and_malformed_attributes(monkeypatch):
    rows = [
        {
            "entity_id": "entity-a",
            "dataset": "synthetic_demo",
            "display_name": "Entity A",
            "attributes_json": "not-json",
        }
    ]
    _session_patch(monkeypatch, shared_attribute_rule, rows)

    assert SharedAttributeRule().evaluate("synthetic_demo", None) == []


def test_shared_attribute_rule_rejects_cross_dataset_rows(monkeypatch):
    rows = [
        {
            "entity_id": "entity-a",
            "dataset": "live_public",
            "display_name": "Entity A",
            "attributes_json": json.dumps({"phone": "9876543210"}),
        }
    ]
    _session_patch(monkeypatch, shared_attribute_rule, rows)

    with pytest.raises(ValueError, match="different dataset"):
        SharedAttributeRule().evaluate("synthetic_demo", None)


def test_shared_attribute_rule_requires_evidence_for_each_entity(monkeypatch):
    rows = [
        {
            "entity_id": entity_id,
            "dataset": "synthetic_demo",
            "display_name": entity_id,
            "attributes_json": json.dumps({"phone": "9876543210"}),
        }
        for entity_id in ("entity-a", "entity-b")
    ]
    _session_patch(monkeypatch, shared_attribute_rule, rows)

    with pytest.raises(RuntimeError, match="No evidence resolved"):
        SharedAttributeRule(FakeResolver()).evaluate("synthetic_demo", None)


def test_shared_attribute_rule_rejects_evidence_from_another_dataset(monkeypatch):
    rows = [
        {
            "entity_id": entity_id,
            "dataset": "synthetic_demo",
            "display_name": entity_id,
            "attributes_json": json.dumps({"phone": "9876543210"}),
        }
        for entity_id in ("entity-a", "entity-b")
    ]
    resolver = FakeResolver(
        entity_evidence={
            "entity-a": [_evidence("ev-a")],
            "entity-b": [_evidence("ev-b", dataset="live_public")],
        }
    )
    _session_patch(monkeypatch, shared_attribute_rule, rows)

    with pytest.raises(RuntimeError, match="different dataset"):
        SharedAttributeRule(resolver).evaluate("synthetic_demo", None)
