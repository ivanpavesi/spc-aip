"""Configurazione dell'applicazione AIP.

Questo modulo definisce la classe Settings che legge le variabili d'ambiente
da un file `.env` o dalle variabili di sistema tramite pydantic-settings.
Tutti i parametri sono tipizzati e validati.
"""

from pathlib import Path
from typing import Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Percorso base del progetto (cartella aip/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Impostazioni dell'applicazione caricate da ambiente o file .env."""

    # Configurazione generale
    APP_NAME: str = "Scuole di Psicoterapia Cognitiva — AIP"
    ENVIRONMENT: Literal["development", "testing", "production"] = "development"
    DEBUG: bool = True

    # Sicurezza e Sessioni
    APP_SECRET_KEY: str = Field(
        default="change-this-secret-key-in-production-at-least-32-chars",
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
        default="EnJr5iK_Y0dfCXOmqEspSzmTk8QL1eRIkg3XIkm7ync=",
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
    )

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
