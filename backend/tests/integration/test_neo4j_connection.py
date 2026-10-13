"""Integration tests for Task A4: Neo4j Connection Layer.

These tests require a real (or containerised) Neo4j instance. They are skipped
automatically when NEO4J_INTEGRATION_TEST=true is not set in the environment,
so CI/CD running without Neo4j is unaffected.

To run locally:
    set NEO4J_INTEGRATION_TEST=true
    set NEO4J_URI=bolt://localhost:7687
    set NEO4J_USER=neo4j
    set NEO4J_PASSWORD=<your-password>
    python -m pytest backend/tests/integration/test_neo4j_connection.py -v
"""

import os

import pytest

# Skip entire module when no real Neo4j is available
pytestmark = pytest.mark.skipif(
    os.environ.get("NEO4J_INTEGRATION_TEST", "").lower() != "true",
    reason="Set NEO4J_INTEGRATION_TEST=true to run Neo4j integration tests",
)

from app.graph import connection as conn_module  # noqa: E402 (after skip guard)


@pytest.fixture(autouse=True)
def reset_driver():
    """Isolate driver singleton between integration tests."""
    conn_module._driver = None
    yield
    conn_module.close_driver()


def test_health_check_returns_true_against_live_neo4j():
    """health_check() returns True when the configured Neo4j instance is reachable."""
    result = conn_module.health_check()
    assert result is True, (
        "health_check() returned False — ensure Neo4j is running and "
        "NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD are set correctly."
    )


def test_get_session_runs_query_against_live_neo4j():
    """get_session() yields a working session that can execute a simple Cypher query."""
    with conn_module.get_session() as session:
        result = session.run("RETURN 1 AS value")
        record = result.single()
        assert record is not None
        assert record["value"] == 1


def test_get_session_round_trips_basic_cypher():
    """A simple MATCH query executes without error against the live graph."""
    with conn_module.get_session() as session:
        result = session.run("MATCH (n) RETURN count(n) AS cnt")
        record = result.single()
        assert record is not None
        assert isinstance(record["cnt"], int)
