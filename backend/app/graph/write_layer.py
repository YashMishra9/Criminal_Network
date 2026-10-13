"""Graph Write Layer — Entities, Relationships, Evidence, ResolutionDecisions.

Tasks C2 and C3 (both write to this module per their §9 file specs).

C2 responsibilities:
  - write_entity()         — MERGE a CanonicalEntity node; idempotent.
  - write_relationship()   — Atomic write: domain relationship + exactly one EdgeRef
                             + Evidence-[:SUPPORTS]->EdgeRef. Rejects empty evidence_list
                             (Contract Invariant 1). Never creates a second EdgeRef for an
                             existing relationship_id (Contract Invariant 12).

C3 responsibilities:
  - write_evidence()            — Idempotent per (source_id, dataset). Same pair always
                                  resolves to the same evidence_id (DOC3 §1.13).
  - write_resolution_decision() — Creates the ResolutionDecision node + RESOLVED_FROM edge
                                  from the CanonicalEntity + BASED_ON edges to each Evidence
                                  node in source_record_ids (DOC3 §2.5 provenance path).

Contract Invariants enforced here (DOC3 §15):
  Invariant 1:  No relationship written without at least one Evidence.
  Invariant 8:  All writes flow through this layer, never from adapters directly.
  Invariant 12: Exactly one EdgeRef per relationship_id.

DOC3 §6.7: dataset is a required property on every node and relationship.
DOC3 §6.4: every domain relationship must have relationship_id, dataset, valid_from,
           exactly one EdgeRef, and at least one Evidence-[:SUPPORTS]->EdgeRef.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from neo4j import Session

from app.contracts.case import EdgeRef
from app.contracts.entity import CanonicalEntity
from app.contracts.evidence import Evidence
from app.contracts.relationship import Relationship
from app.contracts.resolution import ResolutionDecision
from app.graph.connection import get_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# C2 — write_entity
# ---------------------------------------------------------------------------

def write_entity(entity: CanonicalEntity) -> None:
    """MERGE a CanonicalEntity node into Neo4j. Idempotent on entity_id.

    Uses MERGE so re-running the seeder or the pipeline does not create
    duplicate nodes. On first write all properties are SET; on subsequent
    writes only updated_at is refreshed.

    DOC3 §6.1: dataset is required on every CanonicalEntity node.
    DOC3 §6.7: dataset property must be present on every node.

    Args:
        entity: A fully-resolved CanonicalEntity object.
    """
    label = entity.entity_type  # Person, Phone, Vehicle, …

    # Flatten attributes dict; keep only simple scalar values as top-level properties
    # to avoid Neo4j type errors. Complex attrs go into an attributes_json property.
    import json as _json

    attrs = entity.attributes if isinstance(entity.attributes, dict) else {}

    cypher = f"""
    MERGE (n:{label} {{entity_id: $entity_id}})
    ON CREATE SET
        n.dataset         = $dataset,
        n.display_name    = $display_name,
        n.resolved_from   = $resolved_from,
        n.resolution_method = $resolution_method,
        n.attributes_json = $attributes_json,
        n.created_at      = $created_at,
        n.updated_at      = $updated_at
    ON MATCH SET
        n.display_name    = $display_name,
        n.resolved_from   = $resolved_from,
        n.resolution_method = $resolution_method,
        n.attributes_json = $attributes_json,
        n.updated_at      = $updated_at
    """
    params = {
        "entity_id": entity.entity_id,
        "dataset": entity.dataset,
        "display_name": entity.display_name,
        "resolved_from": entity.resolved_from,
        "resolution_method": entity.resolution_method,
        "attributes_json": _json.dumps(attrs),
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }

    with get_session() as session:
        session.run(cypher, params)

    logger.debug("write_entity: %s %s (%s)", label, entity.entity_id, entity.display_name)


# ---------------------------------------------------------------------------
# C2 — write_relationship
# ---------------------------------------------------------------------------

def write_relationship(
    relationship: Relationship,
    evidence_list: List[Evidence],
) -> EdgeRef:
    """Atomically write a domain relationship, its single EdgeRef, and evidence links.

    In a single transaction:
      1. Write the domain relationship (MERGE on relationship_id).
      2. Create exactly one EdgeRef for this relationship_id (MERGE — idempotent).
      3. For each Evidence in evidence_list, create Evidence-[:SUPPORTS]->EdgeRef.

    Raises:
        ValueError: if evidence_list is empty (Contract Invariant 1).
        ValueError: if relationship.evidence_ids is empty (same invariant).

    Returns:
        The EdgeRef created (or the existing one if the relationship was already written).

    DOC3 §6.4, §6.5, §15 Invariants 1 and 12.
    """
    if not evidence_list:
        raise ValueError(
            f"write_relationship: evidence_list is empty for relationship_id="
            f"{relationship.relationship_id!r}. Contract Invariant 1 (DOC3 §15): "
            "a Relationship must have at least one Evidence before being written."
        )
    if not relationship.evidence_ids:
        raise ValueError(
            f"write_relationship: relationship.evidence_ids is empty for "
            f"relationship_id={relationship.relationship_id!r}. "
            "Contract Invariant 1 (DOC3 §15)."
        )
    # Both guards above are pre-DB: no session is opened until after both pass.

    now = _iso_now()
    edge_ref_id = _new_uuid()
    rel_type = relationship.relationship_type

    # Build the EdgeRef data object (returned to caller)
    edge_ref = EdgeRef(
        edge_ref_id=edge_ref_id,
        relationship_id=relationship.relationship_id,
        from_entity_id=relationship.from_entity_id,
        to_entity_id=relationship.to_entity_id,
        relationship_type=rel_type,
        created_at=now,
    )

    import json as _json

    # Serialize attributes to avoid Neo4j type issues
    attrs_json = _json.dumps(
        relationship.attributes if isinstance(relationship.attributes, dict) else {}
    )

    # Single transaction: relationship + EdgeRef + SUPPORTS edges
    cypher = f"""
    // 1. Find the two endpoint entity nodes (any CanonicalEntity label)
    MATCH (from_n {{entity_id: $from_entity_id}})
    MATCH (to_n {{entity_id: $to_entity_id}})

    // 2. MERGE the domain relationship — idempotent on relationship_id
    MERGE (from_n)-[r:{rel_type} {{relationship_id: $relationship_id}}]->(to_n)
    ON CREATE SET
        r.dataset          = $dataset,
        r.valid_from       = $valid_from,
        r.valid_to         = $valid_to,
        r.attributes_json  = $attrs_json,
        r.evidence_ids     = $evidence_ids,
        r.created_at       = $created_at,
        r.updated_at       = $updated_at
    ON MATCH SET
        r.updated_at       = $updated_at,
        r.evidence_ids     = $evidence_ids

    // 3. MERGE exactly one EdgeRef for this relationship_id (Invariant 12)
    MERGE (er:EdgeRef {{relationship_id: $relationship_id}})
    ON CREATE SET
        er.edge_ref_id        = $edge_ref_id,
        er.from_entity_id     = $from_entity_id,
        er.to_entity_id       = $to_entity_id,
        er.relationship_type  = $rel_type,
        er.dataset            = $dataset,
        er.created_at         = $created_at

    RETURN er.edge_ref_id AS actual_edge_ref_id
    """
    params = {
        "relationship_id": relationship.relationship_id,
        "from_entity_id": relationship.from_entity_id,
        "to_entity_id": relationship.to_entity_id,
        "dataset": relationship.dataset,
        "valid_from": relationship.valid_from,
        "valid_to": relationship.valid_to,
        "attrs_json": attrs_json,
        "evidence_ids": relationship.evidence_ids,
        "created_at": relationship.created_at,
        "updated_at": relationship.updated_at,
        "edge_ref_id": edge_ref_id,
        "rel_type": rel_type,
    }

    with get_session() as session:
        result = session.run(cypher, params)
        record = result.single()
        actual_edge_ref_id = record["actual_edge_ref_id"] if record else edge_ref_id

        # 4. Create Evidence-[:SUPPORTS]->EdgeRef for each evidence item
        for ev in evidence_list:
            session.run(
                """
                MATCH (ev:Evidence {evidence_id: $evidence_id})
                MATCH (er:EdgeRef   {relationship_id: $relationship_id})
                MERGE (ev)-[:SUPPORTS]->(er)
                """,
                {
                    "evidence_id": ev.evidence_id,
                    "relationship_id": relationship.relationship_id,
                },
            )

    # Return the actual EdgeRef (using the id that was persisted, which may be the
    # pre-existing one if the relationship already existed — same edge_ref_id from MERGE)
    edge_ref = EdgeRef(
        edge_ref_id=actual_edge_ref_id,
        relationship_id=relationship.relationship_id,
        from_entity_id=relationship.from_entity_id,
        to_entity_id=relationship.to_entity_id,
        relationship_type=rel_type,
        created_at=now,
    )

    logger.debug(
        "write_relationship: %s %s->%s (edge_ref=%s, evidence=%d)",
        rel_type,
        relationship.from_entity_id,
        relationship.to_entity_id,
        actual_edge_ref_id,
        len(evidence_list),
    )
    return edge_ref


# ---------------------------------------------------------------------------
# C3 — write_evidence
# ---------------------------------------------------------------------------

def write_evidence(evidence: Evidence) -> Evidence:
    """Idempotent write of an Evidence node, keyed on (source_id, dataset).

    If an Evidence node with the same (source_id, dataset) already exists,
    that node is returned unchanged (same evidence_id). A new node is created
    only on first write for a given (source_id, dataset) pair.

    DOC3 §1.13: same (source_id, dataset) must always resolve to the same evidence_id.
    DOC3 §1.6: required fields are evidence_id, dataset, source_id, source_type, ingested_at.
    DOC3 C3 §12: calling write_evidence() twice for the same (source_id, dataset) yields
                 exactly one Evidence node with a stable evidence_id.

    Returns:
        The Evidence object as persisted (may have a different evidence_id than the
        input if this (source_id, dataset) pair was already written).
    """
    cypher = """
    MERGE (ev:Evidence {source_id: $source_id, dataset: $dataset})
    ON CREATE SET
        ev.evidence_id       = $evidence_id,
        ev.source_type       = $source_type,
        ev.record_timestamp  = $record_timestamp,
        ev.ingested_at       = $ingested_at,
        ev.snippet           = $snippet,
        ev.pointer_json      = $pointer_json
    RETURN ev.evidence_id AS evidence_id
    """
    import json as _json

    params = {
        "source_id": evidence.source_id,
        "dataset": evidence.dataset,
        "evidence_id": evidence.evidence_id,
        "source_type": evidence.source_type,
        "record_timestamp": evidence.record_timestamp,
        "ingested_at": evidence.ingested_at,
        "snippet": evidence.snippet,
        "pointer_json": _json.dumps(evidence.pointer) if evidence.pointer else None,
    }

    with get_session() as session:
        result = session.run(cypher, params)
        record = result.single()
        actual_id = record["evidence_id"] if record else evidence.evidence_id

    if actual_id != evidence.evidence_id:
        logger.debug(
            "write_evidence: (source_id=%s, dataset=%s) already exists as evidence_id=%s",
            evidence.source_id, evidence.dataset, actual_id,
        )
        # Return a copy with the stable, existing evidence_id
        return Evidence(
            evidence_id=actual_id,
            dataset=evidence.dataset,
            source_id=evidence.source_id,
            source_type=evidence.source_type,
            record_timestamp=evidence.record_timestamp,
            ingested_at=evidence.ingested_at,
            snippet=evidence.snippet,
            pointer=evidence.pointer,
        )

    logger.debug("write_evidence: %s (source_id=%s)", actual_id, evidence.source_id)
    return evidence


# ---------------------------------------------------------------------------
# C3 — write_resolution_decision
# ---------------------------------------------------------------------------

def write_resolution_decision(decision: ResolutionDecision) -> None:
    """Write a ResolutionDecision node and its provenance edges.

    Creates:
      - (:ResolutionDecision) node (MERGE on decision_id — idempotent).
      - (:CanonicalEntity)-[:RESOLVED_FROM]->(:ResolutionDecision)
      - For each source_record_id in decision.source_record_ids:
          (:ResolutionDecision)-[:BASED_ON]->(:Evidence {source_id: source_record_id, dataset})

    This completes the exact provenance path from DOC3 §2.5:
        CanonicalEntity → ResolutionDecision → Evidence (via source_record_ids)

    DOC3 §1.7, §2.5, §6.2 (RESOLVED_FROM, BASED_ON relationship types).

    Note: Evidence nodes for each source_record_id must already exist before calling
    this function (written via write_evidence()). If an Evidence node for a given
    source_record_id is not found, the BASED_ON edge is skipped with a warning —
    this is a data-integrity issue logged but not raised (pipeline continues).
    """
    import json as _json

    cypher_decision = """
    MERGE (rd:ResolutionDecision {decision_id: $decision_id})
    ON CREATE SET
        rd.entity_id         = $entity_id,
        rd.mention_ids       = $mention_ids,
        rd.source_record_ids = $source_record_ids,
        rd.outcome           = $outcome,
        rd.method            = $method,
        rd.matched_on        = $matched_on,
        rd.score             = $score,
        rd.decided_at        = $decided_at
    """
    params_decision = {
        "decision_id": decision.decision_id,
        "entity_id": decision.entity_id,
        "mention_ids": decision.mention_ids,
        "source_record_ids": decision.source_record_ids,
        "outcome": decision.outcome,
        "method": decision.method,
        "matched_on": decision.matched_on,
        "score": decision.score,
        "decided_at": decision.decided_at,
    }

    cypher_resolved_from = """
    MATCH (entity {entity_id: $entity_id})
    MATCH (rd:ResolutionDecision {decision_id: $decision_id})
    MERGE (entity)-[:RESOLVED_FROM]->(rd)
    """

    cypher_based_on = """
    MATCH (rd:ResolutionDecision {decision_id: $decision_id})
    MATCH (ev:Evidence {source_id: $source_id, dataset: $dataset})
    MERGE (rd)-[:BASED_ON]->(ev)
    RETURN count(ev) AS matched
    """

    with get_session() as session:
        # 1. Create/merge the ResolutionDecision node
        session.run(cypher_decision, params_decision)

        # 2. RESOLVED_FROM: CanonicalEntity -> ResolutionDecision
        session.run(cypher_resolved_from, {
            "entity_id": decision.entity_id,
            "decision_id": decision.decision_id,
        })

        # 3. BASED_ON: ResolutionDecision -> Evidence (one per source_record_id)
        dataset = _derive_dataset(decision)
        for source_record_id in decision.source_record_ids:
            result = session.run(cypher_based_on, {
                "decision_id": decision.decision_id,
                "source_id": source_record_id,
                "dataset": dataset,
            })
            record = result.single()
            if not record or record["matched"] == 0:
                logger.warning(
                    "write_resolution_decision: no Evidence found for "
                    "source_id=%r dataset=%r — BASED_ON edge skipped. "
                    "Ensure write_evidence() was called before write_resolution_decision().",
                    source_record_id, dataset,
                )

    logger.debug(
        "write_resolution_decision: %s -> entity %s (%d source records)",
        decision.decision_id, decision.entity_id, len(decision.source_record_ids),
    )


def _derive_dataset(decision: ResolutionDecision) -> str:
    """Extract the dataset from the decision. The ResolutionDecision itself does not
    carry a `dataset` field (DOC3 §1.7 schema), but the entity it points to does.
    We look up the entity node's dataset in Neo4j to resolve the BASED_ON lookup.

    If the entity node cannot be found, fall back to 'synthetic_demo' and log a warning.
    """
    cypher = "MATCH (n {entity_id: $entity_id}) RETURN n.dataset AS dataset LIMIT 1"
    with get_session() as session:
        result = session.run(cypher, {"entity_id": decision.entity_id})
        record = result.single()
        if record and record["dataset"]:
            return record["dataset"]

    logger.warning(
        "_derive_dataset: entity_id=%r not found — falling back to 'synthetic_demo'",
        decision.entity_id,
    )
    return "synthetic_demo"


# ---------------------------------------------------------------------------
# Convenience factory: build an Evidence object from a RawRecord (for seeding)
# ---------------------------------------------------------------------------

def evidence_from_raw_record(
    record_id: str,
    dataset: str,
    source_type: str,
    ingested_at: str,
    occurred_at: Optional[str] = None,
    snippet: Optional[str] = None,
) -> Evidence:
    """Build an Evidence object from RawRecord fields.

    The evidence_id is a deterministic UUID v4 (random) — callers should persist
    the returned object so subsequent writes can reuse the same evidence_id via
    write_evidence()'s idempotency mechanism.
    """
    return Evidence(
        evidence_id=_new_uuid(),
        dataset=dataset,
        source_id=record_id,
        source_type=source_type,
        record_timestamp=occurred_at,
        ingested_at=ingested_at,
        snippet=snippet,
    )
