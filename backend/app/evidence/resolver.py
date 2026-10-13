"""C4 — Evidence / Provenance Resolver.

Implements all five EvidenceResolver methods per DOC3 §9.1:
  - for_entity(entity_id)                              → Evidence[]
  - for_relationship(relationship_id)                  → Evidence[]
  - for_finding(finding_id)                            → Evidence[]
  - for_resolution_decision(decision_id)               → Evidence[]
  - for_case_item(case_id, item_type, item_id)         → Evidence[]

Contract rules (DOC3 §9.1):
  - This is the ONLY place Evidence nodes are queried from. No other component
    may query Evidence directly (DOC3 §9.1, Contract Invariant 10).
  - Each method implements exactly the traversal DOC3 specifies — no shortcuts
    or alternate paths.
  - Every Evidence returned must include source_id, source_type, dataset at minimum
    (DOC3 §9.2).

Traversal paths (DOC3 §2.5, §6.5, §1.8):
  - for_entity:
        CanonicalEntity.entity_id
        → MATCH (n {entity_id}) -[:RESOLVED_FROM]-> (rd:ResolutionDecision)
        → rd.source_record_ids (parallel to mention_ids)
        → MATCH (ev:Evidence {source_id: source_record_id, dataset})
        → return Evidence[]

  - for_relationship:
        relationship_id
        → MATCH (er:EdgeRef {relationship_id})
        → MATCH (ev:Evidence) -[:SUPPORTS]-> (er)
        → return Evidence[]

  - for_finding:
        finding_id
        → MATCH (f:Finding {finding_id})
        → MATCH (ev:Evidence) -[:SUPPORTS]-> (f)
        → return Evidence[]   [direct, no EdgeRef needed — DOC3 §1.8]

  - for_resolution_decision:
        decision_id
        → MATCH (rd:ResolutionDecision {decision_id})
        → MATCH (rd) -[:BASED_ON]-> (ev:Evidence)
        → return Evidence[]

  - for_case_item:
        item_type == "entity"   → for_entity(item_id)
        item_type == "edge_ref" → lookup EdgeRef by edge_ref_id, then for_relationship(relationship_id)
        item_type == "evidence" → return the Evidence node directly
"""

import json
import logging
from typing import List, Literal

from app.contracts.evidence import Evidence
from app.graph.connection import get_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal Cypher helpers
# ---------------------------------------------------------------------------

def _row_to_evidence(record) -> Evidence:
    """Convert a Neo4j record row to an Evidence object.

    DOC3 §9.2: source_id, source_type, dataset are required; others may be null.
    """
    pointer = None
    raw_pointer = record.get("pointer_json")
    if raw_pointer:
        try:
            pointer = json.loads(raw_pointer)
        except (ValueError, TypeError):
            pointer = raw_pointer

    return Evidence(
        evidence_id=record["evidence_id"],
        dataset=record["dataset"],
        source_id=record["source_id"],
        source_type=record["source_type"],
        record_timestamp=record.get("record_timestamp"),
        ingested_at=record.get("ingested_at") or "",
        snippet=record.get("snippet"),
        pointer=pointer,
    )


# ---------------------------------------------------------------------------
# EvidenceResolver
# ---------------------------------------------------------------------------

class EvidenceResolver:
    """Cross-cutting Evidence / Provenance Resolver.

    The ONLY component that queries Evidence nodes (DOC3 §9.1).
    All other components must call this interface — never query Evidence directly.

    All methods are dataset-aware: they derive the dataset from the graph structure
    rather than requiring callers to pass it.
    """

    # ------------------------------------------------------------------
    # for_entity — DOC3 §2.5 canonical provenance path
    # ------------------------------------------------------------------

    def for_entity(self, entity_id: str) -> List[Evidence]:
        """Return Evidence[] for a CanonicalEntity via the §2.5 provenance path.

        Traversal:
          entity -[:RESOLVED_FROM]-> ResolutionDecision -[:BASED_ON]-> Evidence
        """
        cypher = """
        MATCH (n {entity_id: $entity_id})-[:RESOLVED_FROM]->(rd:ResolutionDecision)
        MATCH (rd)-[:BASED_ON]->(ev:Evidence)
        RETURN DISTINCT
            ev.evidence_id      AS evidence_id,
            ev.dataset          AS dataset,
            ev.source_id        AS source_id,
            ev.source_type      AS source_type,
            ev.record_timestamp AS record_timestamp,
            ev.ingested_at      AS ingested_at,
            ev.snippet          AS snippet,
            ev.pointer_json     AS pointer_json
        """
        results = []
        with get_session() as session:
            for record in session.run(cypher, {"entity_id": entity_id}):
                results.append(_row_to_evidence(record))

        logger.debug("for_entity(%s): %d Evidence records", entity_id, len(results))
        return results

    # ------------------------------------------------------------------
    # for_relationship — DOC3 §6.5 EdgeRef traversal
    # ------------------------------------------------------------------

    def for_relationship(self, relationship_id: str) -> List[Evidence]:
        """Return Evidence[] for a Relationship via its single EdgeRef.

        Traversal:
          EdgeRef {relationship_id} <-[:SUPPORTS]- Evidence
        """
        cypher = """
        MATCH (er:EdgeRef {relationship_id: $relationship_id})
        MATCH (ev:Evidence)-[:SUPPORTS]->(er)
        RETURN DISTINCT
            ev.evidence_id      AS evidence_id,
            ev.dataset          AS dataset,
            ev.source_id        AS source_id,
            ev.source_type      AS source_type,
            ev.record_timestamp AS record_timestamp,
            ev.ingested_at      AS ingested_at,
            ev.snippet          AS snippet,
            ev.pointer_json     AS pointer_json
        """
        results = []
        with get_session() as session:
            for record in session.run(cypher, {"relationship_id": relationship_id}):
                results.append(_row_to_evidence(record))

        logger.debug(
            "for_relationship(%s): %d Evidence records", relationship_id, len(results)
        )
        return results

    # ------------------------------------------------------------------
    # for_finding — DOC3 §1.8 direct Evidence-[:SUPPORTS]->Finding
    # ------------------------------------------------------------------

    def for_finding(self, finding_id: str) -> List[Evidence]:
        """Return Evidence[] for a Finding via direct Evidence-[:SUPPORTS]->Finding.

        No EdgeRef indirection — Finding is a node, so Evidence points directly to it
        (DOC3 §1.8, §6.2).
        """
        cypher = """
        MATCH (f:Finding {finding_id: $finding_id})
        MATCH (ev:Evidence)-[:SUPPORTS]->(f)
        RETURN DISTINCT
            ev.evidence_id      AS evidence_id,
            ev.dataset          AS dataset,
            ev.source_id        AS source_id,
            ev.source_type      AS source_type,
            ev.record_timestamp AS record_timestamp,
            ev.ingested_at      AS ingested_at,
            ev.snippet          AS snippet,
            ev.pointer_json     AS pointer_json
        """
        results = []
        with get_session() as session:
            for record in session.run(cypher, {"finding_id": finding_id}):
                results.append(_row_to_evidence(record))

        logger.debug("for_finding(%s): %d Evidence records", finding_id, len(results))
        return results

    # ------------------------------------------------------------------
    # for_resolution_decision — DOC3 §2.5 via BASED_ON directly
    # ------------------------------------------------------------------

    def for_resolution_decision(self, decision_id: str) -> List[Evidence]:
        """Return Evidence[] for a ResolutionDecision via its BASED_ON edges.

        Traversal:
          ResolutionDecision -[:BASED_ON]-> Evidence
        """
        cypher = """
        MATCH (rd:ResolutionDecision {decision_id: $decision_id})-[:BASED_ON]->(ev:Evidence)
        RETURN DISTINCT
            ev.evidence_id      AS evidence_id,
            ev.dataset          AS dataset,
            ev.source_id        AS source_id,
            ev.source_type      AS source_type,
            ev.record_timestamp AS record_timestamp,
            ev.ingested_at      AS ingested_at,
            ev.snippet          AS snippet,
            ev.pointer_json     AS pointer_json
        """
        results = []
        with get_session() as session:
            for record in session.run(cypher, {"decision_id": decision_id}):
                results.append(_row_to_evidence(record))

        logger.debug(
            "for_resolution_decision(%s): %d Evidence records", decision_id, len(results)
        )
        return results

    # ------------------------------------------------------------------
    # for_case_item — DOC3 §9.1
    # ------------------------------------------------------------------

    def for_case_item(
        self,
        case_id: str,
        item_type: Literal["entity", "edge_ref", "evidence"],
        item_id: str,
    ) -> List[Evidence]:
        """Return Evidence[] for a case-associated item.

        Routing:
          item_type == "entity"   → for_entity(item_id)
          item_type == "edge_ref" → look up relationship_id from EdgeRef, then for_relationship()
          item_type == "evidence" → return the single Evidence node directly

        dataset isolation is inherited from the Case's dataset (enforced by Case Workspace);
        we don't re-check it here since the item was already validated when added to the case.
        """
        if item_type == "entity":
            return self.for_entity(item_id)

        elif item_type == "edge_ref":
            # Look up the relationship_id this EdgeRef wraps
            cypher = """
            MATCH (er:EdgeRef {edge_ref_id: $edge_ref_id})
            RETURN er.relationship_id AS relationship_id
            """
            with get_session() as session:
                result = session.run(cypher, {"edge_ref_id": item_id})
                record = result.single()
                if not record:
                    logger.warning(
                        "for_case_item: EdgeRef %r not found (case_id=%s)", item_id, case_id
                    )
                    return []
                return self.for_relationship(record["relationship_id"])

        elif item_type == "evidence":
            # Return the Evidence node directly — caller is referencing it by evidence_id
            cypher = """
            MATCH (ev:Evidence {evidence_id: $evidence_id})
            RETURN
                ev.evidence_id      AS evidence_id,
                ev.dataset          AS dataset,
                ev.source_id        AS source_id,
                ev.source_type      AS source_type,
                ev.record_timestamp AS record_timestamp,
                ev.ingested_at      AS ingested_at,
                ev.snippet          AS snippet,
                ev.pointer_json     AS pointer_json
            """
            with get_session() as session:
                result = session.run(cypher, {"evidence_id": item_id})
                record = result.single()
                if not record:
                    logger.warning(
                        "for_case_item: Evidence %r not found (case_id=%s)", item_id, case_id
                    )
                    return []
                return [_row_to_evidence(record)]

        else:
            raise ValueError(
                f"for_case_item: unknown item_type={item_type!r}. "
                "Must be 'entity', 'edge_ref', or 'evidence' (DOC3 §9.1)."
            )


# ---------------------------------------------------------------------------
# Module-level singleton — callers import this, not the class directly
# ---------------------------------------------------------------------------

evidence_resolver = EvidenceResolver()
