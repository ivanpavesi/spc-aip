"""Regressioni F01: bootstrap su database SQLite isolati, senza dati clinici."""

from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db import session as database
from app.db.base import Base
from app.db.models.admin_config import ClinicalAnalysisButton, SystemSetting
from app.db.models.test_engine import TestDefinition as QuestionnaireDefinition
from app.db.models.user import Therapist, User, UserRole
from app.db.seeds import seed_database, seed_demo_users


@pytest.fixture
def bootstrap_db(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    Base.metadata.create_all(engine)
    with sessions() as db:
        yield db
    engine.dispose()


def assert_catalog(db):
    assert {row.code for row in db.query(QuestionnaireDefinition)} == {"BDI-II", "STAI-Y1"}
    assert db.query(ClinicalAnalysisButton).count() == 7
    assert db.query(SystemSetting).count() == 4


@pytest.mark.parametrize("environment", ["development", "testing", "production"])
def test_repeated_startup_seeds_only_allowed_accounts(bootstrap_db, monkeypatch, environment):
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    database.init_db()
    database.init_db()
    db = bootstrap_db
    assert_catalog(db)
    users = {user.email: user for user in db.query(User)}
    if environment == "production":
        assert users == {}
        assert db.query(Therapist).count() == 0
    else:
        assert set(users) == {"admin@spc.it", "terapeuta@spc.it", "ricercatore@spc.it"}
        for name in ("admin", "terapeuta", "ricercatore"):
            assert verify_password(name, users[f"{name}@spc.it"].hashed_password)
        assert db.query(Therapist).count() == 1


@pytest.mark.parametrize("environment", ["development", "testing", "production"])
def test_bootstrap_preserves_existing_credentials_and_profiles(bootstrap_db, monkeypatch, environment):
    db = bootstrap_db
    original_hash = hash_password("Password-modificata-2026!")
    for name in ("admin", "terapeuta", "ricercatore"):
        db.add(User(email=f"{name}@spc.it", hashed_password=original_hash,
                    role=UserRole.RESEARCHER, is_active=False, totp_enabled=True,
                    totp_secret="SYNTHETIC-TOTP"))
    db.flush()
    therapist = db.query(User).filter_by(email="terapeuta@spc.it").one()
    db.add(Therapist(user_id=therapist.id, full_name="Profilo sintetico personalizzato"))
    db.commit()
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    database.init_db()
    seed_database(db)  # Anche l'invocazione diretta deve essere sicura.
    db.expire_all()
    for user in db.query(User):
        assert user.hashed_password == original_hash
        assert user.role == UserRole.RESEARCHER
        assert not user.is_active
        assert user.totp_enabled and user.totp_secret == "SYNTHETIC-TOTP"
        assert not verify_password(user.email.split("@")[0], user.hashed_password)
    assert db.query(Therapist).one().full_name == "Profilo sintetico personalizzato"
    assert_catalog(db)


@pytest.mark.parametrize("environment", ["production", "unknown"])
def test_direct_demo_seed_fails_closed_without_touching_db(monkeypatch, environment):
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    db = Mock()
    seed_demo_users(db)
    assert db.mock_calls == []


def test_partial_demo_database_preserves_changed_password(bootstrap_db, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    original_hash = hash_password("Password-personalizzata-2026!")
    bootstrap_db.add(User(email="admin@spc.it", hashed_password=original_hash, role=UserRole.ADMIN))
    bootstrap_db.commit()
    seed_database(bootstrap_db)
    seed_database(bootstrap_db)
    assert bootstrap_db.query(User).count() == 3
    assert bootstrap_db.query(User).filter_by(email="admin@spc.it").one().hashed_password == original_hash
    assert bootstrap_db.query(Therapist).count() == 1
