from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.contracts.finding import Finding, INVESTIGATIVE_LEAD_DISCLAIMER
from app.patterns import engine as engine_module
from app.patterns.engine import PatternDetectionEngine, persist_findings


class FakeResult:
    def __init__(self, record=None):
        self._record = record

    def single(self):
        return self._record

    def consume(self):
        return None


class FakeTransaction:
    def __init__(self, database):
        self.database = database

    def run(self, query, params):
        self.database.queries.append((query, params))
        if "RETURN collect(DISTINCT ev.evidence_id) AS ids" in query:
            ids = set(params["ids"]) & self.database.evidence_ids
            return FakeResult({"ids": sorted(ids)})
        if "RETURN collect(DISTINCT entity.entity_id) AS ids" in query:
            ids = set(params["ids"]) & self.database.entity_ids
            return FakeResult({"ids": sorted(ids)})
        if "RETURN collect(DISTINCT edge_ref.relationship_id) AS ids" in query:
            ids = set(params["ids"]) & self.database.edge_ref_ids
            return FakeResult({"ids": sorted(ids)})
        if "MERGE (finding:Finding" in query:
            key = (
                params["rule_id"],
                params["dataset"],
                tuple(params["subject_entity_ids"]),
                tuple(params["subject_relationship_ids"]),
            )
            finding = self.database.findings.setdefault(
                key,
                {"finding_id": params["candidate_finding_id"]},
            )
            finding.update(params)
            return FakeResult({"finding_id": finding["finding_id"]})
        return FakeResult()


class FakeSession:
    def __init__(self, database):
        self._transaction = FakeTransaction(database)

    def execute_write(self, callback, *args):
        return callback(self._transaction, *args)


class FakeDatabase:
    def __init__(self):
        self.evidence_ids = {"ev-1", "ev-2"}
        self.entity_ids = {"entity-a", "entity-b"}
        self.edge_ref_ids = {"rel-1", "rel-2"}
        self.findings = {}
        self.queries = []


def _finding(
    *,
    finding_id="candidate-1",
    rule_id="fixture_rule_v1",
    dataset="synthetic_demo",
    evidence_ids=None,
    subject_entity_ids=None,
    subject_relationship_ids=None,
    detected_at="2024-01-01T00:00:00Z",
    explanation="A fixture-backed pattern.",
):
    return Finding(
        finding_id=finding_id,
        dataset=dataset,
        rule_id=rule_id,
        rule_name="Fixture Rule",
        subject_entity_ids=subject_entity_ids or ["entity-b", "entity-a"],
        subject_relationship_ids=subject_relationship_ids or ["rel-2", "rel-1"],
        explanation=explanation,
        triggering_values={"observed": 3},
        evidence_ids=evidence_ids or ["ev-2", "ev-1"],
        disclaimer=INVESTIGATIVE_LEAD_DISCLAIMER,
        detected_at=detected_at,
    )


def _patch_graph(monkeypatch, database=None):
    database = database or FakeDatabase()

    @contextmanager
    def fake_get_session():
        yield FakeSession(database)

    monkeypatch.setattr(engine_module, "get_session", fake_get_session)
    return database


def test_persist_findings_upserts_by_sorted_identity_and_preserves_id(monkeypatch):
    database = _patch_graph(monkeypatch)
    first = _finding()
    second = _finding(
        finding_id="new-candidate-id",
        detected_at="2024-02-01T00:00:00Z",
        explanation="Updated instance explanation.",
    )

    persisted_first = persist_findings([first])
    persisted_second = persist_findings([second])

    assert persisted_first[0].finding_id == "candidate-1"
    assert persisted_second[0].finding_id == "candidate-1"
    assert persisted_second[0].subject_entity_ids == ["entity-a", "entity-b"]
    assert persisted_second[0].subject_relationship_ids == ["rel-1", "rel-2"]
    assert len(database.findings) == 1
    saved = next(iter(database.findings.values()))
    assert saved["explanation"] == "Updated instance explanation."
    assert saved["detected_at"] == "2024-02-01T00:00:00Z"
    assert saved["disclaimer"] == INVESTIGATIVE_LEAD_DISCLAIMER
    assert any("MERGE (finding:Finding" in query for query, _ in database.queries)
    assert any("MERGE (evidence)-[:SUPPORTS]->(finding)" in query for query, _ in database.queries)
    assert any("MERGE (finding)-[:CONCERNS]->(entity)" in query for query, _ in database.queries)
    assert any("MERGE (finding)-[:CONCERNS]->(edge_ref)" in query for query, _ in database.queries)


def test_persist_findings_empty_input_is_a_no_op(monkeypatch):
    def unexpected_session():
        raise AssertionError("empty persistence should not open a graph session")

    monkeypatch.setattr(engine_module, "get_session", unexpected_session)

    assert persist_findings([]) == []


def test_persist_findings_rejects_empty_evidence_before_graph_access(monkeypatch):
    def unexpected_session():
        raise AssertionError("invalid Finding should be rejected before graph access")

    monkeypatch.setattr(engine_module, "get_session", unexpected_session)
    finding = _finding().model_copy(update={"evidence_ids": []})

    with pytest.raises(ValueError, match="at least one evidence_id"):
        persist_findings([finding])


def test_persist_findings_rejects_wrong_disclaimer_before_graph_access(monkeypatch):
    def unexpected_session():
        raise AssertionError("invalid Finding should be rejected before graph access")

    monkeypatch.setattr(engine_module, "get_session", unexpected_session)
    finding = _finding().model_copy(update={"disclaimer": "reworded disclaimer"})

    with pytest.raises(ValueError, match="fixed literal"):
        persist_findings([finding])


def test_persist_findings_rejects_mixed_dataset_batch_before_graph_access(monkeypatch):
    def unexpected_session():
        raise AssertionError("mixed datasets should be rejected before graph access")

    monkeypatch.setattr(engine_module, "get_session", unexpected_session)

    with pytest.raises(ValueError, match="exactly one dataset"):
        persist_findings([_finding(), _finding(finding_id="candidate-2", dataset="live_public")])


def test_persist_findings_fails_before_upsert_for_missing_evidence(monkeypatch):
    database = FakeDatabase()
    database.evidence_ids.remove("ev-2")
    _patch_graph(monkeypatch, database)

    with pytest.raises(ValueError, match="Evidence IDs"):
        persist_findings([_finding()])

    assert not database.findings
    assert not any("MERGE (finding:Finding" in query for query, _ in database.queries)


def test_persist_findings_fails_before_upsert_for_cross_dataset_entity(monkeypatch):
    database = FakeDatabase()
    database.entity_ids.remove("entity-b")
    _patch_graph(monkeypatch, database)

    with pytest.raises(ValueError, match="CanonicalEntity IDs"):
        persist_findings([_finding()])

    assert not database.findings


def test_persist_findings_propagates_graph_transaction_failure(monkeypatch):
    class FailedSession:
        def execute_write(self, callback, *args):
            raise RuntimeError("graph unavailable")

    @contextmanager
    def fake_get_session():
        yield FailedSession()

    monkeypatch.setattr(engine_module, "get_session", fake_get_session)

    with pytest.raises(RuntimeError, match="graph unavailable"):
        persist_findings([_finding()])


def test_engine_runs_rules_independently_with_same_scope_and_persists_results(monkeypatch):
    calls = []
    first_finding = _finding()
    second_finding = _finding(finding_id="candidate-2", rule_id="other_rule")

    class FixtureRule:
        def __init__(self, findings):
            self.findings = findings

        def evaluate(self, dataset, as_of):
            calls.append((dataset, as_of, self.findings))
            return self.findings

    persisted = []

    def fake_persist(findings):
        persisted.extend(findings)
        return findings

    monkeypatch.setattr(engine_module, "persist_findings", fake_persist)
    engine = PatternDetectionEngine(
        rules=[FixtureRule([first_finding]), FixtureRule([second_finding])]
    )

    result = engine.run("synthetic_demo", "2024-01-31T00:00:00Z")

    assert result == [first_finding, second_finding]
    assert [call[:2] for call in calls] == [
        ("synthetic_demo", "2024-01-31T00:00:00Z"),
        ("synthetic_demo", "2024-01-31T00:00:00Z"),
    ]
    assert persisted == [first_finding, second_finding]


def test_engine_empty_rules_return_empty_without_graph_access(monkeypatch):
    def unexpected_session():
        raise AssertionError("empty detection should not open a graph session")

    monkeypatch.setattr(engine_module, "get_session", unexpected_session)

    assert PatternDetectionEngine(rules=[]).run("synthetic_demo") == []


def test_engine_rejects_invalid_dataset_before_running_rules():
    class UnexpectedRule:
        def evaluate(self, dataset, as_of):
            raise AssertionError("rule should not run for invalid dataset")

    with pytest.raises(ValueError, match="dataset must"):
        PatternDetectionEngine(rules=[UnexpectedRule()]).run("combined")


def test_engine_does_not_persist_when_a_rule_fails(monkeypatch):
    def unexpected_persist(findings):
        raise AssertionError("partial rule results must not be persisted")

    class FailedRule:
        def evaluate(self, dataset, as_of):
            raise RuntimeError("rule failed")

    monkeypatch.setattr(engine_module, "persist_findings", unexpected_persist)

    with pytest.raises(RuntimeError, match="rule failed"):
        PatternDetectionEngine(rules=[FailedRule()]).run("synthetic_demo")
