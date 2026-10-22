"""Migrazioni e concorrenza con transazioni indipendenti, SQLite e PostgreSQL locale.

F04_TEST_POSTGRES_URL deve puntare a un database *di test* su loopback.
Ogni test PostgreSQL usa uno schema casuale, eliminato al termine.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core import mfa
from app.core.auth import create_user_session
from app.core.security import hash_password, hash_token
from app.db.models.user import AuthSession, User, UserRole
from app.db.session import get_db
from app.main import app

BASE = "84d60c0c67b2"
HEAD = "f04a1"
PASSWORD = "Synthetic-Concurrency-Password!"
SECRET = "JBSWY3DPEHPK3PXP"


def migrate(engine, revision, down=False):
    config = Config("alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        (command.downgrade if down else command.upgrade)(config, revision)


@pytest.fixture(params=["sqlite", "postgresql"])
def isolated_engine(request, tmp_path, monkeypatch):
    # Le migrazioni creano già lo schema. Non riavviare init_db sul motore
    # globale SQLite durante richieste concorrenti con connessioni isolate.
    monkeypatch.setattr("app.main.init_db", lambda: None)
    admin_engine = None
    schema = None
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path}/f04_test.sqlite", connect_args={"check_same_thread": False, "timeout": 15})
    else:
        url = os.environ.get("F04_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("PostgreSQL di test: impostare F04_TEST_POSTGRES_URL (solo loopback).")
        parsed = make_url(url)
        if parsed.host not in {"localhost", "127.0.0.1", "::1"} or not parsed.database.endswith("_test"):
            pytest.fail("Rifiutato DB non locale o senza suffisso _test: mai usare produzione.")
        admin_engine = create_engine(url)
        schema = "f04_test_" + uuid.uuid4().hex
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema} -ctimezone=Europe/Rome"})
    try:
        yield engine
    finally:
        engine.dispose()
        if admin_engine:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin_engine.dispose()


def create_account(engine, enabled=True):
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        user = User(email="f04-concurrent@spc.it", hashed_password=hash_password(PASSWORD),
                    role=UserRole.ADMIN, totp_enabled=enabled, totp_secret=SECRET if enabled else None)
        db.add(user)
        db.commit()
        return factory, user.id


def test_migration_preserves_existing_credentials_roles_factors_and_sessions(isolated_engine):
    engine = isolated_engine
    migrate(engine, BASE)
    now = datetime.now(timezone.utc)
    user_id = str(uuid.uuid4())
    password_hash = hash_password(PASSWORD)
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO users (id,email,hashed_password,role,is_active,totp_secret,totp_enabled,created_at,updated_at)
            VALUES (:id,'legacy-f04@spc.it',:password,'ADMIN',true,:secret,false,:now,:now)"""),
            {"id": user_id, "password": password_hash, "secret": SECRET, "now": now})
        connection.execute(text("""INSERT INTO auth_sessions (id,user_id,token_hash,mfa_verified,expires_at,created_at,updated_at)
            VALUES (:id,:uid,:token,false,:expires,:now,:now)"""),
            {"id": str(uuid.uuid4()), "uid": user_id, "token": hash_token("synthetic-session"), "expires": now + timedelta(days=7), "now": now})
        before_user = connection.execute(text("SELECT * FROM users")).mappings().one()
        before_session = connection.execute(text("SELECT * FROM auth_sessions")).mappings().one()
    migrate(engine, HEAD)
    with engine.connect() as connection:
        after_user = connection.execute(text("SELECT * FROM users")).mappings().one()
        after_session = connection.execute(text("SELECT * FROM auth_sessions")).mappings().one()
        assert all(after_user[k] == v for k, v in before_user.items())
        assert all(after_session[k] == v for k, v in before_session.items())
        assert after_user["mfa_version"] == after_session["mfa_version"] == 0
        assert not after_user["totp_required"]
    migrate(engine, BASE, down=True)
    assert "mfa_version" not in {column["name"] for column in inspect(engine).get_columns("users")}
    migrate(engine, HEAD)
    factory = sessionmaker(engine)
    with factory() as db:
        from app.core.auth import get_current_user_optional
        from starlette.requests import Request
        request = Request({"type": "http", "headers": [(b"cookie", b"aip_session=synthetic-session")]})
        assert get_current_user_optional(request, db).id == user_id


def test_migration_blocks_lossy_downgrade(isolated_engine):
    migrate(isolated_engine, HEAD)
    factory, user_id = create_account(isolated_engine)
    with factory() as db:
        db.get(User, user_id).totp_secret = "enc:synthetic-encrypted-factor"
        db.commit()
    with pytest.raises(RuntimeError, match="Downgrade non sicuro"):
        migrate(isolated_engine, BASE, down=True)
    assert "mfa_version" in {column["name"] for column in inspect(isolated_engine).get_columns("users")}


def test_concurrent_same_code_allows_exactly_one_real_login(isolated_engine):
    migrate(isolated_engine, HEAD)
    factory, user_id = create_account(isolated_engine)
    barrier = Barrier(2)
    # Ogni richiesta riceve una propria sessione e connessione DB.
    def override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override
    code = pyotp.TOTP(SECRET).now()
    def worker():
        with TestClient(app) as client:
            barrier.wait(timeout=10)
            result = client.post("/auth/login", data={"email": "f04-concurrent@spc.it", "password": PASSWORD, "totp_code": code}, follow_redirects=False)
            return result.status_code, "aip_session" in result.cookies
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        assert sorted(results) == [(303, True), (401, False)]
        with factory() as db:
            assert db.query(AuthSession).filter_by(user_id=user_id).count() == 1
            assert db.get(User, user_id).totp_last_counter is not None
    finally:
        app.dependency_overrides.clear()


def test_stale_login_cannot_create_session_after_factor_change(isolated_engine):
    migrate(isolated_engine, HEAD)
    factory, user_id = create_account(isolated_engine, enabled=False)
    with factory() as stale_db:
        stale = stale_db.get(User, user_id)
        with factory() as changed_db:
            changed = changed_db.get(User, user_id)
            mfa.guard_user(changed_db, changed)
            changed.totp_enabled = True
            changed.totp_secret = SECRET
            mfa.invalidate_sessions(changed_db, changed)
            changed_db.commit()
        with pytest.raises(HTTPException) as error:
            mfa.guard_user(stale_db, stale)
        assert error.value.status_code == 409
    with factory() as db:
        assert db.query(AuthSession).filter_by(user_id=user_id).count() == 0


def test_consumption_rolls_back_if_session_creation_fails(isolated_engine):
    migrate(isolated_engine, HEAD)
    factory, user_id = create_account(isolated_engine)
    code = pyotp.TOTP(SECRET).now()
    with factory() as db:
        user = db.get(User, user_id)
        mfa.guard_user(db, user)
        mfa.consume_totp(db, user, code, None)
        db.rollback()  # simula errore prima del commit di sessione e audit
    with factory() as db:
        user = db.get(User, user_id)
        assert user.totp_last_counter is None
        mfa.guard_user(db, user)
        mfa.consume_totp(db, user, code, None)
        create_user_session(db, user, True)


def test_full_lifecycle_with_migrated_schema(isolated_engine, deterministic_totp_clock):
    """HTTP -> sessioni/contatori -> reset -> nuovo enrollment su entrambi i DB."""
    import re
    from app.cli.recover_totp import recover_admin_totp
    from app.core.security import read_totp_secret
    migrate(isolated_engine, HEAD)
    # Come init_db al boot: le migrazioni storiche non includono tutte le
    # tabelle non autenticative; create_all completa solo quelle assenti.
    from app.db.base import Base
    Base.metadata.create_all(isolated_engine)
    factory, user_id = create_account(isolated_engine, enabled=False)
    def override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override
    def csrf(response):
        return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
    def enroll(client):
        page = client.get("/auth/totp/setup")
        start = client.post("/auth/totp/setup", data={"password": PASSWORD, "csrf_token": csrf(page)})
        secret = re.search(r'id="totp-secret">([^<]+)', start.text).group(1)
        result = client.post("/auth/totp/verify", data={"code": pyotp.TOTP(secret).now(), "csrf_token": csrf(start)}, follow_redirects=False)
        assert result.status_code == 303
        assert secret not in client.get("/auth/totp/setup").text
        assert client.get("/admin/dashboard").status_code == 200
        return secret
    try:
        with TestClient(app) as client:
            data = {"email": "f04-concurrent@spc.it", "password": PASSWORD}
            assert client.post("/auth/login", data=data, follow_redirects=False).status_code == 303
            secret = enroll(client)
            # Il codice di attivazione è già consumato anche per il successivo login.
            with factory() as db:
                user = db.get(User, user_id)
                assert read_totp_secret(user.totp_secret) == secret
                code = pyotp.TOTP(secret).generate_otp(user.totp_last_counter)
            assert client.post("/auth/login", data={**data, "totp_code": code}, follow_redirects=False).status_code == 401
            deterministic_totp_clock.now += 30
            assert client.post("/auth/login", data={**data, "totp_code": pyotp.TOTP(secret).now()}, follow_redirects=False).status_code == 303
            with factory() as db:
                recover_admin_totp(db, user_id, PASSWORD, "F04-TEST-2")
            assert client.get("/admin/dashboard").status_code == 401
            restricted = client.post("/auth/login", data=data, follow_redirects=False)
            assert restricted.headers["location"] == "/auth/totp/setup"
            assert client.get("/admin/dashboard").status_code == 401
            new_secret = enroll(client)
            assert secret != new_secret
    finally:
        app.dependency_overrides.clear()


def test_concurrent_enrollment_confirmations_allow_one_activation(isolated_engine):
    import re
    from app.services.encryption import encryption_service
    migrate(isolated_engine, HEAD)
    factory, user_id = create_account(isolated_engine, enabled=False)
    with factory() as db:
        user = db.get(User, user_id)
        tokens = [create_user_session(db, user) for _ in range(2)]
        for record in db.query(AuthSession).filter_by(user_id=user_id):
            record.totp_pending_secret = encryption_service.encrypt_text(SECRET)
            record.totp_pending_at = datetime.now(timezone.utc)
        db.commit()
    def override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override
    barrier = Barrier(2)
    code = pyotp.TOTP(SECRET).now()
    def worker(token):
        with TestClient(app) as client:
            client.cookies.set("aip_session", token)
            page = client.get("/auth/totp/setup")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            barrier.wait(timeout=10)
            result = client.post("/auth/totp/verify", data={"code": code, "csrf_token": csrf}, follow_redirects=False)
            return result.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, tokens))
        assert results.count(303) == 1 and any(result in {401, 409} for result in results)
        with factory() as db:
            assert db.get(User, user_id).mfa_version == 1
            assert db.query(AuthSession).filter_by(user_id=user_id).count() == 1
    finally:
        app.dependency_overrides.clear()


def test_enrollment_expiry_does_not_depend_on_database_timezone(isolated_engine):
    import re
    migrate(isolated_engine, HEAD)
    factory, user_id = create_account(isolated_engine, enabled=False)
    def override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            assert client.post("/auth/login", data={"email": "f04-concurrent@spc.it", "password": PASSWORD}, follow_redirects=False).status_code == 303
            page = client.get("/auth/totp/setup")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            start = client.post("/auth/totp/setup", data={"password": PASSWORD, "csrf_token": csrf})
            secret = re.search(r'id="totp-secret">([^<]+)', start.text).group(1)
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', start.text).group(1)
            with factory() as db:
                record = db.query(AuthSession).filter_by(user_id=user_id).one()
                record.totp_pending_at = datetime.now(timezone.utc) - timedelta(minutes=6)
                db.commit()
            assert client.post("/auth/totp/verify", data={"code": pyotp.TOTP(secret).now(), "csrf_token": csrf}, follow_redirects=False).status_code == 401
            with factory() as db:
                assert not db.get(User, user_id).totp_enabled
    finally:
        app.dependency_overrides.clear()
