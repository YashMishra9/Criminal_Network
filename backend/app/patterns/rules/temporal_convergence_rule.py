"""D3 temporal-convergence rule over nearby relationship timestamps."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import networkx as nx

from app.contracts.evidence import Evidence
from app.contracts.finding import Finding, INVESTIGATIVE_LEAD_DISCLAIMER
from app.evidence.resolver import EvidenceResolver, evidence_resolver
from app.graph.connection import get_session
from app.graph.queries import build_as_of_filter

logger = logging.getLogger(__name__)

RULE_ID = "temporal_convergence_v1"
RULE_NAME = "Temporal Convergence"
WINDOW_HOURS = 24
MIN_RELATIONSHIPS = 3
MIN_ENTITIES = 3
DOMAIN_RELATIONSHIP_TYPES = (
    "CALLED|OWNS|USED|TRANSFERRED|VISITED|MET|WORKS_FOR|"
    "ASSOCIATED_WITH|MENTIONED_IN|PART_OF"
)


def _validate_scope(dataset: str, as_of: str | None) -> None:
    if dataset not in {"synthetic_demo", "live_public"}:
        raise ValueError("dataset must be 'synthetic_demo' or 'live_public'")
    if as_of is not None:
        _parse_timestamp(as_of)


def _parse_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("as_of and relationship timestamps must be ISO-8601") from exc
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _row_data(row: Any) -> dict[str, Any]:
    if hasattr(row, "data"):
        return row.data()
    if isinstance(row, Mapping):
        return dict(row)
    return dict(row)


def _evidence_ids(
    resolver: EvidenceResolver,
    relationship_ids: list[str],
    dataset: str,
) -> list[str]:
    result: set[str] = set()
    for relationship_id in relationship_ids:
        evidence: list[Evidence] = resolver.for_relationship(relationship_id)
        if not evidence:
            raise RuntimeError(f"No evidence resolved for relationship {relationship_id!r}")
        for item in evidence:
            if item.dataset != dataset:
                raise RuntimeError("Evidence resolver returned an item from a different dataset")
            result.add(item.evidence_id)
    return sorted(result)


def _candidate_windows(
    dated_relationships: list[tuple[datetime, dict[str, Any]]],
) -> dict[tuple[str, ...], tuple[list[dict[str, Any]], datetime, datetime]]:
    best_by_entities: dict[
        tuple[str, ...], tuple[list[dict[str, Any]], datetime, datetime]
    ] = {}
    max_span = timedelta(hours=WINDOW_HOURS)

    for left, (window_start, _) in enumerate(dated_relationships):
        right = left
        while (
            right < len(dated_relationships)
            and dated_relationships[right][0] - window_start <= max_span
        ):
            right += 1
        window_rows = [row for _, row in dated_relationships[left:right]]
        graph = nx.Graph()
        for row in window_rows:
            graph.add_edge(row["from_entity_id"], row["to_entity_id"])

        for component in nx.connected_components(graph):
            component_rows = [
                row
                for row in window_rows
                if row["from_entity_id"] in component and row["to_entity_id"] in component
            ]
            if len(component_rows) < MIN_RELATIONSHIPS or len(component) < MIN_ENTITIES:
                continue

            entity_ids = tuple(sorted(component))
            start = min(_parse_timestamp(row["valid_from"]) for row in component_rows)
            end = max(_parse_timestamp(row["valid_from"]) for row in component_rows)
            existing = best_by_entities.get(entity_ids)
            if existing is None or (len(component_rows), -(end - start).total_seconds(), -start.timestamp()) > (
                len(existing[0]),
                -(existing[2] - existing[1]).total_seconds(),
                -existing[1].timestamp(),
            ):
                best_by_entities[entity_ids] = (component_rows, start, end)

    return best_by_entities


class TemporalConvergenceRule:
    """Flag connected groups with several relationships in a 24-hour window."""

    rule_id = RULE_ID
    rule_name = RULE_NAME

    def __init__(self, resolver: EvidenceResolver = evidence_resolver) -> None:
        self._resolver = resolver

    def evaluate(self, dataset: str, as_of: str | None) -> list[Finding]:
        _validate_scope(dataset, as_of)
        temporal_filter = build_as_of_filter(as_of, rel_alias="r")
        conditions = [
            "r.dataset = $dataset",
            "from_n.dataset = $dataset",
            "to_n.dataset = $dataset",
        ]
        if temporal_filter.relationship_where:
            conditions.append(temporal_filter.relationship_where)
        query = f"""
        MATCH (from_n)-[r:{DOMAIN_RELATIONSHIP_TYPES}]->(to_n)
        WHERE {' AND '.join(conditions)}
        RETURN
            r.relationship_id AS relationship_id,
            r.dataset AS dataset,
            type(r) AS relationship_type,
            r.valid_from AS valid_from,
            from_n.entity_id AS from_entity_id,
            to_n.entity_id AS to_entity_id
        ORDER BY r.valid_from, r.relationship_id
        """
        params = {"dataset": dataset, **temporal_filter.params}
        with get_session() as session:
            rows = [_row_data(row) for row in session.run(query, params)]

        dated_relationships: list[tuple[datetime, dict[str, Any]]] = []
        seen_ids: set[str] = set()
        for row in rows:
            if row.get("dataset") != dataset:
                raise ValueError("Relationship belongs to a different dataset")
            relationship_id = row.get("relationship_id")
            from_id = row.get("from_entity_id")
            to_id = row.get("to_entity_id")
            valid_from = row.get("valid_from")
            relationship_type = row.get("relationship_type")
            if not all(isinstance(value, str) and value for value in (
                relationship_id, from_id, to_id, valid_from, relationship_type
            )):
                raise ValueError("Graph relationship is missing a required field")
            if relationship_id in seen_ids:
                continue
            if from_id == to_id:
                continue
            dated_relationships.append((_parse_timestamp(valid_from), row))
            seen_ids.add(relationship_id)

        dated_relationships.sort(key=lambda item: (item[0], item[1]["relationship_id"]))
        candidates = _candidate_windows(dated_relationships)
        detected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        findings: list[Finding] = []
        for entity_ids, (component_rows, start, end) in sorted(candidates.items()):
            relationship_ids = sorted({row["relationship_id"] for row in component_rows})
            evidence_ids = _evidence_ids(self._resolver, relationship_ids, dataset)
            elapsed_hours = (end - start).total_seconds() / 3600
            findings.append(
                Finding(
                    finding_id=str(uuid.uuid4()),
                    dataset=dataset,
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    subject_entity_ids=list(entity_ids),
                    subject_relationship_ids=relationship_ids,
                    explanation=(
                        f"{len(relationship_ids)} relationships among {len(entity_ids)} entities occurred "
                        f"within {elapsed_hours:g} hours, inside the {WINDOW_HOURS}-hour convergence window."
                    ),
                    triggering_values={
                        "relationship_count": len(relationship_ids),
                        "entity_count": len(entity_ids),
                        "window_hours": WINDOW_HOURS,
                        "window_start": start.isoformat().replace("+00:00", "Z"),
                        "window_end": end.isoformat().replace("+00:00", "Z"),
                        "relationship_types": sorted({row["relationship_type"] for row in component_rows}),
                    },
                    evidence_ids=evidence_ids,
                    disclaimer=INVESTIGATIVE_LEAD_DISCLAIMER,
                    detected_at=detected_at,
                )
            )

        return findings
