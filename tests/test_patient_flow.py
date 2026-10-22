"""Test del flusso end-to-end: creazione paziente, assegnazione test, compilazione e scoring (STEP 3 & 4)."""

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session
from app.core.security import hash_password
from app.db.models.clinical import ClinicalRecord
from app.db.models.patient import PatientIdentity
from app.db.models.research import ResearchDataset, ResearchStudy
from app.db.models.test_engine import TestAssignment, TestDefinition, TestResponse, TestStatus
from app.db.models.user import Therapist, User, UserRole


@pytest.mark.parametrize("research_consent", [False, True])
@pytest.mark.parametrize("study_state", ["missing", "active", "inactive", "multiple"])
def test_complete_patient_and_questionnaire_flow(client: TestClient, db_session: Session, research_consent, study_state):
    """Verifica il percorso completo tra terapeuta e paziente."""
    if study_state != "missing":
        study = ResearchStudy(code="F09-PATIENT-SYNTH", title="Studio sintetico preesistente",
                              is_active=study_state != "inactive")
        db_session.add(study)
        if study_state == "multiple":
            db_session.add(ResearchStudy(code="F09-PATIENT-SYNTH-OTHER", title="Altro studio sintetico"))
        db_session.commit()
    studies_before = db_session.query(ResearchStudy).count()
    datasets_before = db_session.query(ResearchDataset).count()
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
            "gdpr_research": str(research_consent).lower(),
        },
        follow_redirects=False,
    )
    assert res_create.status_code == 303
    patient_url = res_create.headers.get("location")
    patient_id = patient_url.split("/")[-1]

    # Verifica nel database che il paziente sia stato creato
    patient_db = db_session.query(PatientIdentity).filter_by(id=patient_id).first()
    assert patient_db is not None
    assert patient_db.gdpr_research_consent is research_consent

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
    therapist_token = client.cookies.get("aip_session")
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

    # 7. F09: nessuno studio o conferimento implicito, anche con consenso generico.
    assert db_session.query(ResearchDataset).count() == datasets_before
    assert db_session.query(ResearchStudy).count() == studies_before
    saved_response = db_session.query(TestResponse).filter_by(test_assignment_id=assignment.id).one()
    assert len(saved_response.raw_answers) == 21

    # 8. Non deve essere possibile reinviare lo stesso questionario (idempotenza / blocco 400)
    res_repeat = client.post(f"/p/{token}/submit", data=answers_form)
    assert res_repeat.status_code == 400

    # Le risposte e i punteggi restano consultabili dal terapeuta titolare.
    client.cookies.set("aip_session", therapist_token)
    assert client.get(patient_url).status_code == 200
    assert client.get(f"/therapist/results/{assignment.id}").status_code == 200
