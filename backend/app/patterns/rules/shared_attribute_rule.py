"""D2 shared-attribute rule for canonical entities."""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping

from app.contracts.evidence import Evidence
from app.contracts.finding import Finding, INVESTIGATIVE_LEAD_DISCLAIMER
from app.evidence.resolver import EvidenceResolver, evidence_resolver
from app.graph.connection import get_session
from app.graph.queries import build_as_of_filter

logger = logging.getLogger(__name__)

RULE_ID = "shared_attribute_v1"
RULE_NAME = "Shared Identifier Attribute"
SHARED_IDENTIFIER_ATTRIBUTES = frozenset(
    {"phone", "account", "bank_account", "vehicle", "plate", "pan", "dl", "dob"}
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


def _attributes(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring malformed entity attributes_json")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_value(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    normalized = str(value).strip().casefold()
    return normalized or None


class SharedAttributeRule:
    """Find distinct canonical entities sharing a supported identifier value."""

    rule_id = RULE_ID
    rule_name = RULE_NAME

    def __init__(self, resolver: EvidenceResolver = evidence_resolver) -> None:
        self._resolver = resolver

    def evaluate(self, dataset: str, as_of: str | None) -> list[Finding]:
        _validate_scope(dataset, as_of)
        temporal_filter = build_as_of_filter(as_of, entity_alias="n", rel_alias="r")
        conditions = ["n.entity_id IS NOT NULL", "n.dataset = $dataset"]
        if temporal_filter.entity_subquery:
            conditions.append(temporal_filter.entity_subquery)
        query = f"""
        MATCH (n)
        WHERE {' AND '.join(conditions)}
        RETURN
            n.entity_id AS entity_id,
            n.dataset AS dataset,
            n.display_name AS display_name,
            n.attributes_json AS attributes_json
        ORDER BY n.entity_id
        """
        params = {"dataset": dataset, **temporal_filter.params}

        with get_session() as session:
            rows = [_row_data(row) for row in session.run(query, params)]

        shared_values: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in rows:
            if row.get("dataset") != dataset:
                raise ValueError("Canonical entity belongs to a different dataset")
            entity_id = row.get("entity_id")
            if not isinstance(entity_id, str) or not entity_id:
                raise ValueError("Canonical entity is missing entity_id")
            attributes = _attributes(row.get("attributes_json"))
            for attribute_name, value in attributes.items():
                normalized_name = str(attribute_name).strip().casefold()
                if normalized_name not in SHARED_IDENTIFIER_ATTRIBUTES:
                    continue
                normalized_value = _normalize_value(value)
                if normalized_value is None:
                    continue
                shared_values[(normalized_name, normalized_value)].setdefault(
                    entity_id,
                    {"entity_id": entity_id, "display_name": row.get("display_name") or entity_id},
                )

        findings: list[Finding] = []
        detected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for (attribute_name, normalized_value), entity_map in sorted(shared_values.items()):
            if len(entity_map) < 2:
                continue
            subject_entities = sorted(entity_map)
            evidence_ids: set[str] = set()
            for entity_id in subject_entities:
                evidence: list[Evidence] = self._resolver.for_entity(entity_id)
                if not evidence:
                    raise RuntimeError(f"No evidence resolved for entity {entity_id!r}")
                for item in evidence:
                    if item.dataset != dataset:
                        raise RuntimeError(
                            "Evidence resolver returned an item from a different dataset"
                        )
                    evidence_ids.add(item.evidence_id)

            if not evidence_ids:
                raise RuntimeError("No evidence resolved for shared-attribute finding")
            display_names = [entity_map[entity_id]["display_name"] for entity_id in subject_entities]
            findings.append(
                Finding(
                    finding_id=str(uuid.uuid4()),
                    dataset=dataset,
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    subject_entity_ids=subject_entities,
                    subject_relationship_ids=[],
                    explanation=(
                        f"{len(subject_entities)} entities share the same {attribute_name} attribute: "
                        f"{', '.join(display_names)}."
                    ),
                    triggering_values={
                        "attribute_name": attribute_name,
                        "shared_value": normalized_value,
                        "entity_count": len(subject_entities),
                    },
                    evidence_ids=sorted(evidence_ids),
                    disclaimer=INVESTIGATIVE_LEAD_DISCLAIMER,
                    detected_at=detected_at,
                )
            )

        return findings
