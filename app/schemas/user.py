"""Schemi Pydantic per utenti e autenticazione."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from app.db.models.user import UserRole


class UserBase(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.THERAPIST
    is_active: bool = True


class UserCreate(UserBase):
    password: str = Field(min_length=3, description="Password con almeno 3 caratteri")


class UserRead(UserBase):
    id: str
    totp_enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TherapistProfileRead(BaseModel):
    id: str
    user_id: str
    full_name: str
    license_number: Optional[str] = None
    order_region: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
