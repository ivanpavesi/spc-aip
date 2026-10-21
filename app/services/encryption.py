"""Modulo di crittografia applicativa per dati sanitari e identificativi (GDPR).

Questo modulo implementa la cifratura a livello applicativo (Application-Level Encryption)
per garantire che:
1. I dati anagrafici e i contenuti clinici siano cifrati prima del salvataggio nel database.
2. Anche in caso di leak o dump del database, i dati rimangano illeggibili senza la chiave.
3. La chiave crittografica sia custodita nell'ambiente del server e MAI nel database.
4. Non sia permessa alcuna memorizzazione silenziosa in chiaro in caso di fallimento.
5. Sia predisposta la rotazione delle chiavi tramite MultiFernet.
"""

import logging
from typing import List, Optional
from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from app.core.config import settings, validate_encryption_key

logger = logging.getLogger(__name__)


class EncryptionError(Exception):
    """Eccezione sollevata quando la cifratura del dato fallisce."""
    pass


class DecryptionError(Exception):
    """Eccezione sollevata quando la decifratura del dato fallisce o il token è corrotto."""
    pass


class EncryptionConfigurationError(Exception):
    """Eccezione sollevata quando la chiave di cifratura non è configurata o non è valida."""
    pass


class EncryptionService:
    """Servizio per la cifratura e decifratura di campi testuali sensibili.

    Utilizza Fernet (crittografia simmetrica basata su AES-128 in modalità CBC
    con autenticazione HMAC-SHA256 e timestamp per protezione dal replay).
    """

    def __init__(self, primary_key: Optional[str] = None, fallback_keys: Optional[List[str]] = None) -> None:
        """Inizializza il servizio crittografico.

        Args:
            primary_key: Chiave primaria di cifratura (base64 URL-safe, 32 byte).
                         Se non fornita, viene letta da settings.APP_ENCRYPTION_KEY.
            fallback_keys: Lista opzionale di chiavi precedenti per consentire
                           la lettura durante le procedure di rotazione.
        """
        key = settings.APP_ENCRYPTION_KEY if primary_key is None else primary_key
        if not key:
            raise EncryptionConfigurationError(
                "Nessuna chiave di cifratura configurata. Impostare APP_ENCRYPTION_KEY nel file .env."
            )

        keys_to_load = [key]
        if fallback_keys:
            keys_to_load.extend(fallback_keys)

        fernet_instances: List[Fernet] = []
        for k in keys_to_load:
            self._validate_key(k)
            fernet_instances.append(Fernet(k.encode("utf-8")))

        # MultiFernet usa la prima chiave per cifrare e le successive per decifrare
        self._multi_fernet = MultiFernet(fernet_instances)

    @staticmethod
    def _validate_key(key_str: str) -> None:
        """Verifica che la chiave rispetti rigorosamente i requisiti Fernet (32 byte base64)."""
        try:
            validate_encryption_key(key_str, production=settings.ENVIRONMENT == "production")
        except ValueError as exc:
            raise EncryptionConfigurationError(
                "Chiave di cifratura assente, non valida o non sicura per l'ambiente configurato."
            ) from exc

    def encrypt_text(self, plaintext: str) -> str:
        """Cifra una stringa di testo in chiaro e restituisce una stringa cifrata.

        NON fallbacka mai al testo in chiaro in caso di errore.
        
        Args:
            plaintext: Testo in chiaro da cifrare (es. nome, codice fiscale, note cliniche).

        Returns:
            Stringa cifrata e autenticata.
        """
        if plaintext is None:
            raise EncryptionError("Impossibile cifrare un valore nullo (None).")
        
        # Le stringhe vuote vengono trattate esplicitamente per non generare token ambigui
        if plaintext == "":
            return ""

        try:
            token_bytes = self._multi_fernet.encrypt(plaintext.encode("utf-8"))
            return token_bytes.decode("utf-8")
        except Exception as exc:
            logger.error("Errore durante la cifratura applicativa del dato sensibile.")
            raise EncryptionError(f"Cifratura del testo fallita: {exc}") from exc

    def decrypt_text(self, ciphertext: str) -> str:
        """Decifra una stringa cifrata e restituisce il testo in chiaro originale.

        Args:
            ciphertext: Stringa cifrata precedentemente da questo servizio.

        Returns:
            Testo in chiaro decifrato.

        Raises:
            DecryptionError: Se il token è corrotto, manomesso o la chiave non è corretta.
        """
        if ciphertext is None:
            raise DecryptionError("Impossibile decifrare un valore nullo (None).")
        
        if ciphertext == "":
            return ""

        try:
            plaintext_bytes = self._multi_fernet.decrypt(ciphertext.encode("utf-8"))
            return plaintext_bytes.decode("utf-8")
        except InvalidToken as exc:
            logger.warning("Tentativo di decifratura fallito: token non valido, manomesso o chiave errata.")
            raise DecryptionError("Dato cifrato non valido o chiave di decifratura non corrispondente.") from exc
        except Exception as exc:
            logger.error("Errore imprevisto durante la decifratura.")
            raise DecryptionError(f"Decifratura fallita: {exc}") from exc

    def rotate_token(self, ciphertext: str) -> str:
        """Rici-fra un token con la chiave primaria corrente se era stato cifrato con una chiave precedente."""
        if not ciphertext:
            return ""
        try:
            rotated = self._multi_fernet.rotate(ciphertext.encode("utf-8"))
            return rotated.decode("utf-8")
        except Exception as exc:
            raise DecryptionError(f"Rotazione del token fallita: {exc}") from exc


# Istanza singleton predefinita
encryption_service = EncryptionService()
