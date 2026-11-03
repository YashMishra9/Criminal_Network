"""Unit tests for F2 — CypherValidator (backend/app/ask/validator.py).

Tests required (F2.md §13):
  - One unit test per validation rule.
  - Adversarial CALL-prohibition case specifically.

Acceptance criteria (F2.md §12):
  - Adversarial test queries:
    a) A mutating clause             — REJECTED (Rule 1)
    b) A CALL apoc.* clause          — REJECTED (Rule 2, Invariant 13)
    c) An out-of-schema label        — REJECTED (Rule 4)
    d) A cross-dataset query         — REJECTED (Rule 5)
    e) A timeout-inducing query      — ACCEPTED with timeout_ms embedded (Rule 6)
  All five MUST be rejected / handled — this is explicit per DOC4 Track F DoD.

Additional coverage:
  - Each write clause individually (CREATE, MERGE, SET, DELETE, REMOVE).
  - CALL variants: bare, apoc.*, gds.*, db.* procedures, read-only procedures.
  - YIELD (implies CALL).
  - Forbidden construct keywords (LOAD, FOREACH, PERIODIC, DROP, etc.).
  - Valid queries pass through with generated_by='llm'.
  - dataset injection when filter is absent.
  - Dataset mismatch in literal (wrong quoted value).
  - $dataset param always present in ValidatedQuery.parameters.
  - Pipe-separated relationship type — valid and invalid.
  - Unknown relationship type is rejected.
  - timeout_ms embedded in ValidatedQuery for F3.
  - timeout_ms overridable via constructor.
  - Factory function returns CypherValidator.
  - ValidatedQuery / ValidationFailed shape.
"""

import pytest

from app.ask.validator import (
    CypherValidator,
    ValidatedQuery,
    ValidationFailed,
    get_cypher_validator,
    _ALLOWED_NODE_LABELS,
    _ALLOWED_RELATIONSHIP_TYPES,
)
from app.ask.query_generator import GeneratedQuery


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_query(cypher: str, dataset: str = "synthetic_demo") -> GeneratedQuery:
    """Build a GeneratedQuery fixture for the given Cypher string."""
    return GeneratedQuery(
        cypher=cypher,
        parameters={"dataset": dataset},
        generated_by="llm",
    )


def _validate(cypher: str, dataset: str = "synthetic_demo", timeout_ms: int = 5_000) -> ValidationFailed | ValidatedQuery:
    """Shorthand: create a validator and validate the given Cypher."""
    v = CypherValidator(timeout_ms=timeout_ms)
    return v.validate(_make_query(cypher, dataset), dataset=dataset)


def _assert_failed(result, rule: int | None = None) -> ValidationFailed:
    """Assert result is ValidationFailed and optionally check the rule number."""
    assert isinstance(result, ValidationFailed), (
        f"Expected ValidationFailed but got {type(result).__name__}: {result}"
    )
    if rule is not None:
        assert result.rule == rule, f"Expected rule={rule} but got rule={result.rule}"
    return result


def _assert_valid(result) -> ValidatedQuery:
    """Assert result is ValidatedQuery."""
    assert isinstance(result, ValidatedQuery), (
        f"Expected ValidatedQuery but got {type(result).__name__}: {result}"
    )
    return result


# ---------------------------------------------------------------------------
# Valid baseline queries — must pass all rules
# ---------------------------------------------------------------------------

class TestValidQueries:
    VALID_CYPHER_BASIC = (
        "MATCH (p:Person {dataset: $dataset})-[:CALLED]->(ph:Phone {dataset: $dataset}) "
        "RETURN p.display_name, ph.display_name LIMIT 25"
    )

    def test_basic_valid_query_passes(self):
        result = _validate(self.VALID_CYPHER_BASIC)
        _assert_valid(result)

    def test_valid_query_generated_by_is_llm(self):
        result = _validate(self.VALID_CYPHER_BASIC)
        assert _assert_valid(result).generated_by == "llm"

    def test_valid_query_has_timeout_ms(self):
        result = _validate(self.VALID_CYPHER_BASIC, timeout_ms=10_000)
        assert _assert_valid(result).timeout_ms == 10_000

    def test_valid_query_cypher_preserved(self):
        result = _validate(self.VALID_CYPHER_BASIC)
        assert _assert_valid(result).cypher == self.VALID_CYPHER_BASIC

    def test_optional_match_is_permitted(self):
        cypher = (
            "MATCH (p:Person {dataset: $dataset}) "
            "OPTIONAL MATCH (p)-[:OWNS]->(v:Vehicle {dataset: $dataset}) "
            "RETURN p.display_name, v.display_name"
        )
        _assert_valid(_validate(cypher))

    def test_with_clause_is_permitted(self):
        cypher = (
            "MATCH (p:Person {dataset: $dataset}) "
            "WITH p ORDER BY p.display_name "
            "RETURN p.display_name LIMIT 10"
        )
        _assert_valid(_validate(cypher))

    def test_where_clause_is_permitted(self):
        cypher = (
            "MATCH (p:Person {dataset: $dataset}) "
            "WHERE p.display_name CONTAINS 'Sharma' "
            "RETURN p LIMIT 5"
        )
        _assert_valid(_validate(cypher))

    def test_shortest_path_is_permitted(self):
        cypher = (
            "MATCH path = shortestPath("
            "(a:Person {dataset: $dataset})-[*]-(b:Person {dataset: $dataset})) "
            "RETURN path"
        )
        _assert_valid(_validate(cypher))

    def test_all_canonical_entity_labels_accepted(self):
        for label in _ALLOWED_NODE_LABELS:
            cypher = (
                f"MATCH (n:{label} {{dataset: $dataset}}) RETURN n LIMIT 1"
            )
            result = _validate(cypher)
            assert isinstance(result, ValidatedQuery), (
                f"Label '{label}' should be accepted but was rejected: {result}"
            )

    def test_all_relationship_types_accepted(self):
        for rel in _ALLOWED_RELATIONSHIP_TYPES:
            cypher = (
                f"MATCH (a {{dataset: $dataset}})-[:{rel}]->(b {{dataset: $dataset}}) "
                "RETURN a, b LIMIT 1"
            )
            result = _validate(cypher)
            assert isinstance(result, ValidatedQuery), (
                f"Relationship type '{rel}' should be accepted but was rejected: {result}"
            )

    def test_parameters_dict_contains_dataset(self):
        result = _validate(self.VALID_CYPHER_BASIC, dataset="synthetic_demo")
        assert "dataset" in _assert_valid(result).parameters
        assert _assert_valid(result).parameters["dataset"] == "synthetic_demo"

    def test_parameters_dict_contains_as_of_when_present(self):
        v = CypherValidator(timeout_ms=5_000)
        q = GeneratedQuery(
            cypher=self.VALID_CYPHER_BASIC,
            parameters={"dataset": "synthetic_demo", "as_of": "2024-06-01T00:00:00Z"},
        )
        result = v.validate(q, dataset="synthetic_demo")
        assert _assert_valid(result).parameters.get("as_of") == "2024-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# DOC4 Track F Acceptance Criteria — adversarial cases (F2.md §12)
# ALL FIVE must be rejected / correctly handled
# ---------------------------------------------------------------------------

class TestAdversarialCases:
    """F2.md §12 — explicit adversarial test cases required by DOC4."""

    def test_AC_a_mutating_clause_rejected(self):
        """AC-a: A mutating clause (CREATE) is rejected (Rule 1)."""
        cypher = "CREATE (p:Person {name: 'injected', dataset: $dataset}) RETURN p"
        _assert_failed(_validate(cypher), rule=1)

    def test_AC_b_call_apoc_rejected(self):
        """AC-b: A CALL apoc.* clause is rejected outright (Rule 2, Invariant 13)."""
        cypher = (
            "CALL apoc.path.subgraphAll("
            "(p:Person {dataset: $dataset}), {maxLevel: 3}) "
            "YIELD nodes RETURN nodes"
        )
        _assert_failed(_validate(cypher), rule=2)

    def test_AC_c_out_of_schema_label_rejected(self):
        """AC-c: An out-of-schema node label is rejected (Rule 4)."""
        cypher = (
            "MATCH (h:Hacker {dataset: $dataset}) "
            "RETURN h.display_name LIMIT 10"
        )
        _assert_failed(_validate(cypher), rule=4)

    def test_AC_d_cross_dataset_query_rejected(self):
        """AC-d: A cross-dataset query (wrong literal dataset) is rejected (Rule 5)."""
        cypher = (
            "MATCH (p:Person {dataset: 'live_public'}) "
            "RETURN p LIMIT 10"
        )
        # Request is for synthetic_demo but query hardcodes live_public
        _assert_failed(_validate(cypher, dataset="synthetic_demo"), rule=5)

    def test_AC_e_timeout_query_accepts_with_timeout_ms(self):
        """AC-e: A timeout-inducing query is ACCEPTED but gets timeout_ms embedded.

        Rule 6: timeout enforcement is F3's job; the validator embeds timeout_ms
        into ValidatedQuery so F3 can abort if exceeded.
        """
        # A query that *could* be slow (variable-length path) but is structurally valid
        cypher = (
            "MATCH path = (a:Person {dataset: $dataset})-[*1..10]->"
            "(b:Person {dataset: $dataset}) "
            "RETURN path LIMIT 1"
        )
        result = _validate(cypher, timeout_ms=500)
        vq = _assert_valid(result)
        assert vq.timeout_ms == 500, (
            "Timeout-inducing query must embed timeout_ms for F3 to enforce"
        )


# ---------------------------------------------------------------------------
# Rule 1 — Read-only: no write clauses
# ---------------------------------------------------------------------------

class TestRule1WriteClauseRejection:
    @pytest.mark.parametrize("clause", [
        "CREATE", "MERGE", "SET", "DELETE", "REMOVE",
    ])
    def test_write_clause_rejected(self, clause: str):
        cypher = f"MATCH (p:Person {{dataset: $dataset}}) {clause} (p) RETURN p"
        result = _validate(cypher)
        _assert_failed(result, rule=1)

    def test_create_alone_rejected(self):
        cypher = "CREATE (:Person {name: 'bad', dataset: $dataset})"
        _assert_failed(_validate(cypher), rule=1)

    def test_merge_alone_rejected(self):
        cypher = "MERGE (p:Person {entity_id: 'x', dataset: $dataset}) RETURN p"
        _assert_failed(_validate(cypher), rule=1)

    def test_set_property_rejected(self):
        cypher = (
            "MATCH (p:Person {dataset: $dataset}) SET p.name = 'bad' RETURN p"
        )
        _assert_failed(_validate(cypher), rule=1)

    def test_delete_rejected(self):
        cypher = "MATCH (p:Person {dataset: $dataset}) DELETE p"
        _assert_failed(_validate(cypher), rule=1)

    def test_remove_property_rejected(self):
        cypher = "MATCH (p:Person {dataset: $dataset}) REMOVE p.name RETURN p"
        _assert_failed(_validate(cypher), rule=1)

    def test_case_insensitive_write_clause_rejected(self):
        """Write clause detection is case-insensitive."""
        cypher = "match (p:Person {dataset: $dataset}) create (q:Phone) return q"
        _assert_failed(_validate(cypher), rule=1)


# ---------------------------------------------------------------------------
# Rule 2 — CALL / procedure invocation forbidden outright (Invariant 13)
# ---------------------------------------------------------------------------

class TestRule2CallProhibition:
    def test_call_apoc_subgraph_rejected(self):
        cypher = "CALL apoc.path.subgraphAll(n, {}) YIELD nodes RETURN nodes"
        _assert_failed(_validate(cypher), rule=2)

    def test_call_gds_rejected(self):
        cypher = "CALL gds.pageRank.stream('myGraph') YIELD nodeId, score RETURN nodeId"
        _assert_failed(_validate(cypher), rule=2)

    def test_call_db_procedure_rejected(self):
        cypher = "CALL db.labels() YIELD label RETURN label"
        _assert_failed(_validate(cypher), rule=2)

    def test_call_read_only_procedure_still_rejected(self):
        """Even a read-only CALL is forbidden — no whitelist (Invariant 13)."""
        cypher = "CALL apoc.meta.schema() YIELD value RETURN value"
        _assert_failed(_validate(cypher), rule=2)

    def test_bare_call_rejected(self):
        cypher = "CALL myProcedure()"
        _assert_failed(_validate(cypher), rule=2)

    def test_yield_without_call_rejected(self):
        """YIELD implies CALL — reject it as Rule 2 violation."""
        cypher = (
            "MATCH (p:Person {dataset: $dataset}) "
            "YIELD p.display_name RETURN p.display_name"
        )
        _assert_failed(_validate(cypher), rule=2)

    def test_call_case_insensitive_rejected(self):
        """CALL detection is case-insensitive."""
        cypher = "call apoc.path.subgraphAll(n, {}) yield nodes return nodes"
        _assert_failed(_validate(cypher), rule=2)

    def test_call_inline_subquery_rejected(self):
        """CALL { ... } inline subquery is also forbidden."""
        cypher = (
            "MATCH (p:Person {dataset: $dataset}) "
            "CALL { WITH p MATCH (p)-[:CALLED]->(q) RETURN q } "
            "RETURN p, q"
        )
        _assert_failed(_validate(cypher), rule=2)


# ---------------------------------------------------------------------------
# Rule 3 — Forbidden construct keywords
# ---------------------------------------------------------------------------

class TestRule3ForbiddenConstructs:
    def test_foreach_rejected(self):
        cypher = (
            "MATCH (p:Person {dataset: $dataset}) "
            "FOREACH (x IN [1,2,3] | SET p.count = x) RETURN p"
        )
        _assert_failed(_validate(cypher), rule=3)

    def test_load_csv_rejected(self):
        cypher = "LOAD CSV FROM 'file:///data.csv' AS row RETURN row"
        _assert_failed(_validate(cypher), rule=3)

    def test_drop_index_rejected(self):
        cypher = "DROP INDEX ON :Person(display_name)"
        _assert_failed(_validate(cypher), rule=3)

    def test_using_periodic_commit_rejected(self):
        cypher = "USING PERIODIC COMMIT 1000 LOAD CSV FROM 'x.csv' AS row RETURN row"
        _assert_failed(_validate(cypher))  # rule 3 (PERIODIC) or rule 1 (LOAD)

    def test_detach_delete_rejected(self):
        """DETACH DELETE — DETACH is caught as extra forbidden, DELETE by Rule 1."""
        cypher = "MATCH (p:Person {dataset: $dataset}) DETACH DELETE p"
        # May fail on Rule 1 (DELETE) or Rule 3 (DETACH) — either is correct
        result = _validate(cypher)
        _assert_failed(result)


# ---------------------------------------------------------------------------
# Rule 4 — Schema label and relationship type validation
# ---------------------------------------------------------------------------

class TestRule4SchemaValidation:
    def test_unknown_node_label_rejected(self):
        cypher = "MATCH (x:Suspect {dataset: $dataset}) RETURN x LIMIT 10"
        _assert_failed(_validate(cypher), rule=4)

    def test_unknown_label_Hacker_rejected(self):
        cypher = "MATCH (h:Hacker {dataset: $dataset}) RETURN h"
        _assert_failed(_validate(cypher), rule=4)

    def test_unknown_label_User_rejected(self):
        cypher = "MATCH (u:User {dataset: $dataset}) RETURN u"
        _assert_failed(_validate(cypher), rule=4)

    def test_unknown_relationship_type_rejected(self):
        cypher = (
            "MATCH (p:Person {dataset: $dataset})-[:KNOWS]->(q:Person {dataset: $dataset}) "
            "RETURN p, q"
        )
        _assert_failed(_validate(cypher), rule=4)

    def test_unknown_rel_type_FRIENDS_WITH_rejected(self):
        cypher = (
            "MATCH (a:Person {dataset: $dataset})-[:FRIENDS_WITH]->(b:Person {dataset: $dataset}) "
            "RETURN a, b"
        )
        _assert_failed(_validate(cypher), rule=4)

    def test_pipe_separated_invalid_type_rejected(self):
        """One invalid type in a pipe list rejects the whole query."""
        cypher = (
            "MATCH (a:Person {dataset: $dataset})-[:CALLED|KNOWS]->(b {dataset: $dataset}) "
            "RETURN a, b"
        )
        _assert_failed(_validate(cypher), rule=4)

    def test_pipe_separated_all_valid_types_accepted(self):
        """All valid types in a pipe list is accepted."""
        cypher = (
            "MATCH (a:Person {dataset: $dataset})-[:CALLED|MET|OWNS]->(b {dataset: $dataset}) "
            "RETURN a, b"
        )
        _assert_valid(_validate(cypher))

    def test_known_label_in_filter_not_double_counted(self):
        """A known label appearing in a WHERE property check should not trigger Rule 4."""
        cypher = (
            "MATCH (p:Person {dataset: $dataset}) "
            "WHERE p.entity_type = 'Person' RETURN p"
        )
        _assert_valid(_validate(cypher))


# ---------------------------------------------------------------------------
# Rule 5 — Dataset filter enforcement and injection
# ---------------------------------------------------------------------------

class TestRule5DatasetFilter:
    def test_cross_dataset_literal_mismatch_rejected(self):
        """Hardcoded wrong dataset literal is rejected (AC-d)."""
        cypher = "MATCH (p:Person {dataset: 'live_public'}) RETURN p"
        _assert_failed(_validate(cypher, dataset="synthetic_demo"), rule=5)

    def test_cross_dataset_live_public_in_synthetic_request(self):
        cypher = "MATCH (p:Person {dataset: 'live_public'}) RETURN p LIMIT 5"
        _assert_failed(_validate(cypher, dataset="synthetic_demo"), rule=5)

    def test_dataset_param_reference_accepted(self):
        """$dataset parameter reference is always accepted — not a mismatch."""
        cypher = "MATCH (p:Person {dataset: $dataset}) RETURN p"
        _assert_valid(_validate(cypher, dataset="synthetic_demo"))

    def test_dataset_filter_injected_when_absent(self):
        """Dataset filter is injected when absent (DOC3 §10 rule 5: 'or the validator injects it')."""
        cypher = "MATCH (p:Person) RETURN p LIMIT 5"
        result = _validate(cypher, dataset="synthetic_demo")
        vq = _assert_valid(result)
        # Injected cypher must contain dataset scoping
        assert "dataset" in vq.cypher.lower(), (
            "Injected cypher should contain 'dataset' filter"
        )

    def test_dataset_param_always_in_parameters(self):
        cypher = "MATCH (p:Person {dataset: $dataset}) RETURN p"
        vq = _assert_valid(_validate(cypher, dataset="synthetic_demo"))
        assert vq.parameters["dataset"] == "synthetic_demo"

    def test_correct_literal_dataset_accepted(self):
        """An exact literal match for the requested dataset is accepted."""
        cypher = "MATCH (p:Person {dataset: 'synthetic_demo'}) RETURN p LIMIT 10"
        _assert_valid(_validate(cypher, dataset="synthetic_demo"))

    def test_live_public_dataset_accepted_when_requested(self):
        """live_public queries are valid when the request specifies live_public."""
        cypher = "MATCH (p:Person {dataset: $dataset}) RETURN p LIMIT 5"
        _assert_valid(_validate(cypher, dataset="live_public"))


# ---------------------------------------------------------------------------
# Rule 6 — Timeout embedded in ValidatedQuery for F3
# ---------------------------------------------------------------------------

class TestRule6Timeout:
    def test_timeout_ms_embedded_in_valid_query(self):
        cypher = "MATCH (p:Person {dataset: $dataset}) RETURN p LIMIT 1"
        result = _validate(cypher, timeout_ms=15_000)
        assert _assert_valid(result).timeout_ms == 15_000

    def test_default_timeout_used_when_not_specified(self):
        v = CypherValidator()  # uses config / fallback 30_000
        q = _make_query("MATCH (p:Person {dataset: $dataset}) RETURN p LIMIT 1")
        result = v.validate(q)
        vq = _assert_valid(result)
        assert vq.timeout_ms > 0

    def test_custom_timeout_overrides_default(self):
        v = CypherValidator(timeout_ms=999)
        q = _make_query("MATCH (p:Person {dataset: $dataset}) RETURN p LIMIT 1")
        result = v.validate(q)
        assert _assert_valid(result).timeout_ms == 999


# ---------------------------------------------------------------------------
# ValidationFailed shape / contract
# ---------------------------------------------------------------------------

class TestValidationFailedShape:
    def test_status_is_validation_failed(self):
        cypher = "CREATE (p:Person {dataset: $dataset}) RETURN p"
        result = _validate(cypher)
        vf = _assert_failed(result)
        assert vf.status == "validation_failed"

    def test_rule_number_is_int(self):
        cypher = "CREATE (p:Person {dataset: $dataset}) RETURN p"
        result = _validate(cypher)
        vf = _assert_failed(result)
        assert isinstance(vf.rule, int)

    def test_reason_is_non_empty_string(self):
        cypher = "CALL apoc.meta.schema()"
        result = _validate(cypher)
        vf = _assert_failed(result)
        assert isinstance(vf.reason, str)
        assert len(vf.reason) > 0

    def test_reason_mentions_forbidden_clause(self):
        cypher = "CALL gds.pageRank.stream('g') YIELD nodeId RETURN nodeId"
        vf = _assert_failed(_validate(cypher))
        assert "CALL" in vf.reason


# ---------------------------------------------------------------------------
# ValidatedQuery shape / contract
# ---------------------------------------------------------------------------

class TestValidatedQueryShape:
    BASE = "MATCH (p:Person {dataset: $dataset}) RETURN p LIMIT 1"

    def test_generated_by_is_llm(self):
        vq = _assert_valid(_validate(self.BASE))
        assert vq.generated_by == "llm"

    def test_cypher_is_string(self):
        vq = _assert_valid(_validate(self.BASE))
        assert isinstance(vq.cypher, str)

    def test_parameters_is_dict(self):
        vq = _assert_valid(_validate(self.BASE))
        assert isinstance(vq.parameters, dict)

    def test_timeout_ms_is_int(self):
        vq = _assert_valid(_validate(self.BASE, timeout_ms=5_000))
        assert isinstance(vq.timeout_ms, int)


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

class TestGetCypherValidator:
    def test_returns_cypher_validator(self):
        v = get_cypher_validator()
        assert isinstance(v, CypherValidator)

    def test_accepts_timeout_ms(self):
        v = get_cypher_validator(timeout_ms=1_234)
        assert v._timeout_ms == 1_234


# ---------------------------------------------------------------------------
# Edge cases and security hardening
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_cypher_accepted(self):
        """Empty string — no forbidden clauses, no labels; Rule 5 injects dataset."""
        # An empty query is technically valid structurally (returns nothing);
        # F3 will produce an empty result. Validator should not crash.
        result = _validate("")
        # Either valid (with injection) or failed (no RETURN clause) — both acceptable
        # as long as no exception is raised.
        assert isinstance(result, (ValidatedQuery, ValidationFailed))

    def test_multiline_cypher_accepted(self):
        cypher = (
            "MATCH (p:Person {dataset: $dataset})\n"
            "WHERE p.display_name STARTS WITH 'R'\n"
            "RETURN p.display_name\n"
            "ORDER BY p.display_name\n"
            "LIMIT 10"
        )
        _assert_valid(_validate(cypher))

    def test_case_insensitive_keywords_valid(self):
        """Lowercase keywords are valid Cypher."""
        cypher = "match (p:Person {dataset: $dataset}) return p limit 5"
        _assert_valid(_validate(cypher))

    def test_compound_adversarial_call_and_write(self):
        """Query with both CALL and CREATE — Rule 1 or 2 must fire."""
        cypher = "CALL apoc.create.node(['Person'], {}) YIELD node RETURN node"
        result = _validate(cypher)
        _assert_failed(result)
        assert result.rule in (1, 2)

    def test_valid_query_with_count_aggregation(self):
        cypher = (
            "MATCH (p:Person {dataset: $dataset})-[:CALLED]->(ph:Phone {dataset: $dataset}) "
            "RETURN p.display_name, count(ph) AS call_count "
            "ORDER BY call_count DESC LIMIT 10"
        )
        _assert_valid(_validate(cypher))

    def test_valid_query_with_collect(self):
        cypher = (
            "MATCH (p:Person {dataset: $dataset})-[:CALLED]->(ph:Phone {dataset: $dataset}) "
            "RETURN p.display_name, collect(ph.display_name) AS phones"
        )
        _assert_valid(_validate(cypher))

    def test_where_not_contains_rejected_write(self):
        """'NOT' in WHERE should not interfere with write-clause detection."""
        cypher = (
            "MATCH (p:Person {dataset: $dataset}) "
            "WHERE NOT p.display_name CONTAINS 'Admin' "
            "RETURN p LIMIT 10"
        )
        _assert_valid(_validate(cypher))

    def test_rule_ordering_write_detected_before_schema(self):
        """Rule 1 fires before Rule 4 for a query with both issues."""
        cypher = "CREATE (h:Hacker {dataset: $dataset}) RETURN h"
        vf = _assert_failed(_validate(cypher))
        assert vf.rule == 1  # CREATE caught first

