"""Graph query helpers — C5: as_of filter (DOC3 §2.4A, Contract Invariant 14).

This is the SINGLE implementation of the as_of temporal filter rule. Every
component (C6 / GET /graph, D1 / Analytics, F1-F3 / Ask-the-Network) MUST
import and call the helpers here — never reimplement them (Invariant 14).

DOC3 §2.4A defines two rules:

  Rule 1 — Relationship visibility:
    A relationship is visible at a given ``as_of`` iff:
        valid_from <= as_of  AND  (valid_to IS NULL  OR  valid_to >= as_of)

  Rule 2 — Entity visibility (derived from relationships, not independent):
    An entity is visible at a given ``as_of`` iff:
        (a) it participates in ≥1 visible relationship (Rule 1), OR
        (b) it has zero relationships in the dataset (isolated entity — always shown).
    Entities are NEVER excluded by their own created_at / updated_at timestamp.

These rules are query-time filters, not pre-computed snapshots (DOC2 §11).

When ``as_of`` is None, no temporal filter is applied and all data is returned.

Implementation notes:
  - Relationship properties are stored as ISO-8601 strings; Cypher string
    comparison is lexicographically correct for the ISO-8601 format used
    (YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DD).
  - All Cypher produced here uses named parameters ($as_of, $dataset) to
    allow safe parameterised execution; no values are interpolated as literals.
  - Functions return plain strings (Cypher fragments) or dicts (parameter
    additions) to stay composable — callers assemble the full query.
"""

from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Public API — reused by C6, D1, F1-F3
# ---------------------------------------------------------------------------


def relationship_visibility_clause(
    rel_alias: str = "r",
    as_of_param: str = "as_of",
) -> str:
    """Return a Cypher WHERE sub-expression implementing DOC3 §2.4A Rule 1.

    Evaluates to TRUE when the relationship identified by *rel_alias* is
    temporally visible at the timestamp bound to *as_of_param*.

    ISO-8601 string comparison is used because all ``valid_from`` /
    ``valid_to`` values are stored in the same format and compare
    lexicographically correctly.

    Args:
        rel_alias:    Cypher alias for the domain relationship (default ``r``).
        as_of_param:  Name of the Cypher parameter holding the as_of
                      timestamp string (default ``as_of``).

    Returns:
        A Cypher boolean expression (no leading ``WHERE``).  Example::

            (r.valid_from <= $as_of AND (r.valid_to IS NULL OR r.valid_to >= $as_of))

    Usage (caller composes)::

        clause = relationship_visibility_clause("rel", "as_of")
        cypher = f"MATCH ...-[rel:CALLED]->... WHERE {clause} RETURN rel"
    """
    return (
        f"({rel_alias}.valid_from <= ${as_of_param}"
        f" AND ({rel_alias}.valid_to IS NULL"
        f" OR {rel_alias}.valid_to >= ${as_of_param}))"
    )


def build_as_of_filter(
    as_of: Optional[str],
    *,
    entity_alias: str = "n",
    rel_alias: str = "r",
    dataset_param: str = "dataset",
    as_of_param: str = "as_of",
) -> AsOfFilter:
    """Build the complete DOC3 §2.4A filter for a graph query.

    Returns an ``AsOfFilter`` containing:
    - ``params``: dict of extra parameters to add to the query (``as_of``
      when it is not None).
    - ``relationship_where``: WHERE clause snippet for filtering
      relationships (empty string when ``as_of`` is None).
    - ``entity_subquery``: a Cypher EXISTS sub-expression that implements
      Rule 2 (entity visibility derived from relationship visibility),
      including the isolated-entity exception.  This is designed to be
      placed in a WHERE clause on the entity alias.

    Args:
        as_of:          The temporal cutoff (ISO-8601 string) or None for
                        "no filter — return all data".
        entity_alias:   Cypher alias for the ``CanonicalEntity`` node
                        (default ``n``).
        rel_alias:      Cypher alias used inside the sub-pattern for
                        relationships (default ``r``).
        dataset_param:  Name of the Cypher parameter that holds the dataset
                        value (default ``dataset``).
        as_of_param:    Name of the Cypher parameter that will hold the
                        as_of timestamp (default ``as_of``).

    Returns:
        An :class:`AsOfFilter` instance.
    """
    if as_of is None:
        return AsOfFilter(
            params={},
            relationship_where="",
            entity_subquery="",
        )

    rel_vis = relationship_visibility_clause(rel_alias, as_of_param)

    # Rule 1: relationship WHERE clause (used by callers that directly
    # iterate over relationships).
    relationship_where = rel_vis

    # Rule 2: entity visibility sub-expression.
    #
    # An entity n is visible iff:
    #   (a) EXISTS { MATCH (n)-[r]->() WHERE r.dataset = $dataset AND <rel_vis> }
    #       OR EXISTS { MATCH ()<-[r]-(n) WHERE r.dataset = $dataset AND <rel_vis> }
    #   OR
    #   (b) NOT EXISTS { MATCH (n)-[r {dataset: $dataset}]-() }
    #       (isolated entity — no relationships in the dataset at all)
    #
    # We use a single compound expression so callers can drop it verbatim
    # into a WHERE clause.
    entity_subquery = (
        # (a) has ≥1 visible relationship (either direction)
        f"("
        f"EXISTS {{ MATCH ({entity_alias})-[{rel_alias}]->()"
        f" WHERE {rel_alias}.dataset = ${dataset_param} AND {rel_vis} }}"
        f" OR EXISTS {{ MATCH ({entity_alias})<-[{rel_alias}]-()"
        f" WHERE {rel_alias}.dataset = ${dataset_param} AND {rel_vis} }}"
        # (b) isolated entity — zero domain relationships in this dataset
        f" OR NOT EXISTS {{ MATCH ({entity_alias})-[{rel_alias}]-()"
        f" WHERE {rel_alias}.dataset = ${dataset_param} }}"
        f")"
    )

    return AsOfFilter(
        params={as_of_param: as_of},
        relationship_where=relationship_where,
        entity_subquery=entity_subquery,
    )


def is_relationship_visible(valid_from: str, valid_to: Optional[str], as_of: str) -> bool:
    """Pure-Python evaluation of DOC3 §2.4A Rule 1.

    Determines whether a relationship is visible at *as_of* based on its
    *valid_from* and *valid_to* properties, using identical semantics to the
    Cypher generated by :func:`relationship_visibility_clause`.

    This function is the canonical Python-side reference implementation of
    Rule 1.  It is used in:
    - Unit tests to verify boundary conditions without a live Neo4j instance.
    - Any in-process filtering step that works with already-fetched
      ``Relationship`` objects (e.g. post-fetch client-side filtering).

    Args:
        valid_from:  ISO-8601 string; the relationship's earliest known
                     occurrence.  Must not be None.
        valid_to:    ISO-8601 string or None.  None means open-ended.
        as_of:       ISO-8601 string; the temporal cutoff to evaluate at.

    Returns:
        True iff ``valid_from <= as_of AND (valid_to IS NULL OR valid_to >= as_of)``.

    DOC3 §2.4A Rule 1 (exact): relationship visible iff
        valid_from <= as_of  AND  (valid_to IS NULL  OR  valid_to >= as_of)
    """
    if valid_from > as_of:
        return False
    if valid_to is not None and valid_to < as_of:
        return False
    return True


def is_entity_visible(
    has_visible_relationship: bool,
    total_dataset_relationships: int,
) -> bool:
    """Pure-Python evaluation of DOC3 §2.4A Rule 2.

    Determines whether an entity is visible at a given as_of timestamp,
    given pre-computed facts about its relationships.

    This function is the canonical Python-side reference implementation of
    Rule 2.  It is used in:
    - Unit tests to verify the isolated-entity boundary condition.
    - Any in-process filtering step that works with already-fetched entities.

    Args:
        has_visible_relationship:      True iff the entity participates in ≥1
                                       relationship that satisfies Rule 1 at
                                       the given as_of.
        total_dataset_relationships:   Total number of relationships the entity
                                       has in its dataset (regardless of as_of).
                                       Zero means "isolated entity".

    Returns:
        True iff the entity should be visible:
        - Always True when ``total_dataset_relationships == 0`` (isolated,
          per Rule 2b — "nothing temporal to filter about it").
        - True when ``has_visible_relationship`` is True (Rule 2a).
        - False otherwise (connected entity whose only relationship(s) fall
          outside the as_of window).

    DOC3 §2.4A Rule 2 (exact): entity visible iff
        (a) ≥1 visible relationship (Rule 1), OR
        (b) zero relationships in the dataset (isolated entity — always shown).
    """
    if total_dataset_relationships == 0:
        return True  # Rule 2b: isolated entity — always shown
    return has_visible_relationship  # Rule 2a


# ---------------------------------------------------------------------------
# AsOfFilter dataclass — output of build_as_of_filter()
# ---------------------------------------------------------------------------

class AsOfFilter:
    """Immutable bundle produced by :func:`build_as_of_filter`.

    Attributes:
        params:               Dict of query parameters to merge into the
                              caller's params dict.  Empty when ``as_of``
                              is None.
        relationship_where:   Cypher WHERE sub-expression for Rule 1
                              (relationship visibility).  Empty string when
                              ``as_of`` is None (no filter).
        entity_subquery:      Cypher EXISTS compound expression for Rule 2
                              (entity visibility derived from relationships).
                              Empty string when ``as_of`` is None.

    Usage example::

        f = build_as_of_filter(as_of="2024-06-01", dataset_param="dataset")

        # For a relationship query:
        if f.relationship_where:
            cypher += f" WHERE {f.relationship_where}"

        # For an entity query (Rule 2):
        if f.entity_subquery:
            cypher += f" WHERE {f.entity_subquery}"

        # Always merge params:
        params = {\"dataset\": \"synthetic_demo\", **f.params}
    """

    __slots__ = ("params", "relationship_where", "entity_subquery")

    def __init__(
        self,
        params: dict,
        relationship_where: str,
        entity_subquery: str,
    ) -> None:
        object.__setattr__(self, "params", params)
        object.__setattr__(self, "relationship_where", relationship_where)
        object.__setattr__(self, "entity_subquery", entity_subquery)

    def __setattr__(self, name: str, value: object) -> None:  # type: ignore[override]
        raise AttributeError("AsOfFilter is immutable")

    def __repr__(self) -> str:
        return (
            f"AsOfFilter(params={self.params!r}, "
            f"relationship_where={self.relationship_where!r}, "
            f"entity_subquery={self.entity_subquery!r})"
        )

    @property
    def is_active(self) -> bool:
        """True when an as_of timestamp was supplied (filter is in effect)."""
        return bool(self.params)
