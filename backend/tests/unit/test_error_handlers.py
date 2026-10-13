"""Unit tests for Task A6: Error Envelope & Exception Handling.

Tests (per A6 §13):
- One test per error type confirming correct HTTP status code and envelope body.
- Tests use a minimal FastAPI test app with one route per error type — they do NOT
  rely on the A1 stub routes so that this suite remains isolated.

DOC3 §13 status-code table:
  not_found                   → 404
  validation_error            → 400
  llm_unavailable             → 503
  dataset_isolation_violation → 400
  graph_unavailable           → 503
  internal_error              → 500
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts.errors import (
    DatasetIsolationViolationError,
    GraphUnavailableError,
    InternalError,
    LLMUnavailableError,
    NotFoundError,
    ValidationError,
    register_exception_handlers,
)


# ---------------------------------------------------------------------------
# Minimal test app — one route per error type
# ---------------------------------------------------------------------------

def build_test_app() -> FastAPI:
    """Build a minimal FastAPI app with one route per error type."""
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/raise/not_found")
    def raise_not_found():
        raise NotFoundError("Entity with id 'xyz' was not found.", details={"id": "xyz"})

    @test_app.get("/raise/validation_error")
    def raise_validation_error():
        raise ValidationError("Field 'dataset' must be 'synthetic_demo' or 'live_public'.")

    @test_app.get("/raise/llm_unavailable")
    def raise_llm_unavailable():
        raise LLMUnavailableError("LLM provider did not respond within the timeout.")

    @test_app.get("/raise/dataset_isolation_violation")
    def raise_dataset_isolation():
        raise DatasetIsolationViolationError(
            "Cannot mix synthetic_demo and live_public data.",
            details={"datasets": ["synthetic_demo", "live_public"]},
        )

    @test_app.get("/raise/graph_unavailable")
    def raise_graph_unavailable():
        raise GraphUnavailableError("Neo4j is unreachable.")

    @test_app.get("/raise/internal_error")
    def raise_internal_error():
        raise InternalError("An unexpected error occurred.")

    @test_app.get("/raise/unhandled")
    def raise_unhandled():
        raise RuntimeError("This was not expected.")

    return test_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(build_test_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def assert_error_envelope(response, expected_status: int, expected_type: str):
    """Assert status code and DOC3 §13 envelope shape."""
    assert response.status_code == expected_status, (
        f"Expected HTTP {expected_status}, got {response.status_code}. Body: {response.text}"
    )
    body = response.json()
    assert "error" in body, f"Missing 'error' key in body: {body}"
    assert body["error"]["type"] == expected_type, (
        f"Expected error.type='{expected_type}', got '{body['error']['type']}'"
    )
    assert "message" in body["error"], "Missing 'message' in error detail"
    # details key must exist (may be null)
    assert "details" in body["error"], "Missing 'details' in error detail"


# ---------------------------------------------------------------------------
# One test per error type
# ---------------------------------------------------------------------------

def test_not_found_returns_404(client):
    r = client.get("/raise/not_found")
    assert_error_envelope(r, 404, "not_found")
    assert r.json()["error"]["details"] == {"id": "xyz"}


def test_validation_error_returns_400(client):
    r = client.get("/raise/validation_error")
    assert_error_envelope(r, 400, "validation_error")


def test_llm_unavailable_returns_503(client):
    r = client.get("/raise/llm_unavailable")
    assert_error_envelope(r, 503, "llm_unavailable")


def test_dataset_isolation_violation_returns_400(client):
    r = client.get("/raise/dataset_isolation_violation")
    assert_error_envelope(r, 400, "dataset_isolation_violation")
    assert r.json()["error"]["details"]["datasets"] == ["synthetic_demo", "live_public"]


def test_graph_unavailable_returns_503(client):
    r = client.get("/raise/graph_unavailable")
    assert_error_envelope(r, 503, "graph_unavailable")


def test_internal_error_returns_500(client):
    r = client.get("/raise/internal_error")
    assert_error_envelope(r, 500, "internal_error")


def test_unhandled_exception_returns_500_internal_error(client):
    """Catch-all handler must turn unhandled RuntimeError into internal_error/500."""
    r = client.get("/raise/unhandled")
    assert_error_envelope(r, 500, "internal_error")


# ---------------------------------------------------------------------------
# Exception class API tests (no HTTP layer)
# ---------------------------------------------------------------------------

def test_exception_message_and_details_stored():
    exc = NotFoundError("not here", details={"id": 42})
    assert exc.message == "not here"
    assert exc.details == {"id": 42}


def test_to_response_returns_correct_envelope():
    exc = GraphUnavailableError("Neo4j is down")
    envelope = exc.to_response()
    assert envelope.error.type == "graph_unavailable"
    assert envelope.error.message == "Neo4j is down"
    assert envelope.error.details is None


def test_all_six_exception_classes_have_correct_status_codes():
    expected = {
        NotFoundError: 404,
        ValidationError: 400,
        LLMUnavailableError: 503,
        DatasetIsolationViolationError: 400,
        GraphUnavailableError: 503,
        InternalError: 500,
    }
    for cls, code in expected.items():
        assert cls.http_status_code == code, (
            f"{cls.__name__}.http_status_code should be {code}, got {cls.http_status_code}"
        )


def test_all_six_exception_classes_have_correct_error_types():
    expected = {
        NotFoundError: "not_found",
        ValidationError: "validation_error",
        LLMUnavailableError: "llm_unavailable",
        DatasetIsolationViolationError: "dataset_isolation_violation",
        GraphUnavailableError: "graph_unavailable",
        InternalError: "internal_error",
    }
    for cls, error_type in expected.items():
        assert cls.error_type == error_type, (
            f"{cls.__name__}.error_type should be '{error_type}', got '{cls.error_type}'"
        )


# ---------------------------------------------------------------------------
# A1 regression: ensure existing skeleton test app still has all 8 routers
# ---------------------------------------------------------------------------

def test_main_app_still_has_all_routers_and_handlers():
    """Smoke test: importing main.py with A6 additions does not break A1 or A4.

    - At least two router groups respond (entities, cases)
    - All six typed exception handlers are registered on the app
    """
    from fastapi.testclient import TestClient
    from app.main import app as main_app
    from app.contracts.errors import ALL_API_ERROR_TYPES

    # Verify exception handlers are registered
    for exc_class in ALL_API_ERROR_TYPES:
        assert exc_class in main_app.exception_handlers, (
            f"{exc_class.__name__} not found in app.exception_handlers"
        )

    # Verify at least two router groups have stub routes responding
    c = TestClient(main_app)
    # C6 is now implemented: /entities/search no longer returns 501.
    # Without Neo4j it returns 503 graph_unavailable (DOC3 §13).
    r1 = c.get("/api/v1/entities/search")
    assert r1.status_code in (200, 503), (
        f"/entities/search should return 200 (with Neo4j) or 503 (without), "
        f"got {r1.status_code}: {r1.text}"
    )
    if r1.status_code == 503:
        assert r1.json()["error"]["type"] == "graph_unavailable"
    r2 = c.post("/api/v1/cases")
    assert r2.status_code == 501, f"Expected 501 stub for POST /cases, got {r2.status_code}"
