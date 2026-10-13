"""Unit tests for Task A1: FastAPI App Skeleton.

Tests:
1. App starts and all 8 router groups are mounted with /api/v1 prefix.
2. Every stub route handler responds with placeholder status (HTTP 501) rather than crashing or 404.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_routers_mounted():
    """Verify all 8 DOC3 §12 router groups are mounted under /api/v1."""
    registered_paths = list(app.openapi()["paths"].keys())

    expected_prefixes = [
        "/api/v1/entities",
        "/api/v1/graph",
        "/api/v1/analytics",
        "/api/v1/patterns",
        "/api/v1/evidence",
        "/api/v1/ask",
        "/api/v1/cases",
        "/api/v1/ingestion",
    ]

    for prefix in expected_prefixes:
        matches = [p for p in registered_paths if p.startswith(prefix)]
        assert len(matches) > 0, f"Router prefix {prefix} is not mounted in app routes"


@pytest.mark.parametrize(
    "method,path",
    [
        # NOTE: §12.1–§12.4 (entities/search, entities/{id}, entities/{id}/relationships,
        # graph) are implemented by Task C6 and no longer return HTTP 501.
        # They are tested separately in test_c6_api_endpoints.py.

        # DOC3 §12.5: Analytics
        ("GET", "/api/v1/analytics"),
        # DOC3 §12.6: Patterns
        ("GET", "/api/v1/patterns"),
        # DOC3 §12.7: Evidence
        ("GET", "/api/v1/evidence"),
        # DOC3 §12.8: Ask
        ("POST", "/api/v1/ask"),
        # DOC3 §12.9: Cases
        ("POST", "/api/v1/cases"),
        ("GET", "/api/v1/cases/case_123"),
        ("POST", "/api/v1/cases/case_123/entities"),
        ("POST", "/api/v1/cases/case_123/relationships"),
        ("POST", "/api/v1/cases/case_123/notes"),
        ("GET", "/api/v1/cases/case_123/summary"),
        # DOC3 §12.10: Ingestion
        ("POST", "/api/v1/ingestion/run"),
        ("GET", "/api/v1/ingestion/status"),
    ],
)
def test_stub_routes_respond_with_501(method: str, path: str):
    """Verify each stub route responds with HTTP 501 Not Implemented and does not crash."""
    if method == "GET":
        response = client.get(path)
    elif method == "POST":
        response = client.post(path, json={})
    else:
        pytest.fail(f"Unsupported method: {method}")

    assert response.status_code == 501, (
        f"Expected HTTP 501 for {method} {path}, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert "detail" in data
    assert "to be implemented" in data["detail"]
