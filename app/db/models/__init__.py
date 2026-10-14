"""Esportazione centralizzata dei modelli SQLAlchemy per Alembic e l'applicazione."""

from app.db.base import Base, TimestampMixin
from app.db.models.user import User, UserRole, Therapist, AuthSession
from app.db.models.patient import PatientIdentity, ConsentRecord
from app.db.models.clinical import ClinicalRecord, TherapySession, ClinicalAnalysis
from app.db.models.test_engine import TestDefinition, TestAssignment, TestResponse, TestScore, TestStatus
from app.db.models.research import ResearchStudy, ResearchDataset
from app.db.models.admin_config import ClinicalAnalysisButton, ScientificDocument, SystemSetting
from app.db.models.audit import AuditEvent

__all__ = [
    "Base",
    "TimestampMixin",
    "User",
    "UserRole",
    "Therapist",
    "AuthSession",
    "PatientIdentity",
    "ConsentRecord",
    "ClinicalRecord",
    "TherapySession",
    "ClinicalAnalysis",
    "TestDefinition",
    "TestAssignment",
    "TestResponse",
    "TestScore",
    "TestStatus",
    "ResearchStudy",
    "ResearchDataset",
    "AuditEvent",
    "ClinicalAnalysisButton",
    "ScientificDocument",
    "SystemSetting",
]
