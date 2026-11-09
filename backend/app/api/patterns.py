"""Read-only Patterns API route for persisted Findings (DOC3 §12.6)."""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter
from neo4j.exceptions import AuthError, ServiceUnavailable

from app.api.graph import get_graph as get_graph_snapshot
from app.contracts.errors import GraphUnavailableError, InternalError, ValidationError
from app.contracts.finding import Finding, INVESTIGATIVE_LEAD_DISCLAIMER
from app.graph.connection import get_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/patterns", tags=["patterns"])

_DATASETS = frozenset({"synthetic_demo", "live_public"})

_FINDINGS_QUERY = """
MATCH (finding:Finding)
WHERE finding.dataset = $dataset
RETURN
    finding.finding_id AS finding_id,
    finding.dataset AS dataset,
    finding.rule_id AS rule_id,
    finding.rule_name AS rule_name,
    finding.subject_entity_ids AS subject_entity_ids,
    finding.subject_relationship_ids AS subject_relationship_ids,
    finding.explanation AS explanation,
    finding.triggering_values_json AS triggering_values_json,
    finding.evidence_ids AS evidence_ids,
    finding.disclaimer AS disclaimer,
    finding.detected_at AS detected_at
ORDER BY finding.detected_at DESC, finding.finding_id
"""


def _validate_scope(dataset: str, as_of: Optional[str]) -> None:
    if dataset not in _DATASETS:
        raise ValidationError("dataset must be 'synthetic_demo' or 'live_public'")
    if as_of is not None:
        try:
            datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValidationError("as_of must be an ISO-8601 timestamp") from exc


def _row_to_finding(record: Any, dataset: str) -> Finding:
    if record.get("dataset") != dataset:
        raise InternalError("Stored Finding belongs to a different dataset")
    if not record.get("evidence_ids"):
        raise InternalError("Stored Finding has no supporting evidence")
    if record.get("disclaimer") != INVESTIGATIVE_LEAD_DISCLAIMER:
        raise InternalError("Stored Finding has an invalid investigative-lead disclaimer")

    raw_triggering_values = record.get("triggering_values_json")
    try:
        triggering_values = (
            json.loads(raw_triggering_values)
            if isinstance(raw_triggering_values, str)
            else raw_triggering_values
        )
    except (TypeError, ValueError) as exc:
        raise InternalError("Stored Finding has invalid triggering values") from exc
    if not isinstance(triggering_values, dict):
        raise InternalError("Stored Finding triggering values must be an object")

    try:
        return Finding(
            finding_id=record["finding_id"],
            dataset=dataset,
            rule_id=record["rule_id"],
            rule_name=record["rule_name"],
            subject_entity_ids=list(record["subject_entity_ids"] or []),
            subject_relationship_ids=list(record["subject_relationship_ids"] or []),
            explanation=record["explanation"],
            triggering_values=triggering_values,
            evidence_ids=list(record["evidence_ids"]),
            disclaimer=record["disclaimer"],
            detected_at=record["detected_at"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InternalError("Stored Finding does not match the DOC3 contract") from exc


@router.get("")
async def get_patterns(
    dataset: str = "synthetic_demo",
    as_of: Optional[str] = None,
) -> dict[str, list[Finding]]:
    """Return persisted findings; never runs the pattern detection engine."""
    _validate_scope(dataset, as_of)

    visible_entity_ids: set[str] | None = None
    visible_relationship_ids: set[str] | None = None
    if as_of is not None:
        snapshot = await get_graph_snapshot(dataset=dataset, as_of=as_of)
        visible_entity_ids = {entity.entity_id for entity in snapshot["entities"]}
        visible_relationship_ids = {
            relationship.relationship_id for relationship in snapshot["relationships"]
        }

    try:
        with get_session() as session:
            rows = list(session.run(_FINDINGS_QUERY, {"dataset": dataset}))
    except (ServiceUnavailable, AuthError, OSError) as exc:
        logger.warning("Neo4j unavailable in get_patterns: %s", exc)
        raise GraphUnavailableError(
            "Neo4j graph is unavailable. Try again later.",
            details={"original_error": str(exc)},
        ) from exc

    findings: list[Finding] = []
    for row in rows:
        finding = _row_to_finding(row, dataset)
        if as_of is not None:
            assert visible_entity_ids is not None
            assert visible_relationship_ids is not None
            if not set(finding.subject_entity_ids).issubset(visible_entity_ids):
                continue
            if not set(finding.subject_relationship_ids).issubset(visible_relationship_ids):
                continue
        findings.append(finding)

    return {"findings": findings}
