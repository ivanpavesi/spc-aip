"""Test di integrazione completi per il modulo di Amministrazione di Sistema (STEP 2, 4, 6, 7)."""

import json
from io import BytesIO
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.core.security import hash_password, verify_password
from app.db.models.admin_config import ClinicalAnalysisButton, ScientificDocument, SystemSetting
from app.db.models.audit import AuditEvent
from app.db.models.test_engine import TestDefinition
from app.db.models.user import Therapist, User, UserRole


def test_admin_dashboard_access_and_rbac(client: TestClient, db_session: Session):
    """Verifica che solo gli amministratori autenticati possano accedere alla dashboard admin."""
    # 1. Non autenticato -> 401 Unauthorized
    res_unauth = client.get("/admin/dashboard", follow_redirects=False)
    assert res_unauth.status_code == 401

    # 2. Login come terapeuta -> 403 Forbidden
    client.post("/auth/login", data={"email": "terapeuta@spc.it", "password": "terapeuta"})
    res_therapist = client.get("/admin/dashboard")
    assert res_therapist.status_code == 403

    # 3. Login come amministratore -> 200 OK
    client.post("/auth/login", data={"email": "admin@spc.it", "password": "admin"})
    res_admin = client.get("/admin/dashboard")
    assert res_admin.status_code == 200
    assert "Amministrazione di Sistema" in res_admin.text
    assert "Utenze & Ruoli" in res_admin.text


def test_admin_user_management(client: TestClient, db_session: Session):
    """Verifica creazione, cambio ruolo, reset password e blocco utenze da amministratore."""
    client.post("/auth/login", data={"email": "admin@spc.it", "password": "admin"})

    # Creazione nuovo terapeuta
    res_create = client.post(
        "/admin/users/new",
        data={
            "email": "nuovo.terapeuta@spc.it",
            "password": "PasswordNuova2026!",
            "role": "THERAPIST",
            "full_name": "Dott.ssa Giulia Bianchi",
            "license_number": "54321/Lombardia",
        },
        follow_redirects=False,
    )
    assert res_create.status_code == 303

    created_user = db_session.query(User).filter(User.email == "nuovo.terapeuta@spc.it").first()
    assert created_user is not None
    assert created_user.role == UserRole.THERAPIST
    assert created_user.is_active is True

    # Verifica profilo terapeuta creato automaticamente
    profile = db_session.query(Therapist).filter(Therapist.user_id == created_user.id).first()
    assert profile is not None
    assert profile.full_name == "Dott.ssa Giulia Bianchi"

    # Modifica Ruolo -> Promozione a Ricercatore
    res_role = client.post(
        f"/admin/users/{created_user.id}/change-role",
        data={"new_role": "RESEARCHER"},
        follow_redirects=False,
    )
    assert res_role.status_code == 303
    db_session.refresh(created_user)
    assert created_user.role == UserRole.RESEARCHER

    # Reset Password
    res_pwd = client.post(
        f"/admin/users/{created_user.id}/reset-password",
        data={"new_password": "NuovaPasswordSicura999!"},
        follow_redirects=False,
    )
    assert res_pwd.status_code == 303
    db_session.refresh(created_user)
    assert verify_password("NuovaPasswordSicura999!", created_user.hashed_password) is True

    # Attiva / Disattiva
    res_toggle = client.post(f"/admin/users/{created_user.id}/toggle-active", follow_redirects=False)
    assert res_toggle.status_code == 303
    db_session.refresh(created_user)
    assert created_user.is_active is False

    # Reset TOTP 2FA
    created_user.totp_enabled = True
    created_user.totp_secret = "JBSWY3DPEHPK3PXP"
    db_session.commit()
    res_totp = client.post(f"/admin/users/{created_user.id}/reset-totp", follow_redirects=False)
    assert res_totp.status_code == 303
    db_session.refresh(created_user)
    assert created_user.totp_enabled is False
    assert created_user.totp_secret is None


def test_admin_test_catalog_management(client: TestClient, db_session: Session):
    """Verifica creazione, modifica e disattivazione questionari nel catalogo psicometrico."""
    client.post("/auth/login", data={"email": "admin@spc.it", "password": "admin"})

    new_test_schema = {
        "items": [
            {
                "id": "item_1",
                "text": "Stato di tensione muscolare",
                "options": [{"label": "Assente", "value": 0}, {"label": "Presente", "value": 1}],
            }
        ]
    }
    new_scoring_rules = {
        "method": "SUM",
        "subscales": {},
        "cutoffs": [
            {"min": 0, "max": 0, "label": "Normale"},
            {"min": 1, "max": 1, "label": "Rilevante"},
        ],
    }

    # Creazione nuovo test
    res_new_test = client.post(
        "/admin/tests/new",
        data={
            "code": "HAM-A",
            "title": "Hamilton Anxiety Rating Scale",
            "version": "1.0.0",
            "description": "Scala per la valutazione dell'ansia somatica e psichica.",
            "items_schema_json": json.dumps(new_test_schema),
            "scoring_rules_json": json.dumps(new_scoring_rules),
        },
        follow_redirects=False,
    )
    assert res_new_test.status_code == 303

    ham_a = db_session.query(TestDefinition).filter(TestDefinition.code == "HAM-A").first()
    assert ham_a is not None
    assert ham_a.title == "Hamilton Anxiety Rating Scale"
    assert len(ham_a.items_schema["items"]) == 1

    # Modifica test
    res_edit = client.post(
        f"/admin/tests/{ham_a.id}/edit",
        data={
            "title": "Hamilton Anxiety Scale - Rev",
            "version": "1.1.0",
            "description": "Descrizione aggiornata.",
            "items_schema_json": json.dumps(new_test_schema),
            "scoring_rules_json": json.dumps(new_scoring_rules),
            "is_active": "true",
        },
        follow_redirects=False,
    )
    assert res_edit.status_code == 303
    db_session.refresh(ham_a)
    assert ham_a.title == "Hamilton Anxiety Scale - Rev"
    assert ham_a.version == "1.1.0"

    # Toggle active
    res_toggle = client.post(f"/admin/tests/{ham_a.id}/toggle-active", follow_redirects=False)
    assert res_toggle.status_code == 303
    db_session.refresh(ham_a)
    assert ham_a.is_active is False


def test_admin_clinical_analysis_button_management(client: TestClient, db_session: Session):
    """Verifica la creazione, modifica prompt ed eliminazione dei pulsanti clinici rapidi."""
    client.post("/auth/login", data={"email": "admin@spc.it", "password": "admin"})

    # Creazione pulsante
    res_create = client.post(
        "/admin/buttons/new",
        data={
            "name": "Schema Therapy Mode Analysis",
            "description": "Identifica i mode attivi secondo Young.",
            "system_prompt": "Identifica i mode bambino vulnerabile, critico interiore e adulto sano.",
            "display_order": 99,
            "version": "1.0-ST",
        },
        follow_redirects=False,
    )
    assert res_create.status_code == 303

    btn = db_session.query(ClinicalAnalysisButton).filter(
        ClinicalAnalysisButton.name == "Schema Therapy Mode Analysis"
    ).first()
    assert btn is not None
    assert btn.display_order == 99

    # Modifica prompt
    res_edit = client.post(
        f"/admin/buttons/{btn.id}/edit",
        data={
            "name": "Schema Therapy Mode Analysis",
            "description": "Descrizione aggiornata",
            "system_prompt": "Prompt aggiornato con focus sul critico punitivo.",
            "display_order": 10,
            "version": "2.0-ST",
            "is_active": "true",
        },
        follow_redirects=False,
    )
    assert res_edit.status_code == 303
    db_session.refresh(btn)
    assert btn.version == "2.0-ST"
    assert "punitivo" in btn.system_prompt

    # Toggle active
    res_toggle = client.post(f"/admin/buttons/{btn.id}/toggle", follow_redirects=False)
    assert res_toggle.status_code == 303
    db_session.refresh(btn)
    assert btn.is_active is False

    # Delete
    res_delete = client.post(f"/admin/buttons/{btn.id}/delete", follow_redirects=False)
    assert res_delete.status_code == 303
    btn_deleted = db_session.query(ClinicalAnalysisButton).filter(
        ClinicalAnalysisButton.id == btn.id
    ).first()
    assert btn_deleted is None


def test_admin_ai_settings_and_connection_test(client: TestClient, db_session: Session):
    """Verifica aggiornamento impostazioni AI multi-LLM e test connettività."""
    client.post("/auth/login", data={"email": "admin@spc.it", "password": "admin"})

    res_settings = client.post(
        "/admin/settings/ai",
        data={
            "ai_provider": "HEURISTIC_OFFLINE",
            "gemini_api_key": "test-key-fake-12345",
            "gemini_model": "gemini-1.5-flash",
            "openai_api_key": "sk-proj-test-12345",
            "openai_model": "gpt-4o",
            "anthropic_api_key": "sk-ant-test-12345",
            "anthropic_model": "claude-3-5-sonnet-20241022",
            "custom_ai_base_url": "https://api.mistral.ai/v1",
            "custom_ai_model": "mistral-large-latest",
            "ai_temperature": "0.1",
            "ai_system_preamble": "Sei un assistente cognitivo specializzato.",
        },
        follow_redirects=False,
    )
    assert res_settings.status_code == 303

    # Verifica persistenza in SystemSetting
    provider_setting = db_session.query(SystemSetting).filter(SystemSetting.key == "AI_PROVIDER").first()
    assert provider_setting is not None
    assert provider_setting.value == "HEURISTIC_OFFLINE"

    openai_model_setting = db_session.query(SystemSetting).filter(SystemSetting.key == "OPENAI_MODEL").first()
    assert openai_model_setting is not None
    assert openai_model_setting.value == "gpt-4o"

    # Test connettività per target specifico (Heuristic)
    res_test = client.post(
        "/admin/settings/ai/test-connection",
        data={"target_provider": "HEURISTIC_OFFLINE"},
        follow_redirects=True,
    )
    assert res_test.status_code == 200
    assert "operativo" in res_test.text.lower() or "offline" in res_test.text.lower()


def test_admin_scientific_document_upload_and_rag(client: TestClient, db_session: Session):
    """Verifica caricamento documenti scientifici, estrazione testo e indicizzazione RAG."""
    client.post("/auth/login", data={"email": "admin@spc.it", "password": "admin"})

    sample_doc_content = b"Linee guida SPC: il modello di formulazione del caso clinico richiede l'analisi dei circoli viziosi di mantenimento e degli scopi."
    res_upload = client.post(
        "/admin/documents/upload",
        data={"title": "Linee Guida Formulazione Caso 2026", "test_id": ""},
        files={"document_file": ("linee_guida.txt", BytesIO(sample_doc_content), "text/plain")},
        follow_redirects=False,
    )
    assert res_upload.status_code == 303

    doc = db_session.query(ScientificDocument).filter(
        ScientificDocument.title == "Linee Guida Formulazione Caso 2026"
    ).first()
    assert doc is not None
    assert "circoli viziosi" in doc.extracted_text

    # Verifica eliminazione documento
    res_del = client.post(f"/admin/documents/{doc.id}/delete", follow_redirects=False)
    assert res_del.status_code == 303
    doc_after = db_session.query(ScientificDocument).filter(ScientificDocument.id == doc.id).first()
    assert doc_after is None
