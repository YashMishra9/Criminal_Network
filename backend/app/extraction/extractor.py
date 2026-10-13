"""Extraction orchestrator — B5, DOC3 §4.

Task B5 (partial, non-LLM path):
    Combines RegexExtractor (structured identifiers) and SpacyExtractor
    (NER over free text) into a single ExtractionResult per RawRecord.

Key constraints (DOC3 §4, B5 §11–§17):
  - Stateless per record: no access to other records or the graph.
  - entity_type values match exactly the DOC3 §1.3 enum (excludes Case).
  - record_id and dataset are carried forward unchanged on every mention.
  - Functions fully without the LLM (Contract Invariant 4).
  - Deduplication: if regex and spaCy both find the same raw_text+entity_type,
    only one mention is retained (regex preferred for having a normalized_value).

The LLM path (B6) plugs into this orchestrator by populating additional
mentions with extraction_method='llm' and is handled by a separate module.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from app.contracts.mention import EntityMention, RelationshipMention
from app.contracts.raw_record import RawRecord
from app.extraction.regex_extractor import RegexExtractor
from app.extraction.spacy_extractor import SpacyExtractor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ExtractionResult — DOC3 §4 output contract
# ---------------------------------------------------------------------------

@dataclass
class ExtractionResult:
    """Output of one extraction run over a single RawRecord. DOC3 §4."""

    record_id: str
    """The RawRecord.record_id this result came from."""

    entities: List[EntityMention] = field(default_factory=list)
    """All entity mentions extracted from this record."""

    relationships: List[RelationshipMention] = field(default_factory=list)
    """All relationship mentions extracted from this record."""


# ---------------------------------------------------------------------------
# Extractor — orchestrates regex + spaCy (non-LLM path)
# ---------------------------------------------------------------------------

class Extractor:
    """Stateless per-record extraction orchestrator.

    Runs RegexExtractor and SpacyExtractor in sequence, merges their outputs,
    deduplicates overlapping mentions, and returns an ExtractionResult.

    The Extractor is the IngestionOrchestrator's consumer callback target
    (via a thin wrapper) — see B4's RecordConsumer type.

    LLM extension point (B6):
        An optional llm_extractor can be injected at construction time. When
        present, it is called after regex+spaCy and may add extra mentions
        with extraction_method='llm'. When absent, the pipeline is fully
        LLM-free (Contract Invariant 4).
    """

    def __init__(self, llm_extractor=None) -> None:
        """Initialise the extractor.

        Args:
            llm_extractor: Optional LLM-based extractor (B6). Must expose an
                           extract(record, existing_entities) → (entities, rels)
                           interface. Pass None to run fully without the LLM.
        """
        self._regex = RegexExtractor()
        self._spacy = SpacyExtractor()
        self._llm = llm_extractor

    def extract_one(self, record: RawRecord) -> ExtractionResult:
        """Extract entities and relationships from one RawRecord.

        Stateless — no cross-record or graph state is read or written.

        Args:
            record: one RawRecord from any adapter.

        Returns:
            ExtractionResult with deduplicated entities and relationships.
        """
        # 1. Regex extraction (structured identifiers)
        regex_entities, regex_rels = self._regex.extract(record)

        # 2. spaCy NER (free-text NER over payload_text)
        spacy_entities, spacy_rels = self._spacy.extract(record)

        # 3. Merge and deduplicate
        entities = self._merge_entities(regex_entities, spacy_entities)
        relationships = list(regex_rels) + list(spacy_rels)

        # 4. LLM augmentation (optional, B6)
        if self._llm is not None:
            try:
                llm_entities, llm_rels = self._llm.extract(record, entities)
                entities = self._merge_entities(entities, llm_entities)
                relationships.extend(llm_rels)
            except Exception as exc:  # noqa: BLE001 — LLM must never block
                logger.warning(
                    "LLM extractor failed for record '%s' (skipping): %s",
                    record.record_id, exc,
                )

        # 5. Enforce provenance: every mention must carry record_id + dataset
        for em in entities:
            assert em.record_id == record.record_id, (
                f"Mention {em.mention_id} has wrong record_id: "
                f"{em.record_id!r} != {record.record_id!r}"
            )
            assert em.dataset == record.dataset, (
                f"Mention {em.mention_id} has wrong dataset: "
                f"{em.dataset!r} != {record.dataset!r}"
            )

        logger.debug(
            "Extracted from '%s' (%s): %d entities, %d relationships",
            record.record_id, record.source_type, len(entities), len(relationships),
        )
        return ExtractionResult(
            record_id=record.record_id,
            entities=entities,
            relationships=relationships,
        )

    def extract_batch(self, records: List[RawRecord]) -> List[ExtractionResult]:
        """Extract from a list of records, one at a time (stateless).

        This is the B4 RecordConsumer-compatible entry point.

        Args:
            records: list of RawRecord objects from the Ingestion Orchestrator.

        Returns:
            List of ExtractionResult, one per input record.
        """
        results = []
        for record in records:
            try:
                results.append(self.extract_one(record))
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Extraction failed for record '%s': %s — skipping.",
                    record.record_id, exc,
                )
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_entities(
        primary: List[EntityMention],
        secondary: List[EntityMention],
    ) -> List[EntityMention]:
        """Merge secondary mentions into primary, deduplicating by (entity_type, raw_text).

        Regex mentions are preferred when both methods produce the same entity
        because regex gives a normalized_value; spaCy's mention is dropped in
        that case. This is a simple deduplication — full resolution happens
        downstream in B7.

        Args:
            primary:   mentions from the higher-priority extractor.
            secondary: mentions to merge in if not already present.

        Returns:
            Merged, deduplicated list.
        """
        seen: set = set()
        merged = list(primary)
        for em in primary:
            seen.add((em.entity_type, em.raw_text.lower()))

        for em in secondary:
            key = (em.entity_type, em.raw_text.lower())
            if key not in seen:
                seen.add(key)
                merged.append(em)

        return merged


# ---------------------------------------------------------------------------
# Factory: wires B5 + B6 together (recommended construction path)
# ---------------------------------------------------------------------------

def build_extractor(with_llm: bool = True) -> "Extractor":
    """Factory: return a fully-wired Extractor (B5 + optional B6).

    Args:
        with_llm: When True (default), attaches an LLMExtractor using the
                  configured LLMClient. When False, returns a B5-only
                  Extractor (useful for tests and guaranteed offline mode).

    Returns:
        Configured Extractor instance.
    """
    if not with_llm:
        return Extractor(llm_extractor=None)

    from app.extraction.llm_extractor import LLMExtractor  # lazy — avoids circular at module level
    from app.llm.client import get_llm_client

    llm_extractor = LLMExtractor(llm_client=get_llm_client())
    return Extractor(llm_extractor=llm_extractor)
