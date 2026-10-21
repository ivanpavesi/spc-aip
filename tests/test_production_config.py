"""Regressioni F02: validazione e avvio locale in modalità production, senza servizi esterni."""

import base64
import os
from pathlib import Path
import secrets
import subprocess
import sys

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import DEMO_ENCRYPTION_KEYS, DEMO_SECRET_KEY, Settings, settings
from app.services.encryption import EncryptionConfigurationError, EncryptionService


@pytest.fixture
def production_config():
    return dict(ENVIRONMENT="production", DEBUG=False,
                DATABASE_URL="sqlite:///isolated_config_test.db",
                APP_SECRET_KEY=secrets.token_hex(32),
                APP_ENCRYPTION_KEY=Fernet.generate_key().decode())


def test_production_accepts_explicit_secure_keys_without_changing_them(production_config):
    config = Settings(_env_file=None, **production_config)
    assert config.APP_ENCRYPTION_KEY == production_config["APP_ENCRYPTION_KEY"]
    assert config.APP_SECRET_KEY == production_config["APP_SECRET_KEY"]
    assert config.APP_ENCRYPTION_KEY not in repr(config)
    assert config.APP_SECRET_KEY not in repr(config)


@pytest.mark.parametrize("field", ["APP_SECRET_KEY", "APP_ENCRYPTION_KEY"])
def test_production_rejects_missing_keys(production_config, monkeypatch, field):
    production_config.pop(field)
    monkeypatch.delenv(field, raising=False)
    with pytest.raises(ValidationError, match=field):
        Settings(_env_file=None, **production_config)


@pytest.mark.parametrize("key", ["", " ", "not-a-fernet-key", *sorted(DEMO_ENCRYPTION_KEYS),
    base64.urlsafe_b64encode(b"\x00" * 32).decode(),
    base64.urlsafe_b64encode(b"0123456789abcdef" * 2).decode(),
    base64.urlsafe_b64encode(b"x" * 31).decode(),
    base64.urlsafe_b64encode(bytes(range(32))).decode() + "!",
    " " + base64.urlsafe_b64encode(bytes(range(32))).decode(),
    "/" * 43 + "=", "à" * 44,
], ids=lambda value: f"invalid-fernet-{len(value)}")
def test_production_rejects_unsafe_encryption_keys(production_config, key):
    production_config["APP_ENCRYPTION_KEY"] = key
    with pytest.raises(ValidationError, match="APP_ENCRYPTION_KEY") as error:
        Settings(_env_file=None, **production_config)
    assert production_config["APP_SECRET_KEY"] not in str(error.value)
    if len(key) > 1:
        assert key not in str(error.value)


@pytest.mark.parametrize("secret", ["", " ", "short", DEMO_SECRET_KEY,
    "cambia-questa-chiave-segreta-con-una-stringa-casuale-robusta-da-almeno-32-caratteri",
    "test-secret-key-32-chars-minimum-spc-platform", "x" * 64,
    "0123456789abcdef" * 4, " " + secrets.token_hex(32),
])
def test_production_rejects_unsafe_session_secrets(production_config, secret):
    production_config["APP_SECRET_KEY"] = secret
    with pytest.raises(ValidationError, match="APP_SECRET_KEY"):
        Settings(_env_file=None, **production_config)


def test_production_requires_independent_keys(production_config):
    production_config["APP_SECRET_KEY"] = production_config["APP_ENCRYPTION_KEY"]
    with pytest.raises(ValidationError, match="APP_SECRET_KEY"):
        Settings(_env_file=None, **production_config)


@pytest.mark.parametrize("url", [
    "sqlite:///./aip_dev.db", "sqlite:///:memory:", "sqlite://",
    "sqlite+pysqlite:///./aip_dev.db?check_same_thread=false",
    "sqlite:///file:synthetic?mode=memory&uri=true",
])
def test_production_rejects_demo_database(production_config, url):
    production_config["DATABASE_URL"] = url
    with pytest.raises(ValidationError, match="database dimostrativo"):
        Settings(_env_file=None, **production_config)


@pytest.mark.parametrize("environment", ["development", "testing"])
def test_demo_configuration_still_supported_explicitly(environment):
    config = Settings(_env_file=None, ENVIRONMENT=environment, DATABASE_URL="sqlite:///:memory:",
                      APP_SECRET_KEY=DEMO_SECRET_KEY, APP_ENCRYPTION_KEY=sorted(DEMO_ENCRYPTION_KEYS)[0])
    assert config.ENVIRONMENT == environment


def test_encryption_key_has_no_default(monkeypatch):
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    config = Settings(_env_file=None, ENVIRONMENT="development")
    assert config.APP_ENCRYPTION_KEY == ""


def test_explicit_empty_key_never_falls_back_to_configured_key():
    with pytest.raises(EncryptionConfigurationError):
        EncryptionService(primary_key="")


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("key", sorted(DEMO_ENCRYPTION_KEYS))
def test_production_service_rejects_demo_keys_including_fallback(monkeypatch, fallback, key):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(EncryptionConfigurationError):
        if fallback:
            EncryptionService(primary_key=Fernet.generate_key().decode(), fallback_keys=[key])
        else:
            EncryptionService(primary_key=key)


def test_secure_existing_ciphertext_remains_readable_in_production(monkeypatch):
    key = Fernet.generate_key().decode()
    ciphertext = Fernet(key.encode()).encrypt(b"dato sintetico")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    service = EncryptionService(primary_key=key)
    assert service.decrypt_text(ciphertext.decode()) == "dato sintetico"
    assert Fernet(key.encode()).decrypt(service.encrypt_text("dato sintetico").encode()) == b"dato sintetico"


@pytest.mark.parametrize("bad_field,bad_value", [
    ("APP_ENCRYPTION_KEY", ""),
    ("APP_ENCRYPTION_KEY", sorted(DEMO_ENCRYPTION_KEYS)[0]),
    ("APP_SECRET_KEY", DEMO_SECRET_KEY),
])
def test_actual_app_import_refuses_unsafe_production_before_db_access(tmp_path, production_config, bad_field, bad_value):
    db_path = tmp_path / "must_not_be_created.db"
    env = dict(os.environ, **{key: str(value) for key, value in production_config.items()})
    env.update(DEBUG="false", DATABASE_URL=f"sqlite:///{db_path}")
    env[bad_field] = bad_value
    result = subprocess.run([sys.executable, "-c", "import app.main"],
                            env=env, cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert bad_field in result.stderr
    assert not db_path.exists()
    assert production_config["APP_SECRET_KEY"] not in result.stderr


def test_actual_production_lifespan_keeps_catalog_without_demo_users(tmp_path, production_config):
    db_path = tmp_path / "synthetic_startup.db"
    env = dict(os.environ, **{key: str(value) for key, value in production_config.items()})
    env.update(DEBUG="false", DATABASE_URL=f"sqlite:///{db_path}")
    script = """
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.db.models.user import User, Therapist
from app.db.models.test_engine import TestDefinition
for _ in range(2):
    with TestClient(app) as client:
        response = client.get('/healthz')
        assert response.status_code == 200
        assert response.json()['database'] == 'ok'
with SessionLocal() as db:
    assert db.query(User).count() == 0
    assert db.query(Therapist).count() == 0
    assert db.query(TestDefinition).count() == 2
print('production startup verified')
"""
    result = subprocess.run([sys.executable, "-c", script],
                            env=env, cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "production startup verified" in result.stdout
