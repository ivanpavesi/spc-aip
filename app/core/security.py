"""Utilità di sicurezza, hashing e generazione di credenziali sicure.

Questo modulo garantisce che:
1. I token generati per i pazienti e le sessioni utilizzino il generatore crittografico `secrets`.
2. I token conservati nel database siano protetti da hashing irreversibile (SHA-256).
3. Le password siano protette tramite PBKDF2-HMAC-SHA256 con salt casuale (600.000 iterazioni).
4. Gli identificatori clinici e di ricerca (codici pseudonimi) siano privi di qualsiasi informazione personale.
"""

import binascii
import hashlib
import hmac
import secrets
from time import time
from typing import Tuple


def generate_secure_token(nbytes: int = 32) -> str:
    """Genera un token casuale crittograficamente sicuro URL-safe.

    Utilizza il modulo Python `secrets`, raccomandato per dati di sicurezza.
    """
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Calcola l'hash crittografico SHA-256 di un token di accesso.

    I token dei pazienti non vengono mai salvati in chiaro nel database:
    viene salvato esclusivamente il loro hash crittografico.
    """
    if not token:
        raise ValueError("Il token non può essere vuoto")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_pseudonym_code(prefix: str = "PR", nbytes: int = 4) -> str:
    """Genera un codice pseudonimo tecnico casuale privo di significato personale.

    Esempio: "PR-8F3A2B1C".
    Non contiene elementi derivati da nome, cognome, data di nascita o CF.
    """
    token = secrets.token_hex(nbytes).upper()
    return f"{prefix}-{token}"


def hash_password(password: str) -> str:
    """Genera un hash sicuro della password con salt casuale tramite PBKDF2-HMAC-SHA256.

    Formato restituito: "pbkdf2:sha256:600000$<salt_hex>$<hash_hex>"
    """
    if not password or len(password) < 3:
        raise ValueError("La password deve contenere almeno 3 caratteri")
    
    salt = secrets.token_bytes(16)
    iterations = 600_000
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2:sha256:{iterations}${salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica che una password in chiaro corrisponda all'hash memorizzato in tempo costante."""
    try:
        parts = hashed_password.split("$")
        if len(parts) != 3:
            return False
        meta, salt_hex, hash_hex = parts
        _, _, iterations_str = meta.split(":")
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)

        calculated = hashlib.pbkdf2_hmac(
            "sha256", plain_password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(calculated, expected_hash)
    except Exception:
        return False


def generate_totp_secret() -> str:
    """Genera una chiave segreta casuale Base32 per autenticazione a due fattori (TOTP)."""
    import pyotp
    return pyotp.random_base32()


def get_totp_uri(secret: str, account_name: str, issuer_name: str = "SPC-AIP") -> str:
    """Genera l'URI otpauth per configurare app di autenticazione (Google Authenticator, etc.)."""
    import pyotp
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=account_name, issuer_name=issuer_name)


def matching_totp_counter(secret: str, code: str, now=None):
    """Restituisce il contatore RFC 6238, senza consumarlo (vedi core.mfa)."""
    import pyotp
    if not secret or not code or len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    try:
        secret = read_totp_secret(secret)
        if not secret:
            return None
        totp = pyotp.TOTP(secret)
        counter = int(time() if now is None else now) // totp.interval
        # ASVS 5.0, 6.5.5: durata massima TOTP di 30 secondi.
        return counter if hmac.compare_digest(totp.generate_otp(counter), code) else None
    except (ValueError, TypeError, binascii.Error):
        return None


def verify_totp_code(secret: str, code: str) -> bool:
    """Solo verifica crittografica; i flussi autenticativi devono consumare il contatore."""
    return matching_totp_counter(secret, code) is not None


def read_totp_secret(stored):
    """Legge i segreti legacy; i nuovi fattori sono cifrati con la chiave esistente."""
    import base64
    from app.services.encryption import encryption_service, DecryptionError
    if not stored:
        return None
    try:
        secret = encryption_service.decrypt_text(stored[4:]) if stored.startswith("enc:") else stored
        if len(secret) < 16:
            return None
        base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
        return secret.upper()
    except (DecryptionError, ValueError, TypeError, binascii.Error):
        return None
