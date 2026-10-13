"""spaCy NER extractor — B5, DOC3 §4.

Extracts Person, Organization, Location, and Event mentions using spaCy's
named-entity recognition pipeline. Complements RegexExtractor (which handles
well-formed identifiers). Together they form the non-LLM extraction path
that satisfies Contract Invariant 4.

Graceful degradation (Contract Invariant 4):
    If en_core_web_sm is unavailable, SpacyExtractor falls back to a
    blank spaCy pipeline with no NER component. All callers still receive
    valid (possibly empty) ExtractionResult objects — the pipeline never
    raises or blocks.

DOC2 §7 note on division of labour:
    spaCy handles NER over payload_text (free-form narrative text in FIRs,
    police reports, social media posts, RSS items).
    RegexExtractor handles structured identifiers (phones, vehicles, accounts).
    The Extractor orchestrator (extractor.py) combines both outputs,
    deduplicating by normalized value before returning.
"""

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import spacy
    from spacy.language import Language

    _SPACY_AVAILABLE = True
except ImportError:
    _SPACY_AVAILABLE = False
    logger.warning("spaCy is not installed. SpacyExtractor will produce no mentions.")


# Map spaCy NER label → DOC3 §1.3 entity_type
_LABEL_MAP = {
    "PERSON": "Person",
    "ORG": "Organization",
    "GPE": "Location",      # geo-political entity
    "LOC": "Location",
    "FAC": "Location",      # facility
    "EVENT": "Event",
    "DATE": None,           # ignored at extraction stage
    "TIME": None,
    "MONEY": None,
    "CARDINAL": None,
    "ORDINAL": None,
    "PERCENT": None,
    "QUANTITY": None,
    "NORP": "Organization", # nationalities / religious groups → treat as org
    "PRODUCT": None,
    "WORK_OF_ART": None,
    "LAW": None,
    "LANGUAGE": None,
}

_MODEL_NAME = "en_core_web_sm"


def _load_nlp() -> Optional["Language"]:
    """Load the spaCy model, falling back gracefully if unavailable."""
    if not _SPACY_AVAILABLE:
        return None
    try:
        nlp = spacy.load(_MODEL_NAME)
        logger.info("SpacyExtractor: loaded model '%s'.", _MODEL_NAME)
        return nlp
    except OSError:
        logger.warning(
            "spaCy model '%s' not found. SpacyExtractor will produce no mentions. "
            "Install it with: python -m spacy download %s",
            _MODEL_NAME, _MODEL_NAME,
        )
        try:
            return spacy.blank("en")
        except Exception:
            return None


# Module-level singleton — loaded once
_NLP: Optional["Language"] = None


def _get_nlp() -> Optional["Language"]:
    global _NLP
    if _NLP is None:
        _NLP = _load_nlp()
    return _NLP


# ---------------------------------------------------------------------------
# SpacyExtractor
# ---------------------------------------------------------------------------

from app.contracts.mention import EntityMention, RelationshipMention
from app.contracts.raw_record import RawRecord
from app.extraction.regex_extractor import _make_mention_id  # reuse stable ID helper


class SpacyExtractor:
    """Named-entity extraction over payload_text using spaCy.

    Stateless per record (DOC3 §4). Produces EntityMention objects tagged
    extraction_method='spacy'. Never produces RelationshipMention — that
    requires resolution-level context beyond a single record.

    Falls back transparently (returns empty list) when:
    - spaCy is not installed
    - the model is not downloaded
    - payload_text is None or empty
    """

    def extract(
        self, record: RawRecord
    ) -> Tuple[List[EntityMention], List[RelationshipMention]]:
        """Run spaCy NER over record.payload_text.

        Args:
            record: one RawRecord; processed statelessly.

        Returns:
            (entities, []) — relationships are always empty (NER only).
        """
        text = (record.payload_text or "").strip()
        if not text:
            return [], []

        nlp = _get_nlp()
        if nlp is None:
            return [], []

        try:
            doc = nlp(text)
        except Exception as exc:
            logger.warning(
                "SpacyExtractor: NLP processing failed for record '%s': %s",
                record.record_id, exc,
            )
            return [], []

        entities: List[EntityMention] = []
        seen: set = set()

        for ent in doc.ents:
            entity_type = _LABEL_MAP.get(ent.label_)
            if entity_type is None:
                continue  # label not mapped to a DOC3 §1.3 type

            raw_text = ent.text.strip()
            if not raw_text or raw_text in seen:
                continue
            seen.add(raw_text)

            mention = EntityMention(
                mention_id=_make_mention_id(
                    record.record_id, entity_type, raw_text, len(entities)
                ),
                record_id=record.record_id,
                dataset=record.dataset,
                entity_type=entity_type,  # type: ignore[arg-type]
                raw_text=raw_text,
                normalized_value=None,
                attributes={"spacy_label": ent.label_},
                extraction_method="spacy",
                confidence=None,  # spaCy doesn't expose per-entity confidence by default
            )
            entities.append(mention)

        return entities, []
