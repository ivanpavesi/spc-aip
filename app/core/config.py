"""Configurazione dell'applicazione AIP.

Questo modulo definisce la classe Settings che legge le variabili d'ambiente
da un file `.env` o dalle variabili di sistema tramite pydantic-settings.
Tutti i parametri sono tipizzati e validati.
"""

import base64
import binascii
from pathlib import Path
from typing import Literal
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

# Percorso base del progetto (cartella aip/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Valori pubblicati nel codice/template precedente: solo per riconoscerli e rifiutarli.
DEMO_ENCRYPTION_KEYS = frozenset({
    "EnJr5iK_Y0dfCXOmqEspSzmTk8QL1eRIkg3XIkm7ync=",
    "W3u1rB7HlR3K9Vb8Z6y2TqN1mP4xS7aD0cE5fG8hI9k=",
})
DEMO_SECRET_KEY = "change-this-secret-key-in-production-at-least-32-chars"


def _is_repeated(value: str | bytes) -> bool:
    return any(value == value[:n] * (len(value) // n) for n in range(1, len(value) // 2 + 1))


def validate_encryption_key(key: str, *, production: bool = False) -> None:
    """Valida il formato senza modificare/generare chiavi o esporne il valore."""
    try:
        raw = base64.b64decode(key.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeError, binascii.Error):
        raise ValueError("APP_ENCRYPTION_KEY deve essere una chiave Fernet URL-safe base64 valida.") from None
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode("ascii") != key:
        raise ValueError("APP_ENCRYPTION_KEY deve codificare esattamente 32 byte in base64 URL-safe canonica.")
    if production and (key in DEMO_ENCRYPTION_KEYS or len(set(raw)) < 8 or _is_repeated(raw)):
        raise ValueError("APP_ENCRYPTION_KEY dimostrativa o prevedibile non ammessa in produzione.")


class Settings(BaseSettings):
    """Impostazioni dell'applicazione caricate da ambiente o file .env."""

    # Configurazione generale
    APP_NAME: str = "Scuole di Psicoterapia Cognitiva — AIP"
    ENVIRONMENT: Literal["development", "testing", "production"] = "development"
    DEBUG: bool = True

    # Sicurezza e Sessioni
    APP_SECRET_KEY: str = Field(
        default=DEMO_SECRET_KEY,
        repr=False,
        description="Chiave segreta per firma di sessioni e CSRF",
    )

    # Database
    # Supporta PostgreSQL (es. Supabase) e fallback a SQLite per test e sviluppo locale
    DATABASE_URL: str = Field(
        default="sqlite:///./aip_dev.db",
        description="Stringa di connessione SQLAlchemy al database",
    )

    # Crittografia applicativa dei dati sanitari (PII e note cliniche)
    # Deve essere una chiave Fernet a 32 byte codificata base64 URL-safe
    APP_ENCRYPTION_KEY: str = Field(
        default="",
        repr=False,
        description="Chiave Fernet per la cifratura dei dati sensibili",
    )

    # Server
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # Configurazione caricamento pydantic-settings
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        """Blocca l'avvio produttivo prima di creare connessioni o inizializzare dati."""
        if self.ENVIRONMENT != "production":
            return self

        secret = self.APP_SECRET_KEY
        placeholder_prefixes = (
            "change", "replace", "cambia", "your-secret", "your_secret",
            "demo", "example", "test", "placeholder",
        )
        if (
            len(secret) < 32
            or secret != secret.strip()
            or secret == DEMO_SECRET_KEY
            or secret.lower().startswith(placeholder_prefixes)
            or len(set(secret)) < 8
            or _is_repeated(secret)
            or secret == self.APP_ENCRYPTION_KEY
        ):
            raise ValueError("APP_SECRET_KEY assente o non sicura: usare un segreto casuale indipendente di almeno 32 caratteri.")

        validate_encryption_key(self.APP_ENCRYPTION_KEY, production=True)

        if self.DATABASE_URL.startswith("sqlite"):
            url = make_url(self.DATABASE_URL)
            if (
                not url.database
                or Path(url.database).name == "aip_dev.db"
                or ":memory:" in url.database
                or url.query.get("mode") == "memory"
            ):
                raise ValueError("Il database dimostrativo/in memoria è riservato a sviluppo e test.")
        return self

    @field_validator("DATABASE_URL")
    @classmethod
    def normalise_database_url(cls, v: str) -> str:
        """Adatta se necessario prefissi postgres:// in postgresql+psycopg2://."""
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+psycopg2://", 1)
        if v.startswith("postgresql://") and not v.startswith("postgresql+"):
            return v.replace("postgresql://", "postgresql+psycopg2://", 1)
        return v


# Istanza singleton delle impostazioni
settings = Settings()
