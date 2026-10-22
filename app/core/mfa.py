"""Transazioni del ciclo di vita MFA; nessuna chiamata a servizi esterni."""
import hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy import case, or_, update
from sqlalchemy.orm import Session

from app.core.security import matching_totp_counter, verify_password, hash_token
from app.db.models.audit import AuditEvent
from app.db.models.user import AuthSession, User

ENROLLMENT_SECONDS = 300


def audit(db, user, action, request=None, target_id=None):
    event = AuditEvent(actor_id=user.id, actor_role=user.role.value, action=action,
                      resource_type="User", resource_id=target_id or user.id,
                      ip_address=request.client.host if request and request.client else None)
    db.add(event)
    return event


def reject(db, user, request, action="MFA_VERIFICATION_FAILED", status=401):
    audit(db, user, action, request)
    db.commit()  # conserva tentativi e audit anche in caso di rifiuto
    raise HTTPException(status, "Verifica di sicurezza non riuscita o scaduta. Riprovare o richiedere assistenza.")


def csrf_token(request, raw_token=None):
    from app.core.auth import SESSION_COOKIE_NAME
    return hash_token("mfa-csrf:" + (raw_token or request.cookies.get(SESSION_COOKIE_NAME, "")))


def same_origin(request: Request, token: str):
    """Protegge i POST MFA da CSRF anche con cookie preesistenti."""
    if not token or not token.isascii() or not hmac.compare_digest(csrf_token(request), token):
        raise HTTPException(403, "Token CSRF non valido.")
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Origine non consentita.")
    if origin:
        try:
            parsed = urlsplit(origin)
            base = urlsplit(str(request.base_url))
        except ValueError:
            raise HTTPException(403, "Origine non consentita.") from None
        if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
            raise HTTPException(403, "Origine non consentita.")


def guard_user(db: Session, user: User, *, require_active=True):
    """UPDATE condizionale: serializza anche login senza MFA con enrollment/reset.

    Il confronto versione evita sessioni create con una fotografia obsoleta del
    fattore. Il lock della riga dura fino al commit insieme a sessione e audit.
    Funziona su PostgreSQL e SQLite, senza mutex locali al processo.
    """
    changed = db.execute(update(User).where(
        User.id == user.id, User.mfa_version == user.mfa_version,
        User.hashed_password == user.hashed_password,
        User.is_active.is_(True) if require_active else True,
    ).values(mfa_version=User.mfa_version).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Account modificato. Effettuare nuovamente l'accesso.")
    db.refresh(user)


def attempt(db, user, request):
    now = datetime.now(timezone.utc)
    result = db.execute(update(User).where(
        User.id == user.id,
        or_(User.mfa_locked_until.is_(None), User.mfa_locked_until <= now),
    ).values(
        mfa_failures=case((User.mfa_locked_until <= now, 1), else_=User.mfa_failures + 1),
        mfa_locked_until=case(
            (User.mfa_locked_until <= now, None),
            (User.mfa_failures >= 4, now + timedelta(minutes=5)), else_=None),
    ).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        reject(db, user, request, "MFA_RATE_LIMITED", 429)
    # I successivi aggiornamenti ORM devono vedere anche il tentativo appena scritto.
    db.refresh(user)


def consume_totp(db, user, code, request):
    attempt(db, user, request)
    counter = matching_totp_counter(user.totp_secret, code)
    if counter is None:
        reject(db, user, request)
    result = db.execute(update(User).where(
        User.id == user.id, User.mfa_version == user.mfa_version,
        User.totp_enabled.is_(True), User.totp_secret == user.totp_secret,
        or_(User.totp_last_counter.is_(None), User.totp_last_counter < counter),
    ).values(totp_last_counter=counter, mfa_failures=0, mfa_locked_until=None)
      .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        reject(db, user, request, "MFA_REPLAY_REJECTED")
    audit(db, user, "MFA_VERIFIED", request)
    db.refresh(user)


def reauthenticate(db, user, password, code, request):
    if not verify_password(password, user.hashed_password):
        attempt(db, user, request)
        reject(db, user, request, "MFA_REAUTH_FAILED")
    if user.totp_enabled:
        consume_totp(db, user, code, request)
    else:
        db.execute(update(User).where(User.id == user.id).values(mfa_failures=0, mfa_locked_until=None))


def invalidate_sessions(db, user):
    user.mfa_version += 1
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete(synchronize_session=False)
