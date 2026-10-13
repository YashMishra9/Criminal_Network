"""scripts/seed_demo.py — Reliable, repeatable demo graph seeder.

Task H3 (DOC4): Run the full B→C pipeline against H1's synthetic dataset and
produce a correct, evidence-complete graph from a clean database.

Usage:
    python scripts/seed_demo.py [--clear] [--dataset synthetic_demo]

What this script does:
  1. (Optionally) clears all synthetic_demo data from Neo4j.
  2. Applies the Neo4j schema (C1 — idempotent).
  3. Loads all H1 synthetic records via the synthetic adapter (B2).
  4. Extracts entities/relationships from each record (B3–B5).
  5. Runs batch entity resolution (B7 — BatchResolver).
  6. Writes all Evidence nodes (C3 — write_evidence, idempotent).
  7. Writes all CanonicalEntity nodes (C2 — write_entity).
  8. Writes all ResolutionDecision nodes + provenance edges (C3).
  9. Writes all Relationship nodes + EdgeRef + SUPPORTS edges (C2).

After this script completes, the graph satisfies:
  - Every entity has a ResolutionDecision chain traceable to at least one Evidence.
  - Every Relationship has at least one Evidence via its EdgeRef.
  - H3 integration tests can assert H1's answer-key aliases merged correctly.

Contract Invariants enforced:
  - Invariant 1:  No relationship written without evidence.
  - Invariant 2:  synthetic_demo data only (no cross-dataset contamination).
  - Invariant 7:  live adapter not required or called.
  - Invariant 8:  All writes flow through Graph Write Layer.
  - Invariant 12: Exactly one EdgeRef per relationship.
"""

import argparse
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Allow running from repo root: python scripts/seed_demo.py
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from app.contracts.entity import CanonicalEntity
from app.contracts.evidence import Evidence
from app.contracts.relationship import Relationship
from app.contracts.resolution import ResolutionDecision
from app.extraction.extractor import Extractor, build_extractor
from app.graph.connection import health_check
from app.graph.schema import apply_schema
from app.graph.write_layer import (
    evidence_from_raw_record,
    write_entity,
    write_evidence,
    write_relationship,
    write_resolution_decision,
)
from app.ingestion.synthetic_adapter import SyntheticAdapter
from app.resolution.resolver import BatchResolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("seed_demo")

DATASET = "synthetic_demo"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _clear_synthetic_data() -> None:
    """Delete all synthetic_demo nodes from Neo4j. Non-destructive for live_public."""
    from app.graph.connection import get_session
    logger.info("Clearing existing synthetic_demo data …")
    with get_session() as session:
        session.run("MATCH (n {dataset: 'synthetic_demo'}) DETACH DELETE n")
    logger.info("Cleared.")


# ---------------------------------------------------------------------------
# Step 3+4: Load records and extract mentions
# ---------------------------------------------------------------------------

def _load_and_extract(adapter: SyntheticAdapter) -> Tuple[
    List,         # raw_records
    Dict,         # entity_mentions: record_id -> List[EntityMention]
    Dict,         # rel_mentions: record_id -> List[RelationshipMention]
]:
    records = adapter.fetch_batch()
    logger.info("Loaded %d synthetic records", len(records))

    # build_extractor(with_llm=False) → guaranteed offline, LLM-free path (Contract Invariant 4).
    extractor: Extractor = build_extractor(with_llm=False)
    all_entity_mentions: Dict = {}
    all_rel_mentions: Dict = {}

    for record in records:
        result = extractor.extract_one(record)
        all_entity_mentions[record.record_id] = result.entities
        all_rel_mentions[record.record_id] = result.relationships

    total_entities = sum(len(v) for v in all_entity_mentions.values())
    total_rels = sum(len(v) for v in all_rel_mentions.values())
    logger.info(
        "Extraction complete: %d entity mentions, %d relationship mentions",
        total_entities, total_rels,
    )
    return records, all_entity_mentions, all_rel_mentions


# ---------------------------------------------------------------------------
# Step 5: Batch entity resolution
# ---------------------------------------------------------------------------

def _resolve_entities(all_entity_mentions: Dict) -> Tuple[
    List[CanonicalEntity],
    List[ResolutionDecision],
]:
    # Flatten all mentions for the dataset
    flat_mentions = []
    for mentions in all_entity_mentions.values():
        flat_mentions.extend(mentions)

    logger.info("Running batch resolution on %d mentions …", len(flat_mentions))
    resolver = BatchResolver()
    # BatchResolver.resolve() returns a ResolutionResult dataclass — not a tuple.
    resolution = resolver.resolve(flat_mentions, dataset=DATASET)
    entities = resolution.entities
    decisions = resolution.decisions
    logger.info(
        "Resolution complete: %d canonical entities, %d decisions",
        len(entities), len(decisions),
    )
    return entities, decisions


# ---------------------------------------------------------------------------
# Step 6: Write Evidence nodes (one per unique RawRecord)
# ---------------------------------------------------------------------------

def _write_all_evidence(records) -> Dict[str, Evidence]:
    """Write one Evidence node per RawRecord. Returns record_id -> Evidence mapping."""
    evidence_map: Dict[str, Evidence] = {}
    for record in records:
        ev_obj = evidence_from_raw_record(
            record_id=record.record_id,
            dataset=record.dataset,
            source_type=record.source_type,
            ingested_at=record.ingested_at,
            occurred_at=record.occurred_at,
            snippet=_make_snippet(record),
        )
        # write_evidence is idempotent — safe to call multiple times
        persisted = write_evidence(ev_obj)
        evidence_map[record.record_id] = persisted

    logger.info("Wrote %d Evidence nodes", len(evidence_map))
    return evidence_map


def _make_snippet(record) -> Optional[str]:
    """Create a short human-readable snippet from the record payload."""
    payload = getattr(record, "payload", {}) or {}
    text = getattr(record, "payload_text", None)
    if text:
        return text[:200]
    return f"{record.source_type} record {record.record_id}"


# ---------------------------------------------------------------------------
# Step 7: Write CanonicalEntity nodes
# ---------------------------------------------------------------------------

def _write_all_entities(entities: List[CanonicalEntity]) -> None:
    for entity in entities:
        write_entity(entity)
    logger.info("Wrote %d CanonicalEntity nodes", len(entities))


# ---------------------------------------------------------------------------
# Step 8: Write ResolutionDecision nodes + provenance edges
# ---------------------------------------------------------------------------

def _write_all_decisions(decisions: List[ResolutionDecision]) -> None:
    for decision in decisions:
        write_resolution_decision(decision)
    logger.info("Wrote %d ResolutionDecision nodes", len(decisions))


# ---------------------------------------------------------------------------
# Step 9: Synthesize and write Relationships
# ---------------------------------------------------------------------------

def _write_all_relationships(
    all_rel_mentions: Dict,
    entities: List[CanonicalEntity],
    evidence_map: Dict[str, Evidence],
    all_entity_mentions: Dict,
) -> None:
    """Build Relationship objects from RelationshipMentions and write them to the graph.

    For each RelationshipMention we:
      1. Resolve from_mention_id and to_mention_id to entity_ids.
      2. Find the Evidence node for the source record.
      3. Write the Relationship + EdgeRef + SUPPORTS edge.
    """
    # Build mention_id -> entity_id lookup from resolved entities and their decisions
    mention_to_entity: Dict[str, str] = {}
    for entity in entities:
        for mid in entity.resolved_from:
            mention_to_entity[mid] = entity.entity_id

    written = 0
    skipped = 0

    for record_id, rel_mentions in all_rel_mentions.items():
        evidence = evidence_map.get(record_id)
        if not evidence:
            logger.warning("No evidence for record_id=%r — skipping %d rel mentions",
                           record_id, len(rel_mentions))
            skipped += len(rel_mentions)
            continue

        for rm in rel_mentions:
            from_entity_id = mention_to_entity.get(rm.from_mention_id)
            to_entity_id = mention_to_entity.get(rm.to_mention_id)

            if not from_entity_id or not to_entity_id:
                logger.debug(
                    "Skipping RelMention %s: unresolved endpoint(s) "
                    "(from=%r, to=%r)",
                    rm.relationship_mention_id,
                    rm.from_mention_id,
                    rm.to_mention_id,
                )
                skipped += 1
                continue

            # Derive valid_from from occurred_at (RelationshipMention field, DOC3 §1.3),
            # falling back to the record-level Evidence.ingested_at when not set.
            occurred_at = rm.occurred_at  # Optional[str] per DOC3 §1.3
            valid_from = occurred_at or evidence.ingested_at
            attrs = dict(rm.attributes) if rm.attributes else {}
            if not occurred_at:
                attrs["timestamp_is_fallback"] = True

            relationship_id = _new_uuid()
            rel = Relationship(
                relationship_id=relationship_id,
                relationship_type=rm.relationship_type,
                from_entity_id=from_entity_id,
                to_entity_id=to_entity_id,
                dataset=DATASET,
                attributes=attrs,
                valid_from=valid_from,
                evidence_ids=[evidence.evidence_id],
                created_at=_iso_now(),
                updated_at=_iso_now(),
            )

            try:
                write_relationship(rel, evidence_list=[evidence])
                written += 1
            except ValueError as exc:
                logger.error("write_relationship failed for %s: %s", relationship_id, exc)
                skipped += 1

    logger.info("Wrote %d Relationships; skipped %d", written, skipped)


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------

def seed(clear: bool = False) -> None:
    """Run the full seed pipeline. Safe to re-run (idempotent writes)."""
    logger.info("=== seed_demo.py start ===")

    # Verify Neo4j connectivity
    if not health_check():
        logger.error("Neo4j is not reachable — aborting. Check NEO4J_URI / credentials.")
        sys.exit(1)

    if clear:
        _clear_synthetic_data()

    # C1: Apply schema (idempotent)
    logger.info("Applying Neo4j schema …")
    apply_schema()

    # B2: Load synthetic records
    adapter = SyntheticAdapter()
    records, all_entity_mentions, all_rel_mentions = _load_and_extract(adapter)

    # B7: Batch entity resolution
    entities, decisions = _resolve_entities(all_entity_mentions)

    # C3: Write Evidence nodes
    evidence_map = _write_all_evidence(records)

    # C2: Write CanonicalEntity nodes
    _write_all_entities(entities)

    # C3: Write ResolutionDecision nodes + RESOLVED_FROM + BASED_ON edges
    _write_all_decisions(decisions)

    # C2: Write Relationships + EdgeRef + SUPPORTS edges
    _write_all_relationships(all_rel_mentions, entities, evidence_map, all_entity_mentions)

    logger.info("=== seed_demo.py complete ===")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the Neo4j database with H1 synthetic demo data."
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        default=False,
        help="Delete all existing synthetic_demo data before seeding.",
    )
    args = parser.parse_args()
    seed(clear=args.clear)


if __name__ == "__main__":
    main()
