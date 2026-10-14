"""Modelli per le configurazioni di sistema dell'amministratore (STEP 2, 6, 7).

Include:
- Pulsanti dinamici di analisi clinica SPC/APC
- Documenti scientifici e manuali dei test (RAG)
- Impostazioni globali di sistema e configurazione provider AI
"""

import uuid
from typing import Optional
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin


class ClinicalAnalysisButton(Base, TimestampMixin):
    """Pulsante dinamico di analisi clinica preconfigurato dall'amministratore.

    Permette ai terapeuti di eseguire analisi guidate (es. Formulazione del caso,
    Analisi ABC, Scopi e antiscopi) con prompt di sistema personalizzabili.
    """

    __tablename__ = "clinical_analysis_buttons"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(
        String(150),
        unique=True,
        nullable=False,
        doc="Etichetta del pulsante (es. 'Formulazione del Caso')",
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Breve spiegazione per il terapeuta",
    )
    system_prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Prompt di sistema dettagliato orientato al modello cognitivo SPC/APC",
    )
    version: Mapped[str] = mapped_column(
        String(20),
        default="1.0-SPC",
        nullable=False,
        doc="Versione del prompt",
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Ordinamento nella dashboard clinica",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Se il pulsante è visibile ai terapeuti",
    )


class ScientificDocument(Base, TimestampMixin):
    """Documento scientifico o manuale psicometrico indicizzato per RAG."""

    __tablename__ = "scientific_documents"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="Titolo descrittivo del manuale o articolo scientifico",
    )
    test_definition_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("test_definitions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Questionario associato (se specifico di un test, altrimenti generale)",
    )
    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    file_type: Mapped[str] = mapped_column(
        String(20),
        default="txt",
        nullable=False,
        doc="Estensione del file (pdf, docx, txt)",
    )
    extracted_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Testo estratto indicizzato per contestualizzazione AI / RAG",
    )

    # Relazione opzionale con il catalogo test
    test_definition: Mapped[Optional["TestDefinition"]] = relationship(
        "TestDefinition",
        back_populates="scientific_documents",
    )


class SystemSetting(Base, TimestampMixin):
    """Parametro di configurazione globale della piattaforma gestito dall'amministratore."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        doc="Chiave univoca dell'impostazione (es. AI_PROVIDER, GEMINI_MODEL)",
    )
    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Valore dell'impostazione",
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Descrizione della configurazione",
    )
