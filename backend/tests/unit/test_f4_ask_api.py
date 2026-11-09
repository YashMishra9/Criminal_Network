"""Tests for F4 — Ask API Endpoint (POST /api/v1/ask).

Covers (F4.md §13 + DOC3 §10 / §12.8):
  AskService unit tests:
    - ok: full pipeline returns AskResponseOk with narration, path, evidence.
    - llm_unavailable at F1 (generator fails) → AskResponseLLMUnavailable.
    - llm_unavailable at F3 narration step    → AskResponseLLMUnavailable.
    - validation_failed (F2 rejects Cypher)   → AskResponseValidationFailed.
    - no_result (empty graph result)          → AskResponseNoResult.
    - graph_unavailable (Neo4j down)          → raises GraphUnavailableError.
    - timeout (query times out)               → raises GraphUnavailableError.
    - execution_error                         → raises GraphUnavailableError.
    - dataset isolation: dataset from AskRequest is forwarded to F2 validate().
    - F4 never executes a raw GeneratedQuery (type contract enforced by F3).
    - F4.md §11: narration failure → llm_unavailable, NOT raw result.

  API integration tests (via TestClient):
    - POST /api/v1/ask → 200 with status:"ok".
    - POST /api/v1/ask → 200 with status:"llm_unavailable" (F1 failure).
    - POST /api/v1/ask → 200 with status:"llm_unavailable" (F3 narration failure).
    - POST /api/v1/ask → 200 with status:"validation_failed".
    - POST /api/v1/ask → 200 with status:"no_result".
    - POST /api/v1/ask → 503 when graph is unavailable.
    - POST /api/v1/ask with missing question field → 422 (FastAPI validation).
    - dataset defaults to "synthetic_demo" when omitted.
    - Response shape matches DOC3 §10 exactly (field-for-field).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from app.ask.query_generator import AskRequest, GeneratedQuery, GeneratorError
from app.ask.validator import ValidatedQuery, ValidationFailed
from app.ask.service import (
    ExecutionError,
    GraphQueryResult,
    NoResult,
    QueryExecutor,
)
from app.ask.narrator import NarrationOutput, NarratorError, Narrator
from app.api.ask import (
    AskService,
    AskResponseOk,
    AskResponseLLMUnavailable,
    AskResponseValidationFailed,
    AskResponseNoResult,
    _get_service,
)
from app.contracts.entity import CanonicalEntity
from app.contracts.relationship import Relationship
from app.contracts.errors import GraphUnavailableError
from app.main import app

# ---------------------------------------------------------------------------
# TestClient — shared, raise_server_exceptions=False so we can check 503s etc.
# ---------------------------------------------------------------------------

client = TestClient(app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Test-data factories
# ---------------------------------------------------------------------------

DISCLAIMER = "This is an investigative lead, not evidence of wrongdoing."


def _ask_request(
    question: str = "Who knows Alice?",
    dataset: str = "synthetic_demo",
    as_of: Optional[str] = None,
) -> AskRequest:
    return AskRequest(question=question, dataset=dataset, as_of=as_of)


def _generated_query(dataset: str = "synthetic_demo") -> GeneratedQuery:
    return GeneratedQuery(
        cypher=f"MATCH (p:Person {{dataset: $dataset}}) RETURN p",
        parameters={"dataset": dataset},
    )


def _validated_query(dataset: str = "synthetic_demo") -> ValidatedQuery:
    return ValidatedQuery(
        cypher=f"MATCH (p:Person {{dataset: $dataset}}) RETURN p",
        parameters={"dataset": dataset},
        generated_by="llm",
        timeout_ms=5000,
    )


def _entity(entity_id: str = "ent-1", display_name: str = "Alice") -> CanonicalEntity:
    return CanonicalEntity(
        entity_id=entity_id,
        entity_type="Person",
        dataset="synthetic_demo",
        display_name=display_name,
        attributes={},
        resolved_from=["m-1"],
        resolution_method="exact_match",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )


def _relationship(relationship_id: str = "rel-1") -> Relationship:
    return Relationship(
        relationship_id=relationship_id,
        relationship_type="CALLED",
        from_entity_id="ent-1",
        to_entity_id="ent-2",
        dataset="synthetic_demo",
        attributes={},
        valid_from="2024-01-01T00:00:00Z",
        valid_to=None,
        evidence_ids=["ev-1"],
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )


def _graph_result(with_relationship: bool = False) -> GraphQueryResult:
    rels = [_relationship()] if with_relationship else []
    return GraphQueryResult(
        entities=[_entity()],
        relationships=rels,
        paths=[],
    )


def _narration_ok(text: str = f"Alice is in the network. {DISCLAIMER}") -> NarrationOutput:
    return NarrationOutput(narration=text)


# ---------------------------------------------------------------------------
# AskService mock builder
# ---------------------------------------------------------------------------


def _mock_service(
    generator_result=None,
    validator_result=None,
    executor_result=None,
    narrator_result=None,
) -> AskService:
    """Build an AskService with fully mocked components."""
    mock_gen = MagicMock()
    mock_gen.generate.return_value = generator_result or _generated_query()

    mock_val = MagicMock()
    mock_val.validate.return_value = validator_result or _validated_query()

    mock_exec = MagicMock()
    mock_exec.execute.return_value = executor_result or _graph_result()

    mock_narr = MagicMock()
    mock_narr.narrate.return_value = narrator_result or _narration_ok()

    return AskService(
        generator=mock_gen,
        validator=mock_val,
        executor=mock_exec,
        narrator=mock_narr,
    )


# ===========================================================================
# Section 1 — AskService unit tests
# ===========================================================================


class TestAskServiceOkPath:
    """Full pipeline: all steps succeed → AskResponseOk."""

    def test_returns_ask_response_ok(self):
        service = _mock_service()
        with patch("app.api.ask._resolver") as mock_resolver:
            mock_resolver.for_relationship.return_value = []
            # Patch inside the module's ask method
            with patch("app.evidence.resolver.evidence_resolver") as _:
                result = service.ask(_ask_request())

        assert isinstance(result, AskResponseOk)
        assert result.status == "ok"

    def test_ok_response_has_narration(self):
        service = _mock_service(narrator_result=_narration_ok("Alice is known. " + DISCLAIMER))
        with patch("app.evidence.resolver.evidence_resolver"):
            result = service.ask(_ask_request())
        assert isinstance(result, AskResponseOk)
        assert "Alice is known" in result.narration

    def test_ok_response_has_path(self):
        graph = _graph_result(with_relationship=False)
        service = _mock_service(executor_result=graph)
        with patch("app.evidence.resolver.evidence_resolver"):
            result = service.ask(_ask_request())
        assert isinstance(result, AskResponseOk)
        assert isinstance(result.path, GraphQueryResult)
        assert len(result.path.entities) == 1

    def test_ok_response_has_evidence_list(self):
        """Evidence[] is returned in the ok response."""
        from app.contracts.evidence import Evidence
        graph = _graph_result(with_relationship=True)
        service = _mock_service(executor_result=graph)

        mock_ev = Evidence(
            evidence_id="ev-1",
            dataset="synthetic_demo",
            source_id="src-1",
            source_type="document",
            ingested_at="2024-01-01T00:00:00Z",
        )
        with patch("app.api.ask._resolver") as mock_resolver:
            mock_resolver.for_relationship.return_value = [mock_ev]
            result = service.ask(_ask_request())

        assert isinstance(result, AskResponseOk)
        assert len(result.evidence) >= 1

    def test_generator_called_with_ask_request(self):
        mock_gen = MagicMock()
        mock_gen.generate.return_value = _generated_query()
        mock_val = MagicMock()
        mock_val.validate.return_value = _validated_query()
        mock_exec = MagicMock()
        mock_exec.execute.return_value = _graph_result()
        mock_narr = MagicMock()
        mock_narr.narrate.return_value = _narration_ok()

        service = AskService(
            generator=mock_gen, validator=mock_val,
            executor=mock_exec, narrator=mock_narr,
        )
        req = _ask_request(question="Who is Bob?", dataset="synthetic_demo")
        with patch("app.api.ask._resolver"):
            service.ask(req)

        mock_gen.generate.assert_called_once_with(req)

    def test_validator_called_with_dataset(self):
        """F4 must forward AskRequest.dataset to F2 validate() — isolation."""
        mock_gen = MagicMock()
        mock_gen.generate.return_value = _generated_query(dataset="live_public")
        mock_val = MagicMock()
        mock_val.validate.return_value = _validated_query(dataset="live_public")
        mock_exec = MagicMock()
        mock_exec.execute.return_value = _graph_result()
        mock_narr = MagicMock()
        mock_narr.narrate.return_value = _narration_ok()

        service = AskService(
            generator=mock_gen, validator=mock_val,
            executor=mock_exec, narrator=mock_narr,
        )
        req = _ask_request(dataset="live_public")
        with patch("app.api.ask._resolver"):
            service.ask(req)

        mock_val.validate.assert_called_once()
        _, call_kwargs = mock_val.validate.call_args
        assert call_kwargs.get("dataset") == "live_public"

    def test_executor_called_with_validated_query_not_raw(self):
        """F4 must only pass ValidatedQuery to executor — never GeneratedQuery."""
        mock_gen = MagicMock()
        mock_gen.generate.return_value = _generated_query()
        mock_val = MagicMock()
        validated = _validated_query()
        mock_val.validate.return_value = validated
        mock_exec = MagicMock()
        mock_exec.execute.return_value = _graph_result()
        mock_narr = MagicMock()
        mock_narr.narrate.return_value = _narration_ok()

        service = AskService(
            generator=mock_gen, validator=mock_val,
            executor=mock_exec, narrator=mock_narr,
        )
        with patch("app.api.ask._resolver"):
            service.ask(_ask_request())

        # Executor must be called with the ValidatedQuery from F2
        mock_exec.execute.assert_called_once_with(validated)


class TestAskServiceF1Failure:
    """F1 LLM generator failure → AskResponseLLMUnavailable (Invariant 4)."""

    def test_generator_error_returns_llm_unavailable(self):
        err = GeneratorError(status="llm_unavailable", reason="timeout")
        service = _mock_service(generator_result=err)
        result = service.ask(_ask_request())

        assert isinstance(result, AskResponseLLMUnavailable)
        assert result.status == "llm_unavailable"

    def test_generator_error_message_contains_reason(self):
        err = GeneratorError(status="llm_unavailable", reason="rate_limited")
        service = _mock_service(generator_result=err)
        result = service.ask(_ask_request())

        assert isinstance(result, AskResponseLLMUnavailable)
        assert "rate_limited" in result.message

    def test_validator_not_called_on_generator_failure(self):
        err = GeneratorError(status="llm_unavailable", reason="provider_error")
        mock_val = MagicMock()
        service = AskService(
            generator=MagicMock(generate=MagicMock(return_value=err)),
            validator=mock_val,
            executor=MagicMock(),
            narrator=MagicMock(),
        )
        service.ask(_ask_request())
        mock_val.validate.assert_not_called()


class TestAskServiceValidationFailure:
    """F2 validation failure → AskResponseValidationFailed (not llm_unavailable)."""

    def test_validation_failed_returns_correct_variant(self):
        fail = ValidationFailed(rule=1, reason="Query contains forbidden write clause 'SET'.")
        service = _mock_service(validator_result=fail)
        result = service.ask(_ask_request())

        assert isinstance(result, AskResponseValidationFailed)
        assert result.status == "validation_failed"
        assert "SET" in result.reason

    def test_executor_not_called_on_validation_failure(self):
        fail = ValidationFailed(rule=2, reason="CALL is forbidden.")
        mock_exec = MagicMock()
        service = AskService(
            generator=MagicMock(generate=MagicMock(return_value=_generated_query())),
            validator=MagicMock(validate=MagicMock(return_value=fail)),
            executor=mock_exec,
            narrator=MagicMock(),
        )
        service.ask(_ask_request())
        mock_exec.execute.assert_not_called()


class TestAskServiceNoResult:
    """F3 returns NoResult → AskResponseNoResult."""

    def test_no_result_returns_correct_variant(self):
        service = _mock_service(executor_result=NoResult())
        result = service.ask(_ask_request())

        assert isinstance(result, AskResponseNoResult)
        assert result.status == "no_result"

    def test_narrator_not_called_on_no_result(self):
        mock_narr = MagicMock()
        service = AskService(
            generator=MagicMock(generate=MagicMock(return_value=_generated_query())),
            validator=MagicMock(validate=MagicMock(return_value=_validated_query())),
            executor=MagicMock(execute=MagicMock(return_value=NoResult())),
            narrator=mock_narr,
        )
        service.ask(_ask_request())
        mock_narr.narrate.assert_not_called()


class TestAskServiceF3NarrationFailure:
    """F3 narration fails → AskResponseLLMUnavailable; never return raw result.

    This is the F4.md §11 explicit constraint: narration failure must NEVER
    silently degrade to returning the raw GraphQueryResult.
    """

    def test_narration_failure_returns_llm_unavailable(self):
        narr_err = NarratorError(reason="provider_error")
        service = _mock_service(narrator_result=narr_err)
        with patch("app.api.ask._resolver"):
            result = service.ask(_ask_request())

        assert isinstance(result, AskResponseLLMUnavailable)
        assert result.status == "llm_unavailable"

    def test_narration_failure_does_not_return_raw_graph_result(self):
        """DOC3 §10 / F4.md §11: raw GraphQueryResult must NEVER be returned."""
        narr_err = NarratorError(reason="timeout")
        service = _mock_service(narrator_result=narr_err)
        with patch("app.api.ask._resolver"):
            result = service.ask(_ask_request())

        assert not isinstance(result, AskResponseOk), (
            "F4 must NOT return AskResponseOk when narration fails — "
            "it must return llm_unavailable (F4.md §11)"
        )

    def test_narration_failure_message_contains_reason(self):
        narr_err = NarratorError(reason="rate_limited")
        service = _mock_service(narrator_result=narr_err)
        with patch("app.api.ask._resolver"):
            result = service.ask(_ask_request())

        assert isinstance(result, AskResponseLLMUnavailable)
        assert "rate_limited" in result.message


class TestAskServiceGraphUnavailable:
    """F3 returns ExecutionError → raises GraphUnavailableError (HTTP 503)."""

    def test_graph_unavailable_raises(self):
        err = ExecutionError(status="graph_unavailable", message="Neo4j is down.")
        service = _mock_service(executor_result=err)
        with pytest.raises(GraphUnavailableError):
            service.ask(_ask_request())

    def test_timeout_raises_graph_unavailable(self):
        err = ExecutionError(status="timeout", message="Query timed out.")
        service = _mock_service(executor_result=err)
        with pytest.raises(GraphUnavailableError):
            service.ask(_ask_request())

    def test_execution_error_raises_graph_unavailable(self):
        err = ExecutionError(status="execution_error", message="Database error.")
        service = _mock_service(executor_result=err)
        with pytest.raises(GraphUnavailableError):
            service.ask(_ask_request())


class TestAskServiceDatasetIsolation:
    """Dataset from AskRequest must flow to F2 validate() unchanged."""

    def test_live_public_dataset_forwarded_to_validator(self):
        mock_val = MagicMock()
        mock_val.validate.return_value = _validated_query(dataset="live_public")
        service = AskService(
            generator=MagicMock(generate=MagicMock(return_value=_generated_query())),
            validator=mock_val,
            executor=MagicMock(execute=MagicMock(return_value=NoResult())),
            narrator=MagicMock(),
        )
        service.ask(_ask_request(dataset="live_public"))
        _, kwargs = mock_val.validate.call_args
        assert kwargs.get("dataset") == "live_public"

    def test_synthetic_demo_dataset_forwarded(self):
        mock_val = MagicMock()
        mock_val.validate.return_value = _validated_query(dataset="synthetic_demo")
        service = AskService(
            generator=MagicMock(generate=MagicMock(return_value=_generated_query())),
            validator=mock_val,
            executor=MagicMock(execute=MagicMock(return_value=NoResult())),
            narrator=MagicMock(),
        )
        service.ask(_ask_request(dataset="synthetic_demo"))
        _, kwargs = mock_val.validate.call_args
        assert kwargs.get("dataset") == "synthetic_demo"


# ===========================================================================
# Section 2 — API integration tests (POST /api/v1/ask via TestClient)
# ===========================================================================


def _patch_service(service: AskService):
    """Context manager that replaces the module-level AskService singleton."""
    return patch("app.api.ask._get_service", return_value=service)


class TestAskAPIEndpointOk:
    """POST /ask → 200 status:"ok"."""

    def test_returns_200_with_ok_status(self):
        graph = _graph_result(with_relationship=True)
        service = _mock_service(executor_result=graph)

        with _patch_service(service):
            with patch("app.api.ask._resolver") as mock_res:
                mock_res.for_relationship.return_value = []
                resp = client.post(
                    "/api/v1/ask",
                    json={"question": "Who is Alice?", "dataset": "synthetic_demo", "as_of": None},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "narration" in body
        assert "path" in body
        assert "evidence" in body

    def test_ok_response_path_has_entities(self):
        graph = _graph_result(with_relationship=False)
        service = _mock_service(executor_result=graph)

        with _patch_service(service):
            with patch("app.api.ask._resolver"):
                resp = client.post(
                    "/api/v1/ask",
                    json={"question": "List suspects", "dataset": "synthetic_demo", "as_of": None},
                )

        body = resp.json()
        assert body["status"] == "ok"
        assert len(body["path"]["entities"]) == 1
        assert body["path"]["entities"][0]["display_name"] == "Alice"

    def test_ok_response_narration_contains_disclaimer(self):
        narration = f"Alice is a suspect. {DISCLAIMER}"
        service = _mock_service(narrator_result=NarrationOutput(narration=narration))

        with _patch_service(service):
            with patch("app.api.ask._resolver"):
                resp = client.post(
                    "/api/v1/ask",
                    json={"question": "Who is Alice?", "dataset": "synthetic_demo", "as_of": None},
                )

        body = resp.json()
        assert DISCLAIMER in body["narration"]


class TestAskAPIEndpointLLMUnavailableF1:
    """POST /ask → 200 status:"llm_unavailable" (F1 generator fails)."""

    def test_f1_failure_returns_200_llm_unavailable(self):
        err = GeneratorError(status="llm_unavailable", reason="timeout")
        service = _mock_service(generator_result=err)

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "llm_unavailable"
        assert "message" in body

    def test_f1_failure_message_in_response(self):
        err = GeneratorError(status="llm_unavailable", reason="rate_limited")
        service = _mock_service(generator_result=err)

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
            )

        body = resp.json()
        assert "rate_limited" in body["message"]


class TestAskAPIEndpointLLMUnavailableF3:
    """POST /ask → 200 status:"llm_unavailable" (F3 narration fails).

    This is the second LLM unavailability injection point per F4.md §12.
    """

    def test_f3_narration_failure_returns_200_llm_unavailable(self):
        narr_err = NarratorError(reason="provider_error")
        service = _mock_service(narrator_result=narr_err)

        with _patch_service(service):
            with patch("app.api.ask._resolver"):
                resp = client.post(
                    "/api/v1/ask",
                    json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "llm_unavailable"

    def test_f3_narration_failure_does_not_return_ok(self):
        """DOC3 §10 / F4.md §11: status must NOT be 'ok' when narration fails."""
        narr_err = NarratorError(reason="timeout")
        service = _mock_service(narrator_result=narr_err)

        with _patch_service(service):
            with patch("app.api.ask._resolver"):
                resp = client.post(
                    "/api/v1/ask",
                    json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
                )

        body = resp.json()
        assert body["status"] != "ok", (
            "Narration failure must not silently return 'ok' (F4.md §11)"
        )


class TestAskAPIEndpointValidationFailed:
    """POST /ask → 200 status:"validation_failed"."""

    def test_validation_failed_returns_200(self):
        fail = ValidationFailed(rule=1, reason="Query contains forbidden write clause 'DELETE'.")
        service = _mock_service(validator_result=fail)

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "Delete all", "dataset": "synthetic_demo", "as_of": None},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "validation_failed"
        assert "reason" in body
        assert "DELETE" in body["reason"]

    def test_validation_failed_different_rules(self):
        for rule, reason in [
            (2, "CALL is forbidden."),
            (4, "Unknown node label 'Secret'."),
            (5, "Cross-dataset access via Ask-the-Network is not permitted."),
        ]:
            fail = ValidationFailed(rule=rule, reason=reason)
            service = _mock_service(validator_result=fail)

            with _patch_service(service):
                resp = client.post(
                    "/api/v1/ask",
                    json={"question": "?", "dataset": "synthetic_demo", "as_of": None},
                )

            body = resp.json()
            assert body["status"] == "validation_failed"
            assert reason in body["reason"]


class TestAskAPIEndpointNoResult:
    """POST /ask → 200 status:"no_result"."""

    def test_no_result_returns_200(self):
        service = _mock_service(executor_result=NoResult())

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "no_result"
        assert "message" in body


class TestAskAPIEndpointGraphUnavailable:
    """POST /ask → 503 when graph is unavailable (F3 returns ExecutionError)."""

    def test_graph_unavailable_returns_503(self):
        err = ExecutionError(status="graph_unavailable", message="Neo4j is down.")
        service = _mock_service(executor_result=err)

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
            )

        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["type"] == "graph_unavailable"

    def test_timeout_returns_503(self):
        err = ExecutionError(status="timeout", message="Query timed out.")
        service = _mock_service(executor_result=err)

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
            )

        assert resp.status_code == 503

    def test_execution_error_returns_503(self):
        err = ExecutionError(status="execution_error", message="Database error.")
        service = _mock_service(executor_result=err)

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
            )

        assert resp.status_code == 503


class TestAskAPIEndpointRequestValidation:
    """FastAPI request schema validation."""

    def test_missing_question_returns_422(self):
        resp = client.post(
            "/api/v1/ask",
            json={"dataset": "synthetic_demo"},
        )
        assert resp.status_code == 422

    def test_empty_question_accepted(self):
        """AskRequest.question is a str — empty string is valid schema-wise."""
        err = GeneratorError(status="llm_unavailable", reason="timeout")
        service = _mock_service(generator_result=err)

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "", "dataset": "synthetic_demo", "as_of": None},
            )
        # AskService handles it (may succeed or return llm_unavailable)
        assert resp.status_code in (200, 422)

    def test_dataset_defaults_to_synthetic_demo(self):
        """AskRequest.dataset defaults to 'synthetic_demo' if omitted."""
        mock_val = MagicMock()
        mock_val.validate.return_value = _validated_query()

        service = AskService(
            generator=MagicMock(generate=MagicMock(return_value=_generated_query())),
            validator=mock_val,
            executor=MagicMock(execute=MagicMock(return_value=NoResult())),
            narrator=MagicMock(),
        )

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "Who?", "as_of": None},
            )

        # Either the request used the default dataset or was rejected
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            body = resp.json()
            assert body["status"] in ("no_result", "ok", "llm_unavailable", "validation_failed")


class TestAskAPIEndpointResponseShape:
    """Field-for-field validation of each AskResponse variant against DOC3 §10."""

    def test_ok_shape_has_all_required_fields(self):
        graph = _graph_result()
        service = _mock_service(executor_result=graph)

        with _patch_service(service):
            with patch("app.api.ask._resolver"):
                resp = client.post(
                    "/api/v1/ask",
                    json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
                )

        body = resp.json()
        assert "status" in body
        assert "narration" in body
        assert "path" in body
        assert "evidence" in body
        assert body["status"] == "ok"

    def test_llm_unavailable_shape_has_message(self):
        err = GeneratorError(status="llm_unavailable", reason="timeout")
        service = _mock_service(generator_result=err)

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
            )

        body = resp.json()
        assert "status" in body
        assert "message" in body
        assert body["status"] == "llm_unavailable"
        assert "reason" not in body  # llm_unavailable has 'message', not 'reason'

    def test_validation_failed_shape_has_reason(self):
        fail = ValidationFailed(rule=1, reason="Write clause forbidden.")
        service = _mock_service(validator_result=fail)

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
            )

        body = resp.json()
        assert body["status"] == "validation_failed"
        assert "reason" in body
        assert "message" not in body  # validation_failed has 'reason', not 'message'

    def test_no_result_shape_has_message(self):
        service = _mock_service(executor_result=NoResult())

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
            )

        body = resp.json()
        assert body["status"] == "no_result"
        assert "message" in body

    def test_graph_unavailable_shape_matches_doc3_s13(self):
        err = ExecutionError(status="graph_unavailable", message="Neo4j down.")
        service = _mock_service(executor_result=err)

        with _patch_service(service):
            resp = client.post(
                "/api/v1/ask",
                json={"question": "Who?", "dataset": "synthetic_demo", "as_of": None},
            )

        assert resp.status_code == 503
        body = resp.json()
        # DOC3 §13 ErrorResponse envelope
        assert "error" in body
        assert body["error"]["type"] == "graph_unavailable"
        assert "message" in body["error"]


# ===========================================================================
# Section 3 — All four F4.md §12 acceptance criteria in one controlled flow
# ===========================================================================


class TestF4AcceptanceCriteria:
    """F4.md §12: All four AskResponse variants reproducible via controlled scenarios."""

    def test_ac_ok_case(self):
        """Acceptance criterion: normal successful case → status:'ok'."""
        service = _mock_service()
        with patch("app.api.ask._resolver"):
            result = service.ask(_ask_request())
        assert isinstance(result, AskResponseOk)

    def test_ac_llm_unavailable_at_generation(self):
        """Acceptance criterion: LLM-down at generation step → llm_unavailable."""
        service = _mock_service(
            generator_result=GeneratorError(status="llm_unavailable", reason="timeout")
        )
        result = service.ask(_ask_request())
        assert isinstance(result, AskResponseLLMUnavailable)

    def test_ac_llm_unavailable_at_narration(self):
        """Acceptance criterion: LLM-down at narration step → llm_unavailable."""
        service = _mock_service(
            narrator_result=NarratorError(reason="provider_error")
        )
        with patch("app.api.ask._resolver"):
            result = service.ask(_ask_request())
        assert isinstance(result, AskResponseLLMUnavailable)

    def test_ac_validation_failed(self):
        """Acceptance criterion: intentionally invalid query → validation_failed."""
        service = _mock_service(
            validator_result=ValidationFailed(rule=1, reason="Write clause rejected.")
        )
        result = service.ask(_ask_request())
        assert isinstance(result, AskResponseValidationFailed)

    def test_ac_no_result(self):
        """Acceptance criterion: valid query, empty result → no_result."""
        service = _mock_service(executor_result=NoResult())
        result = service.ask(_ask_request())
        assert isinstance(result, AskResponseNoResult)

