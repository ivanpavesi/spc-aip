"""Router per le pagine informative temporanee degli accessi riservati.

In conformità ai requisiti dello STEP 1:
- Nessun modulo simula una finta autenticazione funzionante.
- Gli accessi riservati conducono a pagine informative chiare che indicano
  la fase di sviluppo prevista (STEP 2 per Terapeuta/Ricercatore/Admin).
"""

from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["Aree Riservate — Segnaposto Temporanei"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


from fastapi.responses import HTMLResponse, RedirectResponse

@router.get("/therapist/login", summary="Redirect Login Terapeuta")
def therapist_login_placeholder(request: Request):
    return RedirectResponse(url="/auth/login?role=THERAPIST", status_code=303)


@router.get("/researcher/login", summary="Redirect Login Ricercatore")
def researcher_login_placeholder(request: Request):
    return RedirectResponse(url="/auth/login?role=RESEARCHER", status_code=303)


@router.get("/admin/login", summary="Redirect Login Amministratore")
def admin_login_placeholder(request: Request):
    return RedirectResponse(url="/auth/login?role=ADMIN", status_code=303)


@router.get("/patient/portal", response_class=HTMLResponse, summary="Segnaposto Portale Paziente")
def patient_portal_placeholder(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="placeholder.html",
        context={
            "area_title": "Portale Compilazione Questionari",
            "step_info": "STEP 3 (Pazienti e Questionari)",
            "message": (
                "L'ambiente protetto per la compilazione deterministica dei questionari psicometrici "
                "tramite credenziali casuali robuste sarà reso operativo nello STEP 3."
            ),
        },
    )
