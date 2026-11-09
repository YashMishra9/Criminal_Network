"""D2 frequency rule for unusually frequent calls.

The rule reports call pairs with at least 10 CALLED relationships in any
seven-day window. This uses the concrete example threshold from DOC3 §8.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.contracts.evidence import Evidence
from app.contracts.finding import Finding, INVESTIGATIVE_LEAD_DISCLAIMER
from app.evidence.resolver import EvidenceResolver, evidence_resolver
from app.graph.connection import get_session
from app.graph.queries import build_as_of_filter

logger = logging.getLogger(__name__)

CALL_THRESHOLD = 10
WINDOW_DAYS = 7
RULE_ID = "frequency_rule_v1"
RULE_NAME = "High Call Frequency"


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


def _resolve_evidence(
    resolver: EvidenceResolver,
    relationship_ids: list[str],
    dataset: str,
) -> list[str]:
    evidence_ids: set[str] = set()
    for relationship_id in relationship_ids:
        evidence: list[Evidence] = resolver.for_relationship(relationship_id)
        if not evidence:
            raise RuntimeError(
                f"No evidence resolved for relationship {relationship_id!r}"
            )
        for item in evidence:
            if item.dataset != dataset:
                raise RuntimeError(
                    "Evidence resolver returned an item from a different dataset"
                )
            evidence_ids.add(item.evidence_id)
    return sorted(evidence_ids)


def _best_window(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dated = []
    seen_relationship_ids: set[str] = set()
    for row in rows:
        relationship_id = row.get("relationship_id")
        if not relationship_id or relationship_id in seen_relationship_ids:
            continue
        timestamp_value = row.get("valid_from")
        if not isinstance(timestamp_value, str):
            raise ValueError("CALLED relationship is missing valid_from")
        dated.append((_parse_timestamp(timestamp_value), row))
        seen_relationship_ids.add(relationship_id)

    dated.sort(key=lambda item: (item[0], item[1]["relationship_id"]))
    best_window: list[dict[str, Any]] = []
    left = 0
    window = timedelta(days=WINDOW_DAYS)

    for right, (end, _) in enumerate(dated):
        while end - dated[left][0] > window:
            left += 1
        current_window = [row for _, row in dated[left : right + 1]]
        if len(current_window) > len(best_window):
            best_window = current_window

    return best_window


class FrequencyRule:
    """Detect call pairs meeting the transparent 10-call/7-day threshold."""

    rule_id = RULE_ID
    rule_name = RULE_NAME

    def __init__(self, resolver: EvidenceResolver = evidence_resolver) -> None:
        self._resolver = resolver

    def evaluate(self, dataset: str, as_of: str | None) -> list[Finding]:
        _validate_scope(dataset, as_of)
        temporal_filter = build_as_of_filter(as_of, rel_alias="r")
        conditions = ["r.dataset = $dataset", "from_n.dataset = $dataset", "to_n.dataset = $dataset"]
        if temporal_filter.relationship_where:
            conditions.append(temporal_filter.relationship_where)
        query = f"""
        MATCH (from_n)-[r:CALLED]->(to_n)
        WHERE {' AND '.join(conditions)}
        RETURN
            r.relationship_id AS relationship_id,
            r.dataset AS dataset,
            r.valid_from AS valid_from,
            from_n.entity_id AS from_entity_id,
            from_n.display_name AS from_display_name,
            to_n.entity_id AS to_entity_id,
            to_n.display_name AS to_display_name
        ORDER BY r.valid_from, r.relationship_id
        """
        params = {"dataset": dataset, **temporal_filter.params}

        with get_session() as session:
            rows = [_row_data(row) for row in session.run(query, params)]

        pairs: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            if row.get("dataset") != dataset:
                raise ValueError("CALLED relationship belongs to a different dataset")
            from_id = row.get("from_entity_id")
            to_id = row.get("to_entity_id")
            if not isinstance(from_id, str) or not from_id or not isinstance(to_id, str) or not to_id:
                raise ValueError("CALLED relationship is missing an endpoint entity_id")
            if from_id == to_id:
                continue
            pair = tuple(sorted((from_id, to_id)))
            pairs.setdefault(pair, []).append(row)

        findings: list[Finding] = []
        detected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for entity_ids, pair_rows in sorted(pairs.items()):
            window_rows = _best_window(pair_rows)
            call_count = len(window_rows)
            if call_count < CALL_THRESHOLD:
                continue

            relationship_ids = sorted({row["relationship_id"] for row in window_rows})
            evidence_ids = _resolve_evidence(self._resolver, relationship_ids, dataset)
            first = window_rows[0]
            names_by_id = {
                first["from_entity_id"]: first.get("from_display_name") or first["from_entity_id"],
                first["to_entity_id"]: first.get("to_display_name") or first["to_entity_id"],
            }
            start = min(_parse_timestamp(row["valid_from"]) for row in window_rows)
            end = max(_parse_timestamp(row["valid_from"]) for row in window_rows)
            elapsed_days = (end - start).total_seconds() / 86400
            subject_names = " and ".join(names_by_id.get(entity_id, entity_id) for entity_id in entity_ids)
            explanation = (
                f"{call_count} calls between {subject_names} over {elapsed_days:g} days, "
                f"meeting the {CALL_THRESHOLD}-call/{WINDOW_DAYS}-day threshold."
            )
            findings.append(
                Finding(
                    finding_id=str(uuid.uuid4()),
                    dataset=dataset,
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    subject_entity_ids=list(entity_ids),
                    subject_relationship_ids=relationship_ids,
                    explanation=explanation,
                    triggering_values={
                        "call_count": call_count,
                        "threshold": CALL_THRESHOLD,
                        "window_days": WINDOW_DAYS,
                        "window_start": start.isoformat().replace("+00:00", "Z"),
                        "window_end": end.isoformat().replace("+00:00", "Z"),
                    },
                    evidence_ids=evidence_ids,
                    disclaimer=INVESTIGATIVE_LEAD_DISCLAIMER,
                    detected_at=detected_at,
                )
            )

        return findings
