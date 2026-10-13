"""Entity Resolvers — B7 (batch) + B8 (incremental), DOC3 §5.

Task B7: Full-dataset clustering and resolution for the synthetic_demo dataset.
Task B8: Incremental, best-effort resolution for live_public new mentions.

Both produce CanonicalEntity[] and ResolutionDecision[] from EntityMention input.

Key constraints (both resolvers):
  - NEVER merges across dataset values (DOC3 §2.6, Contract Invariant 2).
  - source_record_ids must be parallel to mention_ids (DOC3 §1.7).
  - All thresholds in thresholds.py — none hardcoded here (DOC2 §8).
  - In-process only; no Neo4j access (graph writes are Track C).

Batch (B7) algorithm — Union-Find clustering, O(n²) per type:
  1. Group mentions by (entity_type, dataset).
  2. Compare all pairs via matching_rules.compare().
  3. Union-Find clusters merging mentions.
  4. One CanonicalEntity + decision log per cluster.

Incremental (B8) algorithm — single-mention against existing entity set:
  1. For each existing CanonicalEntity of the same type+dataset, call
     matching_rules.compare() between the new mention and a synthetic
     representative mention built from the entity's display_name.
  2. First match found → attach new mention to that entity (best-effort).
  3. No match → new singleton CanonicalEntity (never blocks ingestion).
  B8 is explicitly NOT correctness-guaranteed (DOC1 FR11). It is documented
  in code and tests as best-effort only.

DOC3 §2.5 provenance: source_record_ids parallel to mention_ids on every
ResolutionDecision enables entity → RawRecord → Evidence traversal.

DOC3 §1.13: entity_id and decision_id are globally unique UUIDs.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterator, List, Optional, Tuple

from app.contracts.entity import CanonicalEntity
from app.contracts.mention import EntityMention
from app.contracts.resolution import ResolutionDecision
from app.resolution.matching_rules import MatchResult, compare

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resolution output bundle
# ---------------------------------------------------------------------------

@dataclass
class ResolutionResult:
    """Output of one batch resolution run."""
    entities: List[CanonicalEntity] = field(default_factory=list)
    decisions: List[ResolutionDecision] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Union-Find (path-compressed, for clustering)
# ---------------------------------------------------------------------------

class _UnionFind:
    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank = [0] * n

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path halving
            x = self._parent[x]
        return x

    def union(self, x: int, y: int) -> bool:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1
        return True


# ---------------------------------------------------------------------------
# BatchResolver
# ---------------------------------------------------------------------------

class BatchResolver:
    """Batch entity resolution over a full dataset's EntityMention list.

    Usage:
        resolver = BatchResolver()
        result = resolver.resolve(mentions, dataset="synthetic_demo")

    Args:
        mentions:  All EntityMention objects for one dataset.
        dataset:   The dataset value; used for isolation checking.

    Returns:
        ResolutionResult with CanonicalEntity[] and ResolutionDecision[].
    """

    def resolve(
        self,
        mentions: List[EntityMention],
        dataset: str,
    ) -> ResolutionResult:
        """Run batch resolution over all mentions for a single dataset.

        Args:
            mentions: All EntityMention objects for the given dataset.
            dataset:  The dataset these mentions belong to.

        Returns:
            ResolutionResult containing entities and decisions.
        """
        # DOC3 §2.6: enforce dataset isolation before any comparison
        bad = [m for m in mentions if m.dataset != dataset]
        if bad:
            raise ValueError(
                f"BatchResolver.resolve() received {len(bad)} mentions with "
                f"dataset != '{dataset}'. Refusing to process — dataset isolation "
                f"is a contract invariant (DOC3 §2.6, Contract Invariant 2)."
            )

        result = ResolutionResult()
        now = _iso_now()

        # Group by entity_type (compare only within the same type)
        by_type: Dict[str, List[EntityMention]] = {}
        for m in mentions:
            by_type.setdefault(m.entity_type, []).append(m)

        for entity_type, group in by_type.items():
            entities, decisions = self._resolve_group(group, entity_type, dataset, now)
            result.entities.extend(entities)
            result.decisions.extend(decisions)

        logger.info(
            "BatchResolver: dataset='%s' → %d canonical entities, %d decisions "
            "(from %d input mentions).",
            dataset, len(result.entities), len(result.decisions), len(mentions),
        )
        return result

    # ------------------------------------------------------------------
    # Private — group-level resolution
    # ------------------------------------------------------------------

    def _resolve_group(
        self,
        group: List[EntityMention],
        entity_type: str,
        dataset: str,
        now: str,
    ) -> Tuple[List[CanonicalEntity], List[ResolutionDecision]]:
        """Resolve one entity_type group using Union-Find clustering."""
        n = len(group)
        uf = _UnionFind(n)

        # Store match results for the decision log
        pair_results: Dict[Tuple[int, int], MatchResult] = {}

        # Pairwise comparison — O(n²), acceptable for demo dataset size
        for i in range(n):
            for j in range(i + 1, n):
                result = compare(group[i], group[j])
                if result.should_merge:
                    uf.union(i, j)
                    pair_results[(i, j)] = result

        # Build clusters: root → list of member indices
        clusters: Dict[int, List[int]] = {}
        for idx in range(n):
            root = uf.find(idx)
            clusters.setdefault(root, []).append(idx)

        entities: List[CanonicalEntity] = []
        decisions: List[ResolutionDecision] = []

        for root, members in clusters.items():
            cluster_mentions = [group[idx] for idx in members]
            entity_id = str(uuid.uuid4())

            # Build the CanonicalEntity for this cluster
            entity = self._make_entity(
                entity_id=entity_id,
                entity_type=entity_type,
                dataset=dataset,
                mentions=cluster_mentions,
                now=now,
            )
            entities.append(entity)

            # One ResolutionDecision per matched pair within the cluster
            if len(members) == 1:
                # Singleton — trivial self-merge decision
                m = cluster_mentions[0]
                decisions.append(ResolutionDecision(
                    decision_id=str(uuid.uuid4()),
                    entity_id=entity_id,
                    mention_ids=[m.mention_id],
                    source_record_ids=[m.record_id],
                    outcome="merged",
                    method="exact_match",
                    matched_on=["singleton"],
                    score=1.0,
                    decided_at=now,
                ))
            else:
                # One decision per merged pair
                for i_raw, j_raw in pair_results:
                    # Only include pairs that are in this cluster
                    if uf.find(i_raw) == root and uf.find(j_raw) == root:
                        m1 = group[i_raw]
                        m2 = group[j_raw]
                        r = pair_results[(i_raw, j_raw)]
                        decisions.append(ResolutionDecision(
                            decision_id=str(uuid.uuid4()),
                            entity_id=entity_id,
                            mention_ids=[m1.mention_id, m2.mention_id],
                            source_record_ids=[m1.record_id, m2.record_id],
                            outcome="merged",
                            method=r.method,  # type: ignore[arg-type]
                            matched_on=r.matched_on,
                            score=r.score,
                            decided_at=now,
                        ))
                # Also add a cluster-level summary decision listing all mentions
                all_mention_ids = [m.mention_id for m in cluster_mentions]
                all_record_ids = [m.record_id for m in cluster_mentions]
                # Find best method across all pairs
                all_results = [
                    pair_results[(i, j)]
                    for (i, j) in pair_results
                    if uf.find(i) == root and uf.find(j) == root
                ]
                best_method = _best_method(all_results)
                all_matched_on = sorted({s for r in all_results for s in r.matched_on})
                best_score = max((r.score for r in all_results if r.score is not None), default=1.0)
                decisions.append(ResolutionDecision(
                    decision_id=str(uuid.uuid4()),
                    entity_id=entity_id,
                    mention_ids=all_mention_ids,
                    source_record_ids=all_record_ids,
                    outcome="merged",
                    method=best_method,  # type: ignore[arg-type]
                    matched_on=all_matched_on,
                    score=best_score,
                    decided_at=now,
                ))

        return entities, decisions

    @staticmethod
    def _make_entity(
        entity_id: str,
        entity_type: str,
        dataset: str,
        mentions: List[EntityMention],
        now: str,
    ) -> CanonicalEntity:
        """Build a CanonicalEntity from a cluster of mentions.

        Display name strategy:
          - Phone: prefer normalized E.164 (+91XXXXXXXXXX)
          - Vehicle: prefer normalized plate (no hyphens)
          - BankAccount: use the raw text as-is
          - Person/Org/Location/Event: longest raw_text (most complete name)
        """
        mention_ids = [m.mention_id for m in mentions]

        if entity_type == "Phone":
            # Use the normalized E.164 form; prefer longest normalized value
            display = _best_phone_display(mentions)
        elif entity_type == "Vehicle":
            display = _best_vehicle_display(mentions)
        elif entity_type in ("BankAccount", "Transaction"):
            display = (mentions[0].normalized_value or mentions[0].raw_text).strip()
        else:
            # Person, Organization, Location, Event — longest raw text wins
            display = max((m.raw_text for m in mentions), key=len).strip()

        # Merge attributes from all mentions
        merged_attrs: dict = {}
        for m in mentions:
            if isinstance(m.attributes, dict):
                merged_attrs.update(m.attributes)

        # Determine resolution_method from the ensemble
        methods = {m.extraction_method for m in mentions}
        if "regex" in methods:
            res_method = "exact_match" if entity_type in ("Phone", "Vehicle", "BankAccount", "Transaction") else "fuzzy_match"
        else:
            res_method = "fuzzy_match"

        return CanonicalEntity(
            entity_id=entity_id,
            entity_type=entity_type,  # type: ignore[arg-type]
            dataset=dataset,
            display_name=display,
            attributes=merged_attrs,
            resolved_from=mention_ids,
            resolution_method=res_method,  # type: ignore[arg-type]
            created_at=now,
            updated_at=now,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _best_phone_display(mentions: List[EntityMention]) -> str:
    for m in mentions:
        nv = m.normalized_value or ""
        if len(nv) == 10 and nv.isdigit():
            return f"+91{nv}"
    # Fallback: pick longest normalized value
    best = max(mentions, key=lambda m: len(m.normalized_value or m.raw_text))
    nv = best.normalized_value or best.raw_text
    if len(nv) == 10 and nv.isdigit():
        return f"+91{nv}"
    return nv


def _best_vehicle_display(mentions: List[EntityMention]) -> str:
    """Return the raw plate with standard spacing (e.g., 'MH-01-AB-1234')."""
    import re
    for m in mentions:
        raw = m.raw_text.strip()
        # Prefer already-formatted plates with hyphens
        if re.search(r"[A-Z]{2}-\d{2}-[A-Z]+-\d+", raw):
            return raw
    # Fallback: normalized value
    best = max(mentions, key=lambda m: len(m.raw_text))
    return best.raw_text.strip()


def _best_method(results: List[MatchResult]) -> str:
    """Return the most confident method seen in a set of MatchResults."""
    order = ["exact_match", "shared_attribute", "fuzzy_match", "embedding_similarity", "manual"]
    for preferred in order:
        if any(r.method == preferred for r in results):
            return preferred
    return "fuzzy_match"


# ---------------------------------------------------------------------------
# IncrementalResolver — B8, DOC3 §5 incremental path, DOC1 FR11
# ---------------------------------------------------------------------------

class IncrementalResolver:
    """Incremental, best-effort entity resolution for live_public new mentions.

    ⚠ BEST-EFFORT ONLY — not a correctness guarantee (DOC1 FR11).

    Compares one new EntityMention against an existing CanonicalEntity set for
    the same dataset. The first entity whose representative mention compares as
    'should_merge' is the match. No global clustering is performed.

    If no existing entity matches, the mention becomes a new singleton
    CanonicalEntity — ingestion is never blocked by a failed match.

    Dataset isolation (DOC3 §2.6) is enforced: the incoming mention and the
    existing entity set must share the same dataset value.

    Usage::

        resolver = IncrementalResolver()
        result = resolver.resolve_one(
            mention=new_mention,
            existing_entities=current_live_entities,
            dataset="live_public",
        )
        if result.updated_entity is not None:
            # Existing entity updated — reflect in graph
        else:
            # New entity created
    """

    def resolve_one(
        self,
        mention: EntityMention,
        existing_entities: List[CanonicalEntity],
        dataset: str,
    ) -> "IncrementalResult":
        """Resolve one new mention against the existing entity set.

        Args:
            mention:           The new EntityMention to resolve (must be from `dataset`).
            existing_entities: All current CanonicalEntity objects for `dataset`.
                               Only entities of the same entity_type as `mention`
                               are compared (others are silently skipped).
            dataset:           The dataset value — both mention and existing entities
                               must carry this value (isolation check).

        Returns:
            IncrementalResult with one new or updated CanonicalEntity and one
            ResolutionDecision.

        Raises:
            ValueError: if mention.dataset != dataset (isolation invariant).
        """
        if mention.dataset != dataset:
            raise ValueError(
                f"IncrementalResolver: mention.dataset={mention.dataset!r} "
                f"does not match requested dataset={dataset!r}. "
                f"Dataset isolation is a contract invariant (DOC3 §2.6, Invariant 2)."
            )

        now = _iso_now()

        # Filter to same entity_type and same dataset (isolation)
        candidates = [
            e for e in existing_entities
            if e.entity_type == mention.entity_type and e.dataset == dataset
        ]

        # Try each candidate in order; use first match (best-effort — FR11)
        for candidate in candidates:
            match_result = self._compare_against_entity(mention, candidate)
            if match_result.should_merge:
                # Update the existing entity: add mention to resolved_from
                updated = self._attach_mention(candidate, mention, now)
                decision = ResolutionDecision(
                    decision_id=str(uuid.uuid4()),
                    entity_id=candidate.entity_id,
                    mention_ids=[mention.mention_id],
                    source_record_ids=[mention.record_id],
                    outcome="merged",
                    method=match_result.method,  # type: ignore[arg-type]
                    matched_on=match_result.matched_on,
                    score=match_result.score,
                    decided_at=now,
                )
                logger.info(
                    "IncrementalResolver [%s]: mention '%s' merged into entity '%s' "
                    "(method=%s, matched_on=%s).",
                    dataset, mention.mention_id, candidate.entity_id,
                    match_result.method, match_result.matched_on,
                )
                return IncrementalResult(
                    entity=updated,
                    decision=decision,
                    is_new_entity=False,
                    updated_entity=updated,
                )

        # No match — create new singleton entity (never blocks ingestion — FR11)
        new_entity_id = str(uuid.uuid4())
        new_entity = BatchResolver._make_entity(
            entity_id=new_entity_id,
            entity_type=mention.entity_type,
            dataset=dataset,
            mentions=[mention],
            now=now,
        )
        decision = ResolutionDecision(
            decision_id=str(uuid.uuid4()),
            entity_id=new_entity_id,
            mention_ids=[mention.mention_id],
            source_record_ids=[mention.record_id],
            outcome="merged",
            method="exact_match",
            matched_on=["singleton_new_entity"],
            score=1.0,
            decided_at=now,
        )
        logger.info(
            "IncrementalResolver [%s]: mention '%s' created new entity '%s' "
            "(no match found in %d candidates).",
            dataset, mention.mention_id, new_entity_id, len(candidates),
        )
        return IncrementalResult(
            entity=new_entity,
            decision=decision,
            is_new_entity=True,
            updated_entity=None,
        )

    @staticmethod
    def _compare_against_entity(
        mention: EntityMention,
        entity: CanonicalEntity,
    ) -> MatchResult:
        """Compare a new EntityMention against an existing CanonicalEntity.

        Builds a synthetic 'representative mention' from the entity's display_name
        and delegates to matching_rules.compare(). This keeps the matching logic
        in one place (B7 and B8 share the same rules — B8's dependency on B7).
        """
        import re as _re
        # Normalize the representative value the same way the extractor does
        # (strip non-alphanumeric separators for Vehicle/Phone/BankAccount).
        raw = entity.display_name
        if entity.entity_type in ("Vehicle", "Phone", "BankAccount"):
            norm = _re.sub(r"[\s\-]", "", raw).upper()
        else:
            norm = raw

        # Build a minimal synthetic mention representing the existing entity
        representative = EntityMention(
            mention_id=f"__rep__{entity.entity_id}",
            record_id=entity.entity_id,       # sentinel — not a real record_id
            dataset=entity.dataset,
            entity_type=entity.entity_type,   # type: ignore[arg-type]
            raw_text=raw,
            normalized_value=norm,
            attributes=entity.attributes if isinstance(entity.attributes, dict) else {},
            extraction_method="regex",          # sentinel — doesn't affect matching
            confidence=None,
        )
        return compare(mention, representative)

    @staticmethod
    def _attach_mention(
        entity: CanonicalEntity,
        mention: EntityMention,
        now: str,
    ) -> CanonicalEntity:
        """Return a new CanonicalEntity with mention appended to resolved_from.

        Creates a new object (CanonicalEntity is a Pydantic model — immutable
        by convention). Callers must persist the returned object to the graph.
        """
        new_resolved_from = list(entity.resolved_from) + [mention.mention_id]
        return entity.model_copy(update={
            "resolved_from": new_resolved_from,
            "updated_at": now,
        })


@dataclass
class IncrementalResult:
    """Output of one IncrementalResolver.resolve_one() call.

    ⚠ Best-effort only — DOC1 FR11.
    """

    entity: CanonicalEntity
    """The CanonicalEntity after resolution (new or updated)."""

    decision: ResolutionDecision
    """The ResolutionDecision recording what happened."""

    is_new_entity: bool
    """True if a new CanonicalEntity was created; False if an existing one was updated."""

    updated_entity: Optional[CanonicalEntity]
    """The updated entity if is_new_entity is False, else None."""
