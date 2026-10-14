"""Modelli per l'identità del paziente e il tracciamento dei consensi GDPR."""

import uuid
from datetime import date, datetime
from typing import List, Optional
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin


class PatientIdentity(Base, TimestampMixin):
    """Archivio separato dell'anagrafica identificativa del paziente (PII).

    PRINCIPIO ARCHITETTURALE GDPR:
    I dati anagrafici sono separati dalla cartella clinica ('ClinicalRecord')
    e protetti da crittografia applicativa (Fernet). L'identificatore tecnico
    è un UUID casuale privo di significato personale.
    """

    __tablename__ = "patient_identities"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Identificatore tecnico pseudonimo primario",
    )
    therapist_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("therapists.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )

    # Campi identificativi protetti da cifratura applicativa (mai memorizzati in chiaro)
    encrypted_first_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Nome cifrato con Fernet",
    )
    encrypted_last_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Cognome cifrato con Fernet",
    )
    encrypted_email: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Email cifrata con Fernet",
    )
    encrypted_phone: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Numero di telefono cifrato con Fernet",
    )
    encrypted_tax_id: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Codice fiscale cifrato con Fernet",
    )

    date_of_birth: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        doc="Data di nascita per calcoli normativi di età",
    )

    # Stato dei consensi GDPR
    gdpr_clinical_consent: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Consenso informato al trattamento per finalità cliniche",
    )
    gdpr_research_consent: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Consenso informato separato per finalità di ricerca scientifica",
    )

    # Relazioni
    therapist: Mapped["Therapist"] = relationship("Therapist", back_populates="patients")
    clinical_records: Mapped[List["ClinicalRecord"]] = relationship(
        "ClinicalRecord",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    consents: Mapped[List["ConsentRecord"]] = relationship(
        "ConsentRecord",
        back_populates="patient",
        cascade="all, delete-orphan",
    )


class ConsentRecord(Base, TimestampMixin):
    """Storico immutabile dei consensi informati (prestati o revocati) ai sensi del GDPR."""

    __tablename__ = "consent_records"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    patient_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("patient_identities.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    study_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("research_studies.id", ondelete="SET NULL"),
        nullable=True,
        doc="Riferimento opzionale allo studio di ricerca specifico",
    )
    purpose: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Finalità del trattamento (es. CLINICA, RICERCA_STUDIO_SPC)",
    )
    granted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        doc="True se concesso, False se negato o revocato",
    )
    information_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Versione del documento di informativa mostrato al paziente",
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Data e ora dell'eventuale revoca del consenso",
    )

    patient: Mapped["PatientIdentity"] = relationship("PatientIdentity", back_populates="consents")
    study: Mapped[Optional["ResearchStudy"]] = relationship("ResearchStudy", back_populates="consents")
