"""Area ricerca sospesa in attesa delle autorizzazioni per studio (F09 fase 1)."""

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.auth import get_current_user
from app.db.models.user import User
from app.services.research import ResearchAccessDenied, authorize_research_access

router = APIRouter(prefix="/researcher", tags=["Area Ricerca"])


@router.get("/dashboard", summary="Dashboard Ricercatore temporaneamente sospesa")
@router.get("/export/csv", summary="Esportazione CSV temporaneamente sospesa")
@router.get("/export/excel", summary="Esportazione Excel temporaneamente sospesa")
def research_unavailable(user: User = Depends(get_current_user)) -> Response:
    """Un solo controllo per tutti i percorsi, prima di qualsiasi lettura dati."""
    try:
        authorize_research_access(actor_id=user.id)
    except ResearchAccessDenied as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from None
