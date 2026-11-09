"""D3 bridge-entity rule using D1 analytics output."""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from app.analytics.service import AnalyticsService
from app.contracts.analytics import AnalyticsRequest
from app.contracts.evidence import Evidence
from app.contracts.finding import Finding, INVESTIGATIVE_LEAD_DISCLAIMER
from app.evidence.resolver import EvidenceResolver, evidence_resolver
from app.graph.connection import get_session
from app.graph.queries import build_as_of_filter

logger = logging.getLogger(__name__)

RULE_ID = "bridge_entity_v1"
RULE_NAME = "Bridge Entity"
DOMAIN_RELATIONSHIP_TYPES = (
    "CALLED|OWNS|USED|TRANSFERRED|VISITED|MET|WORKS_FOR|"
    "ASSOCIATED_WITH|MENTIONED_IN|PART_OF"
)


def _validate_scope(dataset: str, as_of: str | None) -> None:
    if dataset not in {"synthetic_demo", "live_public"}:
        raise ValueError("dataset must be 'synthetic_demo' or 'live_public'")
    if as_of is not None:
        try:
            datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("as_of must be ISO-8601") from exc


def _row_data(row: Any) -> dict[str, Any]:
    if hasattr(row, "data"):
        return row.data()
    if isinstance(row, Mapping):
        return dict(row)
    return dict(row)


def _check_evidence_dataset(evidence: list[Evidence], dataset: str, subject: str) -> set[str]:
    if not evidence:
        raise RuntimeError(f"No evidence resolved for {subject}")
    result: set[str] = set()
    for item in evidence:
        if item.dataset != dataset:
            raise RuntimeError("Evidence resolver returned an item from a different dataset")
        result.add(item.evidence_id)
    return result


class BridgeEntityRule:
    """Flag nodes with positive D1 betweenness in a D1-assigned community."""

    rule_id = RULE_ID
    rule_name = RULE_NAME

    def __init__(
        self,
        analytics_service: AnalyticsService | None = None,
        resolver: EvidenceResolver = evidence_resolver,
    ) -> None:
        self._analytics_service = analytics_service or AnalyticsService()
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
            r.valid_to AS valid_to,
            from_n.entity_id AS from_entity_id,
            to_n.entity_id AS to_entity_id
        ORDER BY r.valid_from, r.relationship_id
        """
        params = {"dataset": dataset, **temporal_filter.params}
        with get_session() as session:
            relationships = [_row_data(row) for row in session.run(query, params)]

        incident_relationships: dict[str, set[str]] = {}
        for relationship in relationships:
            if relationship.get("dataset") != dataset:
                raise ValueError("Relationship belongs to a different dataset")
            relationship_id = relationship.get("relationship_id")
            from_id = relationship.get("from_entity_id")
            to_id = relationship.get("to_entity_id")
            valid_from = relationship.get("valid_from")
            relationship_type = relationship.get("relationship_type")
            if not all(
                isinstance(value, str) and value
                for value in (relationship_id, from_id, to_id, valid_from, relationship_type)
            ):
                raise ValueError("Graph relationship is missing a required identifier")
            incident_relationships.setdefault(from_id, set()).add(relationship_id)
            incident_relationships.setdefault(to_id, set()).add(relationship_id)

        request = AnalyticsRequest(
            dataset=dataset,
            as_of=as_of,
            algorithms=["betweenness", "community"],
        )
        analytics_result, _ = self._analytics_service.compute(
            request,
            relationships=relationships,
        )
        if analytics_result.dataset != dataset or analytics_result.as_of != as_of:
            raise ValueError("D1 returned analytics for a different dataset or as_of scope")

        communities = {entry.entity_id: entry.community_id for entry in analytics_result.communities}
        findings: list[Finding] = []
        detected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for entry in analytics_result.centrality:
            score = entry.betweenness
            community_id = communities.get(entry.entity_id)
            if not math.isfinite(score) or score <= 0 or community_id is None:
                continue
            relationship_ids = sorted(incident_relationships.get(entry.entity_id, set()))
            if not relationship_ids:
                continue

            evidence_ids = _check_evidence_dataset(
                self._resolver.for_entity(entry.entity_id), dataset, f"entity {entry.entity_id!r}"
            )
            for relationship_id in relationship_ids:
                evidence_ids.update(
                    _check_evidence_dataset(
                        self._resolver.for_relationship(relationship_id),
                        dataset,
                        f"relationship {relationship_id!r}",
                    )
                )

            findings.append(
                Finding(
                    finding_id=str(uuid.uuid4()),
                    dataset=dataset,
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    subject_entity_ids=[entry.entity_id],
                    subject_relationship_ids=relationship_ids,
                    explanation=(
                        f"{entry.entity_id} has betweenness centrality {score:.3f} and belongs to "
                        f"community {community_id}, placing it on shortest paths through the graph."
                    ),
                    triggering_values={
                        "betweenness": score,
                        "community_id": community_id,
                        "minimum_betweenness": 0.0,
                    },
                    evidence_ids=sorted(evidence_ids),
                    disclaimer=INVESTIGATIVE_LEAD_DISCLAIMER,
                    detected_at=detected_at,
                )
            )

        return findings
