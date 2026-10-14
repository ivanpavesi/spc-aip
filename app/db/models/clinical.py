"""Modelli per la cartella clinica, sedute terapeutiche e analisi cliniche."""

import uuid
from datetime import date
from typing import List, Optional
from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin


class ClinicalRecord(Base, TimestampMixin):
    """Cartella clinica del paziente.

    È collegata all'anagrafica tramite patient_id, ma i dati clinici
    possono essere esportati per la ricerca unicamente tramite 'pseudonym_code',
    garantendo la pseudonimizzazione a livello architetturale.
    """

    __tablename__ = "clinical_records"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Identificativo univoco della cartella clinica",
    )
    patient_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("patient_identities.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    therapist_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("therapists.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    pseudonym_code: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        index=True,
        nullable=False,
        doc="Codice pseudonimo tecnico per ricerca (es. PR-9F8A2B1C)",
    )
    encrypted_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Note cliniche del terapeuta cifrate con Fernet",
    )

    # Relazioni
    patient: Mapped["PatientIdentity"] = relationship("PatientIdentity", back_populates="clinical_records")
    therapist: Mapped["Therapist"] = relationship("Therapist", back_populates="clinical_records")
    sessions: Mapped[List["TherapySession"]] = relationship(
        "TherapySession",
        back_populates="clinical_record",
        cascade="all, delete-orphan",
        order_by="TherapySession.session_number",
    )
    test_assignments: Mapped[List["TestAssignment"]] = relationship(
        "TestAssignment",
        back_populates="clinical_record",
        cascade="all, delete-orphan",
    )
    clinical_analyses: Mapped[List["ClinicalAnalysis"]] = relationship(
        "ClinicalAnalysis",
        back_populates="clinical_record",
        cascade="all, delete-orphan",
    )


class TherapySession(Base, TimestampMixin):
    """Singola seduta psicoterapeutica con eventuale trascrizione associata."""

    __tablename__ = "therapy_sessions"

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
    session_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Numero progressivo della seduta (es. 1, 2, 3)",
    )
    session_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        doc="Data di svolgimento della seduta",
    )
    original_filename: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Nome originale del file caricato (es. seduta_03.docx)",
    )
    encrypted_transcript: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Testo estratto dalla trascrizione, cifrato con Fernet",
    )

    clinical_record: Mapped["ClinicalRecord"] = relationship(
        "ClinicalRecord",
        back_populates="sessions",
    )


class ClinicalAnalysis(Base, TimestampMixin):
    """Risultato strutturato di un'analisi clinica o formulazione del caso."""

    __tablename__ = "clinical_analyses"

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
    analysis_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Tipologia di analisi (es. CASE_FORMULATION, ABC, SCHEMA_ANALYSIS, CUSTOM_PROMPT)",
    )
    prompt_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Versione del prompt di sistema utilizzato",
    )
    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Identificativo del modello AI utilizzato",
    )
    encrypted_result: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Testo del report/formulazione generato, cifrato con Fernet",
    )

    clinical_record: Mapped["ClinicalRecord"] = relationship(
        "ClinicalRecord",
        back_populates="clinical_analyses",
    )
