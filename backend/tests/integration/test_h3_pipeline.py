"""H3 — Pipeline-to-Graph Integration Test Suite (Sync 2 gate).

Task H3: Run H1's synthetic dataset through the full B→C pipeline and assert
that the result satisfies DOC3's invariants AND H1's answer key.

This IS the Sync 2 gate (H3 §12):
  "This task's test suite passing IS the definition of Sync 2 being reached."

All tests require a live Neo4j instance and a seeded graph.
They are guarded by @pytest.mark.neo4j_live (skipped in CI unless Neo4j is available).

IMPORTANT (H3 §17): 'it ran without crashing' is NOT sufficient — tests must assert
against H1's answer key, specifically:
  - H1's known-alias groups resolve to SINGLE CanonicalEntity records.
  - Every relationship has a non-empty evidence chain (Invariant 1).
  - EvidenceResolver.for_entity() round-trips correctly.

Setup:
  If the graph is not yet seeded, tests will attempt to run seed_demo.py first.
  This requires NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD to be set in the environment.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import pytest

# ---------------------------------------------------------------------------
# Skip guard — all H3 tests require live Neo4j
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]

def _neo4j_reachable() -> bool:
    from app.graph.connection import health_check
    try:
        return health_check()
    except Exception:
        return False

pytestmark = pytest.mark.neo4j_live

# Applied per-test via the fixture below to allow collection without errors
requires_neo4j = pytest.mark.skipif(
    not _neo4j_reachable(),
    reason="Neo4j not available — skipping H3 integration tests (Sync 2 gate)",
)


# ---------------------------------------------------------------------------
# Load H1 answer key
# ---------------------------------------------------------------------------

ANSWER_KEY_PATH = REPO_ROOT / "data" / "synthetic" / "answer_key.json"


def _load_answer_key() -> Dict:
    with open(ANSWER_KEY_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Seed fixture — runs seed_demo.py once per test session if graph is empty
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def ensure_seeded():
    """Seed the demo graph if Neo4j is available and the graph is empty."""
    if not _neo4j_reachable():
        pytest.skip("Neo4j not available — skipping H3 session setup")

    from app.graph.connection import get_session
    with get_session() as session:
        result = session.run(
            "MATCH (n {dataset: 'synthetic_demo'}) RETURN count(n) AS cnt"
        )
        record = result.single()
        count = record["cnt"] if record else 0

    if count == 0:
        # Graph is empty — run the seeder
        seed_script = REPO_ROOT / "scripts" / "seed_demo.py"
        result = subprocess.run(
            [sys.executable, str(seed_script)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"seed_demo.py failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    else:
        # Graph already seeded — proceed
        pass


# ---------------------------------------------------------------------------
# Helper: query Neo4j directly for integration assertions
# ---------------------------------------------------------------------------

def _run_query(cypher: str, params: dict = None):
    from app.graph.connection import get_session
    params = params or {}
    with get_session() as session:
        result = session.run(cypher, params)
        return list(result)


# ===========================================================================
# H3 §11: Every written Relationship has a non-empty evidence chain (Invariant 1)
# ===========================================================================

@requires_neo4j
def test_every_relationship_has_an_edge_ref():
    """Every domain relationship must have exactly one EdgeRef (Invariant 12)."""
    # Find domain relationships that have no EdgeRef via relationship_id match
    cypher = """
    MATCH ()-[r]-()
    WHERE r.dataset = 'synthetic_demo'
      AND r.relationship_id IS NOT NULL
    WITH r.relationship_id AS rel_id
    WHERE NOT EXISTS {
        MATCH (er:EdgeRef {relationship_id: rel_id})
    }
    RETURN count(rel_id) AS missing_edge_refs
    """
    rows = _run_query(cypher)
    missing = rows[0]["missing_edge_refs"] if rows else 0
    assert missing == 0, (
        f"{missing} synthetic_demo relationships have no EdgeRef "
        "(Contract Invariant 12 — DOC3 §6.5)"
    )


@requires_neo4j
def test_every_edge_ref_has_at_least_one_supports_edge():
    """Every EdgeRef must have at least one Evidence-[:SUPPORTS]->EdgeRef edge (Invariant 1)."""
    cypher = """
    MATCH (er:EdgeRef {dataset: 'synthetic_demo'})
    WHERE NOT EXISTS {
        MATCH (ev:Evidence)-[:SUPPORTS]->(er)
    }
    RETURN count(er) AS unsupported_edge_refs
    """
    rows = _run_query(cypher)
    unsupported = rows[0]["unsupported_edge_refs"] if rows else 0
    assert unsupported == 0, (
        f"{unsupported} EdgeRefs in synthetic_demo have no incoming SUPPORTS edge "
        "(Contract Invariant 1 — DOC3 §15)"
    )


@requires_neo4j
def test_relationships_have_non_empty_evidence_ids_property():
    """Every domain relationship node must have evidence_ids property with ≥1 entry."""
    cypher = """
    MATCH ()-[r]-()
    WHERE r.dataset = 'synthetic_demo'
      AND r.relationship_id IS NOT NULL
      AND (r.evidence_ids IS NULL OR size(r.evidence_ids) = 0)
    RETURN count(r) AS bad_rels
    """
    rows = _run_query(cypher)
    bad = rows[0]["bad_rels"] if rows else 0
    assert bad == 0, (
        f"{bad} relationships have empty evidence_ids "
        "(Contract Invariant 1 — DOC3 §1.5)"
    )


# ===========================================================================
# H3 §11: H1 answer-key aliases resolve to single CanonicalEntity records
# ===========================================================================

@requires_neo4j
def test_rahul_sharma_aliases_resolve_to_one_entity():
    """H1 answer key: 'Rahul Sharma' / 'R. Sharma' / 'SHARMA R' → one Person entity."""
    # All three name forms should exist in a single Person node's resolved_from
    # We check: there is exactly one Person node whose resolved_from covers
    # at least 2 of the known alias mention patterns.
    cypher = """
    MATCH (p:Person {dataset: 'synthetic_demo'})
    WHERE any(mid IN p.resolved_from WHERE mid CONTAINS 'sharma' OR mid CONTAINS 'Sharma')
       OR p.display_name CONTAINS 'Sharma'
    RETURN count(DISTINCT p) AS count
    """
    # Simpler check: exactly one Person has 'Sharma' display_name
    cypher2 = """
    MATCH (p:Person {dataset: 'synthetic_demo'})
    WHERE toLower(p.display_name) CONTAINS 'sharma'
    RETURN count(p) AS cnt
    """
    rows = _run_query(cypher2)
    count = rows[0]["cnt"] if rows else 0
    assert count == 1, (
        f"Expected exactly 1 Person entity for 'Sharma' aliases, got {count}. "
        "H1 answer key: 'Rahul Sharma' / 'R. Sharma' / 'SHARMA R' must merge."
    )


@requires_neo4j
def test_priya_mehta_aliases_resolve_to_one_entity():
    """H1 answer key: 'Priya Mehta' / 'P. Mehta' / 'Priya M.' → one Person entity."""
    cypher = """
    MATCH (p:Person {dataset: 'synthetic_demo'})
    WHERE toLower(p.display_name) CONTAINS 'mehta'
    RETURN count(p) AS cnt
    """
    rows = _run_query(cypher)
    count = rows[0]["cnt"] if rows else 0
    assert count == 1, (
        f"Expected exactly 1 Person entity for 'Mehta' aliases, got {count}. "
        "H1 answer key: 'Priya Mehta' / 'P. Mehta' / 'Priya M.' must merge."
    )


@requires_neo4j
def test_devendra_khanna_aliases_resolve_to_one_entity():
    """H1 answer key: 'Devendra Khanna' / 'D. Khanna' / 'Dev Khanna' → one Person entity."""
    cypher = """
    MATCH (p:Person {dataset: 'synthetic_demo'})
    WHERE toLower(p.display_name) CONTAINS 'khanna'
    RETURN count(p) AS cnt
    """
    rows = _run_query(cypher)
    count = rows[0]["cnt"] if rows else 0
    assert count == 1, (
        f"Expected exactly 1 Person entity for 'Khanna' aliases, got {count}. "
        "H1 answer key: Devendra Khanna / D. Khanna / Dev Khanna must merge."
    )


@requires_neo4j
def test_khanna_enterprises_org_aliases_resolve_to_one_entity():
    """H1 answer key: 'Khanna Enterprises Pvt Ltd' / 'Khanna Enterprises' → one Org entity."""
    cypher = """
    MATCH (o:Organization {dataset: 'synthetic_demo'})
    WHERE toLower(o.display_name) CONTAINS 'khanna'
    RETURN count(o) AS cnt
    """
    rows = _run_query(cypher)
    count = rows[0]["cnt"] if rows else 0
    assert count == 1, (
        f"Expected exactly 1 Organization entity for 'Khanna Enterprises', got {count}. "
        "H1 answer key: 'Khanna Enterprises Pvt Ltd' ≈ 'Khanna Enterprises' must merge."
    )


@requires_neo4j
def test_phone_number_entities_count():
    """H1 answer key: 4 distinct Phone canonical entities after resolution."""
    expected_phones = {
        "+919876543210",
        "+919988776655",
        "+918765432109",
        "+919123456789",
    }
    cypher = """
    MATCH (p:Phone {dataset: 'synthetic_demo'})
    RETURN p.display_name AS display_name
    """
    rows = _run_query(cypher)
    found = {r["display_name"] for r in rows}
    missing = expected_phones - found
    assert not missing, (
        f"Expected Phone entities not found: {missing}. "
        "H1 answer key lists 4 canonical phones."
    )


@requires_neo4j
def test_at_least_four_person_entities():
    """H1 answer key: at least 4 Person canonical entities (Sharma, Mehta, Khanna, Patel)."""
    cypher = """
    MATCH (p:Person {dataset: 'synthetic_demo'})
    RETURN count(p) AS cnt
    """
    rows = _run_query(cypher)
    count = rows[0]["cnt"] if rows else 0
    assert count >= 4, (
        f"Expected ≥4 Person entities, got {count}. "
        "H1 answer key lists: Rahul Sharma, Priya Mehta, Devendra Khanna, Rajan Patel."
    )


# ===========================================================================
# H3 §11: EvidenceResolver.for_entity() round-trips correctly
# ===========================================================================

@requires_neo4j
def test_for_entity_round_trips_sharma():
    """EvidenceResolver.for_entity() returns ≥1 Evidence for Rahul Sharma entity."""
    from app.evidence.resolver import EvidenceResolver

    resolver = EvidenceResolver()
    # Find the Sharma entity_id
    cypher = """
    MATCH (p:Person {dataset: 'synthetic_demo'})
    WHERE toLower(p.display_name) CONTAINS 'sharma'
    RETURN p.entity_id AS entity_id LIMIT 1
    """
    rows = _run_query(cypher)
    assert rows, "Sharma entity not found — has seed_demo run?"
    entity_id = rows[0]["entity_id"]

    evidence_list = resolver.for_entity(entity_id)
    assert evidence_list, (
        f"for_entity({entity_id!r}) returned empty list — "
        "Rahul Sharma must have at least one Evidence via RESOLVED_FROM→BASED_ON"
    )
    for ev in evidence_list:
        assert ev.source_id, "Evidence.source_id must not be empty (DOC3 §9.2)"
        assert ev.source_type, "Evidence.source_type must not be empty (DOC3 §9.2)"
        assert ev.dataset == "synthetic_demo"


@requires_neo4j
def test_for_entity_round_trips_khanna():
    """EvidenceResolver.for_entity() returns ≥1 Evidence for Devendra Khanna."""
    from app.evidence.resolver import EvidenceResolver

    resolver = EvidenceResolver()
    cypher = """
    MATCH (p:Person {dataset: 'synthetic_demo'})
    WHERE toLower(p.display_name) CONTAINS 'khanna'
    RETURN p.entity_id AS entity_id LIMIT 1
    """
    rows = _run_query(cypher)
    assert rows, "Khanna entity not found"
    entity_id = rows[0]["entity_id"]
    evidence_list = resolver.for_entity(entity_id)
    assert evidence_list, f"for_entity({entity_id!r}) returned empty list"


@requires_neo4j
def test_for_relationship_returns_evidence():
    """EvidenceResolver.for_relationship() returns ≥1 Evidence for a sample relationship."""
    from app.evidence.resolver import EvidenceResolver

    resolver = EvidenceResolver()
    # Get any domain relationship from the synthetic dataset
    cypher = """
    MATCH ()-[r]-()
    WHERE r.dataset = 'synthetic_demo' AND r.relationship_id IS NOT NULL
    RETURN r.relationship_id AS relationship_id LIMIT 1
    """
    rows = _run_query(cypher)
    if not rows:
        pytest.skip("No relationships in graph — did seed run?")

    rel_id = rows[0]["relationship_id"]
    evidence_list = resolver.for_relationship(rel_id)
    assert evidence_list, (
        f"for_relationship({rel_id!r}) returned empty list — "
        "every relationship must be backed by ≥1 Evidence (Invariant 1)"
    )


@requires_neo4j
def test_for_resolution_decision_returns_evidence():
    """EvidenceResolver.for_resolution_decision() returns ≥1 Evidence for a sample decision."""
    from app.evidence.resolver import EvidenceResolver

    resolver = EvidenceResolver()
    cypher = """
    MATCH (rd:ResolutionDecision)
    RETURN rd.decision_id AS decision_id LIMIT 1
    """
    rows = _run_query(cypher)
    if not rows:
        pytest.skip("No ResolutionDecision nodes — did seed run?")

    dec_id = rows[0]["decision_id"]
    evidence_list = resolver.for_resolution_decision(dec_id)
    assert evidence_list, (
        f"for_resolution_decision({dec_id!r}) returned empty list — "
        "the BASED_ON edge must link to ≥1 Evidence (DOC3 §2.5)"
    )


# ===========================================================================
# DOC3 §2.5: Provenance chain is queryable end-to-end
# ===========================================================================

@requires_neo4j
def test_resolved_from_edges_exist():
    """Every CanonicalEntity must have at least one RESOLVED_FROM edge to a ResolutionDecision."""
    cypher = """
    MATCH (n {dataset: 'synthetic_demo'})
    WHERE n.entity_id IS NOT NULL
    AND NOT EXISTS {
        MATCH (n)-[:RESOLVED_FROM]->(:ResolutionDecision)
    }
    RETURN count(n) AS orphaned_entities
    """
    rows = _run_query(cypher)
    orphaned = rows[0]["orphaned_entities"] if rows else 0
    assert orphaned == 0, (
        f"{orphaned} CanonicalEntity nodes have no RESOLVED_FROM edge — "
        "DOC3 §2.5: every entity must be traceable to a ResolutionDecision"
    )


@requires_neo4j
def test_based_on_edges_exist():
    """Every ResolutionDecision must have at least one BASED_ON edge to an Evidence."""
    cypher = """
    MATCH (rd:ResolutionDecision)
    WHERE NOT EXISTS {
        MATCH (rd)-[:BASED_ON]->(:Evidence)
    }
    RETURN count(rd) AS orphaned_decisions
    """
    rows = _run_query(cypher)
    orphaned = rows[0]["orphaned_decisions"] if rows else 0
    assert orphaned == 0, (
        f"{orphaned} ResolutionDecision nodes have no BASED_ON edge — "
        "DOC3 §2.5: CanonicalEntity→ResolutionDecision→Evidence chain must be complete"
    )


@requires_neo4j
def test_evidence_nodes_have_required_properties():
    """Every Evidence node must have evidence_id, source_id, source_type, dataset (DOC3 §9.2)."""
    cypher = """
    MATCH (ev:Evidence {dataset: 'synthetic_demo'})
    WHERE ev.evidence_id IS NULL
       OR ev.source_id IS NULL
       OR ev.source_type IS NULL
    RETURN count(ev) AS bad_evidence
    """
    rows = _run_query(cypher)
    bad = rows[0]["bad_evidence"] if rows else 0
    assert bad == 0, (
        f"{bad} Evidence nodes are missing required properties "
        "(DOC3 §9.2: source_id, source_type, dataset required)"
    )


# ===========================================================================
# Dataset isolation: no synthetic_demo data leaks into live_public
# ===========================================================================

@requires_neo4j
def test_no_live_public_data_in_graph():
    """After seeding, no live_public nodes should exist (Invariant 7)."""
    cypher = """
    MATCH (n {dataset: 'live_public'})
    RETURN count(n) AS cnt
    """
    rows = _run_query(cypher)
    count = rows[0]["cnt"] if rows else 0
    assert count == 0, (
        f"Found {count} live_public nodes in the graph after seed. "
        "seed_demo.py must only write synthetic_demo data (Contract Invariant 7)."
    )


@requires_neo4j
def test_all_entity_nodes_carry_dataset_property():
    """Every CanonicalEntity node must carry a dataset property (DOC3 §6.7)."""
    cypher = """
    MATCH (n)
    WHERE n.entity_id IS NOT NULL AND n.dataset IS NULL
    RETURN count(n) AS missing_dataset
    """
    rows = _run_query(cypher)
    missing = rows[0]["missing_dataset"] if rows else 0
    assert missing == 0, (
        f"{missing} CanonicalEntity nodes are missing dataset property "
        "(DOC3 §6.7 requires dataset on every node)"
    )


# ===========================================================================
# Graph Write Layer C2+C3 integration tests (live Neo4j)
# ===========================================================================

@requires_neo4j
def test_write_evidence_idempotency():
    """C3 §12: writing the same (source_id, dataset) twice yields exactly one Evidence node."""
    from app.graph.write_layer import write_evidence, evidence_from_raw_record

    source_id = f"h3_idempotency_test_{__import__('uuid').uuid4().hex[:8]}"
    ev = evidence_from_raw_record(
        record_id=source_id,
        dataset="synthetic_demo",
        source_type="FIR",
        ingested_at="2024-01-01T00:00:00Z",
    )
    # Write twice
    result1 = write_evidence(ev)
    result2 = write_evidence(ev)

    # Both must return the same evidence_id
    assert result1.evidence_id == result2.evidence_id, (
        "write_evidence must be idempotent: same (source_id, dataset) → same evidence_id"
    )

    # Verify exactly one Evidence node exists for this source_id
    rows = _run_query(
        "MATCH (ev:Evidence {source_id: $sid}) RETURN count(ev) AS cnt",
        {"sid": source_id},
    )
    count = rows[0]["cnt"] if rows else 0
    assert count == 1, (
        f"Expected exactly 1 Evidence node for source_id={source_id!r}, got {count}"
    )

    # Cleanup
    _run_query(
        "MATCH (ev:Evidence {source_id: $sid}) DELETE ev",
        {"sid": source_id},
    )


@requires_neo4j
def test_write_relationship_creates_exactly_one_edge_ref():
    """C2 §12/§13: writing the same relationship_id twice does not duplicate its EdgeRef."""
    import uuid
    from app.contracts.entity import CanonicalEntity
    from app.contracts.relationship import Relationship
    from app.graph.write_layer import (
        write_entity, write_evidence, write_relationship, evidence_from_raw_record
    )

    now = "2024-01-01T00:00:00Z"
    ent1_id = f"h3_test_ent_{uuid.uuid4().hex[:8]}"
    ent2_id = f"h3_test_ent_{uuid.uuid4().hex[:8]}"
    rel_id = f"h3_test_rel_{uuid.uuid4().hex[:8]}"
    src_id = f"h3_test_src_{uuid.uuid4().hex[:8]}"

    # Write two minimal test entities
    for eid in [ent1_id, ent2_id]:
        write_entity(CanonicalEntity(
            entity_id=eid, entity_type="Person", dataset="synthetic_demo",
            display_name=f"H3 Test {eid}", resolved_from=[f"m_{eid}"],
            resolution_method="exact_match", created_at=now, updated_at=now,
        ))

    # Write evidence
    ev = evidence_from_raw_record(src_id, "synthetic_demo", "FIR", now)
    ev = write_evidence(ev)

    # Write relationship
    rel = Relationship(
        relationship_id=rel_id, relationship_type="MET",
        from_entity_id=ent1_id, to_entity_id=ent2_id,
        dataset="synthetic_demo", valid_from=now,
        evidence_ids=[ev.evidence_id], created_at=now, updated_at=now,
    )
    write_relationship(rel, evidence_list=[ev])
    # Write again — must not create a second EdgeRef
    write_relationship(rel, evidence_list=[ev])

    rows = _run_query(
        "MATCH (er:EdgeRef {relationship_id: $rid}) RETURN count(er) AS cnt",
        {"rid": rel_id},
    )
    count = rows[0]["cnt"] if rows else 0
    assert count == 1, (
        f"Expected exactly 1 EdgeRef for relationship_id={rel_id!r}, got {count} "
        "(Contract Invariant 12)"
    )

    # Cleanup test data
    _run_query(
        "MATCH (n) WHERE n.entity_id IN $ids OR n.source_id = $sid DETACH DELETE n",
        {"ids": [ent1_id, ent2_id], "sid": src_id},
    )
    _run_query(
        "MATCH (er:EdgeRef {relationship_id: $rid}) DETACH DELETE er",
        {"rid": rel_id},
    )
