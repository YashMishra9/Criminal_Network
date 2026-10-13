"""Contract types — DOC3 §1 data models (Pydantic).

This package is the single source of truth for all shared types.
Every other backend module must import from here; no hand-rolled duplicates.
"""

from app.contracts.raw_record import AdapterDescriptor, RawRecord
from app.contracts.mention import EntityMention, RelationshipMention
from app.contracts.entity import CanonicalEntity
from app.contracts.relationship import Relationship
from app.contracts.evidence import Evidence
from app.contracts.resolution import ResolutionDecision
from app.contracts.finding import Finding
from app.contracts.case import Case, EdgeRef, Note
from app.contracts.analytics import AnalyticsResult, ShortestPathResult
from app.contracts.errors import (
    ErrorDetail,
    ErrorResponse,
    NotFoundError,
    ValidationError,
    LLMUnavailableError,
    DatasetIsolationViolationError,
    GraphUnavailableError,
    InternalError,
    register_exception_handlers,
)

__all__ = [
    "RawRecord",
    "AdapterDescriptor",
    "EntityMention",
    "RelationshipMention",
    "CanonicalEntity",
    "Relationship",
    "Evidence",
    "ResolutionDecision",
    "Finding",
    "Case",
    "Note",
    "EdgeRef",
    "AnalyticsResult",
    "ShortestPathResult",
    "ErrorDetail",
    "ErrorResponse",
    "NotFoundError",
    "ValidationError",
    "LLMUnavailableError",
    "DatasetIsolationViolationError",
    "GraphUnavailableError",
    "InternalError",
    "register_exception_handlers",
]
