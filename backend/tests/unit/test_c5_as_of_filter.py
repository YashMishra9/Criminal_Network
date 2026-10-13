"""Unit tests for C5 — as_of Query Filter (DOC3 §2.4A, Contract Invariant 14).

Task C5 acceptance criteria (§12):
  AC1: A relationship exactly at valid_from is included.
  AC2: A relationship with valid_to before as_of is excluded.
  AC3: An isolated entity is always included regardless of as_of.
  AC4: A connected entity is excluded when its only relationship falls
       outside the as_of window.

Additional boundary conditions:
  - valid_to IS NULL (open-ended) — always visible when valid_from <= as_of.
  - valid_to == as_of (boundary at the close end) — must be included.
  - valid_from > as_of — excluded.
  - as_of is None — no filter applied (is_active False, empty strings).
  - Cypher fragments are well-formed strings with correct parameter names.

All tests are pure-Python; no Neo4j connection is required.
"""

import pytest

from app.graph.queries import (
    AsOfFilter,
    build_as_of_filter,
    is_entity_visible,
    is_relationship_visible,
    relationship_visibility_clause,
)


# ===========================================================================
# is_relationship_visible() — DOC3 §2.4A Rule 1
# ===========================================================================

class TestRelationshipVisibility:
    """Pure-Python Rule 1 boundary conditions."""

    # AC1 — relationship at exactly valid_from must be included
    def test_ac1_exactly_at_valid_from_is_visible(self):
        """AC1: valid_from == as_of → included."""
        assert is_relationship_visible(
            valid_from="2024-01-01T00:00:00Z",
            valid_to=None,
            as_of="2024-01-01T00:00:00Z",
        )

    # AC2 — valid_to before as_of → excluded
    def test_ac2_valid_to_before_as_of_is_excluded(self):
        """AC2: valid_to < as_of → excluded (relationship has ended)."""
        assert not is_relationship_visible(
            valid_from="2024-01-01T00:00:00Z",
            valid_to="2024-03-01T00:00:00Z",
            as_of="2024-06-01T00:00:00Z",
        )

    def test_valid_from_after_as_of_is_excluded(self):
        """Rule 1: valid_from > as_of → excluded (hasn't started yet)."""
        assert not is_relationship_visible(
            valid_from="2024-07-01T00:00:00Z",
            valid_to=None,
            as_of="2024-06-01T00:00:00Z",
        )

    def test_null_valid_to_is_open_ended_visible(self):
        """valid_to=None means open-ended — visible for all as_of >= valid_from."""
        assert is_relationship_visible(
            valid_from="2023-01-01T00:00:00Z",
            valid_to=None,
            as_of="2099-12-31T23:59:59Z",
        )

    def test_valid_to_exactly_at_as_of_is_included(self):
        """Boundary at close end: valid_to == as_of → included (>= rule)."""
        assert is_relationship_visible(
            valid_from="2024-01-01T00:00:00Z",
            valid_to="2024-06-01T00:00:00Z",
            as_of="2024-06-01T00:00:00Z",
        )

    def test_valid_from_before_and_valid_to_after_is_visible(self):
        """Normal in-window case: valid_from < as_of < valid_to → visible."""
        assert is_relationship_visible(
            valid_from="2024-01-01T00:00:00Z",
            valid_to="2024-12-31T00:00:00Z",
            as_of="2024-06-15T00:00:00Z",
        )

    def test_valid_to_one_day_before_as_of_excluded(self):
        """valid_to one second before as_of → excluded."""
        assert not is_relationship_visible(
            valid_from="2024-01-01T00:00:00Z",
            valid_to="2024-05-31T23:59:59Z",
            as_of="2024-06-01T00:00:00Z",
        )

    def test_valid_from_exactly_one_second_after_as_of_excluded(self):
        """valid_from one second after as_of → excluded (hasn't started yet)."""
        assert not is_relationship_visible(
            valid_from="2024-06-01T00:00:01Z",
            valid_to=None,
            as_of="2024-06-01T00:00:00Z",
        )

    def test_date_only_format_boundary(self):
        """ISO-8601 date-only strings compare correctly (YYYY-MM-DD)."""
        assert is_relationship_visible(
            valid_from="2024-01-01",
            valid_to=None,
            as_of="2024-01-01",
        )
        assert not is_relationship_visible(
            valid_from="2024-01-02",
            valid_to=None,
            as_of="2024-01-01",
        )


# ===========================================================================
# is_entity_visible() — DOC3 §2.4A Rule 2
# ===========================================================================

class TestEntityVisibility:
    """Pure-Python Rule 2: entity visibility is derived, not independent."""

    # AC3 — isolated entity always visible
    def test_ac3_isolated_entity_always_visible(self):
        """AC3: entity with zero dataset relationships is always shown."""
        assert is_entity_visible(
            has_visible_relationship=False,
            total_dataset_relationships=0,
        )

    # AC4 — connected entity excluded when its only relationship is outside window
    def test_ac4_connected_entity_excluded_when_no_visible_relationships(self):
        """AC4: entity with relationships but none visible → excluded."""
        assert not is_entity_visible(
            has_visible_relationship=False,
            total_dataset_relationships=2,
        )

    def test_entity_with_visible_relationship_is_included(self):
        """Rule 2a: entity has ≥1 visible relationship → shown."""
        assert is_entity_visible(
            has_visible_relationship=True,
            total_dataset_relationships=1,
        )

    def test_entity_with_multiple_rels_but_none_visible_excluded(self):
        """Connected entity (many rels), none visible at as_of → excluded."""
        assert not is_entity_visible(
            has_visible_relationship=False,
            total_dataset_relationships=10,
        )

    def test_isolated_entity_visible_regardless_of_has_visible_rel_flag(self):
        """Rule 2b takes priority: total_dataset_relationships==0 always wins."""
        # Even if has_visible_relationship is somehow True (shouldn't happen in
        # practice for an isolated entity), the result must still be True.
        assert is_entity_visible(
            has_visible_relationship=True,
            total_dataset_relationships=0,
        )

    def test_entity_never_excluded_by_its_own_timestamps(self):
        """DOC3 §2.4A: entities have no independent temporal rule; Rule 2 only.

        is_entity_visible() has no created_at/updated_at parameter — callers
        must not pass entity timestamps here.
        """
        import inspect
        sig = inspect.signature(is_entity_visible)
        param_names = set(sig.parameters.keys())
        # Must not have any entity-timestamp parameters
        assert "created_at" not in param_names
        assert "updated_at" not in param_names


# ===========================================================================
# relationship_visibility_clause() — Cypher fragment
# ===========================================================================

class TestRelationshipVisibilityClause:
    """Verify the Cypher fragment is well-formed and uses correct param names."""

    def test_default_aliases_in_output(self):
        """Default rel_alias='r' and as_of_param='as_of' appear in fragment."""
        clause = relationship_visibility_clause()
        assert "r.valid_from" in clause
        assert "r.valid_to" in clause
        assert "$as_of" in clause

    def test_custom_alias_appears_in_output(self):
        """Custom rel_alias propagates into the Cypher fragment."""
        clause = relationship_visibility_clause(rel_alias="rel", as_of_param="cutoff")
        assert "rel.valid_from" in clause
        assert "rel.valid_to" in clause
        assert "$cutoff" in clause
        assert "r.valid_from" not in clause  # default alias must not bleed through

    def test_clause_contains_null_check(self):
        """Fragment must include IS NULL for the valid_to open-ended case."""
        clause = relationship_visibility_clause()
        assert "IS NULL" in clause

    def test_clause_contains_both_comparisons(self):
        """Fragment must include both <= (valid_from) and >= (valid_to)."""
        clause = relationship_visibility_clause()
        assert "<=" in clause
        assert ">=" in clause

    def test_clause_is_nonempty_string(self):
        """relationship_visibility_clause() must return a non-empty string."""
        clause = relationship_visibility_clause()
        assert isinstance(clause, str)
        assert len(clause) > 0

    def test_no_literal_values_interpolated(self):
        """No literal timestamps or dataset values must appear in the fragment.

        The fragment must use only parameter references ($param) to be safe
        for parameterised execution.
        """
        clause = relationship_visibility_clause()
        # Should not contain any ISO-8601 literal dates
        import re
        has_literal_date = bool(re.search(r"\d{4}-\d{2}-\d{2}", clause))
        assert not has_literal_date, (
            f"Literal date found in Cypher fragment (should use $param): {clause}"
        )


# ===========================================================================
# build_as_of_filter() — complete filter bundle
# ===========================================================================

class TestBuildAsOfFilter:
    """Verify build_as_of_filter() builds correctly for both None and active cases."""

    # --- as_of is None (no filter) ---

    def test_none_as_of_returns_empty_params(self):
        """as_of=None → params dict is empty (no temporal parameter added)."""
        f = build_as_of_filter(None)
        assert f.params == {}

    def test_none_as_of_returns_empty_relationship_where(self):
        """as_of=None → relationship_where is empty string (no filter)."""
        f = build_as_of_filter(None)
        assert f.relationship_where == ""

    def test_none_as_of_returns_empty_entity_subquery(self):
        """as_of=None → entity_subquery is empty string (no filter)."""
        f = build_as_of_filter(None)
        assert f.entity_subquery == ""

    def test_none_as_of_is_not_active(self):
        """as_of=None → is_active is False."""
        f = build_as_of_filter(None)
        assert not f.is_active

    # --- as_of is provided (filter active) ---

    def test_active_as_of_is_active(self):
        """Supplying as_of → is_active is True."""
        f = build_as_of_filter("2024-06-01T00:00:00Z")
        assert f.is_active

    def test_active_as_of_params_contains_as_of_key(self):
        """params dict must contain the as_of_param key with the supplied value."""
        ts = "2024-06-01T00:00:00Z"
        f = build_as_of_filter(ts)
        assert "as_of" in f.params
        assert f.params["as_of"] == ts

    def test_custom_as_of_param_name_used_in_params_and_clause(self):
        """Custom as_of_param propagates into both params dict and Cypher."""
        ts = "2024-06-01T00:00:00Z"
        f = build_as_of_filter(ts, as_of_param="cutoff")
        assert "cutoff" in f.params
        assert f.params["cutoff"] == ts
        assert "$cutoff" in f.relationship_where

    def test_relationship_where_nonempty_when_active(self):
        """relationship_where must be a non-empty string when as_of is given."""
        f = build_as_of_filter("2024-06-01T00:00:00Z")
        assert isinstance(f.relationship_where, str)
        assert len(f.relationship_where) > 0

    def test_entity_subquery_nonempty_when_active(self):
        """entity_subquery must be a non-empty string when as_of is given."""
        f = build_as_of_filter("2024-06-01T00:00:00Z")
        assert isinstance(f.entity_subquery, str)
        assert len(f.entity_subquery) > 0

    def test_entity_subquery_contains_dataset_param(self):
        """Entity subquery must reference the dataset parameter."""
        f = build_as_of_filter("2024-06-01T00:00:00Z", dataset_param="dataset")
        assert "$dataset" in f.entity_subquery

    def test_entity_subquery_contains_exists_keyword(self):
        """Entity subquery must use EXISTS for the sub-pattern match (Cypher)."""
        f = build_as_of_filter("2024-06-01T00:00:00Z")
        assert "EXISTS" in f.entity_subquery

    def test_entity_subquery_contains_not_exists_for_isolated(self):
        """Entity subquery must include NOT EXISTS for the isolated-entity case."""
        f = build_as_of_filter("2024-06-01T00:00:00Z")
        assert "NOT EXISTS" in f.entity_subquery

    def test_entity_subquery_covers_both_directions(self):
        """Entity subquery must check both outgoing and incoming relationships."""
        f = build_as_of_filter("2024-06-01T00:00:00Z")
        # Bidirectional: -[r]->() and ()<-[r]-
        assert "->" in f.entity_subquery
        assert "<-" in f.entity_subquery

    def test_relationship_where_contains_rule1_logic(self):
        """relationship_where must encode Rule 1 (valid_from, valid_to, IS NULL)."""
        f = build_as_of_filter("2024-06-01T00:00:00Z")
        clause = f.relationship_where
        assert "valid_from" in clause
        assert "valid_to" in clause
        assert "IS NULL" in clause

    def test_custom_entity_alias_appears_in_entity_subquery(self):
        """Custom entity_alias propagates into entity_subquery."""
        f = build_as_of_filter("2024-06-01", entity_alias="entity")
        assert "entity" in f.entity_subquery

    def test_no_literal_values_in_relationship_where(self):
        """relationship_where must not contain any literal timestamps."""
        import re
        f = build_as_of_filter("2024-06-01T00:00:00Z")
        has_literal = bool(re.search(r"\d{4}-\d{2}-\d{2}", f.relationship_where))
        assert not has_literal, (
            "relationship_where must use $param, not a literal timestamp"
        )

    def test_no_literal_values_in_entity_subquery(self):
        """entity_subquery must not contain any literal timestamps."""
        import re
        f = build_as_of_filter("2024-06-01T00:00:00Z")
        has_literal = bool(re.search(r"\d{4}-\d{2}-\d{2}", f.entity_subquery))
        assert not has_literal, (
            "entity_subquery must use $param, not a literal timestamp"
        )


# ===========================================================================
# AsOfFilter immutability
# ===========================================================================

class TestAsOfFilterImmutability:
    """AsOfFilter must be immutable after construction."""

    def test_filter_is_immutable(self):
        """Attempting to set an attribute on AsOfFilter raises AttributeError."""
        f = build_as_of_filter("2024-06-01T00:00:00Z")
        with pytest.raises(AttributeError):
            f.params = {}  # type: ignore[misc]

    def test_filter_has_repr(self):
        """AsOfFilter must have a useful repr for debugging."""
        f = build_as_of_filter("2024-06-01T00:00:00Z")
        r = repr(f)
        assert "AsOfFilter" in r


# ===========================================================================
# AC boundary conditions: combined Rule 1 + Rule 2
# ===========================================================================

class TestBoundaryConditionsCombined:
    """End-to-end acceptance criteria boundary checks using pure-Python helpers."""

    def test_ac1_exactly_at_valid_from_relationship_visible(self):
        """AC1 full: relationship at exactly valid_from is included."""
        as_of = "2024-01-15T12:00:00Z"
        assert is_relationship_visible(
            valid_from=as_of,  # exactly at the boundary
            valid_to=None,
            as_of=as_of,
        )

    def test_ac2_valid_to_before_as_of_relationship_excluded(self):
        """AC2 full: relationship with valid_to before as_of is excluded."""
        assert not is_relationship_visible(
            valid_from="2024-01-01T00:00:00Z",
            valid_to="2024-02-28T23:59:59Z",
            as_of="2024-06-01T00:00:00Z",
        )

    def test_ac3_isolated_entity_always_included(self):
        """AC3 full: isolated entity always shown regardless of as_of."""
        # No matter what as_of is, an entity with 0 relationships is always visible
        for total_rels in [0]:
            assert is_entity_visible(
                has_visible_relationship=False,
                total_dataset_relationships=total_rels,
            ), "Isolated entity must always be visible"

    def test_ac4_connected_entity_excluded_only_relationship_out_of_window(self):
        """AC4 full: connected entity excluded when its only relationship is outside window."""
        # The entity has 1 relationship (total_dataset_relationships=1)
        # but it falls outside the as_of window (has_visible_relationship=False)
        assert not is_entity_visible(
            has_visible_relationship=False,
            total_dataset_relationships=1,
        ), "Connected entity with no visible rels must be excluded"

    def test_no_as_of_means_no_filter(self):
        """as_of=None produces an inactive filter (passes through all data)."""
        f = build_as_of_filter(None)
        assert not f.is_active
        assert f.params == {}
        assert f.relationship_where == ""
        assert f.entity_subquery == ""


# ===========================================================================
# Contract Invariant 14 — single implementation check
# ===========================================================================

class TestInvariant14SingleImplementation:
    """Verify queries.py is the canonical location (no competing implementations)."""

    def test_public_api_exports_all_required_symbols(self):
        """queries.py must export all symbols downstream callers will import."""
        import app.graph.queries as q_module
        required = [
            "relationship_visibility_clause",
            "build_as_of_filter",
            "is_relationship_visible",
            "is_entity_visible",
            "AsOfFilter",
        ]
        for name in required:
            assert hasattr(q_module, name), (
                f"queries.py is missing required export: {name!r}"
            )

    def test_as_of_filter_is_active_property_works(self):
        """AsOfFilter.is_active must be False for None and True for a timestamp."""
        inactive = build_as_of_filter(None)
        active = build_as_of_filter("2024-06-01T00:00:00Z")
        assert not inactive.is_active
        assert active.is_active

    def test_queries_module_importable_without_neo4j(self):
        """queries.py must be importable without a live Neo4j connection."""
        # This import must succeed even when Neo4j is unavailable.
        import importlib
        mod = importlib.import_module("app.graph.queries")
        assert mod is not None
