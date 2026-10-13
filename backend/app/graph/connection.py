"""Neo4j Connection Layer.

Task A4: Driver/session management, connection pooling, and health-check.
References: DOC2 §5.2 (single Neo4j instance), DOC2 §15 (deployment).

This is the ONLY Neo4j connection in the system. No other module may open
a second driver or connection pool (DOC2 §5.2, DOC1 §9.2).
"""

import logging
from contextlib import contextmanager
from typing import Generator

from neo4j import GraphDatabase, Session
from neo4j.exceptions import AuthError, ServiceUnavailable

from app.config import get_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level driver singleton — created once on first use, closed on shutdown.
# ---------------------------------------------------------------------------
_driver = None


def _get_driver():
    """Return the module-level Neo4j Driver singleton, creating it if needed."""
    global _driver
    if _driver is None:
        cfg = get_config()
        _driver = GraphDatabase.driver(
            cfg.NEO4J_URI,
            auth=(cfg.NEO4J_USER, cfg.NEO4J_PASSWORD),
        )
        logger.info("Neo4j driver initialised (URI=%s, user=%s)", cfg.NEO4J_URI, cfg.NEO4J_USER)
    return _driver


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Yield a Neo4j Session from the connection pool.

    Usage:
        with get_session() as session:
            result = session.run("MATCH (n) RETURN count(n) AS cnt")
            ...

    The session is automatically closed when the context exits, returning the
    underlying connection to the pool.
    """
    driver = _get_driver()
    session = driver.session()
    try:
        yield session
    finally:
        session.close()


def health_check() -> bool:
    """Return True if Neo4j is reachable; False otherwise — never raises.

    Callers map False to the graph_unavailable error type (DOC3 §13, Task A6)
    rather than catching an exception, keeping error-handling consistent across
    the system without tightly coupling every caller to Neo4j exception types.
    """
    try:
        driver = _get_driver()
        driver.verify_connectivity()
        return True
    except (ServiceUnavailable, AuthError, Exception) as exc:
        logger.warning("Neo4j health check failed: %s", exc)
        return False


def close_driver() -> None:
    """Close the driver and release all pooled connections.

    Intended for application shutdown (e.g., FastAPI lifespan handler).
    After this call the next get_session() will re-create the driver.
    """
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("Neo4j driver closed.")
