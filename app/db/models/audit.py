"""Modello per la registrazione degli eventi di sicurezza e audit trail."""

import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON
from app.db.base import Base


class AuditEvent(Base):
    """Tracciamento degli eventi di sicurezza e accessi rilevanti (GDPR Audit Trail).

    REQUISITO DI SICUREZZA FONDAMENTALE:
    Nessun dato sanitario, testo di diagnosi o dato anagrafico in chiaro
    può essere memorizzato in questa tabella o nei log applicativi.
    """

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        doc="ID dell'utente che ha eseguito l'azione (o None per accessi anonimi/falliti)",
    )
    actor_role: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        doc="Ruolo dell'attore al momento dell'evento",
    )
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Azione registrata (es. LOGIN_SUCCESS, TEST_ASSIGNED, CONSENT_REVOKED)",
    )
    resource_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Tipo di risorsa coinvolta (es. User, PatientIdentity, TestAssignment)",
    )
    resource_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        doc="Identificativo tecnico della risorsa",
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
        doc="Indirizzo IP del client",
    )
    technical_details: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        doc="Metadati tecnici (es. User-Agent, esito, codici errore tecnici)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_audit_events_created_actor", "created_at", "actor_id"),
    )
