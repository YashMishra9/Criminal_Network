"""DOC3 §13 — ErrorResponse envelope, typed exception classes, and handler registration.

Task A6 adds:
- Six typed exception classes (one per DOC3 §13 error type).
- register_exception_handlers() — wire all six handlers into the FastAPI app.

Status-code mapping (DOC3 §13 table):
  not_found                  → 404
  validation_error           → 400
  llm_unavailable            → 503
  dataset_isolation_violation → 400
  graph_unavailable          → 503
  internal_error             → 500
"""

import logging
from typing import Any, Literal, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

ErrorType = Literal[
    "not_found",
    "validation_error",
    "llm_unavailable",
    "dataset_isolation_violation",
    "graph_unavailable",
    "internal_error",
]

# ---------------------------------------------------------------------------
# Envelope models (defined in A3, unchanged)
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    """Inner error object (DOC3 §13)."""

    type: ErrorType
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    """Consistent error envelope for all API error responses.

    DOC3 §13. Every non-2xx response must use this shape.
    """

    error: ErrorDetail


# ---------------------------------------------------------------------------
# Typed exception classes — one per DOC3 §13 error type
# ---------------------------------------------------------------------------

class _BaseAPIError(Exception):
    """Base class for all DOC3 §13 typed exceptions.

    Subclasses set error_type and http_status_code as class attributes.
    """

    error_type: ErrorType
    http_status_code: int

    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(
            error=ErrorDetail(
                type=self.error_type,
                message=self.message,
                details=self.details,
            )
        )


class NotFoundError(_BaseAPIError):
    """Resource not found — HTTP 404.  DOC3 §13."""

    error_type: ErrorType = "not_found"
    http_status_code: int = 404


class ValidationError(_BaseAPIError):
    """Request payload or parameter is invalid — HTTP 400.  DOC3 §13.

    Distinct from FastAPI's own RequestValidationError; used when business-logic
    validation (not schema validation) fails.
    """

    error_type: ErrorType = "validation_error"
    http_status_code: int = 400


class LLMUnavailableError(_BaseAPIError):
    """LLM provider is unavailable — HTTP 503.  DOC3 §13."""

    error_type: ErrorType = "llm_unavailable"
    http_status_code: int = 503


class DatasetIsolationViolationError(_BaseAPIError):
    """Cross-dataset operation attempted — HTTP 400.  DOC3 §13."""

    error_type: ErrorType = "dataset_isolation_violation"
    http_status_code: int = 400


class GraphUnavailableError(_BaseAPIError):
    """Neo4j graph is unreachable — HTTP 503.  DOC3 §13."""

    error_type: ErrorType = "graph_unavailable"
    http_status_code: int = 503


class InternalError(_BaseAPIError):
    """Unexpected server error — HTTP 500.  DOC3 §13."""

    error_type: ErrorType = "internal_error"
    http_status_code: int = 500


# Convenience tuple — useful for isinstance() checks in tests and handlers
ALL_API_ERROR_TYPES = (
    NotFoundError,
    ValidationError,
    LLMUnavailableError,
    DatasetIsolationViolationError,
    GraphUnavailableError,
    InternalError,
)

# ---------------------------------------------------------------------------
# Handler factory + registration
# ---------------------------------------------------------------------------

def _make_handler(exc_class: type[_BaseAPIError]):
    """Return an async exception handler for the given typed exception class."""

    async def handler(request: Request, exc: _BaseAPIError) -> JSONResponse:
        logger.warning(
            "API error [%s %s]: %s — %s",
            request.method,
            request.url.path,
            exc_class.__name__,
            exc.message,
        )
        return JSONResponse(
            status_code=exc_class.http_status_code,
            content=exc.to_response().model_dump(),
        )

    return handler


def register_exception_handlers(app: FastAPI) -> None:
    """Register all six DOC3 §13 exception handlers on the FastAPI app.

    Also registers a catch-all handler for any unhandled Exception so that
    no endpoint can silently return HTTP 200 with partial/missing data on
    internal failure (DOC3 §13 rule, A6 §11).

    Call this once during app setup (in main.py), after creating the FastAPI
    instance and before the app starts serving requests.
    """
    for exc_class in ALL_API_ERROR_TYPES:
        app.add_exception_handler(exc_class, _make_handler(exc_class))

    # Catch-all: any unhandled exception becomes internal_error/500
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled exception on [%s %s]", request.method, request.url.path
        )
        body = ErrorResponse(
            error=ErrorDetail(
                type="internal_error",
                message="An unexpected internal error occurred.",
                details=None,
            )
        ).model_dump()
        return JSONResponse(status_code=500, content=body)

    app.add_exception_handler(Exception, _unhandled_handler)
