"""Regressioni F06: nessun dato reale e nessun SDK/provider esterno invocato."""

from datetime import date
from unittest.mock import Mock

import pytest

from app.core.auth import SESSION_COOKIE_NAME, create_user_session
from app.db.models.admin_config import SystemSetting
from app.db.models.clinical import ClinicalAnalysis, ClinicalRecord, TherapySession
from app.db.models.patient import PatientIdentity
from app.db.models.user import Therapist, User, UserRole
from app.services.ai import provider
from app.services.ai.policy import AIProviderConfigurationError, AIProviderPolicyError, SUPPORTED_PROVIDERS
from app.services.encryption import encryption_service


def configure(db, **values):
    for key, value in values.items():
        row = db.get(SystemSetting, key)
        if row is None:
            db.add(SystemSetting(key=key, value=value))
        else:
            row.value = value
    db.commit()


@pytest.fixture
def external_providers(monkeypatch):
    """Sostituisce ogni costruttore SDK: le credenziali sono soltanto stringhe sintetiche."""
    factories = {}
    for name in ("GeminiAIProvider", "OpenAIProvider", "AnthropicProvider", "CustomOpenAICompatibleProvider"):
        def build(*, model_name, **kwargs):
            instance = Mock()
            instance.model_name = model_name
            instance.generate_clinical_analysis.return_value = "Report sintetico F06"
            instance.test_connection.return_value = (True, "Connessione sintetica")
            return instance
        factories[name] = Mock(side_effect=build)
        monkeypatch.setattr(provider, name, factories[name])
    return factories


@pytest.fixture
def clinical_case(client, db_session):
    user = User(email="f06-therapist@example.test", hashed_password="synthetic-unused-hash", role=UserRole.THERAPIST)
    db_session.add(user)
    db_session.flush()
    therapist = Therapist(user_id=user.id, full_name="Terapeuta sintetico F06")
    db_session.add(therapist)
    db_session.flush()
    patient = PatientIdentity(therapist_id=therapist.id,
                              encrypted_first_name=encryption_service.encrypt_text("Nome sintetico"),
                              encrypted_last_name=encryption_service.encrypt_text("F06"))
    db_session.add(patient)
    db_session.flush()
    record = ClinicalRecord(patient_id=patient.id, therapist_id=therapist.id, pseudonym_code="PR-SYNTHETIC-F06")
    db_session.add(record)
    db_session.flush()
    db_session.add(TherapySession(clinical_record_id=record.id, session_number=1, session_date=date(2026, 1, 1),
                                 encrypted_transcript=encryption_service.encrypt_text("Trascrizione interamente sintetica F06")))
    db_session.commit()
    client.cookies.set(SESSION_COOKIE_NAME, create_user_session(db_session, user))
    return patient, record


def test_offline_blocks_external_model_before_decrypting_clinical_data(
    client, db_session, clinical_case, external_providers, monkeypatch,
):
    patient, record = clinical_case
    configure(db_session, AI_PROVIDER="HEURISTIC_OFFLINE", OPENAI_API_KEY="synthetic-key-f06")
    decrypt = Mock(wraps=encryption_service.decrypt_text)
    monkeypatch.setattr(encryption_service, "decrypt_text", decrypt)

    response = client.post(f"/therapist/patients/{patient.id}/analyze",
                           data={"analysis_type": "Analisi ABC", "llm_model": "gpt-4o"}, follow_redirects=False)

    assert response.status_code == 403
    decrypt.assert_not_called()
    for factory in external_providers.values():
        factory.assert_not_called()
    assert db_session.query(ClinicalAnalysis).filter_by(clinical_record_id=record.id).count() == 0


@pytest.mark.parametrize("active", list(SUPPORTED_PROVIDERS))
@pytest.mark.parametrize("requested", ["gemini-1.5-flash", "gpt-4o", "claude-3-5-sonnet-20241022",
                                        "mistral-large-latest", "cbt-spc-offline", "gpt-forged", "unknown"])
def test_model_cannot_change_configured_destination(active, requested, db_session, external_providers):
    configure(db_session, AI_PROVIDER=active, GEMINI_API_KEY="synthetic-gemini", OPENAI_API_KEY="synthetic-openai",
              ANTHROPIC_API_KEY="synthetic-anthropic")
    if requested in SUPPORTED_PROVIDERS[active]["models"]:
        selected = provider.get_ai_provider(model_name=requested, db=db_session)
        assert selected.model_name == requested
        assert sum(factory.call_count for factory in external_providers.values()) == (active != "HEURISTIC_OFFLINE")
        if active != "HEURISTIC_OFFLINE":
            expected = {"GEMINI": "GeminiAIProvider", "OPENAI": "OpenAIProvider", "ANTHROPIC": "AnthropicProvider",
                        "CUSTOM": "CustomOpenAICompatibleProvider"}[active]
            external_providers[expected].assert_called_once()
    else:
        with pytest.raises(AIProviderPolicyError):
            provider.get_ai_provider(model_name=requested, db=db_session)
        for factory in external_providers.values():
            factory.assert_not_called()


@pytest.mark.parametrize("active,model,factory", [
    ("GEMINI", "gemini-admin-synthetic", "GeminiAIProvider"),
    ("OPENAI", "openai-admin-synthetic", "OpenAIProvider"),
    ("ANTHROPIC", "claude-admin-synthetic", "AnthropicProvider"),
    ("CUSTOM", "local-admin-alias", "CustomOpenAICompatibleProvider"),
])
def test_administrator_configured_model_is_the_default(active, model, factory, db_session, external_providers):
    configure(db_session, AI_PROVIDER=active, **{f"{active}_MODEL": model, f"{active}_API_KEY": "synthetic-key"})
    for requested in (None, "", "  ", model):
        assert provider.get_ai_provider(model_name=requested, db=db_session).model_name == model
    assert external_providers[factory].call_count == 4
    for name, constructor in external_providers.items():
        if name != factory:
            constructor.assert_not_called()


def test_api_keys_alone_never_enable_external_provider(db_session, external_providers, monkeypatch):
    for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CUSTOM_AI_API_KEY"):
        monkeypatch.setenv(key, "synthetic-environment-key")
    db_session.query(SystemSetting).filter_by(key="AI_PROVIDER").delete()
    db_session.commit()
    assert isinstance(provider.get_ai_provider(db=db_session), provider.HeuristicClinicalAIProvider)
    assert isinstance(provider.get_ai_provider(), provider.HeuristicClinicalAIProvider)
    with pytest.raises(AIProviderPolicyError):
        provider.get_ai_provider(model_name="gpt-4o")
    for factory in external_providers.values():
        factory.assert_not_called()


@pytest.mark.parametrize("invalid", ["UNKNOWN", "", "OPENAI-forged"])
def test_invalid_configuration_fails_closed(invalid, db_session, external_providers):
    configure(db_session, AI_PROVIDER=invalid)
    with pytest.raises(AIProviderConfigurationError):
        provider.get_ai_provider(model_name="gpt-4o", db=db_session)
    for factory in external_providers.values():
        factory.assert_not_called()


def test_settings_read_failure_never_infers_a_provider(external_providers):
    db = Mock()
    db.query.side_effect = RuntimeError("synthetic-private-db-details")
    with pytest.raises(AIProviderConfigurationError) as exc:
        provider.get_ai_provider(model_name="gpt-4o", db=db)
    assert "synthetic-private" not in str(exc.value)
    for factory in external_providers.values():
        factory.assert_not_called()


@pytest.mark.parametrize("failure", ["missing_key", "sdk_error", "invalid_temperature"])
def test_unavailable_provider_does_not_decrypt_or_save_a_fallback(
    failure, client, db_session, clinical_case, external_providers, monkeypatch,
):
    patient, record = clinical_case
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    configure(db_session, AI_PROVIDER="OPENAI", OPENAI_API_KEY="" if failure == "missing_key" else "synthetic-key",
              AI_TEMPERATURE="invalid" if failure == "invalid_temperature" else "0.2")
    if failure == "sdk_error":
        external_providers["OpenAIProvider"].side_effect = RuntimeError("synthetic-private-sdk-details")
    decrypt = Mock(wraps=encryption_service.decrypt_text)
    monkeypatch.setattr(encryption_service, "decrypt_text", decrypt)
    response = client.post(f"/therapist/patients/{patient.id}/analyze", data={"analysis_type": "Analisi ABC"},
                           follow_redirects=False)
    assert response.status_code == 503
    assert "synthetic-private" not in response.text
    decrypt.assert_not_called()
    assert db_session.query(ClinicalAnalysis).filter_by(clinical_record_id=record.id).count() == 0


def test_authorized_analysis_uses_only_enabled_provider_and_encrypts_result(
    client, db_session, clinical_case, external_providers,
):
    patient, record = clinical_case
    configure(db_session, AI_PROVIDER="OPENAI", OPENAI_API_KEY="synthetic-key")
    fake = Mock(model_name="gpt-4o-mini")
    fake.generate_clinical_analysis.return_value = "Report sintetico F06"
    external_providers["OpenAIProvider"].side_effect = None
    external_providers["OpenAIProvider"].return_value = fake
    response = client.post(f"/therapist/patients/{patient.id}/analyze",
                           data={"analysis_type": "Analisi ABC", "llm_model": "gpt-4o-mini"}, follow_redirects=False)
    assert response.status_code == 303
    external_providers["OpenAIProvider"].assert_called_once()
    fake.generate_clinical_analysis.assert_called_once()
    assert "Trascrizione interamente sintetica F06" in fake.generate_clinical_analysis.call_args.kwargs["clinical_context"]
    # Il contenuto salvato resta protetto dalla cifratura applicativa esistente.
    saved = db_session.query(ClinicalAnalysis).filter_by(clinical_record_id=record.id).one()
    assert saved.model_name == "gpt-4o-mini"
    assert "Report sintetico" not in saved.encrypted_result
    assert encryption_service.decrypt_text(saved.encrypted_result) == "Report sintetico F06"
    for name, factory in external_providers.items():
        if name != "OpenAIProvider":
            factory.assert_not_called()


def test_display_and_post_follow_policy_changes(client, db_session, clinical_case, external_providers):
    patient, record = clinical_case
    configure(db_session, AI_PROVIDER="OPENAI", OPENAI_API_KEY="synthetic-key", OPENAI_MODEL="openai-admin-synthetic")
    page = client.get(f"/therapist/patients/{patient.id}")
    assert page.status_code == 200
    choices = {choice["id"] for choice in page.context["available_models"]}
    assert {"", "gpt-4o", "gpt-4o-mini", "openai-admin-synthetic"} <= choices
    assert not {"gemini-1.5-pro", "cbt-spc-offline", "mistral-large-latest"} & choices
    configure(db_session, AI_PROVIDER="HEURISTIC_OFFLINE")
    response = client.post(f"/therapist/patients/{patient.id}/analyze",
                           data={"analysis_type": "Analisi ABC", "llm_model": "gpt-4o"}, follow_redirects=False)
    assert response.status_code == 403  # form aperto prima della modifica amministrativa
    assert {choice["id"] for choice in client.get(f"/therapist/patients/{patient.id}").context["available_models"]} == {"", "cbt-spc-offline"}
    for factory in external_providers.values():
        factory.assert_not_called()


def test_admin_connection_probe_is_separate_and_never_receives_clinical_context(
    client, db_session, external_providers,
):
    configure(db_session, AI_PROVIDER="HEURISTIC_OFFLINE", OPENAI_API_KEY="synthetic-key")
    admin = db_session.query(User).filter_by(email="admin@spc.it").one()
    client.cookies.set(SESSION_COOKIE_NAME, create_user_session(db_session, admin))
    fake = Mock(model_name="gpt-4o")
    fake.test_connection.return_value = (True, "Connessione sintetica")
    external_providers["OpenAIProvider"].side_effect = None
    external_providers["OpenAIProvider"].return_value = fake
    response = client.post("/admin/settings/ai/test-connection", data={"target_provider": "OPENAI"}, follow_redirects=False)
    assert response.status_code == 303
    fake.test_connection.assert_called_once_with()
    fake.generate_clinical_analysis.assert_not_called()
    assert db_session.get(SystemSetting, "AI_PROVIDER").value == "HEURISTIC_OFFLINE"
    assert isinstance(provider.get_ai_provider(db=db_session), provider.HeuristicClinicalAIProvider)


def test_therapist_cannot_use_admin_probe(client, db_session, clinical_case, external_providers):
    response = client.post("/admin/settings/ai/test-connection", data={"target_provider": "OPENAI"}, follow_redirects=False)
    assert response.status_code == 403
    for factory in external_providers.values():
        factory.assert_not_called()


def test_other_therapist_cannot_trigger_analysis(client, db_session, clinical_case, external_providers):
    patient, record = clinical_case
    other = User(email="f06-other@example.test", hashed_password="synthetic-unused-hash", role=UserRole.THERAPIST)
    db_session.add(other)
    db_session.flush()
    db_session.add(Therapist(user_id=other.id, full_name="Altro terapeuta sintetico"))
    db_session.commit()
    client.cookies.set(SESSION_COOKIE_NAME, create_user_session(db_session, other))
    response = client.post(f"/therapist/patients/{patient.id}/analyze", data={"analysis_type": "Analisi ABC"},
                           follow_redirects=False)
    assert response.status_code == 404
    for factory in external_providers.values():
        factory.assert_not_called()
    assert db_session.query(ClinicalAnalysis).filter_by(clinical_record_id=record.id).count() == 0
