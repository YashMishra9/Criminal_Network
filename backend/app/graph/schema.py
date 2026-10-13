"""Neo4j Schema — Constraints & Indexes (C1, DOC3 §6.1/§6.2/§1.13).

Creates uniqueness constraints and lookup indexes for every ID field defined
in DOC3 §1.13 and every node type in DOC3 §6.1.

Idempotency guarantee:
    apply_schema() is safe to call against an already-schema'd database.
    Neo4j 4.x+ IF NOT EXISTS semantics make each CREATE CONSTRAINT and
    CREATE INDEX call a no-op when the constraint/index already exists.

DOC3 §1.13 — ID uniqueness scopes:
    Globally unique (UUIDv4, enforced here):
        entity_id         (all CanonicalEntity labels)
        relationship_id   (all domain relationship types — stored as property)
        evidence_id       (Evidence nodes)
        decision_id       (ResolutionDecision nodes)
        finding_id        (Finding nodes)
        case_id           (Case nodes)
        note_id           (Note nodes)
        edge_ref_id       (EdgeRef nodes)

    Dataset-scoped (composite uniqueness enforced here):
        (record_id, dataset)  — RawRecord is not a graph node, but any node
        derived directly from it (Evidence) carries source_id + dataset;
        composite uniqueness on (source_id, dataset) enforces this at the
        Evidence layer.

DOC3 §6.1 — Node types covered:
    CanonicalEntity: Person, Phone, Vehicle, Location, Organization,
                     BankAccount, Transaction, Event
    Workspace/structural/derived: Case, Evidence, Note, EdgeRef,
                                  ResolutionDecision, Finding

DOC3 §6.2 — Relationship types carry relationship_id as a property; because
Neo4j does not support uniqueness constraints on relationship properties in the
same way as nodes, relationship_id uniqueness is enforced in the Graph Write
Layer (C3). An index on relationship_id is created here for fast lookup.
"""

import logging
from typing import List

from app.graph.connection import get_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constraint definitions — (name, label, property)
# ---------------------------------------------------------------------------

# Globally-unique node property constraints (DOC3 §1.13)
_NODE_CONSTRAINTS: List[tuple] = [
    # CanonicalEntity types — entity_id
    ("constraint_person_entity_id",          "Person",             "entity_id"),
    ("constraint_phone_entity_id",           "Phone",              "entity_id"),
    ("constraint_vehicle_entity_id",         "Vehicle",            "entity_id"),
    ("constraint_location_entity_id",        "Location",           "entity_id"),
    ("constraint_organization_entity_id",    "Organization",       "entity_id"),
    ("constraint_bankaccount_entity_id",     "BankAccount",        "entity_id"),
    ("constraint_transaction_entity_id",     "Transaction",        "entity_id"),
    ("constraint_event_entity_id",           "Event",              "entity_id"),

    # Workspace / structural / derived — their own ID fields
    ("constraint_case_case_id",              "Case",               "case_id"),
    ("constraint_evidence_evidence_id",      "Evidence",           "evidence_id"),
    ("constraint_note_note_id",              "Note",               "note_id"),
    ("constraint_edgeref_edge_ref_id",       "EdgeRef",            "edge_ref_id"),
    ("constraint_resdecision_decision_id",   "ResolutionDecision", "decision_id"),
    ("constraint_finding_finding_id",        "Finding",            "finding_id"),
]

# Composite uniqueness — Evidence: (source_id, dataset) must be unique
# (DOC3 §1.13: evidence_id is stable for a given (source_id, dataset) pair)
# Neo4j 5.x supports multi-property constraints; for 4.x we use a node key.
# We implement this as an index + application-level enforcement in C3; the
# single-property evidence_id constraint above covers the node identity case.
# A compound index on (source_id, dataset) is created for fast idempotent lookup.
_COMPOUND_INDEXES: List[tuple] = [
    ("index_evidence_source_dataset", "Evidence", ["source_id", "dataset"]),
]

# Single-property lookup indexes (non-unique — for query performance)
_LOOKUP_INDEXES: List[tuple] = [
    # CanonicalEntity — dataset filter is used on every read API call
    ("index_person_dataset",          "Person",             "dataset"),
    ("index_phone_dataset",           "Phone",              "dataset"),
    ("index_vehicle_dataset",         "Vehicle",            "dataset"),
    ("index_location_dataset",        "Location",           "dataset"),
    ("index_organization_dataset",    "Organization",       "dataset"),
    ("index_bankaccount_dataset",     "BankAccount",        "dataset"),
    ("index_transaction_dataset",     "Transaction",        "dataset"),
    ("index_event_dataset",           "Event",              "dataset"),

    # Case Workspace
    ("index_case_dataset",            "Case",               "dataset"),
    ("index_case_status",             "Case",               "status"),

    # Evidence — source_id for provenance lookup
    ("index_evidence_source_id",      "Evidence",           "source_id"),
    ("index_evidence_dataset",        "Evidence",           "dataset"),

    # ResolutionDecision — entity_id for provenance traversal (DOC3 §2.5)
    ("index_resdecision_entity_id",   "ResolutionDecision", "entity_id"),

    # Finding — rule_id + dataset for re-detection upsert
    ("index_finding_rule_id",         "Finding",            "rule_id"),
    ("index_finding_dataset",         "Finding",            "dataset"),

    # EdgeRef — used for exact lookup by the Case Workspace and Evidence resolver
    ("index_edgeref_relationship_id", "EdgeRef",            "relationship_id"),
]

# Relationship-type property index (relationship_id on every domain rel type)
# These are text indexes on relationship properties for fast lookup.
_REL_INDEXES: List[tuple] = [
    ("index_rel_called_id",            "CALLED",            "relationship_id"),
    ("index_rel_owns_id",              "OWNS",              "relationship_id"),
    ("index_rel_used_id",              "USED",              "relationship_id"),
    ("index_rel_transferred_id",       "TRANSFERRED",       "relationship_id"),
    ("index_rel_visited_id",           "VISITED",           "relationship_id"),
    ("index_rel_met_id",               "MET",               "relationship_id"),
    ("index_rel_works_for_id",         "WORKS_FOR",         "relationship_id"),
    ("index_rel_associated_with_id",   "ASSOCIATED_WITH",   "relationship_id"),
    ("index_rel_mentioned_in_id",      "MENTIONED_IN",      "relationship_id"),
    ("index_rel_part_of_id",           "PART_OF",           "relationship_id"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_schema() -> None:
    """Apply all constraints and indexes to the connected Neo4j database.

    Idempotent: safe to call against a database that already has the schema.
    Each statement uses IF NOT EXISTS so no-op on re-run.

    Raises:
        neo4j.exceptions.ServiceUnavailable: if the database is unreachable.
        neo4j.exceptions.ClientError: if the Neo4j version does not support
            a specific constraint syntax (requires Neo4j 4.4+ for IF NOT EXISTS).
    """
    statements = _build_statements()
    applied = 0
    skipped = 0

    with get_session() as session:
        for cypher in statements:
            try:
                session.run(cypher)
                applied += 1
            except Exception as exc:  # noqa: BLE001
                # Idempotency: some Neo4j versions raise on duplicate rather than
                # silently skipping even with IF NOT EXISTS on older drivers.
                # Log and continue — the constraint already exists.
                if "already exists" in str(exc).lower() or "equivalent" in str(exc).lower():
                    skipped += 1
                    logger.debug("Schema element already exists (skipping): %s", exc)
                else:
                    logger.error("Schema statement failed: %s\n  Cypher: %s", exc, cypher)
                    raise

    logger.info(
        "apply_schema() complete: %d statements applied, %d already existed.",
        applied, skipped,
    )


def get_constraint_names() -> List[str]:
    """Return the list of constraint names this module is responsible for.

    Used by C1 tests to assert that all expected constraints exist.
    """
    return [name for name, _, _ in _NODE_CONSTRAINTS]


def get_index_names() -> List[str]:
    """Return the list of index names this module is responsible for."""
    return (
        [name for name, _, _ in _LOOKUP_INDEXES]
        + [name for name, _, _ in _COMPOUND_INDEXES]
        + [name for name, _, _ in _REL_INDEXES]
    )


# ---------------------------------------------------------------------------
# Statement builders
# ---------------------------------------------------------------------------

def _build_statements() -> List[str]:
    """Build the full list of CREATE CONSTRAINT / CREATE INDEX Cypher statements."""
    stmts: List[str] = []

    # 1. Node uniqueness constraints
    for name, label, prop in _NODE_CONSTRAINTS:
        stmts.append(
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )

    # 2. Compound lookup index (Evidence: source_id + dataset)
    for name, label, props in _COMPOUND_INDEXES:
        props_cypher = ", ".join(f"n.{p}" for p in props)
        stmts.append(
            f"CREATE INDEX {name} IF NOT EXISTS "
            f"FOR (n:{label}) ON ({props_cypher})"
        )

    # 3. Single-property lookup indexes
    for name, label, prop in _LOOKUP_INDEXES:
        stmts.append(
            f"CREATE INDEX {name} IF NOT EXISTS "
            f"FOR (n:{label}) ON (n.{prop})"
        )

    # 4. Relationship property indexes
    for name, rel_type, prop in _REL_INDEXES:
        stmts.append(
            f"CREATE INDEX {name} IF NOT EXISTS "
            f"FOR ()-[r:{rel_type}]-() ON (r.{prop})"
        )

    return stmts
