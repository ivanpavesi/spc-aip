"""Router per l'Area Amministrazione (STEP 2, 4, 6, 7).

Fornisce la governance completa della piattaforma per l'Amministratore:
1. Gestione Utenze e Ruoli (creazione, cambio ruolo, reset password, reset 2FA, attivazione/disattivazione).
2. Gestione Catalogo Questionari e Regole di Scoring (creazione, modifica schema item, cut-off).
3. Gestione Pulsanti Dinamici di Analisi Clinica SPC/APC (creazione, prompt di sistema, ordinamento, attivazione).
4. Configurazione Provider e Modelli AI (selezione provider, API key, modelli, test di connessione).
5. Gestione Biblioteca Documenti Scientifici e Manuali RAG (upload PDF/DOCX/TXT, indicizzazione testo).
6. Consultazione e monitoraggio dell'Audit Trail di sicurezza.
"""

import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.auth import require_admin, rotate_session_token, set_session_cookie
from app.core import mfa
from app.core.security import hash_password
from app.db.models.admin_config import ClinicalAnalysisButton, ScientificDocument, SystemSetting
from app.db.models.audit import AuditEvent
from app.db.models.test_engine import TestDefinition
from app.db.models.user import AuthSession, Therapist, User, UserRole
from app.db.session import get_db
from app.services.ai.provider import get_ai_provider_for_connection_test
from app.services.ai.policy import AIProviderConfigurationError
from app.services.documents import extract_text_from_file

router = APIRouter(prefix="/admin", tags=["Amministrazione"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def log_admin_audit(
    db: Session,
    actor: User,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None,
    request: Optional[Request] = None,
) -> None:
    """Registra un evento nell'audit trail di sicurezza."""
    ip = request.client.host if request and request.client else None
    audit = AuditEvent(
        actor_id=actor.id,
        actor_role=actor.role.value if actor else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip,
        technical_details=details,
    )
    db.add(audit)


# -----------------------------------------------------------------------------
# 1. Dashboard Amministratore Principale
# -----------------------------------------------------------------------------

@router.get("/dashboard", response_class=HTMLResponse, summary="Dashboard Amministratore")
def admin_dashboard(
    request: Request,
    tab: str = Query("users"),
    msg: Optional[str] = Query(None),
    err: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    users_list = db.query(User).order_by(User.created_at.desc()).all()
    tests_list = db.query(TestDefinition).order_by(TestDefinition.code.asc()).all()
    buttons_list = db.query(ClinicalAnalysisButton).order_by(ClinicalAnalysisButton.display_order.asc()).all()
    documents_list = db.query(ScientificDocument).order_by(ScientificDocument.created_at.desc()).all()
    
    settings_rows = db.query(SystemSetting).all()
    settings_map = {s.key: s.value for s in settings_rows}

    recent_audits = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(40).all()

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "user": user,
            "active_tab": tab,
            "msg": msg,
            "err": err,
            "users": users_list,
            "tests": tests_list,
            "buttons": buttons_list,
            "documents": documents_list,
            "settings": settings_map,
            "audits": recent_audits,
        },
    )


# -----------------------------------------------------------------------------
# 2. Gestione Utenze e Ruoli
# -----------------------------------------------------------------------------

@router.post("/users/new", summary="Creazione Nuovo Utente da Amministratore")
def create_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    full_name: Optional[str] = Form(None),
    license_number: Optional[str] = Form(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    clean_email = email.strip().lower()
    existing = db.query(User).filter(User.email == clean_email).first()
    if existing:
        return RedirectResponse(
            url="/admin/dashboard?tab=users&err=Esiste+gi%C3%A0+un+utente+con+questa+email",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        user_role = UserRole(role.upper())
    except ValueError:
        return RedirectResponse(
            url="/admin/dashboard?tab=users&err=Ruolo+specificato+non+valido",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if len(password) < 3:
        return RedirectResponse(
            url="/admin/dashboard?tab=users&err=La+password+deve+contenere+almeno+3+caratteri",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    new_user = User(
        email=clean_email,
        hashed_password=hash_password(password),
        role=user_role,
        is_active=True,
    )
    db.add(new_user)
    db.flush()

    # Se l'utente è terapeuta, crea automaticamente la scheda professionale
    if user_role == UserRole.THERAPIST:
        name = full_name.strip() if full_name else clean_email.split("@")[0].replace(".", " ").title()
        lic = license_number.strip() if license_number else "In fase di inserimento"
        therapist_profile = Therapist(
            user_id=new_user.id,
            full_name=name,
            license_number=lic,
        )
        db.add(therapist_profile)

    log_admin_audit(
        db,
        actor=user,
        action="USER_CREATED",
        resource_type="User",
        resource_id=new_user.id,
        details={"email": clean_email, "role": user_role.value},
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=users&msg=Nuovo+utente+creato+con+successo",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/users/{user_id}/change-role", summary="Modifica Ruolo Utente")
def change_user_role(
    user_id: str,
    request: Request,
    new_role: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Utente non trovato.")

    # Impedisci all'amministratore di declassare se stesso per evitare lock-out
    if target_user.id == user.id:
        return RedirectResponse(
            url="/admin/dashboard?tab=users&err=Non+puoi+modificare+il+ruolo+del+tuo+stesso+account",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        role_enum = UserRole(new_role.upper())
    except ValueError:
        return RedirectResponse(
            url="/admin/dashboard?tab=users&err=Ruolo+non+valido",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    old_role = target_user.role.value
    target_user.role = role_enum

    # Se promosso a terapeuta e non ha il profilo, crealo
    if role_enum == UserRole.THERAPIST:
        profile = db.query(Therapist).filter(Therapist.user_id == target_user.id).first()
        if not profile:
            db.add(Therapist(
                user_id=target_user.id,
                full_name=target_user.email.split("@")[0].replace(".", " ").title(),
                license_number="In fase di inserimento",
            ))

    log_admin_audit(
        db,
        actor=user,
        action="USER_ROLE_CHANGED",
        resource_type="User",
        resource_id=target_user.id,
        details={"old_role": old_role, "new_role": role_enum.value},
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=users&msg=Ruolo+utente+aggiornato",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/users/{user_id}/reset-password", summary="Reset Password Utente da Amministratore")
def reset_user_password(
    user_id: str,
    request: Request,
    new_password: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Utente non trovato.")

    if len(new_password) < 3:
        return RedirectResponse(
            url="/admin/dashboard?tab=users&err=La+password+deve+contenere+almeno+3+caratteri",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    target_user.hashed_password = hash_password(new_password)
    # Invalida tutte le sessioni aperte dell'utente per sicurezza
    db.query(AuthSession).filter(AuthSession.user_id == target_user.id).delete()

    log_admin_audit(
        db,
        actor=user,
        action="PASSWORD_RESET_BY_ADMIN",
        resource_type="User",
        resource_id=target_user.id,
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=users&msg=Password+resettata+e+sessioni+revocate",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/users/{user_id}/reset-totp", response_class=HTMLResponse)
def reset_totp_page(user_id: str, request: Request, user: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Utente non trovato.")
    return templates.TemplateResponse(request=request, name="admin/totp_reset.html",
        context={"user": user, "target": target, "csrf_token": mfa.csrf_token(request)},
        headers={"Cache-Control": "no-store"})


@router.post("/users/{user_id}/reset-totp", summary="Reset protetto del fattore TOTP")
def reset_user_totp(user_id: str, request: Request, password: str = Form(...),
                    current_code: str = Form(""), csrf_token: str = Form(""),
                    identity_confirmed: str = Form(""),
                    user: User = Depends(require_admin), db: Session = Depends(get_db)):
    mfa.same_origin(request, csrf_token)
    if user_id == user.id or identity_confirmed != "yes":
        mfa.reject(db, user, request, "MFA_RESET_DENIED", 403)
    mfa.guard_user(db, user)
    if user.role != UserRole.ADMIN or not user.totp_enabled:
        mfa.reject(db, user, request, "MFA_RESET_DENIED", 403)
    mfa.reauthenticate(db, user, password, current_code, request)
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(404, "Utente non trovato.")
    mfa.guard_user(db, target_user, require_active=False)
    target_user.totp_enabled = False
    target_user.totp_secret = None
    target_user.totp_required = True
    target_user.totp_last_counter = None
    target_user.mfa_failures = 0
    target_user.mfa_locked_until = None
    mfa.invalidate_sessions(db, target_user)
    event = mfa.audit(db, user, "USER_TOTP_RESET", request, target_id=target_user.id)
    event.technical_details = {"identity_proofing": "operator_confirmed_independent_channel"}
    token = rotate_session_token(request, db)
    db.commit()
    response = RedirectResponse("/admin/dashboard?tab=users&msg=2FA+resettata:+nuova+configurazione+richiesta", status_code=303)
    set_session_cookie(response, token)
    return response


@router.post("/users/{user_id}/toggle-active", summary="Attiva/Disattiva Utente")
def toggle_user_active(
    user_id: str,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Utente non trovato.")

    # Non disattivare se stesso
    if target_user.id != user.id:
        target_user.is_active = not target_user.is_active
        if not target_user.is_active:
            # Revoca le sessioni attive
            db.query(AuthSession).filter(AuthSession.user_id == target_user.id).delete()

        log_admin_audit(
            db,
            actor=user,
            action="USER_STATUS_TOGGLED",
            resource_type="User",
            resource_id=target_user.id,
            details={"is_active": target_user.is_active},
            request=request,
        )
        db.commit()

    return RedirectResponse(url="/admin/dashboard?tab=users&msg=Stato+utente+aggiornato", status_code=status.HTTP_303_SEE_OTHER)


# -----------------------------------------------------------------------------
# 3. Gestione Catalogo Questionari e Regole di Scoring
# -----------------------------------------------------------------------------

@router.get("/tests/new", response_class=HTMLResponse, summary="Pagina Nuovo Questionario")
def new_test_page(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    # Esempio di schema JSON predefinito per agevolare l'amministratore
    sample_items = {
        "items": [
            {
                "id": "item_1",
                "text": "Esempio affermazione test clinico",
                "options": [
                    {"label": "Per nulla", "value": 0},
                    {"label": "Un poco", "value": 1},
                    {"label": "Moderatamente", "value": 2},
                    {"label": "Molto", "value": 3}
                ]
            }
        ]
    }
    sample_rules = {
        "method": "SUM",
        "subscales": {},
        "cutoffs": [
            {"min": 0, "max": 13, "label": "Minima / Assente"},
            {"min": 14, "max": 19, "label": "Lieve"},
            {"min": 20, "max": 28, "label": "Moderata"},
            {"min": 29, "max": 63, "label": "Grave"}
        ]
    }

    return templates.TemplateResponse(
        request=request,
        name="admin/test_edit.html",
        context={
            "user": user,
            "test": None,
            "sample_items_json": json.dumps(sample_items, indent=2, ensure_ascii=False),
            "sample_rules_json": json.dumps(sample_rules, indent=2, ensure_ascii=False),
            "error_msg": None,
        },
    )


@router.post("/tests/new", summary="Salva Nuovo Questionario")
def create_test(
    request: Request,
    code: str = Form(...),
    title: str = Form(...),
    version: str = Form("1.0.0"),
    description: Optional[str] = Form(None),
    items_schema_json: str = Form(...),
    scoring_rules_json: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    clean_code = code.strip().upper()
    existing = db.query(TestDefinition).filter(TestDefinition.code == clean_code).first()
    if existing:
        return templates.TemplateResponse(
            request=request,
            name="admin/test_edit.html",
            context={
                "user": user,
                "test": None,
                "sample_items_json": items_schema_json,
                "sample_rules_json": scoring_rules_json,
                "error_msg": f"Esiste già un questionario con la sigla '{clean_code}'.",
            },
            status_code=400,
        )

    # Validazione formati JSON
    try:
        items_dict = json.loads(items_schema_json)
        if "items" not in items_dict or not isinstance(items_dict["items"], list):
            raise ValueError("Lo schema item deve contenere una lista sotto la chiave 'items'.")
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="admin/test_edit.html",
            context={
                "user": user,
                "test": None,
                "sample_items_json": items_schema_json,
                "sample_rules_json": scoring_rules_json,
                "error_msg": f"Errore nel JSON degli Item: {str(exc)}",
            },
            status_code=400,
        )

    try:
        rules_dict = json.loads(scoring_rules_json)
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="admin/test_edit.html",
            context={
                "user": user,
                "test": None,
                "sample_items_json": items_schema_json,
                "sample_rules_json": scoring_rules_json,
                "error_msg": f"Errore nel JSON delle Regole di Scoring: {str(exc)}",
            },
            status_code=400,
        )

    new_test = TestDefinition(
        code=clean_code,
        title=title.strip(),
        version=version.strip(),
        description=description.strip() if description else None,
        items_schema=items_dict,
        scoring_rules=rules_dict,
        is_active=True,
    )
    db.add(new_test)
    log_admin_audit(
        db,
        actor=user,
        action="TEST_DEFINITION_CREATED",
        resource_type="TestDefinition",
        resource_id=new_test.id,
        details={"code": clean_code, "items_count": len(items_dict.get("items", []))},
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=tests&msg=Nuovo+questionario+creato+con+successo",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/tests/{test_id}", response_class=HTMLResponse, summary="Dettaglio e Modifica Questionario")
def edit_test_page(
    test_id: str,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    test_def = db.query(TestDefinition).filter(TestDefinition.id == test_id).first()
    if not test_def:
        raise HTTPException(status_code=404, detail="Questionario non trovato.")

    return templates.TemplateResponse(
        request=request,
        name="admin/test_edit.html",
        context={
            "user": user,
            "test": test_def,
            "sample_items_json": json.dumps(test_def.items_schema, indent=2, ensure_ascii=False),
            "sample_rules_json": json.dumps(test_def.scoring_rules, indent=2, ensure_ascii=False),
            "error_msg": None,
        },
    )


@router.post("/tests/{test_id}/edit", summary="Salva Modifiche Questionario")
def update_test(
    test_id: str,
    request: Request,
    title: str = Form(...),
    version: str = Form(...),
    description: Optional[str] = Form(None),
    items_schema_json: str = Form(...),
    scoring_rules_json: str = Form(...),
    is_active: bool = Form(False),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    test_def = db.query(TestDefinition).filter(TestDefinition.id == test_id).first()
    if not test_def:
        raise HTTPException(status_code=404, detail="Questionario non trovato.")

    try:
        items_dict = json.loads(items_schema_json)
        rules_dict = json.loads(scoring_rules_json)
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="admin/test_edit.html",
            context={
                "user": user,
                "test": test_def,
                "sample_items_json": items_schema_json,
                "sample_rules_json": scoring_rules_json,
                "error_msg": f"Errore sintattico nel JSON: {str(exc)}",
            },
            status_code=400,
        )

    test_def.title = title.strip()
    test_def.version = version.strip()
    test_def.description = description.strip() if description else None
    test_def.items_schema = items_dict
    test_def.scoring_rules = rules_dict
    test_def.is_active = is_active

    log_admin_audit(
        db,
        actor=user,
        action="TEST_DEFINITION_UPDATED",
        resource_type="TestDefinition",
        resource_id=test_def.id,
        details={"code": test_def.code, "version": test_def.version},
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=tests&msg=Questionario+aggiornato+con+successo",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/tests/{test_id}/toggle-active", summary="Attiva/Disattiva Questionario")
def toggle_test_active(
    test_id: str,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    test_def = db.query(TestDefinition).filter(TestDefinition.id == test_id).first()
    if not test_def:
        raise HTTPException(status_code=404, detail="Questionario non trovato.")

    test_def.is_active = not test_def.is_active
    log_admin_audit(
        db,
        actor=user,
        action="TEST_STATUS_TOGGLED",
        resource_type="TestDefinition",
        resource_id=test_def.id,
        details={"is_active": test_def.is_active},
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=tests&msg=Stato+questionario+aggiornato",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# -----------------------------------------------------------------------------
# 4. Gestione Pulsanti di Analisi Clinica Dinamici
# -----------------------------------------------------------------------------

@router.post("/buttons/new", summary="Aggiungi Pulsante di Analisi Clinica")
def create_clinical_button(
    request: Request,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    system_prompt: str = Form(...),
    display_order: int = Form(0),
    version: str = Form("1.0-SPC"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    clean_name = name.strip()
    existing = db.query(ClinicalAnalysisButton).filter(ClinicalAnalysisButton.name == clean_name).first()
    if existing:
        return RedirectResponse(
            url="/admin/dashboard?tab=buttons&err=Esiste+gi%C3%A0+un+pulsante+con+questo+nome",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    btn = ClinicalAnalysisButton(
        name=clean_name,
        description=description.strip() if description else None,
        system_prompt=system_prompt.strip(),
        display_order=display_order,
        version=version.strip(),
        is_active=True,
    )
    db.add(btn)
    log_admin_audit(
        db,
        actor=user,
        action="ANALYSIS_BUTTON_CREATED",
        resource_type="ClinicalAnalysisButton",
        resource_id=btn.id,
        details={"name": clean_name},
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=buttons&msg=Nuovo+pulsante+di+analisi+aggiunto",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/buttons/{button_id}/edit", summary="Modifica Pulsante di Analisi Clinica")
def edit_clinical_button(
    button_id: str,
    request: Request,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    system_prompt: str = Form(...),
    display_order: int = Form(0),
    version: str = Form("1.0-SPC"),
    is_active: bool = Form(False),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    btn = db.query(ClinicalAnalysisButton).filter(ClinicalAnalysisButton.id == button_id).first()
    if not btn:
        raise HTTPException(status_code=404, detail="Pulsante non trovato.")

    btn.name = name.strip()
    btn.description = description.strip() if description else None
    btn.system_prompt = system_prompt.strip()
    btn.display_order = display_order
    btn.version = version.strip()
    btn.is_active = is_active

    log_admin_audit(
        db,
        actor=user,
        action="ANALYSIS_BUTTON_UPDATED",
        resource_type="ClinicalAnalysisButton",
        resource_id=btn.id,
        details={"name": btn.name},
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=buttons&msg=Pulsante+di+analisi+aggiornato",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/buttons/{button_id}/toggle", summary="Attiva/Disattiva Pulsante di Analisi")
def toggle_clinical_button(
    button_id: str,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    btn = db.query(ClinicalAnalysisButton).filter(ClinicalAnalysisButton.id == button_id).first()
    if not btn:
        raise HTTPException(status_code=404, detail="Pulsante non trovato.")

    btn.is_active = not btn.is_active
    log_admin_audit(
        db,
        actor=user,
        action="ANALYSIS_BUTTON_TOGGLED",
        resource_type="ClinicalAnalysisButton",
        resource_id=btn.id,
        details={"name": btn.name, "is_active": btn.is_active},
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=buttons&msg=Stato+pulsante+aggiornato",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/buttons/{button_id}/delete", summary="Elimina Pulsante di Analisi")
def delete_clinical_button(
    button_id: str,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    btn = db.query(ClinicalAnalysisButton).filter(ClinicalAnalysisButton.id == button_id).first()
    if not btn:
        raise HTTPException(status_code=404, detail="Pulsante non trovato.")

    log_admin_audit(
        db,
        actor=user,
        action="ANALYSIS_BUTTON_DELETED",
        resource_type="ClinicalAnalysisButton",
        resource_id=btn.id,
        details={"name": btn.name},
        request=request,
    )
    db.delete(btn)
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=buttons&msg=Pulsante+eliminato",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# -----------------------------------------------------------------------------
# 5. Configurazione AI & Provider
# -----------------------------------------------------------------------------

@router.post("/settings/ai", summary="Aggiorna Impostazioni Provider AI Multi-LLM")
def update_ai_settings(
    request: Request,
    ai_provider: str = Form("HEURISTIC_OFFLINE"),
    gemini_api_key: Optional[str] = Form(None),
    gemini_model: str = Form("gemini-1.5-pro"),
    openai_api_key: Optional[str] = Form(None),
    openai_model: str = Form("gpt-4o"),
    anthropic_api_key: Optional[str] = Form(None),
    anthropic_model: str = Form("claude-3-5-sonnet-20241022"),
    custom_ai_base_url: Optional[str] = Form(None),
    custom_ai_api_key: Optional[str] = Form(None),
    custom_ai_model: Optional[str] = Form(None),
    ai_temperature: str = Form("0.2"),
    ai_system_preamble: Optional[str] = Form(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    settings_to_update = {
        "AI_PROVIDER": ai_provider.strip().upper(),
        "GEMINI_MODEL": gemini_model.strip(),
        "OPENAI_MODEL": openai_model.strip(),
        "ANTHROPIC_MODEL": anthropic_model.strip(),
        "AI_TEMPERATURE": ai_temperature.strip(),
    }
    if gemini_api_key and gemini_api_key.strip():
        settings_to_update["GEMINI_API_KEY"] = gemini_api_key.strip()
    if openai_api_key and openai_api_key.strip():
        settings_to_update["OPENAI_API_KEY"] = openai_api_key.strip()
    if anthropic_api_key and anthropic_api_key.strip():
        settings_to_update["ANTHROPIC_API_KEY"] = anthropic_api_key.strip()
    if custom_ai_base_url and custom_ai_base_url.strip():
        settings_to_update["CUSTOM_AI_BASE_URL"] = custom_ai_base_url.strip()
    if custom_ai_api_key and custom_ai_api_key.strip():
        settings_to_update["CUSTOM_AI_API_KEY"] = custom_ai_api_key.strip()
    if custom_ai_model and custom_ai_model.strip():
        settings_to_update["CUSTOM_AI_MODEL"] = custom_ai_model.strip()
    if ai_system_preamble:
        settings_to_update["AI_SYSTEM_PREAMBLE"] = ai_system_preamble.strip()

    for k, v in settings_to_update.items():
        row = db.query(SystemSetting).filter(SystemSetting.key == k).first()
        if row:
            row.value = v
        else:
            db.add(SystemSetting(key=k, value=v))

    log_admin_audit(
        db,
        actor=user,
        action="AI_SETTINGS_UPDATED",
        resource_type="SystemSetting",
        details={"active_provider": ai_provider},
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=ai&msg=Configurazione+multi-LLM+salvata+con+successo",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/settings/ai/test-connection", summary="Test Connessione Provider AI")
def test_ai_connection(
    request: Request,
    target_provider: Optional[str] = Form(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    try:
        provider = get_ai_provider_for_connection_test(target_provider, db)
    except AIProviderConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    is_ok, message = provider.test_connection()

    status_param = "msg" if is_ok else "err"
    import urllib.parse
    encoded_msg = urllib.parse.quote(message)

    return RedirectResponse(
        url=f"/admin/dashboard?tab=ai&{status_param}={encoded_msg}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# -----------------------------------------------------------------------------
# 6. Gestione Biblioteca Documenti Scientifici e RAG
# -----------------------------------------------------------------------------

@router.post("/documents/upload", summary="Carica Documento Scientifico o Manuale RAG")
async def upload_scientific_document(
    request: Request,
    title: str = Form(...),
    test_id: Optional[str] = Form(None),
    document_file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    filename = document_file.filename or "documento.txt"
    content_bytes = await document_file.read()

    extracted_text = extract_text_from_file(filename, content_bytes)
    if not extracted_text.strip():
        return RedirectResponse(
            url="/admin/dashboard?tab=docs&err=Impossibile+estrarre+testo+dal+file+caricato",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    file_ext = filename.split(".")[-1].lower() if "." in filename else "txt"
    clean_test_id = test_id if test_id and test_id.strip() else None

    doc = ScientificDocument(
        title=title.strip(),
        test_definition_id=clean_test_id,
        filename=filename,
        file_type=file_ext,
        extracted_text=extracted_text,
    )
    db.add(doc)
    log_admin_audit(
        db,
        actor=user,
        action="SCIENTIFIC_DOCUMENT_UPLOADED",
        resource_type="ScientificDocument",
        resource_id=doc.id,
        details={"title": title, "filename": filename, "chars_extracted": len(extracted_text)},
        request=request,
    )
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=docs&msg=Documento+scientifico+indicizzato+con+successo",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/documents/{doc_id}/delete", summary="Elimina Documento Scientifico")
def delete_scientific_document(
    doc_id: str,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    doc = db.query(ScientificDocument).filter(ScientificDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato.")

    log_admin_audit(
        db,
        actor=user,
        action="SCIENTIFIC_DOCUMENT_DELETED",
        resource_type="ScientificDocument",
        resource_id=doc.id,
        details={"title": doc.title},
        request=request,
    )
    db.delete(doc)
    db.commit()

    return RedirectResponse(
        url="/admin/dashboard?tab=docs&msg=Documento+scientifico+rimosso",
        status_code=status.HTTP_303_SEE_OTHER,
    )
