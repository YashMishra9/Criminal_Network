"""D4 — Pattern Detection Engine and Finding persistence."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Iterable, Protocol

from app.contracts.finding import Finding, INVESTIGATIVE_LEAD_DISCLAIMER
from app.graph.connection import get_session
from app.patterns.rules.bridge_entity_rule import BridgeEntityRule
from app.patterns.rules.frequency_rule import FrequencyRule
from app.patterns.rules.shared_attribute_rule import SharedAttributeRule
from app.patterns.rules.temporal_convergence_rule import TemporalConvergenceRule

logger = logging.getLogger(__name__)

_DATASETS = frozenset({"synthetic_demo", "live_public"})


class _PatternRule(Protocol):
    rule_id: str
    rule_name: str

    def evaluate(self, dataset: str, as_of: str | None) -> list[Finding]: ...


DEFAULT_RULES: tuple[_PatternRule, ...] = (
    FrequencyRule(),
    SharedAttributeRule(),
    BridgeEntityRule(),
    TemporalConvergenceRule(),
)


_EVIDENCE_IDS_QUERY = """
MATCH (ev:Evidence)
WHERE ev.evidence_id IN $ids AND ev.dataset = $dataset
RETURN collect(DISTINCT ev.evidence_id) AS ids
"""

_ENTITY_IDS_QUERY = """
MATCH (entity)
WHERE entity.entity_id IN $ids AND entity.dataset = $dataset
RETURN collect(DISTINCT entity.entity_id) AS ids
"""

_EDGE_REF_IDS_QUERY = """
MATCH (edge_ref:EdgeRef)
WHERE edge_ref.relationship_id IN $ids AND edge_ref.dataset = $dataset
RETURN collect(DISTINCT edge_ref.relationship_id) AS ids
"""

_UPSERT_FINDING_QUERY = """
MERGE (finding:Finding {
    rule_id: $rule_id,
    dataset: $dataset,
    subject_entity_ids: $subject_entity_ids,
    subject_relationship_ids: $subject_relationship_ids
})
ON CREATE SET finding.finding_id = $candidate_finding_id
SET
    finding.rule_name = $rule_name,
    finding.explanation = $explanation,
    finding.triggering_values_json = $triggering_values_json,
    finding.evidence_ids = $evidence_ids,
    finding.disclaimer = $disclaimer,
    finding.detected_at = $detected_at
RETURN finding.finding_id AS finding_id
"""

_DELETE_STALE_SUPPORT_QUERY = """
MATCH (old_evidence:Evidence)-[support:SUPPORTS]->(finding:Finding {
    finding_id: $finding_id,
    dataset: $dataset
})
WHERE old_evidence.dataset <> $dataset
   OR NOT old_evidence.evidence_id IN $evidence_ids
DELETE support
"""

_LINK_ENTITIES_QUERY = """
MATCH (finding:Finding {finding_id: $finding_id, dataset: $dataset})
UNWIND $ids AS entity_id
MATCH (entity)
WHERE entity.entity_id = entity_id AND entity.dataset = $dataset
MERGE (finding)-[:CONCERNS]->(entity)
"""

_LINK_EDGE_REFS_QUERY = """
MATCH (finding:Finding {finding_id: $finding_id, dataset: $dataset})
UNWIND $ids AS relationship_id
MATCH (edge_ref:EdgeRef)
WHERE edge_ref.relationship_id = relationship_id AND edge_ref.dataset = $dataset
MERGE (finding)-[:CONCERNS]->(edge_ref)
"""

_LINK_EVIDENCE_QUERY = """
MATCH (finding:Finding {finding_id: $finding_id, dataset: $dataset})
UNWIND $ids AS evidence_id
MATCH (evidence:Evidence)
WHERE evidence.evidence_id = evidence_id AND evidence.dataset = $dataset
MERGE (evidence)-[:SUPPORTS]->(finding)
"""


def _validate_scope(dataset: str, as_of: str | None) -> None:
    if dataset not in _DATASETS:
        raise ValueError("dataset must be 'synthetic_demo' or 'live_public'")
    if as_of is not None:
        try:
            datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("as_of must be ISO-8601") from exc


def _sorted_unique_ids(values: Iterable[str], field: str) -> list[str]:
    ids = list(values)
    if any(not isinstance(value, str) or not value for value in ids):
        raise ValueError(f"{field} must contain non-empty string IDs")
    return sorted(set(ids))


def _normalized_finding(finding: Finding, dataset: str | None = None) -> Finding:
    if not finding.finding_id:
        raise ValueError("finding_id must not be empty")
    if finding.dataset not in _DATASETS:
        raise ValueError("Finding dataset must be 'synthetic_demo' or 'live_public'")
    if dataset is not None and finding.dataset != dataset:
        raise ValueError("Finding belongs to a different dataset than the detection run")
    if not finding.evidence_ids:
        raise ValueError("A Finding must have at least one evidence_id")
    if finding.disclaimer != INVESTIGATIVE_LEAD_DISCLAIMER:
        raise ValueError("Finding disclaimer does not match the DOC3 fixed literal")
    if not finding.rule_id or not finding.rule_name:
        raise ValueError("Finding rule_id and rule_name must not be empty")

    return finding.model_copy(
        update={
            "subject_entity_ids": _sorted_unique_ids(
                finding.subject_entity_ids, "subject_entity_ids"
            ),
            "subject_relationship_ids": _sorted_unique_ids(
                finding.subject_relationship_ids, "subject_relationship_ids"
            ),
            "evidence_ids": _sorted_unique_ids(finding.evidence_ids, "evidence_ids"),
        }
    )


def _record_ids(transaction: Any, query: str, ids: list[str], dataset: str) -> set[str]:
    record = transaction.run(query, {"ids": ids, "dataset": dataset}).single()
    return set(record["ids"] or []) if record else set()


def _validate_references(transaction: Any, finding: Finding) -> None:
    dataset = finding.dataset
    expected_references = (
        (_EVIDENCE_IDS_QUERY, finding.evidence_ids, "Evidence"),
        (_ENTITY_IDS_QUERY, finding.subject_entity_ids, "CanonicalEntity"),
        (_EDGE_REF_IDS_QUERY, finding.subject_relationship_ids, "EdgeRef"),
    )
    for query, ids, label in expected_references:
        matched_ids = _record_ids(transaction, query, ids, dataset)
        if matched_ids != set(ids):
            missing_ids = sorted(set(ids) - matched_ids)
            raise ValueError(
                f"Finding references missing or cross-dataset {label} IDs: {missing_ids}"
            )


def _upsert_finding_transaction(transaction: Any, finding: Finding) -> str:
    _validate_references(transaction, finding)
    params = {
        "candidate_finding_id": finding.finding_id,
        "rule_id": finding.rule_id,
        "rule_name": finding.rule_name,
        "dataset": finding.dataset,
        "subject_entity_ids": finding.subject_entity_ids,
        "subject_relationship_ids": finding.subject_relationship_ids,
        "explanation": finding.explanation,
        "triggering_values_json": json.dumps(finding.triggering_values, sort_keys=True),
        "evidence_ids": finding.evidence_ids,
        "disclaimer": INVESTIGATIVE_LEAD_DISCLAIMER,
        "detected_at": finding.detected_at,
    }
    record = transaction.run(_UPSERT_FINDING_QUERY, params).single()
    if not record or not record.get("finding_id"):
        raise RuntimeError("Finding upsert did not return a finding_id")
    persisted_id = record["finding_id"]
    link_params = {"finding_id": persisted_id, "dataset": finding.dataset}

    transaction.run(
        _DELETE_STALE_SUPPORT_QUERY,
        {**link_params, "evidence_ids": finding.evidence_ids},
    ).consume()
    if finding.subject_entity_ids:
        transaction.run(
            _LINK_ENTITIES_QUERY,
            {**link_params, "ids": finding.subject_entity_ids},
        ).consume()
    if finding.subject_relationship_ids:
        transaction.run(
            _LINK_EDGE_REFS_QUERY,
            {**link_params, "ids": finding.subject_relationship_ids},
        ).consume()
    transaction.run(
        _LINK_EVIDENCE_QUERY,
        {**link_params, "ids": finding.evidence_ids},
    ).consume()
    return persisted_id


def persist_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Upsert Findings by the DOC3 §1.8 identity key and return stable IDs."""
    normalized = [_normalized_finding(finding) for finding in findings]
    if not normalized:
        return []
    datasets = {finding.dataset for finding in normalized}
    if len(datasets) != 1:
        raise ValueError("A persistence batch must contain exactly one dataset")

    persisted: list[Finding] = []
    with get_session() as session:
        for finding in normalized:
            persisted_id = session.execute_write(_upsert_finding_transaction, finding)
            persisted.append(finding.model_copy(update={"finding_id": persisted_id}))
    return persisted


class PatternDetectionEngine:
    """Run independent rules for one dataset/as_of scope, then persist results."""

    def __init__(self, rules: Iterable[_PatternRule] | None = None) -> None:
        self._rules = tuple(DEFAULT_RULES if rules is None else rules)

    def run(self, dataset: str, as_of: str | None = None) -> list[Finding]:
        _validate_scope(dataset, as_of)
        findings: list[Finding] = []
        for rule in self._rules:
            findings.extend(rule.evaluate(dataset, as_of))
        return persist_findings(findings)


__all__ = ["PatternDetectionEngine", "persist_findings"]
