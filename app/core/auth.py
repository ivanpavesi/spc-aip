"""Gestione autenticazione, sessioni crittografiche e autorizzazioni per ruoli (STEP 2)."""

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import generate_secure_token, hash_token, verify_password
from app.db.models.user import AuthSession, User, UserRole
from app.db.session import get_db

SESSION_COOKIE_NAME = "aip_session"
SESSION_LIFETIME_DAYS = 7


def create_user_session(db: Session, user: User, mfa_verified: bool = False) -> str:
    """Crea una nuova sessione persistente nel DB e restituisce il raw token per il cookie."""
    raw_token = generate_secure_token(32)
    token_hash = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_LIFETIME_DAYS)

    session_record = AuthSession(
        user_id=user.id,
        token_hash=token_hash,
        mfa_verified=mfa_verified,
        expires_at=expires_at,
    )
    db.add(session_record)
    db.commit()
    return raw_token


def get_session_from_cookie(request: Request, db: Session) -> Optional[AuthSession]:
    """Recupera la sessione valida dal cookie HttpOnly firmato."""
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        return None

    token_hash = hash_token(raw_token)
    now = datetime.now(timezone.utc)

    session_record = (
        db.query(AuthSession)
        .filter(
            AuthSession.token_hash == token_hash,
            AuthSession.expires_at > now,
        )
        .first()
    )
    return session_record


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Restituisce l'utente autenticato corrente, oppure None se anonimo."""
    session_record = get_session_from_cookie(request, db)
    if not session_record:
        return None

    user = db.query(User).filter(User.id == session_record.user_id, User.is_active == True).first()
    return user


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Dependency che richiede un utente autenticato con sessione valida."""
    user = get_current_user_optional(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessione non valida o scaduta. Effettuare l'accesso.",
        )
    return user


def require_role(required_role: UserRole) -> Callable:
    """Dependency factory per autorizzazione basata su ruoli (RBAC)."""
    def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role != required_role and user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Accesso negato: richiesto ruolo {required_role.value}",
            )
        return user
    return role_checker


require_therapist = require_role(UserRole.THERAPIST)
require_researcher = require_role(UserRole.RESEARCHER)
require_admin = require_role(UserRole.ADMIN)


def revoke_session(request: Request, db: Session) -> None:
    """Revoca la sessione corrente invalidandola nel database."""
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        token_hash = hash_token(raw_token)
        db.query(AuthSession).filter(AuthSession.token_hash == token_hash).delete()
        db.commit()
