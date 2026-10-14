"""Modelli per il catalogo dei test psicometrici, assegnazioni, risposte e punteggi."""

import enum
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON
from app.db.base import Base, TimestampMixin


class TestStatus(str, enum.Enum):
    """Stato di avanzamento di un'assegnazione test al paziente."""
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class TestDefinition(Base, TimestampMixin):
    """Definizione strutturata di un questionario psicometrico.

    Contiene gli item, le opzioni di risposta e le formule di scoring deterministico.
    """

    __tablename__ = "test_definitions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
        doc="Sigla univoca dello strumento (es. BDI-II, STAI-Y1, SCL-90)",
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="Titolo esteso del questionario",
    )
    version: Mapped[str] = mapped_column(
        String(20),
        default="1.0.0",
        nullable=False,
        doc="Versione semantica della definizione",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Descrizione clinica dello strumento",
    )
    items_schema: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        doc="Struttura JSON degli item, opzioni e scale",
    )
    scoring_rules: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        doc="Regole deterministiche di calcolo e cut-off normativi",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    assignments: Mapped[list["TestAssignment"]] = relationship(
        "TestAssignment",
        back_populates="test_definition",
    )
    scientific_documents: Mapped[list["ScientificDocument"]] = relationship(
        "ScientificDocument",
        back_populates="test_definition",
        cascade="all, delete-orphan",
    )


class TestAssignment(Base, TimestampMixin):
    """Assegnazione di un test a una cartella clinica con token di accesso paziente."""

    __tablename__ = "test_assignments"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    clinical_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clinical_records.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    test_definition_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_definitions.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )

    # Token di accesso: viene salvato SOLO l'hash SHA-256, mai il token in chiaro!
    access_token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
        doc="Hash SHA-256 della credenziale di accesso fornita al paziente",
    )

    status: Mapped[TestStatus] = mapped_column(
        Enum(TestStatus, name="test_status_enum"),
        default=TestStatus.PENDING,
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Scadenza della sessione di compilazione",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Data e ora del completamento definitivo",
    )

    # Snapshot immutabile della definizione del test al momento dell'assegnazione
    definition_snapshot: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        doc="Copia immutabile della definizione per garantire la riproducibilità psicometrica",
    )

    # Relazioni
    clinical_record: Mapped["ClinicalRecord"] = relationship(
        "ClinicalRecord",
        back_populates="test_assignments",
    )
    test_definition: Mapped["TestDefinition"] = relationship(
        "TestDefinition",
        back_populates="assignments",
    )
    response: Mapped[Optional["TestResponse"]] = relationship(
        "TestResponse",
        back_populates="assignment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    score: Mapped[Optional["TestScore"]] = relationship(
        "TestScore",
        back_populates="assignment",
        uselist=False,
        cascade="all, delete-orphan",
    )


class TestResponse(Base, TimestampMixin):
    """Risposte fornite dal paziente agli item del questionario."""

    __tablename__ = "test_responses"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    test_assignment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_assignments.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    raw_answers: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        doc="Mappa item_id -> valore selezionato dal paziente",
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc) if hasattr(datetime, 'now') else datetime.utcnow(),
        nullable=False,
    )

    assignment: Mapped["TestAssignment"] = relationship(
        "TestAssignment",
        back_populates="response",
    )


class TestScore(Base, TimestampMixin):
    """Punteggi psicometrici calcolati in modo deterministico da codice Python."""

    __tablename__ = "test_scores"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    test_assignment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_assignments.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    raw_scores: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        doc="Punteggi grezzi per scala e sottoscala calcolati deterministicamente",
    )
    standardized_scores: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        doc="Punteggi standardizzati (Punti T, Sten, Percentili)",
    )
    interpretation_summary: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        doc="Sintesi dei cut-off clinici superati",
    )
    scoring_version: Mapped[str] = mapped_column(
        String(20),
        default="1.0.0",
        nullable=False,
        doc="Versione dell'algoritmo psicometrico utilizzato",
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    assignment: Mapped["TestAssignment"] = relationship(
        "TestAssignment",
        back_populates="score",
    )
