"""Recupero controllato dell'unico amministratore; nessun endpoint HTTP.

Eseguire solo con accesso amministrativo al server/DB, identità verificata e ticket
approvato. Richiede la password dell'account e conferma interattiva del suo UUID.
Non stampa né legge i segreti TOTP e non modifica password, chiavi o ruoli.
"""
import argparse
import getpass
import re

from fastapi import HTTPException
from app.core import mfa
from app.core.security import verify_password
from app.db.models.user import User, UserRole
from app.db.session import SessionLocal


def recover_admin_totp(db, user_id, password, ticket):
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{2,63}", ticket):
        raise ValueError("Usare il solo identificativo tecnico del ticket (3-64 caratteri A-Z, 0-9, trattino).")
    user = db.get(User, user_id)
    if not user or not user.is_active or user.role != UserRole.ADMIN:
        raise ValueError("È richiesto un amministratore attivo identificato tramite UUID.")
    mfa.guard_user(db, user)
    if user.role != UserRole.ADMIN:
        mfa.reject(db, user, None, "MFA_OPERATOR_RECOVERY_DENIED", 403)
    mfa.attempt(db, user, None)
    if not verify_password(password, user.hashed_password):
        mfa.reject(db, user, None, "MFA_OPERATOR_RECOVERY_DENIED")
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_required = True
    user.totp_last_counter = None
    user.mfa_failures = 0
    user.mfa_locked_until = None
    mfa.invalidate_sessions(db, user)
    event = mfa.audit(db, user, "MFA_OPERATOR_RECOVERY")
    # Solo riferimento tecnico, nessun nominativo o contenuto del ticket.
    event.technical_details = {"ticket": ticket, "channel": "server_cli"}
    db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--ticket", required=True)
    args = parser.parse_args()
    print("Questo comando revoca le sessioni del solo account indicato e richiede una nuova configurazione 2FA.")
    if input("Conferma digitando l'UUID completo dell'account: ") != args.user_id:
        parser.exit(1, "Conferma non valida: nessuna modifica.\n")
    password = getpass.getpass("Password attuale dell'amministratore: ")
    try:
        with SessionLocal() as db:
            recover_admin_totp(db, args.user_id, password, args.ticket)
    except (ValueError, HTTPException):
        parser.exit(1, "Recupero rifiutato. Verificare account, ticket e credenziali; consultare l'audit.\n")
    print("Recupero registrato. Accedere con la password e completare subito una nuova configurazione 2FA.")


if __name__ == "__main__":
    main()
