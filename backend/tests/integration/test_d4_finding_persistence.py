"""D4 integration test for Finding upsert idempotency against Neo4j."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("NEO4J_INTEGRATION_TEST", "").lower() != "true",
    reason="Set NEO4J_INTEGRATION_TEST=true to run Finding persistence integration tests",
)


class _RepeatedFindingRule:
    rule_id = "d4_integration_rule_v1"
    rule_name = "D4 Integration Fixture"

    def __init__(self, entity_id: str, evidence_id: str) -> None:
        self._entity_id = entity_id
        self._evidence_id = evidence_id

    def evaluate(self, dataset: str, as_of: str | None):
        from app.contracts.finding import Finding, INVESTIGATIVE_LEAD_DISCLAIMER

        return [
            Finding(
                finding_id=str(uuid.uuid4()),
                dataset=dataset,
                rule_id=self.rule_id,
                rule_name=self.rule_name,
                subject_entity_ids=[self._entity_id],
                subject_relationship_ids=[],
                explanation="A stable D4 integration-test pattern.",
                triggering_values={"fixture": True},
                evidence_ids=[self._evidence_id],
                disclaimer=INVESTIGATIVE_LEAD_DISCLAIMER,
                detected_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            )
        ]


def test_two_detection_runs_reuse_finding_id_and_evidence_link():
    from app.contracts.entity import CanonicalEntity
    from app.contracts.evidence import Evidence
    from app.evidence.resolver import EvidenceResolver
    from app.graph.connection import get_session
    from app.graph.write_layer import write_entity, write_evidence
    from app.patterns.engine import PatternDetectionEngine

    entity_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())
    source_id = f"d4_integration_{uuid.uuid4()}"
    dataset = "synthetic_demo"
    persisted_finding_id = None

    try:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        write_entity(
            CanonicalEntity(
                entity_id=entity_id,
                entity_type="Person",
                dataset=dataset,
                display_name="D4 integration fixture",
                attributes={},
                resolved_from=[],
                resolution_method="manual",
                created_at=now,
                updated_at=now,
            )
        )
        write_evidence(
            Evidence(
                evidence_id=evidence_id,
                dataset=dataset,
                source_id=source_id,
                source_type="synthetic",
                record_timestamp=now,
                ingested_at=now,
                snippet="D4 persistence integration fixture",
            )
        )

        engine = PatternDetectionEngine(
            rules=[_RepeatedFindingRule(entity_id=entity_id, evidence_id=evidence_id)]
        )
        first = engine.run(dataset)
        second = engine.run(dataset)

        assert len(first) == len(second) == 1
        assert first[0].finding_id == second[0].finding_id
        persisted_finding_id = first[0].finding_id

        with get_session() as session:
            record = session.run(
                """
                MATCH (finding:Finding {finding_id: $finding_id, dataset: $dataset})
                RETURN count(finding) AS count
                """,
                {"finding_id": persisted_finding_id, "dataset": dataset},
            ).single()
        assert record is not None and record["count"] == 1

        resolved = EvidenceResolver().for_finding(persisted_finding_id)
        assert [item.evidence_id for item in resolved] == [evidence_id]
    finally:
        with get_session() as session:
            if persisted_finding_id is not None:
                session.run(
                    "MATCH (finding:Finding {finding_id: $finding_id}) DETACH DELETE finding",
                    {"finding_id": persisted_finding_id},
                ).consume()
            session.run(
                "MATCH (entity:Person {entity_id: $entity_id}) DETACH DELETE entity",
                {"entity_id": entity_id},
            ).consume()
            session.run(
                "MATCH (evidence:Evidence {evidence_id: $evidence_id}) DETACH DELETE evidence",
                {"evidence_id": evidence_id},
            ).consume()
