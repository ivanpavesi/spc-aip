"""Test per la gestione delle sedute, estrazione documenti e analisi cliniche con AI (STEP 6 & 7)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.core.security import hash_password
from app.db.models.clinical import ClinicalAnalysis, ClinicalRecord, TherapySession
from app.db.models.patient import PatientIdentity
from app.db.models.user import Therapist, User, UserRole
from app.services.documents import extract_text_from_file
from app.services.encryption import encryption_service


def test_document_extraction():
    """Verifica l'estrazione di testo da stringhe e file."""
    # Test .txt
    txt_content = "Trascrizione seduta: il paziente riferisce ansia anticipatoria.".encode("utf-8")
    assert "ansia anticipatoria" in extract_text_from_file("seduta1.txt", txt_content)


def test_therapist_session_and_ai_analysis(client: TestClient, db_session: Session):
    """Verifica il salvataggio di una seduta cifrata e la generazione di un'analisi clinica AI."""
    # Setup Terapeuta e Paziente
    u = User(email="t.ai@spc.it", hashed_password=hash_password("Pass12345!"), role=UserRole.THERAPIST)
    db_session.add(u)
    db_session.flush()
    therapist = Therapist(user_id=u.id, full_name="Dott. Andrea")
    db_session.add(therapist)
    db_session.flush()

    patient = PatientIdentity(
        therapist_id=therapist.id,
        encrypted_first_name=encryption_service.encrypt_text("Paolo"),
        encrypted_last_name=encryption_service.encrypt_text("Galli"),
    )
    db_session.add(patient)
    db_session.flush()

    clinical_rec = ClinicalRecord(
        patient_id=patient.id,
        therapist_id=therapist.id,
        pseudonym_code="PR-TEST-AI",
    )
    db_session.add(clinical_rec)
    db_session.commit()

    # Login
    client.post("/auth/login", data={"email": "t.ai@spc.it", "password": "Pass12345!"})

    # 1. Aggiunta Seduta con trascrizione
    res_session = client.post(
        f"/therapist/patients/{patient.id}/sessions/new",
        data={
            "session_number": 1,
            "session_date": "2026-10-10",
            "transcript_text": "Paziente: Quando devo parlare in pubblico provo un senso di soffocamento e penso che tutti mi giudicheranno ridicolo.",
        },
        follow_redirects=False,
    )
    assert res_session.status_code == 303

    saved_session = db_session.query(TherapySession).filter_by(clinical_record_id=clinical_rec.id).first()
    assert saved_session is not None
    # Verifica che nel DB la trascrizione sia cifrata
    assert "giudicheranno ridicolo" not in saved_session.encrypted_transcript
    assert "giudicheranno ridicolo" in encryption_service.decrypt_text(saved_session.encrypted_transcript)

    # 2. Esecuzione Analisi Clinica "Analisi ABC" tramite il provider AI
    res_analysis = client.post(
        f"/therapist/patients/{patient.id}/analyze",
        data={"analysis_type": "Analisi ABC"},
        follow_redirects=False,
    )
    assert res_analysis.status_code == 303

    saved_analysis = db_session.query(ClinicalAnalysis).filter_by(clinical_record_id=clinical_rec.id).first()
    assert saved_analysis is not None
    assert saved_analysis.analysis_type == "Analisi ABC"
    
    # Decifra il referto clinico e verifica la struttura CBT
    decrypted_report = encryption_service.decrypt_text(saved_analysis.encrypted_result)
    assert "Analisi ABC" in decrypted_report
    assert "Antecedente" in decrypted_report
    assert "Beliefs" in decrypted_report
    assert "Conseguenze" in decrypted_report


def test_therapist_analysis_with_selected_llm_model(client: TestClient, db_session: Session):
    """Verifica che il terapeuta possa selezionare esplicitamente un modello LLM per l'analisi."""
    u = User(email="t.multi@spc.it", hashed_password=hash_password("Pass12345!"), role=UserRole.THERAPIST)
    db_session.add(u)
    db_session.flush()
    therapist = Therapist(user_id=u.id, full_name="Dott.ssa MultiLLM")
    db_session.add(therapist)
    db_session.flush()

    patient = PatientIdentity(
        therapist_id=therapist.id,
        encrypted_first_name=encryption_service.encrypt_text("Mario"),
        encrypted_last_name=encryption_service.encrypt_text("Verdi"),
    )
    db_session.add(patient)
    db_session.flush()

    clinical_rec = ClinicalRecord(
        patient_id=patient.id,
        therapist_id=therapist.id,
        pseudonym_code="PR-MULTI-LLM",
    )
    db_session.add(clinical_rec)
    db_session.commit()

    client.post("/auth/login", data={"email": "t.multi@spc.it", "password": "Pass12345!"})

    # Esegui analisi specificando 'cbt-spc-offline'
    res = client.post(
        f"/therapist/patients/{patient.id}/analyze",
        data={
            "analysis_type": "Formulazione del Caso",
            "llm_model": "cbt-spc-offline",
        },
        follow_redirects=False,
    )
    assert res.status_code == 303

    saved = db_session.query(ClinicalAnalysis).filter_by(clinical_record_id=clinical_rec.id).first()
    assert saved is not None
    assert saved.analysis_type == "Formulazione del Caso"
    assert "cbt-spc-offline" in saved.model_name
