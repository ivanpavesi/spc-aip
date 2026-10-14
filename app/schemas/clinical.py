"""Schemi Pydantic per cartella clinica e sedute."""

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class ClinicalRecordRead(BaseModel):
    id: str
    patient_id: str
    therapist_id: str
    pseudonym_code: str
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TherapySessionRead(BaseModel):
    id: str
    clinical_record_id: str
    session_number: int
    session_date: date
    original_filename: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
