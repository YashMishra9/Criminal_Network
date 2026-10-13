"""Patterns API Router.

Implements route stubs for DOC3 §12.6:
- GET /patterns

TODO: Real implementation belongs to Task D5 (Analytics & Patterns API Endpoints).
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/patterns", tags=["patterns"])


@router.get("")
async def get_patterns(
    dataset: Optional[str] = "synthetic_demo",
    as_of: Optional[str] = None,
):
    """Get flagged pattern findings with explanations and disclaimer (DOC3 §12.6).

    TODO(Task D5): Implement retrieval of persisted Finding nodes filtered by as_of (DOC3 §1.8, §8).
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Endpoint stub: GET /patterns to be implemented in Task D5",
    )
