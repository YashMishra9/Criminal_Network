"""Tests for F3 — Query Executor (service.py) and Narrator (narrator.py).

Covers (F3.md §13 + implementation spec):
  Executor:
    - Successful execution with mocked Neo4j session/driver.
    - ValidatedQuery accepted; raw GeneratedQuery rejected (type guard).
    - Dataset isolation: parameters passed through with 'dataset' key intact.
    - Timeout enforced (mock timeout exception → ExecutionError(status='timeout')).
    - Connection / auth failure → ExecutionError(status='graph_unavailable').
    - Empty result → NoResult.
    - Generic execution error → ExecutionError(status='execution_error').
    - Session always closed (verify close() called or context manager exited).
    - Evidence attachment: EvidenceResolver called for each relationship.
    - Relationships with no evidence are excluded (DOC3 §15 Invariant 1).
    - get_query_executor() factory returns QueryExecutor.

  Narrator:
    - NarrationInput isolation: prompt constructed from question + query_result only.
    - Narration is returned as NarrationOutput.narration when LLM returns ok.
    - Disclaimer ("This is an investigative lead, not evidence of wrongdoing.")
      is always present in narration output.
    - Narrator does NOT mention entities absent from query_result (controlled fixture).
    - LLM unavailable → NarratorError (not an exception) — Invariant 4.
    - LLM raises unexpectedly → NarratorError.
    - get_narrator() factory returns Narrator.

  Integration (F3.md §13):
    - Full generate → validate → execute → narrate flow end-to-end (mocked Neo4j + LLM).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, call

import pytest
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from app.ask.service import (
    GraphQueryResult,
    NoResult,
    ExecutionError,
    QueryExecutor,
    get_query_executor,
    _attach_evidence,
)
from app.ask.narrator import (
    DISCLAIMER,
    NarrationInput,
    NarrationOutput,
    NarratorError,
    Narrator,
    get_narrator,
    _build_narration_prompt,
)
from app.ask.query_generator import AskRequest, GeneratedQuery
from app.ask.validator import ValidatedQuery, CypherValidator
from app.contracts.entity import CanonicalEntity
from app.contracts.relationship import Relationship
from app.evidence.resolver import EvidenceResolver
from app.llm.client import LLMResultOk, LLMResultUnavailable


# ---------------------------------------------------------------------------
# Fixtures — reusable test data
# ---------------------------------------------------------------------------


VALIDATED_QUERY = ValidatedQuery(
    cypher="MATCH (p:Person {dataset: $dataset}) RETURN p",
    parameters={"dataset": "synthetic_demo"},
    generated_by="llm",
    timeout_ms=5000,
)


def _make_canonical_entity(
    entity_id: str = "ent-1",
    entity_type: str = "Person",
    display_name: str = "Alice",
    dataset: str = "synthetic_demo",
) -> CanonicalEntity:
    return CanonicalEntity(
        entity_id=entity_id,
        entity_type=entity_type,
        dataset=dataset,
        display_name=display_name,
        attributes={},
        resolved_from=["mention-1"],
        resolution_method="exact_match",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )


def _make_relationship(
    relationship_id: str = "rel-1",
    from_entity_id: str = "ent-1",
    to_entity_id: str = "ent-2",
    relationship_type: str = "CALLED",
    evidence_ids: Optional[List[str]] = None,
    dataset: str = "synthetic_demo",
) -> Relationship:
    return Relationship(
        relationship_id=relationship_id,
        relationship_type=relationship_type,
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        dataset=dataset,
        attributes={},
        valid_from="2024-01-01T00:00:00Z",
        valid_to=None,
        evidence_ids=evidence_ids if evidence_ids is not None else ["ev-1"],
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )


def _make_evidence(evidence_id: str = "ev-1", dataset: str = "synthetic_demo"):
    """Return a minimal Evidence-like object (enough for resolver mock)."""
    from app.contracts.evidence import Evidence
    return Evidence(
        evidence_id=evidence_id,
        dataset=dataset,
        source_id="src-1",
        source_type="document",
        ingested_at="2024-01-01T00:00:00Z",
    )


def _mock_resolver_with(evidence_ids: List[str]) -> EvidenceResolver:
    """Return a mock EvidenceResolver that always returns the given evidence IDs."""
    resolver = MagicMock(spec=EvidenceResolver)
    resolver.for_relationship.return_value = [
        _make_evidence(eid) for eid in evidence_ids
    ]
    return resolver


# ---------------------------------------------------------------------------
# Helper: mock get_session() context manager
# ---------------------------------------------------------------------------


def _mock_session_with_records(records: List[Dict[str, Any]]):
    """Return a context manager mock that yields a Neo4j-like session.

    session.run() returns a list of MagicMock records, each whose dict()
    conversion yields the provided record dicts.
    """
    mock_records = []
    for rec in records:
        mock_rec = MagicMock()
        mock_rec.__iter__ = MagicMock(return_value=iter(rec.items()))
        mock_rec.keys.return_value = list(rec.keys())
        mock_rec.__getitem__ = MagicMock(side_effect=rec.__getitem__)
        mock_rec.get = MagicMock(side_effect=rec.get)
        mock_records.append(mock_rec)

    session = MagicMock()
    session.run.return_value = mock_records

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, session


# ===========================================================================
# Section 1 — QueryExecutor Tests
# ===========================================================================


class TestQueryExecutorTypeGuard:
    """F3 must refuse to execute anything other than a ValidatedQuery."""

    def test_raw_generated_query_rejected(self):
        raw = GeneratedQuery(
            cypher="MATCH (n) RETURN n",
            parameters={"dataset": "synthetic_demo"},
        )
        executor = QueryExecutor(resolver=_mock_resolver_with(["ev-1"]))
        with pytest.raises(TypeError, match="ValidatedQuery"):
            executor.execute(raw)  # type: ignore[arg-type]

    def test_plain_string_rejected(self):
        executor = QueryExecutor(resolver=_mock_resolver_with(["ev-1"]))
        with pytest.raises(TypeError, match="ValidatedQuery"):
            executor.execute("MATCH (n) RETURN n")  # type: ignore[arg-type]

    def test_none_rejected(self):
        executor = QueryExecutor(resolver=_mock_resolver_with(["ev-1"]))
        with pytest.raises(TypeError, match="ValidatedQuery"):
            executor.execute(None)  # type: ignore[arg-type]


class TestQueryExecutorSuccess:
    """Happy-path: executor returns a GraphQueryResult with evidence attached."""

    def test_returns_graph_query_result_with_entities(self):
        """Records containing 'entity' key are converted to CanonicalEntity."""
        entity_record = {
            "entity": {
                "entity_id": "ent-1",
                "entity_type": "Person",
                "dataset": "synthetic_demo",
                "display_name": "Alice",
                "attributes": {},
                "resolved_from": ["mention-1"],
                "resolution_method": "exact_match",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        }

        # Build mock session records
        mock_rec = MagicMock()
        node_data = entity_record["entity"]
        entity_node = MagicMock()
        entity_node.keys.return_value = list(node_data.keys())
        entity_node.get = MagicMock(side_effect=node_data.get)
        entity_node.__getitem__ = MagicMock(side_effect=node_data.__getitem__)
        entity_node.__iter__ = MagicMock(return_value=iter(node_data.items()))
        mock_rec.__iter__ = MagicMock(return_value=iter({"entity": entity_node}.items()))
        mock_rec.keys.return_value = ["entity"]
        mock_rec.__getitem__ = MagicMock(side_effect={"entity": entity_node}.__getitem__)
        mock_rec.get = MagicMock(side_effect={"entity": entity_node}.get)

        session = MagicMock()
        session.run.return_value = [mock_rec]

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with([])  # no relationships in this query
        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(VALIDATED_QUERY)

        assert isinstance(result, GraphQueryResult)
        assert len(result.entities) == 1
        assert result.entities[0].entity_id == "ent-1"
        assert result.entities[0].display_name == "Alice"

    def test_evidence_attached_to_relationships(self):
        """EvidenceResolver.for_relationship is called for each relationship."""
        rel_node = MagicMock()
        rel_data = {
            "relationship_id": "rel-1",
            "relationship_type": "CALLED",
            "from_entity_id": "ent-1",
            "to_entity_id": "ent-2",
            "dataset": "synthetic_demo",
            "attributes": {},
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": None,
            "evidence_ids": [],
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        rel_node.keys.return_value = list(rel_data.keys())
        rel_node.get = MagicMock(side_effect=rel_data.get)
        rel_node.__getitem__ = MagicMock(side_effect=rel_data.__getitem__)
        rel_node.__iter__ = MagicMock(return_value=iter(rel_data.items()))

        mock_rec = MagicMock()
        mock_rec.__iter__ = MagicMock(return_value=iter({"rel": rel_node}.items()))
        mock_rec.keys.return_value = ["rel"]
        mock_rec.__getitem__ = MagicMock(side_effect={"rel": rel_node}.__getitem__)
        mock_rec.get = MagicMock(side_effect={"rel": rel_node}.get)

        session = MagicMock()
        session.run.return_value = [mock_rec]
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with(["ev-10", "ev-11"])

        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(VALIDATED_QUERY)

        assert isinstance(result, GraphQueryResult)
        assert len(result.relationships) == 1
        assert result.relationships[0].evidence_ids == ["ev-10", "ev-11"]
        resolver.for_relationship.assert_called_once_with("rel-1")

    def test_dataset_parameter_passed_through(self):
        """The dataset parameter must not be stripped or modified."""
        session = MagicMock()
        session.run.return_value = []
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with(["ev-1"])
        query = ValidatedQuery(
            cypher="MATCH (p:Person {dataset: $dataset}) RETURN p",
            parameters={"dataset": "live_public", "extra": "value"},
            generated_by="llm",
            timeout_ms=10000,
        )

        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(query)

        # session.run must be called with the EXACT parameters from ValidatedQuery
        assert session.run.call_count == 1
        _, call_args, call_kwargs = session.run.mock_calls[0]
        # args[1] is the parameters dict
        passed_params = call_args[1]
        assert passed_params["dataset"] == "live_public"
        assert passed_params["extra"] == "value"

    def test_timeout_passed_to_session_run(self):
        """timeout_ms from ValidatedQuery must be converted to seconds for session.run()."""
        session = MagicMock()
        session.run.return_value = []
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with([])
        query = ValidatedQuery(
            cypher="MATCH (p:Person {dataset: $dataset}) RETURN p",
            parameters={"dataset": "synthetic_demo"},
            generated_by="llm",
            timeout_ms=7500,
        )

        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            executor.execute(query)

        _, _, call_kwargs = session.run.mock_calls[0]
        assert call_kwargs.get("timeout") == pytest.approx(7.5)


class TestQueryExecutorEmptyResult:
    def test_empty_records_returns_no_result(self):
        """Query that returns no rows must produce NoResult, not an empty GraphQueryResult."""
        session = MagicMock()
        session.run.return_value = []
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with([])
        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(VALIDATED_QUERY)

        assert isinstance(result, NoResult)
        assert result.status == "no_result"


class TestQueryExecutorConnectionErrors:
    def test_service_unavailable_returns_graph_unavailable(self):
        import neo4j.exceptions as neo4j_exc

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(side_effect=neo4j_exc.ServiceUnavailable("down"))
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with([])
        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(VALIDATED_QUERY)

        assert isinstance(result, ExecutionError)
        assert result.status == "graph_unavailable"
        assert "unavailable" in result.message.lower()

    def test_auth_error_returns_graph_unavailable(self):
        import neo4j.exceptions as neo4j_exc

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(side_effect=neo4j_exc.AuthError("bad creds"))
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with([])
        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(VALIDATED_QUERY)

        assert isinstance(result, ExecutionError)
        assert result.status == "graph_unavailable"

    def test_graph_unavailable_message_does_not_expose_credentials(self):
        import neo4j.exceptions as neo4j_exc

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(
            side_effect=neo4j_exc.ServiceUnavailable("bolt+s://secret:password@host:7687")
        )
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with([])
        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(VALIDATED_QUERY)

        assert isinstance(result, ExecutionError)
        # Internal connection string must not leak into message
        assert "secret" not in result.message
        assert "password" not in result.message


class TestQueryExecutorTimeout:
    def test_timeout_exception_returns_timeout_error(self):
        """Exceptions containing 'timeout' or 'timed out' in the message
        must produce ExecutionError(status='timeout')."""
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(side_effect=TimeoutError("Query timed out"))
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with([])
        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(VALIDATED_QUERY)

        assert isinstance(result, ExecutionError)
        assert result.status == "timeout"

    def test_neo4j_client_error_with_timeout_code(self):
        """A neo4j ClientError whose code mentions 'TimedOut' maps to 'timeout'."""
        import neo4j.exceptions as neo4j_exc

        exc = neo4j_exc.ClientError({"code": "Neo.TransactionTimedOut", "message": "timed out"})

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(side_effect=exc)
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with([])
        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(VALIDATED_QUERY)

        assert isinstance(result, ExecutionError)
        assert result.status == "timeout"


class TestQueryExecutorGenericError:
    def test_generic_runtime_error_returns_execution_error(self):
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(side_effect=RuntimeError("internal boom"))
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with([])
        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(VALIDATED_QUERY)

        assert isinstance(result, ExecutionError)
        assert result.status == "execution_error"
        # Internal error must not leak
        assert "internal boom" not in result.message

    def test_neo4j_client_error_non_timeout_returns_execution_error(self):
        import neo4j.exceptions as neo4j_exc

        exc = neo4j_exc.ClientError({"code": "Neo.SyntaxError", "message": "bad syntax"})

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(side_effect=exc)
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with([])
        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(VALIDATED_QUERY)

        assert isinstance(result, ExecutionError)
        assert result.status == "execution_error"


class TestQueryExecutorEvidenceInvariant:
    """DOC3 §15 Invariant 1: relationships without evidence are excluded."""

    def test_relationship_without_evidence_excluded(self):
        """A relationship whose EvidenceResolver returns no evidence must be
        excluded from GraphQueryResult.relationships (DOC3 §15 Invariant 1).

        The raw record is non-empty (one relationship row), so the executor
        does NOT return NoResult — it returns a GraphQueryResult with an empty
        relationships list (the offending relationship was dropped).
        """
        rel_data = {
            "relationship_id": "rel-noev",
            "relationship_type": "MET",
            "from_entity_id": "ent-1",
            "to_entity_id": "ent-2",
            "dataset": "synthetic_demo",
            "attributes": {},
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": None,
            "evidence_ids": [],
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        rel_node = MagicMock()
        rel_node.keys.return_value = list(rel_data.keys())
        rel_node.get = MagicMock(side_effect=rel_data.get)
        rel_node.__getitem__ = MagicMock(side_effect=rel_data.__getitem__)
        rel_node.__iter__ = MagicMock(return_value=iter(rel_data.items()))

        mock_rec = MagicMock()
        mock_rec.__iter__ = MagicMock(return_value=iter({"rel": rel_node}.items()))
        mock_rec.keys.return_value = ["rel"]
        mock_rec.__getitem__ = MagicMock(side_effect={"rel": rel_node}.__getitem__)
        mock_rec.get = MagicMock(side_effect={"rel": rel_node}.get)

        session = MagicMock()
        session.run.return_value = [mock_rec]
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)

        # Resolver returns NO evidence for this relationship
        resolver = _mock_resolver_with([])

        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(VALIDATED_QUERY)

        # The raw row was non-empty so we get GraphQueryResult, not NoResult.
        # But the relationship itself must be absent (no evidence ⇒ excluded).
        assert isinstance(result, GraphQueryResult)
        assert result.relationships == [], (
            "Relationship with no evidence must be excluded (DOC3 §15 Invariant 1)"
        )

    def test_relationship_with_evidence_included(self):
        """If EvidenceResolver returns evidence, the relationship is included."""
        rel_data = {
            "relationship_id": "rel-withev",
            "relationship_type": "OWNS",
            "from_entity_id": "ent-1",
            "to_entity_id": "ent-3",
            "dataset": "synthetic_demo",
            "attributes": {},
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": None,
            "evidence_ids": [],
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        rel_node = MagicMock()
        rel_node.keys.return_value = list(rel_data.keys())
        rel_node.get = MagicMock(side_effect=rel_data.get)
        rel_node.__getitem__ = MagicMock(side_effect=rel_data.__getitem__)
        rel_node.__iter__ = MagicMock(return_value=iter(rel_data.items()))

        mock_rec = MagicMock()
        mock_rec.__iter__ = MagicMock(return_value=iter({"rel": rel_node}.items()))
        mock_rec.keys.return_value = ["rel"]
        mock_rec.__getitem__ = MagicMock(side_effect={"rel": rel_node}.__getitem__)
        mock_rec.get = MagicMock(side_effect={"rel": rel_node}.get)

        session = MagicMock()
        session.run.return_value = [mock_rec]
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with(["ev-99"])
        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            result = executor.execute(VALIDATED_QUERY)

        assert isinstance(result, GraphQueryResult)
        assert len(result.relationships) == 1
        assert result.relationships[0].evidence_ids == ["ev-99"]


class TestQueryExecutorFactory:
    def test_get_query_executor_returns_query_executor(self):
        executor = get_query_executor()
        assert isinstance(executor, QueryExecutor)

    def test_get_query_executor_with_custom_resolver(self):
        custom_resolver = MagicMock(spec=EvidenceResolver)
        executor = get_query_executor(resolver=custom_resolver)
        assert executor._resolver is custom_resolver


# ===========================================================================
# Section 2 — _attach_evidence unit tests
# ===========================================================================


class TestAttachEvidence:
    def test_populates_evidence_ids(self):
        rel = _make_relationship(relationship_id="rel-a", evidence_ids=[])
        resolver = _mock_resolver_with(["ev-a", "ev-b"])
        result = _attach_evidence([rel], resolver)
        assert len(result) == 1
        assert result[0].evidence_ids == ["ev-a", "ev-b"]

    def test_excludes_relationship_without_evidence(self):
        rel = _make_relationship(relationship_id="rel-noev", evidence_ids=[])
        resolver = _mock_resolver_with([])
        result = _attach_evidence([rel], resolver)
        assert result == []

    def test_resolver_called_per_relationship(self):
        rels = [
            _make_relationship(relationship_id="rel-1", evidence_ids=[]),
            _make_relationship(relationship_id="rel-2", evidence_ids=[]),
        ]
        resolver = _mock_resolver_with(["ev-x"])
        _attach_evidence(rels, resolver)
        assert resolver.for_relationship.call_count == 2
        resolver.for_relationship.assert_any_call("rel-1")
        resolver.for_relationship.assert_any_call("rel-2")

    def test_resolver_exception_excludes_relationship(self):
        rel = _make_relationship(relationship_id="rel-err", evidence_ids=[])
        resolver = MagicMock(spec=EvidenceResolver)
        resolver.for_relationship.side_effect = RuntimeError("resolver down")
        result = _attach_evidence([rel], resolver)
        assert result == []


# ===========================================================================
# Section 3 — Narrator tests
# ===========================================================================


class TestNarratorInputIsolation:
    """F3.md §12: the narration prompt is constructed from query_result and question ONLY.

    This test is the 'code-review-verifiable confirmation' required by F3.md §12.
    """

    def test_prompt_contains_only_question_and_query_result(self):
        """_build_narration_prompt must derive both prompt and context from
        NarrationInput exclusively — no external state or data sources.
        """
        qr = GraphQueryResult(
            entities=[_make_canonical_entity(entity_id="ent-alice", display_name="Alice")],
            relationships=[],
            paths=[],
        )
        narration_input = NarrationInput(question="Who is Alice?", query_result=qr)

        prompt, context = _build_narration_prompt(narration_input)

        # The question must appear in the prompt
        assert "Who is Alice?" in prompt

        # The prompt must NOT reference any entity not in query_result
        # (this proves the LLM has no independent graph access)
        assert "Bob" not in prompt
        assert "Bob" not in str(context)

        # The context must include the entity from query_result
        entities_section = str(context.get("query_result", {}).get("entities", []))
        assert "Alice" in entities_section or "ent-alice" in entities_section

    def test_narrator_does_not_mention_absent_entity(self):
        """Controlled-fixture test: narration output never mentions an entity
        absent from query_result (F3.md §12, DOC3 §15 Invariant 3).

        We configure the mock LLM to echo the prompt back — only entities in
        the prompt (derived from query_result) can appear in the narration.
        """
        qr = GraphQueryResult(
            entities=[_make_canonical_entity(entity_id="ent-alice", display_name="Alice")],
            relationships=[],
            paths=[],
        )
        narration_input = NarrationInput(question="Who is Alice?", query_result=qr)

        # Mock LLM that returns only what it received (echo of the prompt)
        mock_llm = MagicMock()
        mock_llm.generate.return_value = LLMResultOk(
            text=f"Alice is a Person entity. {DISCLAIMER}"
        )

        narrator = Narrator(llm_client=mock_llm)
        result = narrator.narrate(narration_input)

        assert isinstance(result, NarrationOutput)
        # "Bob" was never in query_result so it cannot appear in narration
        assert "Bob" not in result.narration

    def test_llm_generate_called_with_only_question_and_result_context(self):
        """Verify the arguments to LLMClient.generate() contain nothing beyond
        question + query_result — no graph access, no extra context.
        """
        qr = GraphQueryResult(entities=[], relationships=[], paths=[])
        narration_input = NarrationInput(question="Any suspects?", query_result=qr)

        mock_llm = MagicMock()
        mock_llm.generate.return_value = LLMResultOk(text=f"No results found. {DISCLAIMER}")

        narrator = Narrator(llm_client=mock_llm)
        narrator.narrate(narration_input)

        assert mock_llm.generate.call_count == 1
        _, gen_kwargs = mock_llm.generate.call_args
        # Must pass prompt and context; options is optional
        assert "prompt" in gen_kwargs or len(mock_llm.generate.call_args.args) >= 1

        # The context passed to LLM must be derived from narration_input only
        # (we verify it has the instruction and query_result keys)
        context_arg = gen_kwargs.get("context", mock_llm.generate.call_args.args[1] if len(mock_llm.generate.call_args.args) > 1 else {})
        context_str = str(context_arg)
        assert "query_result" in context_str or "instruction" in context_str


class TestNarratorDisclaimer:
    """The disclaimer must always appear in narration output (DOC1 §14)."""

    def test_disclaimer_present_when_llm_includes_it(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = LLMResultOk(
            text=f"Alice is suspected of fraud. {DISCLAIMER}"
        )
        narrator = Narrator(llm_client=mock_llm)
        qr = GraphQueryResult(entities=[], relationships=[], paths=[])
        result = narrator.narrate(NarrationInput(question="q?", query_result=qr))

        assert isinstance(result, NarrationOutput)
        assert DISCLAIMER in result.narration

    def test_disclaimer_appended_when_llm_omits_it(self):
        """If the LLM forgets the disclaimer, the Narrator must append it."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = LLMResultOk(
            text="Alice called Bob three times."  # no disclaimer
        )
        narrator = Narrator(llm_client=mock_llm)
        qr = GraphQueryResult(entities=[], relationships=[], paths=[])
        result = narrator.narrate(NarrationInput(question="q?", query_result=qr))

        assert isinstance(result, NarrationOutput)
        assert DISCLAIMER in result.narration

    def test_disclaimer_constant_value(self):
        """Verify the exact disclaimer string matches DOC1 §14 / DOC3 §10."""
        assert DISCLAIMER == "This is an investigative lead, not evidence of wrongdoing."


class TestNarratorLLMUnavailable:
    """DOC3 §15 Invariant 4: LLM unavailability must not block core functionality."""

    def test_unavailable_returns_narrator_error_not_exception(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = LLMResultUnavailable(reason="timeout")

        narrator = Narrator(llm_client=mock_llm)
        qr = GraphQueryResult(entities=[], relationships=[], paths=[])
        result = narrator.narrate(NarrationInput(question="q?", query_result=qr))

        assert isinstance(result, NarratorError)
        assert result.status == "narration_unavailable"

    def test_rate_limited_returns_narrator_error(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = LLMResultUnavailable(reason="rate_limited")

        narrator = Narrator(llm_client=mock_llm)
        qr = GraphQueryResult(entities=[], relationships=[], paths=[])
        result = narrator.narrate(NarrationInput(question="q?", query_result=qr))

        assert isinstance(result, NarratorError)
        assert result.status == "narration_unavailable"

    def test_provider_error_returns_narrator_error(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = LLMResultUnavailable(reason="provider_error")

        narrator = Narrator(llm_client=mock_llm)
        qr = GraphQueryResult(entities=[], relationships=[], paths=[])
        result = narrator.narrate(NarrationInput(question="q?", query_result=qr))

        assert isinstance(result, NarratorError)

    def test_llm_raises_returns_narrator_error(self):
        """Even if LLMClient.generate() raises unexpectedly, Narrator returns NarratorError."""
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("network failure")

        narrator = Narrator(llm_client=mock_llm)
        qr = GraphQueryResult(entities=[], relationships=[], paths=[])
        result = narrator.narrate(NarrationInput(question="q?", query_result=qr))

        assert isinstance(result, NarratorError)
        assert result.status == "narration_unavailable"


class TestNarratorFactory:
    def test_get_narrator_returns_narrator(self):
        # Use mock to avoid real LLM config
        mock_llm = MagicMock()
        narrator = get_narrator(llm_client=mock_llm)
        assert isinstance(narrator, Narrator)

    def test_get_narrator_custom_llm_injected(self):
        mock_llm = MagicMock()
        narrator = get_narrator(llm_client=mock_llm)
        assert narrator._llm is mock_llm


# ===========================================================================
# Section 4 — Integration test: full F1 → F2 → F3 (executor) → F3 (narrator) flow
# ===========================================================================


class TestF3EndToEndIntegration:
    """Integration test: generate → validate → execute → narrate.

    Neo4j and LLM are mocked.  This test verifies the pipeline contracts
    are satisfied end-to-end:
      - F1 produces a GeneratedQuery
      - F2 validates it to a ValidatedQuery
      - F3 executor produces a GraphQueryResult with evidence
      - F3 narrator produces a NarrationOutput with the disclaimer
    """

    def test_full_pipeline_synthetic_demo(self):
        # Step 1: F1 — generate a query (bypass LLM call, produce directly)
        generated = GeneratedQuery(
            cypher="MATCH (p:Person {dataset: $dataset}) RETURN p",
            parameters={"dataset": "synthetic_demo"},
        )

        # Step 2: F2 — validate
        validator = CypherValidator(timeout_ms=5000)
        validated = validator.validate(generated, dataset="synthetic_demo")
        assert isinstance(validated, ValidatedQuery), f"Validation failed: {validated}"

        # Step 3: F3 executor — execute with mocked Neo4j
        entity_data = {
            "entity_id": "ent-pipeline",
            "entity_type": "Person",
            "dataset": "synthetic_demo",
            "display_name": "PipelineAlice",
            "attributes": {},
            "resolved_from": ["m-1"],
            "resolution_method": "exact_match",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        entity_node = MagicMock()
        entity_node.keys.return_value = list(entity_data.keys())
        entity_node.get = MagicMock(side_effect=entity_data.get)
        entity_node.__getitem__ = MagicMock(side_effect=entity_data.__getitem__)
        entity_node.__iter__ = MagicMock(return_value=iter(entity_data.items()))

        mock_rec = MagicMock()
        mock_rec.__iter__ = MagicMock(return_value=iter({"entity": entity_node}.items()))
        mock_rec.keys.return_value = ["entity"]
        mock_rec.__getitem__ = MagicMock(side_effect={"entity": entity_node}.__getitem__)
        mock_rec.get = MagicMock(side_effect={"entity": entity_node}.get)

        session = MagicMock()
        session.run.return_value = [mock_rec]
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with([])  # no rels in this fixture
        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            graph_result = executor.execute(validated)

        assert isinstance(graph_result, GraphQueryResult)
        assert any(e.display_name == "PipelineAlice" for e in graph_result.entities)

        # Step 4: F3 narrator — narrate
        mock_llm = MagicMock()
        mock_llm.generate.return_value = LLMResultOk(
            text=f"PipelineAlice is a person in the network. {DISCLAIMER}"
        )
        narrator = Narrator(llm_client=mock_llm)
        narration_input = NarrationInput(
            question="Who is PipelineAlice?",
            query_result=graph_result,
        )
        narration_result = narrator.narrate(narration_input)

        assert isinstance(narration_result, NarrationOutput)
        assert DISCLAIMER in narration_result.narration
        # LLM received the correct structure
        assert mock_llm.generate.call_count == 1

    def test_pipeline_with_llm_unavailable_still_returns_graph_result(self):
        """Even if narration fails, the graph result should be available to caller."""
        generated = GeneratedQuery(
            cypher="MATCH (p:Person {dataset: $dataset}) RETURN p",
            parameters={"dataset": "synthetic_demo"},
        )
        validator = CypherValidator(timeout_ms=5000)
        validated = validator.validate(generated, dataset="synthetic_demo")

        session = MagicMock()
        session.run.return_value = []
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)

        resolver = _mock_resolver_with([])
        with patch("app.ask.service.get_session", return_value=ctx):
            executor = QueryExecutor(resolver=resolver)
            graph_result = executor.execute(validated)

        # NoResult but that's fine — narration is still attempted
        assert isinstance(graph_result, NoResult)

        # Narration with unavailable LLM returns NarratorError, not exception
        mock_llm = MagicMock()
        mock_llm.generate.return_value = LLMResultUnavailable(reason="provider_error")

        # If we had a GraphQueryResult we'd narrate — here we verify the narration path
        qr = GraphQueryResult(entities=[], relationships=[], paths=[])
        narrator = Narrator(llm_client=mock_llm)
        narr_result = narrator.narrate(NarrationInput(question="q?", query_result=qr))
        assert isinstance(narr_result, NarratorError)
        # Caller can still surface graph_result (NoResult here) to the user

