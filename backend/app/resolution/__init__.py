"""Resolution package — B7 (batch) + B8 (incremental)."""

from app.resolution.resolver import (
    BatchResolver,
    ResolutionResult,
    IncrementalResolver,
    IncrementalResult,
)
from app.resolution.matching_rules import compare, MatchResult
from app.resolution import thresholds

__all__ = [
    "BatchResolver",
    "ResolutionResult",
    "IncrementalResolver",
    "IncrementalResult",
    "MatchResult",
    "compare",
    "thresholds",
]
