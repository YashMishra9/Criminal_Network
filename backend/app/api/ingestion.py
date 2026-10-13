"""Ingestion & Adapter Status API Router.

Implements route stubs for DOC3 §12.10:
- POST /ingestion/run
- GET /ingestion/status

TODO: Real implementation belongs to Track B (B4-adjacent ingestion endpoints).
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/run")
async def run_ingestion(adapter_id: Optional[str] = None):
    """Trigger batch fetch or poll for the named adapter (DOC3 §12.10).

    TODO(Track B): Implement adapter trigger and orchestrator pipeline run.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Endpoint stub: POST /ingestion/run to be implemented in Track B (B4-adjacent)",
    )


@router.get("/status")
async def get_ingestion_status():
    """Get status of all configured source adapters (DOC3 §12.10).

    TODO(Track B): Implement adapter status inspection reporting AdapterDescriptor list.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Endpoint stub: GET /ingestion/status to be implemented in Track B (B4-adjacent)",
    )
