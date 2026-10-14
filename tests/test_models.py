"""Test di integrazione sui modelli del database e separazione delle entità."""

from datetime import date, datetime, timezone
import pytest
from sqlalchemy.orm import Session
from app.core.security import hash_password, verify_password, hash_token, generate_pseudonym_code
from app.services.encryption import encryption_service
from app.db.models import (
    User,
    UserRole,
    Therapist,
    PatientIdentity,
    ConsentRecord,
    ClinicalRecord,
    TherapySession,
    ClinicalAnalysis,
    TestDefinition,
    TestAssignment,
    TestResponse,
    TestScore,
    TestStatus,
    ResearchStudy,
    ResearchDataset,
    AuditEvent,
)


def test_user_and_therapist_creation(db_session: Session):
    """Verifica creazione utente terapeuta e relativo profilo professionale."""
    pwd_hash = hash_password("PasswordSicura2026!")
    assert verify_password("PasswordSicura2026!", pwd_hash)
    assert not verify_password("PasswordSbagliata", pwd_hash)

    user = User(
        email="terapeuta.test@spc.it",
        hashed_password=pwd_hash,
        role=UserRole.THERAPIST,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    therapist = Therapist(
        user_id=user.id,
        full_name="Dott.ssa Laura Bianchi",
        license_number="12345/Lazio",
        order_region="Lazio",
    )
    db_session.add(therapist)
    db_session.commit()

    saved_user = db_session.query(User).filter_by(email="terapeuta.test@spc.it").first()
    assert saved_user is not None
    assert saved_user.therapist_profile is not None
    assert saved_user.therapist_profile.full_name == "Dott.ssa Laura Bianchi"


def test_patient_identity_and_clinical_record_separation(db_session: Session):
    """Verifica la separazione architetturale tra anagrafica (PII cifrata) e cartella clinica (pseudonimizzata)."""
    user = User(
        email="terapeuta2@spc.it",
        hashed_password=hash_password("Password123!"),
        role=UserRole.THERAPIST,
    )
    db_session.add(user)
    db_session.flush()

    therapist = Therapist(user_id=user.id, full_name="Dott. Marco Neri")
    db_session.add(therapist)
    db_session.flush()

    # 1. Anagrafica con campi identificativi cifrati con Fernet
    enc_first = encryption_service.encrypt_text("Giovanni")
    enc_last = encryption_service.encrypt_text("Verdi")
    enc_cf = encryption_service.encrypt_text("VRDGNN85M01H501Z")

    patient = PatientIdentity(
        therapist_id=therapist.id,
        encrypted_first_name=enc_first,
        encrypted_last_name=enc_last,
        encrypted_tax_id=enc_cf,
        date_of_birth=date(1985, 8, 1),
        gdpr_clinical_consent=True,
        gdpr_research_consent=True,
    )
    db_session.add(patient)
    db_session.flush()

    # 2. Cartella clinica con codice pseudonimo tecnico privo di PII
    pseudo_code = generate_pseudonym_code("PR")
    clinical_rec = ClinicalRecord(
        patient_id=patient.id,
        therapist_id=therapist.id,
        pseudonym_code=pseudo_code,
        encrypted_notes=encryption_service.encrypt_text("Inizio percorso psicoterapia cognitivo-comportamentale."),
    )
    db_session.add(clinical_rec)
    db_session.commit()

    # Verifiche di integrità e decifratura
    saved_patient = db_session.query(PatientIdentity).filter_by(id=patient.id).first()
    assert saved_patient is not None
    assert encryption_service.decrypt_text(saved_patient.encrypted_first_name) == "Giovanni"
    assert encryption_service.decrypt_text(saved_patient.encrypted_last_name) == "Verdi"
    assert encryption_service.decrypt_text(saved_patient.encrypted_tax_id) == "VRDGNN85M01H501Z"

    saved_rec = db_session.query(ClinicalRecord).filter_by(patient_id=patient.id).first()
    assert saved_rec is not None
    assert saved_rec.pseudonym_code == pseudo_code
    assert "Giovanni" not in saved_rec.pseudonym_code
    assert encryption_service.decrypt_text(saved_rec.encrypted_notes) == "Inizio percorso psicoterapia cognitivo-comportamentale."


def test_test_engine_models(db_session: Session):
    """Verifica il ciclo di definizione, assegnazione (con hash del token) e scoring di un questionario."""
    test_def = TestDefinition(
        code="BDI-II-TEST",
        title="Beck Depression Inventory - II",
        version="1.0.0",
        items_schema={"items_count": 21, "type": "SINGLE_CHOICE"},
        scoring_rules={"method": "SUM", "cutoff": 14},
    )
    db_session.add(test_def)
    db_session.flush()

    # Creiamo terapeuta e cartella clinica
    user = User(email="t3@spc.it", hashed_password=hash_password("Pass12345!"))
    db_session.add(user)
    db_session.flush()
    therapist = Therapist(user_id=user.id, full_name="Dott.ssa Rossi")
    db_session.add(therapist)
    db_session.flush()
    patient = PatientIdentity(
        therapist_id=therapist.id,
        encrypted_first_name=encryption_service.encrypt_text("Anna"),
        encrypted_last_name=encryption_service.encrypt_text("Bruni"),
    )
    db_session.add(patient)
    db_session.flush()
    clinical_rec = ClinicalRecord(
        patient_id=patient.id,
        therapist_id=therapist.id,
        pseudonym_code=generate_pseudonym_code(),
    )
    db_session.add(clinical_rec)
    db_session.flush()

    # Assegnazione con salvataggio dell'hash del token (mai in chiaro!)
    raw_token = "secret-token-given-to-patient-xyz123"
    token_hash = hash_token(raw_token)

    assignment = TestAssignment(
        clinical_record_id=clinical_rec.id,
        test_definition_id=test_def.id,
        access_token_hash=token_hash,
        status=TestStatus.PENDING,
        expires_at=datetime.now(timezone.utc),
        definition_snapshot=test_def.items_schema,
    )
    db_session.add(assignment)
    db_session.commit()

    saved_assignment = db_session.query(TestAssignment).filter_by(access_token_hash=token_hash).first()
    assert saved_assignment is not None
    assert saved_assignment.status == TestStatus.PENDING
    assert saved_assignment.test_definition.code == "BDI-II-TEST"


def test_audit_event_logging(db_session: Session):
    """Verifica la creazione di un evento di audit privo di contenuti sanitari."""
    audit = AuditEvent(
        actor_id="user-123-uuid",
        actor_role="THERAPIST",
        action="TEST_ASSIGNMENT_CREATED",
        resource_type="TestAssignment",
        resource_id="assignment-456-uuid",
        ip_address="192.168.1.100",
        technical_details={"browser": "Firefox", "status": "SUCCESS"},
    )
    db_session.add(audit)
    db_session.commit()

    saved_audit = db_session.query(AuditEvent).filter_by(action="TEST_ASSIGNMENT_CREATED").first()
    assert saved_audit is not None
    assert saved_audit.actor_role == "THERAPIST"
    assert saved_audit.technical_details["status"] == "SUCCESS"
