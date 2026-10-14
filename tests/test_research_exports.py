"""Test per le esportazioni CSV/Excel e statistiche aggregate per i Ricercatori (STEP 5)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.core.security import hash_password
from app.db.models.audit import AuditEvent
from app.db.models.research import ResearchDataset, ResearchStudy
from app.db.models.user import User, UserRole


def test_research_dashboard_and_exports(client: TestClient, db_session: Session):
    """Verifica il calcolo di medie e deviazioni standard e le esportazioni CSV/Excel."""
    # Setup Ricercatore
    u = User(email="prof.ricerca@spc.it", hashed_password=hash_password("Pass12345!"), role=UserRole.RESEARCHER)
    db_session.add(u)
    db_session.flush()

    study = ResearchStudy(
        code="SPC-STUDY-01",
        title="Studio Clinico Depressione",
    )
    db_session.add(study)
    db_session.flush()

    # Creiamo alcuni record di ricerca con punteggi
    scores_samples = [10.0, 15.0, 20.0, 25.0, 30.0]
    for idx, sc in enumerate(scores_samples):
        d = ResearchDataset(
            study_id=study.id,
            pseudonym_code=f"PR-RES-{idx}",
            test_code="BDI-II",
            scores_data={"total": sc},
            minified_demographics={"age_bracket": "30-39"},
            consent_verified=True,
        )
        db_session.add(d)
    db_session.commit()

    # Login Ricercatore
    client.post("/auth/login", data={"email": "prof.ricerca@spc.it", "password": "Pass12345!"})

    # 1. Verifica Dashboard Statistica
    res_dash = client.get("/researcher/dashboard")
    assert res_dash.status_code == 200
    # Media dei punteggi [10, 15, 20, 25, 30] = 20.0
    assert "20.0" in res_dash.text
    assert "BDI-II" in res_dash.text

    # 2. Esportazione CSV
    res_csv = client.get("/researcher/export/csv")
    assert res_csv.status_code == 200
    assert res_csv.headers["content-type"].startswith("text/csv")
    csv_text = res_csv.text
    assert "pseudonym_code" in csv_text
    assert "score_total" in csv_text
    assert "PR-RES-0" in csv_text

    # 3. Esportazione Excel
    res_excel = client.get("/researcher/export/excel")
    assert res_excel.status_code == 200
    assert "spreadsheetml" in res_excel.headers["content-type"]
    assert len(res_excel.content) > 1000

    # 4. Verifica che sia stato registrato l'Audit Trail dell'esportazione
    audits = db_session.query(AuditEvent).filter_by(actor_id=u.id).all()
    assert len(audits) >= 2
    actions = [a.action for a in audits]
    assert "RESEARCH_DATASET_EXPORT_CSV" in actions
    assert "RESEARCH_DATASET_EXPORT_EXCEL" in actions
