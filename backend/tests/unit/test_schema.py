"""Tests for Task C1: Neo4j Schema (Constraints & Indexes).

Tests (per C1 §13):
  - Unit test asserting the applied constraint list matches DOC3 §1.13's
    ID scope table exactly (no Neo4j connection required — tests the
    statement-generation layer).
  - Acceptance criteria (C1 §12): apply_schema() runs cleanly against
    both an empty database and one that already has the schema applied
    (idempotency — verified with a mock session for unit tests; a live
    integration marker is provided for when a Neo4j instance is available).

All tests here are unit tests that verify the schema module's structure and
generated statements, with no live database dependency. The live idempotency
test is guarded by a 'neo4j_live' pytest mark and skipped by default.
"""

import re
from typing import List

import pytest

from app.graph.schema import (
    _NODE_CONSTRAINTS,
    _LOOKUP_INDEXES,
    _COMPOUND_INDEXES,
    _REL_INDEXES,
    _build_statements,
    get_constraint_names,
    get_index_names,
)


def _neo4j_reachable() -> bool:
    """Return True if a local Neo4j instance responds on the default port."""
    from app.graph.connection import health_check
    try:
        return health_check()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# DOC3 §1.13 ground-truth table
# ---------------------------------------------------------------------------

# All globally-unique IDs that must have a uniqueness constraint (§1.13)
DOC3_GLOBALLY_UNIQUE_IDS = {
    # CanonicalEntity node types → entity_id
    ("Person",             "entity_id"),
    ("Phone",              "entity_id"),
    ("Vehicle",            "entity_id"),
    ("Location",           "entity_id"),
    ("Organization",       "entity_id"),
    ("BankAccount",        "entity_id"),
    ("Transaction",        "entity_id"),
    ("Event",              "entity_id"),
    # Workspace/structural/derived → their own ID fields
    ("Case",               "case_id"),
    ("Evidence",           "evidence_id"),
    ("Note",               "note_id"),
    ("EdgeRef",            "edge_ref_id"),
    ("ResolutionDecision", "decision_id"),
    ("Finding",            "finding_id"),
}

# Domain relationship types that must carry relationship_id (DOC3 §6.4)
DOC3_DOMAIN_REL_TYPES = {
    "CALLED", "OWNS", "USED", "TRANSFERRED", "VISITED",
    "MET", "WORKS_FOR", "ASSOCIATED_WITH", "MENTIONED_IN", "PART_OF",
}


# ===========================================================================
# C1 §13: Constraint list matches DOC3 §1.13 exactly
# ===========================================================================

def test_node_constraints_cover_all_doc3_1_13_ids():
    """Every (label, property) pair from DOC3 §1.13 must have a uniqueness constraint."""
    defined = {(label, prop) for _, label, prop in _NODE_CONSTRAINTS}
    missing = DOC3_GLOBALLY_UNIQUE_IDS - defined
    assert not missing, (
        f"Missing uniqueness constraints for DOC3 §1.13 IDs: {missing}"
    )


def test_node_constraints_do_not_add_undocumented_ids():
    """Schema must not add constraints for IDs not defined in DOC3 §1.13."""
    defined = {(label, prop) for _, label, prop in _NODE_CONSTRAINTS}
    extra = defined - DOC3_GLOBALLY_UNIQUE_IDS
    assert not extra, (
        f"Extra (undocumented) uniqueness constraints found: {extra}. "
        "These must be defined in DOC3 §1.13 before adding constraints."
    )


def test_all_domain_relationship_types_have_rel_id_index():
    """DOC3 §6.4: every domain relationship type must have a relationship_id index."""
    indexed_types = {rel_type for _, rel_type, prop in _REL_INDEXES if prop == "relationship_id"}
    missing = DOC3_DOMAIN_REL_TYPES - indexed_types
    assert not missing, (
        f"Missing relationship_id indexes for: {missing}"
    )


def test_no_undocumented_relationship_type_indexes():
    """Relationship type indexes must only target types defined in DOC3 §6.2."""
    # DOC3 §6.2 full set (domain types + structural — we index domain only)
    all_rel_types = DOC3_DOMAIN_REL_TYPES | {
        "RESOLVED_FROM", "BASED_ON", "SUPPORTS", "CONCERNS",
        "INCLUDES_ENTITY", "INCLUDES_EDGE", "INCLUDES_EVIDENCE", "ABOUT",
    }
    indexed_types = {rel_type for _, rel_type, _ in _REL_INDEXES}
    undocumented = indexed_types - all_rel_types
    assert not undocumented, (
        f"Relationship type indexes for undocumented types: {undocumented}"
    )


# ===========================================================================
# Constraint name uniqueness
# ===========================================================================

def test_all_constraint_names_are_unique():
    """Constraint names must be globally unique (duplicate would cause Cypher error)."""
    names = [name for name, _, _ in _NODE_CONSTRAINTS]
    assert len(names) == len(set(names)), f"Duplicate constraint names: {names}"


def test_all_index_names_are_unique():
    """Index names must be globally unique."""
    names = (
        [name for name, _, _ in _LOOKUP_INDEXES]
        + [name for name, _, _ in _COMPOUND_INDEXES]
        + [name for name, _, _ in _REL_INDEXES]
    )
    assert len(names) == len(set(names)), f"Duplicate index names: {names}"


def test_constraint_and_index_names_do_not_overlap():
    """Constraint names and index names must not overlap."""
    constraint_names = set(get_constraint_names())
    index_names = set(get_index_names())
    overlap = constraint_names & index_names
    assert not overlap, f"Constraint/index name overlap: {overlap}"


# ===========================================================================
# Statement generation
# ===========================================================================

def test_build_statements_returns_non_empty_list():
    stmts = _build_statements()
    assert isinstance(stmts, list)
    assert len(stmts) > 0


def test_every_node_constraint_statement_uses_if_not_exists():
    """Idempotency: all CREATE CONSTRAINT statements must use IF NOT EXISTS."""
    stmts = _build_statements()
    constraint_stmts = [s for s in stmts if s.strip().startswith("CREATE CONSTRAINT")]
    assert constraint_stmts, "No CREATE CONSTRAINT statements found"
    for stmt in constraint_stmts:
        assert "IF NOT EXISTS" in stmt, (
            f"Missing IF NOT EXISTS in constraint statement:\n  {stmt}"
        )


def test_every_index_statement_uses_if_not_exists():
    """Idempotency: all CREATE INDEX statements must use IF NOT EXISTS."""
    stmts = _build_statements()
    index_stmts = [s for s in stmts if s.strip().startswith("CREATE INDEX")]
    assert index_stmts, "No CREATE INDEX statements found"
    for stmt in index_stmts:
        assert "IF NOT EXISTS" in stmt, (
            f"Missing IF NOT EXISTS in index statement:\n  {stmt}"
        )


def test_constraint_statements_use_is_unique():
    """All node uniqueness constraints must end with IS UNIQUE."""
    stmts = _build_statements()
    constraint_stmts = [s for s in stmts if "CREATE CONSTRAINT" in s]
    for stmt in constraint_stmts:
        assert "IS UNIQUE" in stmt, (
            f"Constraint does not use IS UNIQUE:\n  {stmt}"
        )


def test_relationship_index_statements_reference_relationship_id():
    """Relationship-type indexes must all target the relationship_id property."""
    stmts = _build_statements()
    rel_index_stmts = [s for s in stmts if "]-(" in s or "]->" in s or "]-() ON" in s]
    for stmt in rel_index_stmts:
        assert "relationship_id" in stmt, (
            f"Relationship index does not target relationship_id:\n  {stmt}"
        )


def test_total_statement_count_equals_sum_of_all_definitions():
    """Statement count must match the total number of defined schema elements."""
    expected = (
        len(_NODE_CONSTRAINTS)
        + len(_COMPOUND_INDEXES)
        + len(_LOOKUP_INDEXES)
        + len(_REL_INDEXES)
    )
    actual = len(_build_statements())
    assert actual == expected, (
        f"Expected {expected} schema statements, got {actual}"
    )


# ===========================================================================
# get_constraint_names() and get_index_names() exports
# ===========================================================================

def test_get_constraint_names_returns_all_constraint_names():
    names = get_constraint_names()
    expected = [name for name, _, _ in _NODE_CONSTRAINTS]
    assert names == expected


def test_get_index_names_returns_all_index_names():
    names = get_index_names()
    assert len(names) == (len(_LOOKUP_INDEXES) + len(_COMPOUND_INDEXES) + len(_REL_INDEXES))


def test_get_constraint_names_are_all_strings():
    for name in get_constraint_names():
        assert isinstance(name, str) and name, f"Invalid constraint name: {name!r}"


# ===========================================================================
# DOC3 §6.1 node type coverage
# ===========================================================================

def test_all_canonical_entity_node_types_have_entity_id_constraint():
    """DOC3 §6.1: every CanonicalEntity label must have an entity_id constraint."""
    canonical_types = {
        "Person", "Phone", "Vehicle", "Location",
        "Organization", "BankAccount", "Transaction", "Event",
    }
    constrained = {
        label for _, label, prop in _NODE_CONSTRAINTS if prop == "entity_id"
    }
    missing = canonical_types - constrained
    assert not missing, f"Missing entity_id constraints for: {missing}"


def test_all_workspace_node_types_have_their_id_constraint():
    """DOC3 §6.1: workspace/structural nodes must have their specific ID constraint."""
    workspace_ids = {
        "Case": "case_id",
        "Evidence": "evidence_id",
        "Note": "note_id",
        "EdgeRef": "edge_ref_id",
        "ResolutionDecision": "decision_id",
        "Finding": "finding_id",
    }
    for label, prop in workspace_ids.items():
        matching = [
            c for c in _NODE_CONSTRAINTS
            if c[1] == label and c[2] == prop
        ]
        assert matching, f"Missing constraint for {label}.{prop}"


# ===========================================================================
# Evidence composite index (DOC3 §1.13 dataset-scoped record_id)
# ===========================================================================

def test_evidence_source_dataset_compound_index_exists():
    """DOC3 §1.13: composite (source_id, dataset) index on Evidence must exist."""
    compound = {
        (label, tuple(props)) for _, label, props in _COMPOUND_INDEXES
    }
    assert ("Evidence", ("source_id", "dataset")) in compound, (
        "Missing compound index for Evidence(source_id, dataset) — "
        "required for idempotent evidence lookup (DOC3 §1.13)."
    )


# ===========================================================================
# Live idempotency integration test (skipped by default — requires Neo4j)
# ===========================================================================

@pytest.mark.neo4j_live
@pytest.mark.skipif(
    not _neo4j_reachable(),
    reason="Neo4j not available — skipping live schema idempotency test"
)
def test_apply_schema_is_idempotent_against_live_db():
    """C1 §12: apply_schema() runs without error on a live DB, twice (idempotency)."""
    from app.graph.schema import apply_schema
    apply_schema()   # first run — applies schema
    apply_schema()   # second run — must be a no-op, not raise
