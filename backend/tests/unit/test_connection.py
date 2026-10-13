"""Unit tests for Task A4: Neo4j Connection Layer.

Tests the graceful-degradation path (health_check returns False, never raises)
without requiring a real Neo4j instance by patching the driver.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from neo4j.exceptions import AuthError, ServiceUnavailable

from app.graph import connection as conn_module


# ---------------------------------------------------------------------------
# Helpers: isolate the driver singleton between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_driver():
    """Ensure the driver singleton is reset before and after each test."""
    conn_module._driver = None
    yield
    if conn_module._driver is not None:
        try:
            conn_module._driver.close()
        except Exception:
            pass
        conn_module._driver = None


# ---------------------------------------------------------------------------
# health_check() graceful-degradation tests (no real Neo4j needed)
# ---------------------------------------------------------------------------

def test_health_check_returns_false_on_service_unavailable():
    """health_check() must return False (not raise) when Neo4j is unreachable."""
    mock_driver = MagicMock()
    mock_driver.verify_connectivity.side_effect = ServiceUnavailable("connection refused")

    with patch("app.graph.connection.GraphDatabase.driver", return_value=mock_driver):
        result = conn_module.health_check()

    assert result is False, "health_check() must return False when Neo4j is unreachable"


def test_health_check_returns_false_on_auth_error():
    """health_check() must return False (not raise) on authentication failure."""
    mock_driver = MagicMock()
    mock_driver.verify_connectivity.side_effect = AuthError("Unauthorized")

    with patch("app.graph.connection.GraphDatabase.driver", return_value=mock_driver):
        result = conn_module.health_check()

    assert result is False


def test_health_check_returns_false_on_generic_exception():
    """health_check() must return False (not raise) for any unexpected exception."""
    mock_driver = MagicMock()
    mock_driver.verify_connectivity.side_effect = RuntimeError("unexpected")

    with patch("app.graph.connection.GraphDatabase.driver", return_value=mock_driver):
        result = conn_module.health_check()

    assert result is False


def test_health_check_returns_true_when_reachable():
    """health_check() returns True when verify_connectivity succeeds."""
    mock_driver = MagicMock()
    mock_driver.verify_connectivity.return_value = None  # success

    with patch("app.graph.connection.GraphDatabase.driver", return_value=mock_driver):
        result = conn_module.health_check()

    assert result is True


# ---------------------------------------------------------------------------
# get_session() tests (mocked driver)
# ---------------------------------------------------------------------------

def test_get_session_yields_session_and_closes_it():
    """get_session() yields a session and closes it on context exit."""
    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session

    with patch("app.graph.connection.GraphDatabase.driver", return_value=mock_driver):
        with conn_module.get_session() as session:
            assert session is mock_session

    mock_session.close.assert_called_once()


def test_get_session_closes_session_on_exception():
    """get_session() closes the session even when an exception occurs inside the block."""
    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session

    with patch("app.graph.connection.GraphDatabase.driver", return_value=mock_driver):
        with pytest.raises(ValueError):
            with conn_module.get_session() as session:
                raise ValueError("test error inside session block")

    mock_session.close.assert_called_once()


# ---------------------------------------------------------------------------
# Driver singleton tests
# ---------------------------------------------------------------------------

def test_driver_is_singleton():
    """_get_driver() returns the same driver object on repeated calls."""
    mock_driver = MagicMock()

    with patch("app.graph.connection.GraphDatabase.driver", return_value=mock_driver) as mock_factory:
        d1 = conn_module._get_driver()
        d2 = conn_module._get_driver()

    assert d1 is d2
    mock_factory.assert_called_once()  # created only once


def test_close_driver_resets_singleton():
    """close_driver() closes and nulls the driver so the next call re-creates it."""
    mock_driver = MagicMock()

    with patch("app.graph.connection.GraphDatabase.driver", return_value=mock_driver):
        conn_module._get_driver()
        assert conn_module._driver is not None

        conn_module.close_driver()
        assert conn_module._driver is None

    mock_driver.close.assert_called_once()


def test_close_driver_when_none_is_noop():
    """close_driver() is a no-op when no driver has been created yet."""
    assert conn_module._driver is None
    conn_module.close_driver()  # must not raise
    assert conn_module._driver is None
