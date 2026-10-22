"""Modelli per Utenti di sistema e Terapeuti."""

import enum
import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin


class UserRole(str, enum.Enum):
    """Ruoli di sistema disponibili nella piattaforma AIP."""
    ADMIN = "ADMIN"
    THERAPIST = "THERAPIST"
    RESEARCHER = "RESEARCHER"


class User(Base, TimestampMixin):
    """Account operatore di sistema (Terapeuta, Ricercatore, Amministratore).

    Nota GDPR: i pazienti non hanno un account 'User' con email/password,
    ma accedono tramite credenziali di sessione dedicate (vedi TestAssignment).
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Identificativo univoco casuale (UUID)",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        doc="Email istituzionale dell'operatore",
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Hash della password con PBKDF2/Argon2",
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role_enum"),
        default=UserRole.THERAPIST,
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Indica se l'account è attivo",
    )

    # Secondo fattore di autenticazione (TOTP)
    totp_secret: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Segreto TOTP per 2FA",
    )
    totp_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Versione del fattore: invalida solo le sessioni dell'account modificato.
    mfa_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    totp_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    totp_last_counter: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    mfa_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    mfa_locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relazione opzionale con il profilo Terapeuta
    therapist_profile: Mapped[Optional["Therapist"]] = relationship(
        "Therapist",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # Relazione con le sessioni di autenticazione
    sessions: Mapped[List["AuthSession"]] = relationship(
        "AuthSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class AuthSession(Base, TimestampMixin):
    """Sessione di autenticazione persistente e revocabile per operatori."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
        doc="Hash SHA-256 del session token salvato nel cookie del client",
    )
    mfa_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="True se il secondo fattore TOTP è stato verificato con successo",
    )
    mfa_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # Enrollment legato alla sessione, con scadenza e password appena verificata.
    totp_pending_secret: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    totp_pending_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="sessions")


class Therapist(Base, TimestampMixin):
    """Profilo professionale del terapeuta SPC/APC."""

    __tablename__ = "therapists"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        doc="Nome e cognome professionale del terapeuta",
    )
    license_number: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        doc="Numero iscrizione all'Ordine degli Psicologi/Medici",
    )
    order_region: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        doc="Regione dell'Ordine di appartenenza",
    )

    user: Mapped["User"] = relationship("User", back_populates="therapist_profile")
    patients: Mapped[List["PatientIdentity"]] = relationship(
        "PatientIdentity",
        back_populates="therapist",
    )
    clinical_records: Mapped[List["ClinicalRecord"]] = relationship(
        "ClinicalRecord",
        back_populates="therapist",
    )
