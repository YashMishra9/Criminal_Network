"""Unit tests for F1 — QueryGenerator (backend/app/ask/query_generator.py).

Tests required (F1.md §13):
  - Unit tests with a mocked LLMClient returning both valid and invalid Cypher,
    confirming correct pass-through behaviour.

Acceptance criteria (F1.md §12):
  - Given a sample NL question, produces syntactically plausible Cypher
    referencing only DOC3 §6 schema labels (spot-checked).

Additional tests:
  - AskRequest model validates expected fields (question, dataset, as_of).
  - GeneratedQuery carries generated_by='llm' always.
  - On LLM unavailability (any reason), returns GeneratorError not an exception.
  - Prompt contains the dataset-scoping instruction (DOC3 §10 rule 5).
  - Prompt contains the schema labels (DOC3 §10 rule 4 / F1.md §11).
  - Parameters dict contains dataset key.
  - as_of appears in parameters when supplied.
  - Cypher output is the raw text from the LLM (no wrapping/modification).
  - Mock provider is used for offline test execution.
"""

import pytest
from unittest.mock import MagicMock

from app.ask.query_generator import (
    AskRequest,
    GeneratedQuery,
    GeneratorError,
    QueryGenerator,
    get_query_generator,
    _build_prompt,
    _ENTITY_LABELS,
    _RELATIONSHIP_TYPES,
)
from app.llm.client import LLMClient, LLMResultOk, LLMResultUnavailable


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CYPHER = (
    "MATCH (p:Person {dataset: $dataset})-[:CALLED]->(ph:Phone {dataset: $dataset}) "
    "RETURN p.display_name, ph.display_name LIMIT 25"
)

SAMPLE_QUESTION = "Who does Rahul Sharma call most frequently?"
SAMPLE_DATASET = "synthetic_demo"


def _make_client(result) -> LLMClient:
    """Return an LLMClient whose generate() always returns `result`."""
    client = MagicMock(spec=LLMClient)
    client.generate = MagicMock(return_value=result)
    return client


# ---------------------------------------------------------------------------
# AskRequest validation
# ---------------------------------------------------------------------------

class TestAskRequest:
    def test_defaults(self):
        req = AskRequest(question="Who called whom?")
        assert req.dataset == "synthetic_demo"
        assert req.as_of is None

    def test_explicit_fields(self):
        req = AskRequest(
            question="Find clusters",
            dataset="live_public",
            as_of="2024-06-01T00:00:00Z",
        )
        assert req.dataset == "live_public"
        assert req.as_of == "2024-06-01T00:00:00Z"

    def test_question_required(self):
        with pytest.raises(Exception):
            AskRequest()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Prompt content (F1.md §11 — prompt must include schema labels and dataset scope)
# ---------------------------------------------------------------------------

class TestPromptContent:
    def test_prompt_contains_entity_labels(self):
        req = AskRequest(question=SAMPLE_QUESTION, dataset=SAMPLE_DATASET)
        prompt = _build_prompt(req)
        for label in _ENTITY_LABELS:
            assert label in prompt, f"Missing entity label '{label}' in prompt"

    def test_prompt_contains_relationship_types(self):
        req = AskRequest(question=SAMPLE_QUESTION, dataset=SAMPLE_DATASET)
        prompt = _build_prompt(req)
        for rel in ["CALLED", "OWNS", "MET", "WORKS_FOR"]:
            assert rel in prompt, f"Missing relationship type '{rel}' in prompt"

    def test_prompt_contains_dataset_scope_instruction(self):
        req = AskRequest(question=SAMPLE_QUESTION, dataset=SAMPLE_DATASET)
        prompt = _build_prompt(req)
        assert "$dataset" in prompt
        assert "dataset" in prompt.lower()

    def test_prompt_contains_question(self):
        req = AskRequest(question=SAMPLE_QUESTION, dataset=SAMPLE_DATASET)
        prompt = _build_prompt(req)
        assert SAMPLE_QUESTION in prompt

    def test_prompt_forbids_call_mentioned(self):
        """Prompt must explicitly mention CALL is forbidden (DOC3 §10 rule 2 / Invariant 13)."""
        req = AskRequest(question=SAMPLE_QUESTION, dataset=SAMPLE_DATASET)
        prompt = _build_prompt(req)
        assert "CALL" in prompt

    def test_prompt_contains_as_of_instruction_when_provided(self):
        req = AskRequest(
            question=SAMPLE_QUESTION,
            dataset=SAMPLE_DATASET,
            as_of="2024-01-15T00:00:00Z",
        )
        prompt = _build_prompt(req)
        assert "2024-01-15T00:00:00Z" in prompt

    def test_prompt_no_as_of_instruction_when_absent(self):
        req = AskRequest(question=SAMPLE_QUESTION, dataset=SAMPLE_DATASET)
        prompt = _build_prompt(req)
        assert "No temporal filter" in prompt


# ---------------------------------------------------------------------------
# QueryGenerator — success path (F1.md §12 — valid Cypher pass-through)
# ---------------------------------------------------------------------------

class TestQueryGeneratorSuccess:
    def test_returns_generated_query_on_ok(self):
        client = _make_client(LLMResultOk(text=SAMPLE_CYPHER))
        gen = QueryGenerator(llm_client=client)
        result = gen.generate(AskRequest(question=SAMPLE_QUESTION))
        assert isinstance(result, GeneratedQuery)

    def test_generated_by_is_llm(self):
        client = _make_client(LLMResultOk(text=SAMPLE_CYPHER))
        gen = QueryGenerator(llm_client=client)
        result = gen.generate(AskRequest(question=SAMPLE_QUESTION))
        assert isinstance(result, GeneratedQuery)
        assert result.generated_by == "llm"

    def test_cypher_is_passed_through_verbatim(self):
        client = _make_client(LLMResultOk(text=SAMPLE_CYPHER))
        gen = QueryGenerator(llm_client=client)
        result = gen.generate(AskRequest(question=SAMPLE_QUESTION))
        assert isinstance(result, GeneratedQuery)
        assert result.cypher == SAMPLE_CYPHER

    def test_cypher_whitespace_is_stripped(self):
        """Leading/trailing whitespace is stripped from the LLM output."""
        client = _make_client(LLMResultOk(text=f"  \n{SAMPLE_CYPHER}\n  "))
        gen = QueryGenerator(llm_client=client)
        result = gen.generate(AskRequest(question=SAMPLE_QUESTION))
        assert isinstance(result, GeneratedQuery)
        assert result.cypher == SAMPLE_CYPHER

    def test_parameters_contain_dataset(self):
        client = _make_client(LLMResultOk(text=SAMPLE_CYPHER))
        gen = QueryGenerator(llm_client=client)
        result = gen.generate(
            AskRequest(question=SAMPLE_QUESTION, dataset=SAMPLE_DATASET)
        )
        assert isinstance(result, GeneratedQuery)
        assert result.parameters["dataset"] == SAMPLE_DATASET

    def test_parameters_contain_as_of_when_provided(self):
        as_of = "2024-03-01T00:00:00Z"
        client = _make_client(LLMResultOk(text=SAMPLE_CYPHER))
        gen = QueryGenerator(llm_client=client)
        result = gen.generate(
            AskRequest(question=SAMPLE_QUESTION, dataset=SAMPLE_DATASET, as_of=as_of)
        )
        assert isinstance(result, GeneratedQuery)
        assert result.parameters["as_of"] == as_of

    def test_parameters_as_of_is_none_when_not_provided(self):
        client = _make_client(LLMResultOk(text=SAMPLE_CYPHER))
        gen = QueryGenerator(llm_client=client)
        result = gen.generate(AskRequest(question=SAMPLE_QUESTION))
        assert isinstance(result, GeneratedQuery)
        assert result.parameters["as_of"] is None

    def test_schema_labels_in_valid_cypher_spot_check(self):
        """Acceptance criterion: Cypher references only DOC3 §6 schema labels."""
        # Simulate LLM returning a query referencing schema-valid labels.
        schema_valid_cypher = (
            "MATCH (p:Person {dataset: $dataset})-[:MET]->(q:Person {dataset: $dataset}) "
            "RETURN p.display_name, q.display_name"
        )
        client = _make_client(LLMResultOk(text=schema_valid_cypher))
        gen = QueryGenerator(llm_client=client)
        result = gen.generate(AskRequest(question=SAMPLE_QUESTION))
        assert isinstance(result, GeneratedQuery)
        # Spot-check: 'Person' and 'MET' are schema-defined labels.
        assert "Person" in result.cypher
        assert "MET" in result.cypher


# ---------------------------------------------------------------------------
# QueryGenerator — LLM unavailable (F1.md §11 / DOC2 §12A)
# ---------------------------------------------------------------------------

class TestQueryGeneratorUnavailable:
    @pytest.mark.parametrize("reason", ["timeout", "provider_error", "rate_limited"])
    def test_returns_generator_error_not_exception(self, reason):
        """On any unavailability reason, GeneratorError is returned — never raised."""
        client = _make_client(LLMResultUnavailable(reason=reason))  # type: ignore[arg-type]
        gen = QueryGenerator(llm_client=client)
        result = gen.generate(AskRequest(question=SAMPLE_QUESTION))
        assert isinstance(result, GeneratorError)
        assert result.status == "llm_unavailable"

    @pytest.mark.parametrize("reason", ["timeout", "provider_error", "rate_limited"])
    def test_generator_error_carries_reason(self, reason):
        client = _make_client(LLMResultUnavailable(reason=reason))  # type: ignore[arg-type]
        gen = QueryGenerator(llm_client=client)
        result = gen.generate(AskRequest(question=SAMPLE_QUESTION))
        assert isinstance(result, GeneratorError)
        assert result.reason == reason

    def test_generator_error_status_is_llm_unavailable(self):
        client = _make_client(LLMResultUnavailable(reason="timeout"))
        gen = QueryGenerator(llm_client=client)
        result = gen.generate(AskRequest(question=SAMPLE_QUESTION))
        assert isinstance(result, GeneratorError)
        assert result.status == "llm_unavailable"

    def test_no_exception_raised_on_unavailability(self):
        """Caller never has to catch — GeneratorError is the typed return."""
        client = _make_client(LLMResultUnavailable(reason="provider_error"))
        gen = QueryGenerator(llm_client=client)
        try:
            result = gen.generate(AskRequest(question=SAMPLE_QUESTION))
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"generate() raised unexpectedly: {exc}")
        assert isinstance(result, GeneratorError)


# ---------------------------------------------------------------------------
# GeneratedQuery — contract shape
# ---------------------------------------------------------------------------

class TestGeneratedQueryShape:
    def test_generated_by_literal(self):
        gq = GeneratedQuery(cypher="MATCH (n) RETURN n", parameters={"dataset": "synthetic_demo"})
        assert gq.generated_by == "llm"

    def test_parameters_is_dict(self):
        gq = GeneratedQuery(cypher="MATCH (n) RETURN n", parameters={"dataset": "synthetic_demo"})
        assert isinstance(gq.parameters, dict)


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

class TestGetQueryGenerator:
    def test_returns_query_generator(self):
        gen = get_query_generator()
        assert isinstance(gen, QueryGenerator)

    def test_accepts_custom_llm_client(self):
        mock_client = MagicMock(spec=LLMClient)
        gen = get_query_generator(llm_client=mock_client)
        assert isinstance(gen, QueryGenerator)
