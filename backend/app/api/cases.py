"""Case Workspace API Router.

Implements route stubs for DOC3 §12.9:
- POST /cases
- GET /cases/{case_id}
- POST /cases/{case_id}/entities
- POST /cases/{case_id}/relationships
- POST /cases/{case_id}/notes
- GET /cases/{case_id}/summary

TODO: Real implementation belongs to Task G3 (Case Workspace API Endpoints).
"""

from typing import Any, Dict
from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("")
async def create_case(case_data: Dict[str, Any] = None):
    """Create a new investigation case (DOC3 §12.9).

    TODO(Task G3): Implement case creation with dataset scoping via CaseWorkspace.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Endpoint stub: POST /cases to be implemented in Task G3",
    )


@router.get("/{case_id}")
async def get_case(case_id: str):
    """Get case details with associated entities, relationships, evidence, and notes (DOC3 §12.9).

    TODO(Task G3): Implement case retrieval via CaseWorkspace.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Endpoint stub: GET /cases/{case_id} to be implemented in Task G3",
    )


@router.post("/{case_id}/entities")
async def add_entity_to_case(case_id: str, entity_data: Dict[str, Any] = None):
    """Associate an entity with a case (DOC3 §12.9).

    TODO(Task G3): Implement entity association with dataset isolation check.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Endpoint stub: POST /cases/{case_id}/entities to be implemented in Task G3",
    )


@router.post("/{case_id}/relationships")
async def add_relationship_to_case(case_id: str, relationship_data: Dict[str, Any] = None):
    """Associate a relationship (via its existing EdgeRef) with a case (DOC3 §12.9).

    TODO(Task G3): Implement relationship association reusing existing EdgeRef (DOC3 §6.5, Invariant 12).
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Endpoint stub: POST /cases/{case_id}/relationships to be implemented in Task G3",
    )


@router.post("/{case_id}/notes")
async def add_note_to_case(case_id: str, note_data: Dict[str, Any] = None):
    """Add a note to a case, optionally scoped via 'about' (DOC3 §12.9).

    TODO(Task G3): Implement note creation with optional 'about' target validation.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Endpoint stub: POST /cases/{case_id}/notes to be implemented in Task G3",
    )


@router.get("/{case_id}/summary")
async def get_case_summary(case_id: str):
    """Generate or retrieve investigation summary for a case (DOC3 §12.9).

    TODO(Task G3): Implement LLM-driven summary generation with degradation handling (DOC3 §11, DOC2 §12A).
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Endpoint stub: GET /cases/{case_id}/summary to be implemented in Task G3",
    )
