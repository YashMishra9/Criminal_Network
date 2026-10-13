"""Evidence API Router.

Implements route stubs for DOC3 §12.7:
- GET /evidence

TODO: Real implementation belongs to Tasks C4 / C6 (EvidenceResolver & Graph/Entity Endpoints).
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("")
async def get_evidence(
    entity_id: Optional[str] = None,
    relationship_id: Optional[str] = None,
    finding_id: Optional[str] = None,
    decision_id: Optional[str] = None,
):
    """Get supporting evidence for an entity, relationship, finding, or decision (DOC3 §12.7).

    TODO(Tasks C4/C6): Implement evidence retrieval via EvidenceResolver (DOC3 §9.1).
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Endpoint stub: GET /evidence to be implemented in Tasks C4 / C6",
    )
