"""Router per la compilazione dei questionari da parte del paziente (STEP 3 & STEP 4)."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
from urllib.parse import quote
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.security import hash_token
from app.db.models.test_engine import TestAssignment, TestDefinition, TestResponse, TestScore, TestStatus
from app.db.session import get_db
from app.services.scoring.engine import PsychometricScoringEngine, ScoringError

router = APIRouter(tags=["Portale Paziente"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/p/{token}", response_class=HTMLResponse, summary="Schermata Compilazione Questionario")
def patient_test_form(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    clean_token = token.strip()
    token_h = hash_token(clean_token)
    now = datetime.now(timezone.utc)

    assignment = (
        db.query(TestAssignment)
        .filter(TestAssignment.access_token_hash == token_h)
        .first()
    )

    if not assignment:
        return templates.TemplateResponse(
            request=request,
            name="patient/error.html",
            context={
                "error_title": "Codice Non Valido",
                "error_message": "Il codice di accesso inserito non corrisponde ad alcun questionario attivo. Verifica il codice ricevuto o contatta il tuo terapeuta.",
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if assignment.status == TestStatus.COMPLETED:
        return templates.TemplateResponse(
            request=request,
            name="patient/error.html",
            context={
                "error_title": "Questionario Già Completato",
                "error_message": "Questo questionario è già stato inviato e completato. Le risposte sono state salvate e trasmesse al terapeuta.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if assignment.status == TestStatus.REVOKED:
        return templates.TemplateResponse(
            request=request,
            name="patient/error.html",
            context={
                "error_title": "Accesso Revocato",
                "error_message": "L'accesso a questo questionario è stato revocato dal terapeuta.",
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # Verifica scadenza temporale
    exp = assignment.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        assignment.status = TestStatus.EXPIRED
        db.commit()
        return templates.TemplateResponse(
            request=request,
            name="patient/error.html",
            context={
                "error_title": "Questionario Scaduto",
                "error_message": "Il termine previsto per la compilazione di questo questionario è scaduto. Richiedi al tuo terapeuta una nuova assegnazione.",
            },
            status_code=status.HTTP_410_GONE,
        )

    test_schema = assignment.definition_snapshot
    items = test_schema.get("items", [])

    return templates.TemplateResponse(
        request=request,
        name="patient/questionnaire.html",
        context={
            "assignment": assignment,
            "test_title": assignment.test_definition.title,
            "test_description": assignment.test_definition.description,
            "items": items,
            "token": clean_token,
            "error_msg": None,
        },
    )


@router.post("/p/{token}/submit", response_class=HTMLResponse, summary="Invio Risposte e Scoring Deterministico")
async def submit_questionnaire(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    clean_token = token.strip()
    token_h = hash_token(clean_token)
    now = datetime.now(timezone.utc)

    assignment = (
        db.query(TestAssignment)
        .filter(TestAssignment.access_token_hash == token_h)
        .first()
    )

    if not assignment or assignment.status != TestStatus.PENDING:
        return templates.TemplateResponse(
            request=request,
            name="patient/error.html",
            context={
                "error_title": "Operazione Non Consentita",
                "error_message": "Questo questionario non è in stato di attesa o è già stato elaborato.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    form_data = await request.form()
    items_schema = assignment.definition_snapshot
    scoring_rules = assignment.test_definition.scoring_rules

    # Estrazione risposte dal form
    answers: Dict[str, int] = {}
    missing_items = []

    for item in items_schema.get("items", []):
        iid = item["id"]
        val_str = form_data.get(f"item_{iid}")
        if val_str is None or val_str == "":
            missing_items.append(item.get("number", iid))
        else:
            try:
                answers[iid] = int(val_str)
            except ValueError:
                missing_items.append(item.get("number", iid))

    if missing_items:
        items = items_schema.get("items", [])
        return templates.TemplateResponse(
            request=request,
            name="patient/questionnaire.html",
            context={
                "assignment": assignment,
                "test_title": assignment.test_definition.title,
                "test_description": assignment.test_definition.description,
                "items": items,
                "token": clean_token,
                "error_msg": f"Rispondi a tutte le domande per completare il test. Mancano le domande: {', '.join(map(str, missing_items[:10]))}",
                "previous_answers": answers,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # Calcolo deterministico dei punteggi
    try:
        calculated_results = PsychometricScoringEngine.score_test(
            items_schema=items_schema,
            scoring_rules=scoring_rules,
            answers=answers,
        )
    except ScoringError as exc:
        raise HTTPException(status_code=400, detail=f"Errore nel calcolo del punteggio: {exc}")

    # Transazione atomica di salvataggio
    try:
        # 1. Salva risposte grezze
        response_rec = TestResponse(
            test_assignment_id=assignment.id,
            raw_answers=answers,
            submitted_at=now,
        )
        db.add(response_rec)

        # 2. Salva punteggi calcolati deterministicamente
        score_rec = TestScore(
            test_assignment_id=assignment.id,
            raw_scores=calculated_results["raw_scores"],
            standardized_scores=calculated_results["subscales"],
            interpretation_summary=calculated_results["clinical_cutoffs"],
            scoring_version=calculated_results["engine_version"],
            calculated_at=now,
        )
        db.add(score_rec)

        # 3. Aggiorna stato assegnazione a COMPLETED
        assignment.status = TestStatus.COMPLETED
        assignment.completed_at = now

        # F09 fase 1: nessun conferimento alla ricerca senza un protocollo e
        # autorizzazioni verificabili. Il consenso generico non associa studi.
        # Il salvataggio clinico resta indipendente dalla ricerca sospesa.

        db.commit()

    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Errore durante il salvataggio dei risultati: {exc}")

    return templates.TemplateResponse(
        request=request,
        name="patient/completed.html",
        context={
            "test_title": assignment.test_definition.title,
        },
    )
