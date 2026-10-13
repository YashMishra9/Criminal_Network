"""LLM-assisted extraction — B6, DOC3 §4, DOC2 §7.

Task B6: Augments B5's spaCy/regex results with additional mentions for
genuinely ambiguous cases that the structured extractors could not confidently
resolve. The LLM is invoked ONLY after B5 has run and ONLY when there is
likely residual ambiguity (Contract Invariant 4, DOC3 §4 'LLM use' clause).

Key design rules:
  1. The LLM is NEVER invoked first — B5 (spaCy + regex) always runs first.
  2. When LLMClient returns {status: 'unavailable'}, the extractor silently
     skips the LLM step for that record and returns B5's results unchanged.
     The pipeline NEVER fails because of LLM unavailability.
  3. LLM output is parsed strictly — only mentions matching the DOC3 §1.3
     entity_type enum and producing valid EntityMention/RelationshipMention
     objects are accepted. Malformed LLM output is dropped, not propagated.
  4. LLM mentions are tagged extraction_method='llm' (DOC3 §1.3).
  5. The LLM never originates a factual claim reaching the user (DOC3
     Contract Invariant 3) — its output is parsed into structured mentions
     that are then subject to the same resolution and evidence chain as any
     other mention.

Prompt design:
  The prompt provides the record's payload_text as the text to analyze and
  the already-extracted entities (from B5) as context, asking the LLM only
  to find additional entity mentions that the structured methods missed. This
  keeps the LLM scoped to a bounded, auditable task.

Output format expected from the LLM (instructed in the prompt):
  A JSON array of objects, each with:
    { "entity_type": "Person"|"Phone"|..., "raw_text": "..." }
  Relationship mentions are not requested from the LLM (too unreliable
  without resolution context); they are left entirely to B5's regex path.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.contracts.mention import EntityMention, RelationshipMention
from app.contracts.raw_record import RawRecord
from app.extraction.regex_extractor import _make_mention_id
from app.llm.client import LLMClient, LLMResultOk

logger = logging.getLogger(__name__)

# DOC3 §1.3 valid entity types — used to validate LLM output
_VALID_ENTITY_TYPES = frozenset({
    "Person", "Phone", "Vehicle", "Location",
    "Organization", "BankAccount", "Transaction", "Event",
})

# Minimum payload_text length to bother calling the LLM
_MIN_TEXT_LEN = 20

# System-level instruction context passed with every extraction prompt
_EXTRACTION_SYSTEM_CONTEXT = (
    "You are a structured entity extractor for a criminal network analysis system. "
    "Your task is to identify named entities in text that a spaCy/regex pipeline "
    "may have missed. You must output ONLY a valid JSON array — no prose, "
    "no markdown, no explanation. Each element must be an object with exactly "
    "two keys: 'entity_type' and 'raw_text'. "
    f"Valid entity_type values: {sorted(_VALID_ENTITY_TYPES)}. "
    "Do NOT include entity types not in this list. "
    "Do NOT include entities already listed under 'already_extracted'. "
    "If you find nothing new, return an empty array: []"
)


class LLMExtractor:
    """LLM-assisted extraction — plugs into Extractor as the optional llm_extractor.

    The interface this class exposes matches the extension point defined in
    extractor.py: extract(record, existing_entities) → (entities, relationships).

    Args:
        llm_client: An LLMClient instance (injected for testability).
        min_confidence_threshold: B5 mentions with confidence ≥ this value are
            considered 'resolved'; only records with potentially incomplete
            extraction trigger an LLM call. Defaults to 0.85.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        min_confidence_threshold: float = 0.85,
    ) -> None:
        self._client = llm_client
        self._threshold = min_confidence_threshold

    def extract(
        self,
        record: RawRecord,
        existing_entities: List[EntityMention],
    ) -> Tuple[List[EntityMention], List[RelationshipMention]]:
        """Augment B5 results with LLM-found entities (best-effort, graceful).

        Args:
            record:            The RawRecord being processed.
            existing_entities: EntityMention list already produced by B5.

        Returns:
            (new_entities, []) — only new entities not already in
            existing_entities are returned; relationships are always []
            (the LLM is not asked to produce relationships here).

        On any LLM failure (unavailable, parse error, etc.) returns ([], []).
        """
        text = (record.payload_text or "").strip()
        if len(text) < _MIN_TEXT_LEN:
            logger.debug(
                "LLMExtractor: record '%s' payload_text too short (%d chars), skipping.",
                record.record_id, len(text),
            )
            return [], []

        if not self._needs_llm(record, existing_entities):
            logger.debug(
                "LLMExtractor: record '%s' already well-covered by B5 (%d entities), skipping.",
                record.record_id, len(existing_entities),
            )
            return [], []

        prompt = self._build_prompt(text, existing_entities)

        result = self._client.generate(
            prompt=prompt,
            context=_EXTRACTION_SYSTEM_CONTEXT,
            options={"timeout_ms": 15_000},
        )

        if not isinstance(result, LLMResultOk):
            logger.info(
                "LLMExtractor: LLM unavailable for record '%s' (reason=%s). "
                "Proceeding with B5-only results.",
                record.record_id, result.reason,  # type: ignore[union-attr]
            )
            return [], []

        new_mentions = self._parse_llm_output(result.text, record, existing_entities)
        if new_mentions:
            logger.info(
                "LLMExtractor: %d new mention(s) from LLM for record '%s'.",
                len(new_mentions), record.record_id,
            )
        return new_mentions, []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _needs_llm(
        self,
        record: RawRecord,
        existing_entities: List[EntityMention],
    ) -> bool:
        """Return True when LLM augmentation is likely worthwhile.

        Heuristic: call the LLM if the record has meaningful free text AND
        either has no Person/Organization mentions yet (the two types most
        likely to require NLP) or has low-confidence mentions from B5.

        This keeps LLM calls bounded and purposeful (DOC2 §7).
        """
        text = record.payload_text or ""
        if len(text) < _MIN_TEXT_LEN:
            return False

        # Records from structured identifier-only sources rarely need LLM
        if record.source_type in ("CDR",):
            return False

        # Check whether any Person or Org mention is low-confidence or absent
        person_org = [
            e for e in existing_entities
            if e.entity_type in ("Person", "Organization")
        ]
        if not person_org:
            return True  # No persons/orgs found yet — LLM may help

        low_confidence = [
            e for e in person_org
            if e.confidence is None or e.confidence < self._threshold
        ]
        return len(low_confidence) > 0

    @staticmethod
    def _build_prompt(
        text: str,
        existing: List[EntityMention],
    ) -> str:
        """Build the extraction prompt.

        Includes the text to analyze and the already-found entities so the
        LLM only adds new information (grounded output, DOC3 Invariant 3).
        """
        already_found = [
            {"entity_type": e.entity_type, "raw_text": e.raw_text}
            for e in existing
        ]
        already_json = json.dumps(already_found, ensure_ascii=False)

        return (
            f"TEXT TO ANALYZE:\n{text}\n\n"
            f"ALREADY EXTRACTED (do NOT repeat these):\n{already_json}\n\n"
            "OUTPUT: A JSON array of objects with 'entity_type' and 'raw_text' "
            "for any additional entities you find. Return [] if nothing new."
        )

    @staticmethod
    def _parse_llm_output(
        raw_text: str,
        record: RawRecord,
        existing: List[EntityMention],
    ) -> List[EntityMention]:
        """Parse and validate the LLM's JSON output into EntityMention objects.

        Strict parsing: any malformed element is silently dropped. This ensures
        that a misbehaving LLM response can never corrupt the pipeline.

        Args:
            raw_text:  The LLM's text response.
            record:    The originating RawRecord (for provenance fields).
            existing:  Already-found entities (used to deduplicate).

        Returns:
            List of new, valid EntityMention objects.
        """
        # Extract the first JSON array from the response (the LLM sometimes
        # wraps its output in markdown code fences)
        json_text = raw_text.strip()
        # Strip markdown fences if present
        json_text = re.sub(r"^```(?:json)?\s*", "", json_text)
        json_text = re.sub(r"\s*```$", "", json_text.strip())

        # Find the outermost [...] array
        match = re.search(r"\[.*\]", json_text, re.DOTALL)
        if not match:
            logger.warning(
                "LLMExtractor: could not find JSON array in response for '%s'. "
                "Response: %r", record.record_id, raw_text[:200],
            )
            return []

        try:
            items = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            logger.warning(
                "LLMExtractor: JSON parse error for record '%s': %s",
                record.record_id, exc,
            )
            return []

        if not isinstance(items, list):
            return []

        # Deduplicate against already-extracted (case-insensitive raw_text)
        existing_keys = {
            (e.entity_type, e.raw_text.lower()) for e in existing
        }

        mentions: List[EntityMention] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            entity_type = item.get("entity_type", "")
            raw_text_val = str(item.get("raw_text", "")).strip()

            if entity_type not in _VALID_ENTITY_TYPES:
                logger.debug(
                    "LLMExtractor: invalid entity_type '%s' from LLM, dropping.",
                    entity_type,
                )
                continue

            if not raw_text_val:
                continue

            key = (entity_type, raw_text_val.lower())
            if key in existing_keys:
                continue  # already extracted by B5
            existing_keys.add(key)

            mention = EntityMention(
                mention_id=_make_mention_id(record.record_id, entity_type, raw_text_val, i),
                record_id=record.record_id,
                dataset=record.dataset,
                entity_type=entity_type,  # type: ignore[arg-type]
                raw_text=raw_text_val,
                normalized_value=None,
                attributes={"llm_generated": True},
                extraction_method="llm",
                confidence=None,
            )
            mentions.append(mention)

        return mentions
