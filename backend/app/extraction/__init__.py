"""Entity/Relationship Extraction package — B5 + B6.

Exports:
    ExtractionResult   — the output contract (DOC3 §4)
    RegexExtractor     — identifier-pattern extraction (phones, vehicles, accounts, …)
    SpacyExtractor     — NER-based entity extraction (persons, orgs, locations, events)
    LLMExtractor       — LLM-assisted augmentation (B6, optional, graceful degradation)
    Extractor          — orchestrates all three; the consumer-facing entry point
    build_extractor    — factory: returns a wired Extractor (B5+B6 or B5-only)
"""

from app.extraction.extractor import ExtractionResult, Extractor, build_extractor
from app.extraction.llm_extractor import LLMExtractor
from app.extraction.regex_extractor import RegexExtractor
from app.extraction.spacy_extractor import SpacyExtractor

__all__ = [
    "ExtractionResult",
    "Extractor",
    "build_extractor",
    "LLMExtractor",
    "RegexExtractor",
    "SpacyExtractor",
]
