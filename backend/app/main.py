"""FastAPI Application Entrypoint.

Task A1: Stands up the FastAPI application and registers router stubs
for all 8 DOC3 §12 endpoint groups under the /api/v1 prefix.

Task A6: Registers global exception handlers for all six DOC3 §13 error types.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    analytics,
    ask,
    cases,
    entities,
    evidence,
    graph,
    ingestion,
    patterns,
)
from app.contracts.errors import register_exception_handlers
from app.graph.connection import close_driver


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler — run startup/shutdown logic here."""
    yield
    # Shutdown: release the Neo4j connection pool (A4)
    close_driver()


app = FastAPI(
    title="AI-Powered Criminal Network Analysis System",
    description="Backend API for Criminal Network Analysis System (DOC3 §12)",
    version="0.1.0",
    lifespan=lifespan,
)

# Register all 8 DOC3 §12 router groups prefixed with /api/v1
app.include_router(entities.router, prefix="/api/v1")
app.include_router(graph.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(patterns.router, prefix="/api/v1")
app.include_router(evidence.router, prefix="/api/v1")
app.include_router(ask.router, prefix="/api/v1")
app.include_router(cases.router, prefix="/api/v1")
app.include_router(ingestion.router, prefix="/api/v1")

# Register all six DOC3 §13 error type handlers (A6)
register_exception_handlers(app)
