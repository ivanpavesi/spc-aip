"""Test del flusso end-to-end: creazione paziente, assegnazione test, compilazione e scoring (STEP 3 & 4)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.core.security import hash_password
from app.db.models.clinical import ClinicalRecord
from app.db.models.patient import PatientIdentity
from app.db.models.research import ResearchDataset
from app.db.models.test_engine import TestAssignment, TestDefinition, TestStatus
from app.db.models.user import Therapist, User, UserRole


def test_complete_patient_and_questionnaire_flow(client: TestClient, db_session: Session):
    """Verifica il percorso completo tra terapeuta e paziente."""
    # 1. Login Terapeuta
    therapist_user = User(
        email="dr.giorgio@spc.it",
        hashed_password=hash_password("Pass12345!"),
        role=UserRole.THERAPIST,
    )
    db_session.add(therapist_user)
    db_session.flush()

    therapist = Therapist(user_id=therapist_user.id, full_name="Dott. Giorgio Bianchi")
    db_session.add(therapist)
    db_session.commit()

    client.post("/auth/login", data={"email": "dr.giorgio@spc.it", "password": "Pass12345!"})

    # 2. Creazione Paziente con consensi clinici e ricerca
    res_create = client.post(
        "/therapist/patients/new",
        data={
            "first_name": "Elena",
            "last_name": "Fontana",
            "date_of_birth": "1990-05-15",
            "tax_id": "FNTLNE90E55H501K",
            "gdpr_clinical": "true",
            "gdpr_research": "true",
        },
        follow_redirects=False,
    )
    assert res_create.status_code == 303
    patient_url = res_create.headers.get("location")
    patient_id = patient_url.split("/")[-1]

    # Verifica nel database che il paziente sia stato creato
    patient_db = db_session.query(PatientIdentity).filter_by(id=patient_id).first()
    assert patient_db is not None
    assert patient_db.gdpr_research_consent is True

    # 3. Assegnazione questionario BDI-II
    bdi_def = db_session.query(TestDefinition).filter_by(code="BDI-II").first()
    assert bdi_def is not None

    res_assign = client.post(
        f"/therapist/patients/{patient_id}/assign-test",
        data={"test_id": bdi_def.id, "days_valid": 7},
        follow_redirects=False,
    )
    assert res_assign.status_code == 303
    redirect_with_token = res_assign.headers.get("location")
    assert "invited_token=" in redirect_with_token
    token = redirect_with_token.split("invited_token=")[-1]

    # 4. Accesso Paziente con il token ricevuto
    # Logout operatore per simulare browser del paziente
    client.cookies.clear()

    res_portal = client.get(f"/p/{token}")
    assert res_portal.status_code == 200
    assert "Beck Depression Inventory" in res_portal.text
    assert "Invia definitivamente le risposte" in res_portal.text

    # 5. Compilazione e Invio delle risposte da parte del paziente (tutte a 1 -> totale 21)
    answers_form = {f"item_bdi_{i}": "1" for i in range(1, 22)}
    res_submit = client.post(f"/p/{token}/submit", data=answers_form)
    assert res_submit.status_code == 200
    assert "Compilazione Completata" in res_submit.text

    # 6. Verifica che l'assegnazione sia marcata COMPLETED e che il punteggio sia calcolato
    assignment = db_session.query(TestAssignment).filter_by(test_definition_id=bdi_def.id).first()
    assert assignment.status == TestStatus.COMPLETED
    assert assignment.score is not None
    assert assignment.score.raw_scores["total"] == 21.0
    assert assignment.score.interpretation_summary["severity"] == "MODERATA"

    # 7. Verifica che il dataset di ricerca pseudonimizzato sia stato popolato
    research_entry = db_session.query(ResearchDataset).filter_by(test_code="BDI-II").first()
    assert research_entry is not None
    assert research_entry.scores_data["total"] == 21.0
    assert research_entry.minified_demographics["age_bracket"] != "N/D"

    # 8. Non deve essere possibile reinviare lo stesso questionario (idempotenza / blocco 400)
    res_repeat = client.post(f"/p/{token}/submit", data=answers_form)
    assert res_repeat.status_code == 400
