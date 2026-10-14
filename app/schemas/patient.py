"""Schemi Pydantic per gestione anagrafica paziente e accessi."""

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class PatientAccessRequest(BaseModel):
    """Schema per il form di accesso paziente da homepage."""
    access_code: str = Field(
        min_length=6,
        max_length=128,
        description="Codice personale di accesso ricevuto dal terapeuta",
    )


class PatientIdentityCreate(BaseModel):
    """Dati in chiaro forniti dal terapeuta per la creazione del paziente (da cifrare subito)."""
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    tax_id: Optional[str] = Field(None, max_length=16, description="Codice fiscale")
    date_of_birth: Optional[date] = None
    gdpr_clinical_consent: bool = False
    gdpr_research_consent: bool = False


class PatientIdentityRead(BaseModel):
    """Dati decifrati visibili esclusivamente al terapeuta proprietario."""
    id: str
    therapist_id: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gdpr_clinical_consent: bool
    gdpr_research_consent: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
