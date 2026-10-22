"""Router per autenticazione operatori, gestione sessioni e 2FA TOTP (STEP 2)."""

from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.auth import (
    SESSION_COOKIE_NAME,
    create_user_session,
    get_enrollment_user,
    get_session_from_cookie,
    get_current_user_optional,
    revoke_session,
    rotate_session_token,
    set_session_cookie,
)
from app.core import mfa
from app.services.encryption import encryption_service
from app.core.security import (
    generate_totp_secret,
    matching_totp_counter,
    read_totp_secret,
    verify_password,
)
from app.db.models.user import User, UserRole
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["Autenticazione Operatori"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/login", response_class=HTMLResponse, summary="Pagina di Accesso")
def login_page(
    request: Request,
    role: Optional[str] = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    # Se già autenticato, reindirizza alla dashboard opportuna
    user = get_current_user_optional(request, db)
    if user:
        if user.role == UserRole.THERAPIST:
            return RedirectResponse(url="/therapist/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        elif user.role == UserRole.RESEARCHER:
            return RedirectResponse(url="/researcher/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        elif user.role == UserRole.ADMIN:
            return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "role_hint": role or "THERAPIST",
            "error_msg": None,
        },
    )


@router.post("/login", response_class=HTMLResponse, summary="Esecuzione Login")
def handle_login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    totp_code: Optional[str] = Form(None),
    role_hint: Optional[str] = Form(None),
    db: Session = Depends(get_db),
) -> Response:
    raw_identifier = email.strip().lower()
    clean_email = f"{raw_identifier}@spc.it" if "@" not in raw_identifier else raw_identifier
    user = db.query(User).filter(User.email == clean_email, User.is_active == True).first()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "role_hint": role_hint or "THERAPIST",
                "error_msg": "Credenziali non valide. Verifica username o email e password.",
                "entered_email": email.strip(),
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    mfa.guard_user(db, user)
    # Fail closed anche per segreto assente, corrotto o non decifrabile.
    if user.totp_enabled:
        if not read_totp_secret(user.totp_secret):
            mfa.reject(db, user, request, "MFA_CONFIGURATION_INVALID")
        if not totp_code:
            mfa.audit(db, user, "MFA_CODE_REQUIRED", request)
            db.commit()
            return templates.TemplateResponse(
                request=request,
                name="auth/login.html",
                context={
                    "role_hint": role_hint or user.role.value,
                    "require_totp": True,
                    "error_msg": "Codice 2FA non valido o mancante. Inserisci il codice a 6 cifre dall'app di autenticazione.",
                    "entered_email": clean_email,
                },
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        mfa.consume_totp(db, user, totp_code, request)

    # Creazione sessione e consumo TOTP nella stessa transazione.
    session_token = create_user_session(db, user, mfa_verified=user.totp_enabled)

    # Determina destinazione in base al ruolo
    redirect_target = "/therapist/dashboard"
    if user.role == UserRole.RESEARCHER:
        redirect_target = "/researcher/dashboard"
    elif user.role == UserRole.ADMIN:
        redirect_target = "/admin/dashboard"

    if user.totp_required and not user.totp_enabled:
        redirect_target = "/auth/totp/setup"

    redirect_response = RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(redirect_response, session_token)
    return redirect_response


def setup_response(request, user, secret=None, pending=False, session_token=None):
    response = templates.TemplateResponse(
        request=request, name="auth/totp_setup.html",
        context={"user": user, "secret": secret, "pending": pending, "csrf_token": mfa.csrf_token(request, session_token)},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )
    if session_token:
        set_session_cookie(response, session_token)
    return response


@router.get("/totp/setup", response_class=HTMLResponse)
def totp_setup_page(request: Request, user: User = Depends(get_enrollment_user),
                    db: Session = Depends(get_db)):
    # Nessuna mutazione o esposizione del segreto attraverso GET.
    record = get_session_from_cookie(request, db)
    return setup_response(request, user, pending=bool(record.totp_pending_secret))


@router.post("/totp/setup", response_class=HTMLResponse)
def totp_begin(request: Request, password: str = Form(...),
               current_code: str = Form(""), csrf_token: str = Form(""), user: User = Depends(get_enrollment_user),
               db: Session = Depends(get_db)):
    mfa.same_origin(request, csrf_token)
    mfa.guard_user(db, user)
    mfa.reauthenticate(db, user, password, current_code, request)
    record = get_session_from_cookie(request, db)
    # Un'altra transazione potrebbe aver revocato la sessione prima del lock.
    if not record or record.mfa_version != user.mfa_version:
        mfa.reject(db, user, request, "MFA_ENROLLMENT_STALE")
    secret = generate_totp_secret()
    record.totp_pending_secret = encryption_service.encrypt_text(secret)
    record.totp_pending_at = datetime.now(timezone.utc)
    mfa.audit(db, user, "MFA_ENROLLMENT_STARTED", request)
    session_token = rotate_session_token(request, db)
    db.commit()
    return setup_response(request, user, secret=secret, pending=True, session_token=session_token)


@router.post("/totp/verify", response_class=HTMLResponse)
def totp_verify(request: Request, code: str = Form(...), csrf_token: str = Form(""),
                user: User = Depends(get_enrollment_user), db: Session = Depends(get_db)):
    mfa.same_origin(request, csrf_token)
    mfa.guard_user(db, user)
    record = get_session_from_cookie(request, db)
    now = datetime.now(timezone.utc)
    pending_at = record.totp_pending_at if record else None
    if pending_at and pending_at.tzinfo is None:
        # SQLite restituisce datetime naive; PostgreSQL conserva l'offset.
        pending_at = pending_at.replace(tzinfo=timezone.utc)
    if (not record or record.mfa_version != user.mfa_version or not record.totp_pending_secret
            or not pending_at or pending_at > now
            or pending_at < now - timedelta(seconds=mfa.ENROLLMENT_SECONDS)):
        mfa.reject(db, user, request, "MFA_ENROLLMENT_EXPIRED")
    mfa.attempt(db, user, request)
    secret = read_totp_secret("enc:" + record.totp_pending_secret)
    counter = matching_totp_counter(secret, code)
    if counter is None:
        mfa.reject(db, user, request)
    user.totp_secret = "enc:" + record.totp_pending_secret
    user.totp_enabled = True
    user.totp_required = True
    user.totp_last_counter = counter
    user.mfa_failures = 0
    user.mfa_locked_until = None
    mfa.invalidate_sessions(db, user)
    db.flush()
    mfa.audit(db, user, "MFA_ACTIVATED", request)
    # Ruota il cookie; soltanto questa nuova sessione è verificata.
    token = create_user_session(db, user, mfa_verified=True)
    response = RedirectResponse("/auth/login", status_code=303)
    set_session_cookie(response, token)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/logout", summary="Logout Operatore")
def logout(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    revoke_session(request, db)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
