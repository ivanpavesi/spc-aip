"""Router pubblico per homepage istituzionale e healthcheck."""

from pathlib import Path
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db

router = APIRouter(tags=["Pubblico"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse, summary="Homepage Istituzionale")
def get_home_page(request: Request) -> HTMLResponse:
    """Mostra la homepage delle Scuole di Psicoterapia Cognitiva (AIP).

    Presenta esclusivamente le due card principali (Accesso Paziente e Area Terapeuta)
    e i collegamenti secondari nel footer per Ricercatore e Amministratore.
    """
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"app_name": settings.APP_NAME},
    )


@router.post("/patient/verify", response_class=HTMLResponse, summary="Verifica Codice Paziente")
def verify_patient_code(
    request: Request,
    access_code: str = Form(..., description="Codice personale di accesso"),
) -> HTMLResponse:
    """Gestisce il tentativo di accesso da parte del paziente con il codice personale.

    In questo STEP 1, la compilazione dei questionari non è ancora attiva (prevista in STEP 3).
    Questo endpoint valida formalmente la richiesta e mostra una pagina informativa trasparente.
    """
    cleaned_code = access_code.strip()
    if not cleaned_code:
        # Se il codice è vuoto, ritorna sulla home
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # Reindirizza direttamente alla pagina di compilazione del questionario
    return RedirectResponse(url=f"/p/{cleaned_code}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/health", summary="Stato del Sistema")
@router.get("/healthz", summary="Stato del Sistema (Cloud Check)")
def healthcheck(db: Session = Depends(get_db)) -> dict:
    """Verifica lo stato di salute dell'applicazione e la connettività al database."""
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"unhealthy: {exc}"

    return {
        "status": "ok",
        "app_name": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "database": db_status,
        "version": "0.1.0",
    }
