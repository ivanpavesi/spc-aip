"""Router per autenticazione operatori, gestione sessioni e 2FA TOTP (STEP 2)."""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.auth import (
    SESSION_COOKIE_NAME,
    create_user_session,
    get_current_user,
    get_current_user_optional,
    revoke_session,
)
from app.core.config import settings
from app.core.security import (
    generate_totp_secret,
    get_totp_uri,
    hash_password,
    verify_password,
    verify_totp_code,
)
from app.db.models.user import Therapist, User, UserRole
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

    # Verifica secondo fattore (TOTP) se attivo
    if user.totp_enabled and user.totp_secret:
        if not totp_code or not verify_totp_code(user.totp_secret, totp_code):
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

    # Creazione sessione
    session_token = create_user_session(db, user, mfa_verified=user.totp_enabled)

    # Determina destinazione in base al ruolo
    redirect_target = "/therapist/dashboard"
    if user.role == UserRole.RESEARCHER:
        redirect_target = "/researcher/dashboard"
    elif user.role == UserRole.ADMIN:
        redirect_target = "/admin/dashboard"

    redirect_response = RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)
    redirect_response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
        max_age=7 * 24 * 3600,
    )
    return redirect_response


@router.get("/totp/setup", response_class=HTMLResponse, summary="Configurazione 2FA TOTP")
def totp_setup_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if not user.totp_secret:
        user.totp_secret = generate_totp_secret()
        db.commit()

    otp_uri = get_totp_uri(user.totp_secret, user.email)

    return templates.TemplateResponse(
        request=request,
        name="auth/totp_setup.html",
        context={
            "user": user,
            "secret": user.totp_secret,
            "otp_uri": otp_uri,
            "error_msg": None,
        },
    )


@router.post("/totp/verify", response_class=HTMLResponse, summary="Verifica e Attivazione 2FA")
def totp_verify(
    request: Request,
    code: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    if not user.totp_secret or not verify_totp_code(user.totp_secret, code):
        otp_uri = get_totp_uri(user.totp_secret or "", user.email)
        return templates.TemplateResponse(
            request=request,
            name="auth/totp_setup.html",
            context={
                "user": user,
                "secret": user.totp_secret,
                "otp_uri": otp_uri,
                "error_msg": "Codice non valido. Assicurati che l'orologio del telefono sia sincronizzato.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user.totp_enabled = True
    db.commit()

    return RedirectResponse(url="/therapist/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout", summary="Logout Operatore")
def logout(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    revoke_session(request, db)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
