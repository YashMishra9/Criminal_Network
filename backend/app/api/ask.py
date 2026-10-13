"""Ask-the-Network API Router.

Implements route stubs for DOC3 §12.8:
- POST /ask

TODO: Real implementation belongs to Task F4 (Ask API Endpoint).
"""

from typing import Any, Dict
from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("")
async def ask_network(request_body: Dict[str, Any] = None):
    """Natural-language query interface grounded in graph structure (DOC3 §12.8).

    TODO(Task F4): Implement Ask-the-Network flow: NL->Cypher generation, validation,
    execution, evidence attachment, and narration (DOC3 §10).
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Endpoint stub: POST /ask to be implemented in Task F4",
    )
