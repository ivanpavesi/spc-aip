"""Modelli per i progetti di ricerca e i dataset aggregati o pseudonimizzati."""

import uuid
from typing import List, Optional
from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON
from app.db.base import Base, TimestampMixin


class ResearchStudy(Base, TimestampMixin):
    """Studio o protocollo di ricerca scientifico approvato."""

    __tablename__ = "research_studies"

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
        doc="Codice identificativo dello studio (es. SPC-STUDY-2026-A)",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Titolo del progetto di ricerca",
    )
    ethics_committee_approval: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="Numero di approvazione del Comitato Etico",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    consents: Mapped[List["ConsentRecord"]] = relationship(
        "ConsentRecord",
        back_populates="study",
    )
    datasets: Mapped[List["ResearchDataset"]] = relationship(
        "ResearchDataset",
        back_populates="study",
        cascade="all, delete-orphan",
    )


class ResearchDataset(Base, TimestampMixin):
    """Record di ricerca minimizzato e pseudonimizzato.

    Accessibile ai Ricercatori autorizzati:
    non contiene dati anagrafici, nomi o testi clinici individuali.
    """

    __tablename__ = "research_datasets"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    study_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("research_studies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    pseudonym_code: Mapped[str] = mapped_column(
        String(32),
        index=True,
        nullable=False,
        doc="Codice pseudonimo corrispondente alla cartella clinica",
    )
    test_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Codice dello strumento psicometrico (es. BDI-II)",
    )
    scores_data: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        doc="Punteggi grezzi e standardizzati calcolati",
    )
    minified_demographics: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        doc="Dati demografici minimizzati (es. fascia d'età) per prevenire la re-identificazione",
    )
    consent_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Verifica preliminare della presenza di valido consenso alla ricerca",
    )

    study: Mapped["ResearchStudy"] = relationship("ResearchStudy", back_populates="datasets")
