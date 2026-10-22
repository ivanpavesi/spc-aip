"""F04: flussi HTTP su dati sintetici, nessun servizio applicativo esterno."""
import re
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from fastapi import HTTPException

from app.core.auth import create_user_session
from app.core.security import hash_password, hash_token, read_totp_secret
from app.db.models.audit import AuditEvent
from app.db.models.user import AuthSession, User, UserRole
from app.cli.recover_totp import recover_admin_totp

PASSWORD = "Synthetic-F04-password!"
SECRET = "JBSWY3DPEHPK3PXP"


def set_cookie(client, token):
    client.cookies.clear()
    client.cookies.set("aip_session", token, domain="testserver.local", path="/")


def csrf(page):
    return re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)


def new_user(db, enabled=False, secret=None, required=False, role=UserRole.RESEARCHER):
    user = User(email="synthetic-f04@spc.it", hashed_password=hash_password(PASSWORD),
                role=role, totp_enabled=enabled, totp_secret=secret, totp_required=required)
    db.add(user)
    db.commit()
    return user


def login(client, code=None):
    return client.post("/auth/login", data={"email": "synthetic-f04@spc.it", "password": PASSWORD,
                       **({"totp_code": code} if code else {})}, follow_redirects=False)


def begin(client, password=PASSWORD, current_code=""):
    page = client.get("/auth/totp/setup")
    return client.post("/auth/totp/setup", data={"password": password, "current_code": current_code,
                       "csrf_token": csrf(page)}, follow_redirects=False)


def secret_from(page):
    return re.search(r'id="totp-secret">([^<]+)', page.text).group(1)


def verify(client, page, code):
    return client.post("/auth/totp/verify", data={"code": code, "csrf_token": csrf(page)}, follow_redirects=False)


def test_activation_rotates_session_revokes_others_and_never_reveals_active_secret(client, db_session):
    user = new_user(db_session)
    other_token = create_user_session(db_session, user)
    login(client)
    previous_token = client.cookies.get("aip_session")
    start = begin(client)
    secret = secret_from(start)
    assert start.headers["cache-control"] == "no-store"
    db_session.refresh(user)
    assert user.totp_secret is None and not user.totp_enabled
    assert secret not in client.get("/auth/totp/setup").text
    record = db_session.query(AuthSession).filter_by(token_hash=hash_token(client.cookies.get("aip_session"))).one()
    assert secret not in record.totp_pending_secret
    assert verify(client, start, pyotp.TOTP(secret).now()).status_code == 303
    db_session.refresh(user)
    assert user.totp_enabled and user.totp_required and user.mfa_version == 1
    assert user.totp_secret.startswith("enc:") and secret not in user.totp_secret
    assert read_totp_secret(user.totp_secret) == secret
    assert client.cookies.get("aip_session") != previous_token
    assert db_session.query(AuthSession).filter_by(user_id=user.id).count() == 1
    assert client.get("/researcher/dashboard").status_code == 200
    active_page = client.get("/auth/totp/setup")
    assert secret not in active_page.text and "otpauth:" not in active_page.text
    assert verify(client, active_page, pyotp.TOTP(secret).now()).status_code == 401
    for token in (other_token, previous_token):
        set_cookie(client, token)
        assert client.get("/researcher/dashboard").status_code == 401
    assert db_session.query(AuditEvent).filter_by(action="MFA_ACTIVATED", resource_id=user.id).count() == 1


def test_enrollment_requires_password_csrf_and_recent_session_bound_confirmation(client, db_session):
    user = new_user(db_session)
    login(client)
    page = client.get("/auth/totp/setup")
    assert user.totp_secret is None
    assert client.post("/auth/totp/setup", data={"password": PASSWORD}).status_code == 403
    assert client.post("/auth/totp/setup", data={"password": PASSWORD, "csrf_token": "非ascii"}).status_code == 403
    assert begin(client, password="wrong-password").status_code == 401
    assert verify(client, page, "123456").status_code == 401
    start = begin(client)
    secret = secret_from(start)
    token = client.cookies.get("aip_session")
    # Un altro login non eredita la verifica recente né il segreto provvisorio.
    login(client)
    assert verify(client, client.get("/auth/totp/setup"), pyotp.TOTP(secret).now()).status_code == 401
    set_cookie(client, token)
    record = db_session.query(AuthSession).filter_by(token_hash=hash_token(token)).one()
    record.totp_pending_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    db_session.commit()
    assert verify(client, start, pyotp.TOTP(secret).now()).status_code == 401
    db_session.refresh(user)
    assert not user.totp_enabled


@pytest.mark.parametrize("code", ["000000", "12345", "1234567", "abcdef", "１２３４５６", " 123456"])
def test_invalid_enrollment_code_does_not_activate_or_expose_secret(client, db_session, code):
    user = new_user(db_session)
    login(client)
    start = begin(client)
    secret = secret_from(start)
    if code == "000000":
        # Sceglie un codice numerico realmente errato senza probabilità di collisione.
        from app.core.security import time
        step = int(time()) // 30
        valid = {pyotp.TOTP(secret).generate_otp(c) for c in range(step - 2, step + 3)}
        code = next(f"{c:06}" for c in range(100) if f"{c:06}" not in valid)
    response = verify(client, start, code)
    assert response.status_code == 401 and secret not in response.text
    db_session.refresh(user)
    assert not user.totp_enabled


def test_existing_plaintext_totp_login_consumes_code_and_rejects_replay(client, db_session):
    user = new_user(db_session, enabled=True, secret=SECRET)
    code = pyotp.TOTP(SECRET).now()
    assert login(client).status_code == 401
    assert login(client, "abcdef").status_code == 401
    assert login(client, code).status_code == 303
    assert client.get("/researcher/dashboard").status_code == 200
    assert login(client, code).status_code == 401
    db_session.refresh(user)
    assert user.totp_last_counter is not None
    assert user.totp_secret == SECRET  # nessuna conversione silenziosa degli account legacy


@pytest.mark.parametrize("secret", [None, "", "INVALID-BASE32", "enc:corrupt-token"])
def test_enabled_but_inconsistent_configuration_fails_closed(client, db_session, secret):
    user = new_user(db_session, enabled=True, secret=secret)
    assert login(client, "123456").status_code == 401
    token = create_user_session(db_session, user, mfa_verified=True)
    set_cookie(client, token)
    assert client.get("/researcher/dashboard").status_code == 401
    assert client.get("/auth/totp/setup").status_code == 401


def test_unverified_session_is_denied_everywhere_for_enabled_user(client, db_session):
    user = new_user(db_session, enabled=True, secret=SECRET)
    token = create_user_session(db_session, user, mfa_verified=False)
    set_cookie(client, token)
    for path in ("/researcher/dashboard", "/admin/dashboard", "/therapist/dashboard", "/auth/totp/setup"):
        assert client.get(path).status_code == 401
    assert client.get("/auth/login", follow_redirects=False).status_code == 200


def test_required_incomplete_account_has_only_enrollment_access(client, db_session):
    user = new_user(db_session, required=True)
    response = login(client)
    assert response.status_code == 303 and response.headers["location"] == "/auth/totp/setup"
    assert client.get("/researcher/dashboard").status_code == 401
    start = begin(client)
    assert verify(client, start, pyotp.TOTP(secret_from(start)).now()).status_code == 303
    assert client.get("/researcher/dashboard").status_code == 200


def test_no_mfa_accounts_and_other_users_sessions_remain_compatible(client, db_session):
    user = new_user(db_session)
    token = create_user_session(db_session, user, mfa_verified=False)
    set_cookie(client, token)
    assert client.get("/researcher/dashboard").status_code == 200
    assert login(client).status_code == 303
    assert client.get("/researcher/dashboard").status_code == 200
    db_session.refresh(user)
    assert not user.totp_required and user.mfa_version == 0


def test_replacement_keeps_old_factor_until_confirmation_then_revokes_sessions(client, db_session):
    user = new_user(db_session, enabled=True, secret=SECRET)
    token = create_user_session(db_session, user, mfa_verified=True)
    set_cookie(client, token)
    assert begin(client).status_code == 401  # password da sola non sostituisce MFA
    start = begin(client, current_code=pyotp.TOTP(SECRET).now())
    secret = secret_from(start)
    db_session.refresh(user)
    assert user.totp_secret == SECRET and user.totp_enabled
    assert begin(client, current_code=pyotp.TOTP(SECRET).now()).status_code == 401
    assert verify(client, start, pyotp.TOTP(secret).now()).status_code == 303
    db_session.refresh(user)
    assert read_totp_secret(user.totp_secret) == secret and user.mfa_version == 1
    set_cookie(client, token)
    assert client.get("/researcher/dashboard").status_code == 401


def test_mfa_attempt_budget_is_persistent_and_expires(client, db_session):
    user = new_user(db_session, enabled=True, secret=SECRET)
    for _ in range(5):
        assert login(client, "bad-code").status_code == 401
    assert login(client, pyotp.TOTP(SECRET).now()).status_code == 429
    db_session.refresh(user)
    user.mfa_locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert login(client, pyotp.TOTP(SECRET).now()).status_code == 303
    db_session.refresh(user)
    assert user.mfa_failures == 0 and user.mfa_locked_until is None


def test_reset_requires_admin_password_csrf_identity_and_revokes_target_sessions(client, db_session, deterministic_totp_clock):
    target = new_user(db_session, enabled=True, secret=SECRET)
    target_token = create_user_session(db_session, target, True)
    client.post("/auth/login", data={"email": "admin", "password": "admin"})
    # Un amministratore senza MFA può accedere, ma non resettare fattori altrui.
    path = f"/admin/users/{target.id}/reset-totp"
    assert client.post(path, data={"password": "admin", "csrf_token": csrf(client.get("/auth/totp/setup")), "identity_confirmed": "yes"}).status_code == 403
    start = begin(client, password="admin")
    admin_secret = secret_from(start)
    assert verify(client, start, pyotp.TOTP(admin_secret).now()).status_code == 303
    deterministic_totp_clock.now += 30
    admin_token = client.cookies.get("aip_session")
    path = f"/admin/users/{target.id}/reset-totp"
    page = client.get(path)
    data = {"password": "admin", "csrf_token": csrf(page), "identity_confirmed": "yes",
            "current_code": pyotp.TOTP(admin_secret).now()}
    assert client.post(path, data={**data, "csrf_token": "bad"}).status_code == 403
    assert client.post(path, data={**data, "password": "wrong"}).status_code == 401
    assert client.post(path, data={**data, "identity_confirmed": ""}).status_code == 403
    assert client.post(path, data=data, follow_redirects=False).status_code == 303
    db_session.refresh(target)
    assert not target.totp_enabled and not target.totp_secret and target.totp_required
    assert target.mfa_version == 1
    assert client.get("/admin/dashboard").status_code == 200
    assert client.cookies.get("aip_session") != admin_token
    assert db_session.query(AuthSession).filter_by(token_hash=hash_token(admin_token)).count() == 0
    set_cookie(client, target_token)
    assert client.get("/researcher/dashboard").status_code == 401
    assert login(client).headers["location"] == "/auth/totp/setup"
    assert client.get("/researcher/dashboard").status_code == 401
    event = db_session.query(AuditEvent).filter_by(action="USER_TOTP_RESET", resource_id=target.id).one()
    assert SECRET not in str(event.technical_details)


def test_admin_with_mfa_must_supply_fresh_code_and_cannot_reset_self(client, db_session):
    target = new_user(db_session, enabled=True, secret=SECRET)
    admin = db_session.query(User).filter_by(email="admin@spc.it").one()
    admin.totp_enabled = True
    admin.totp_secret = pyotp.random_base32()
    db_session.commit()
    token = create_user_session(db_session, admin, True)
    set_cookie(client, token)
    path = f"/admin/users/{target.id}/reset-totp"
    data = {"password": "admin", "csrf_token": csrf(client.get(path)), "identity_confirmed": "yes"}
    assert client.post(path, data=data).status_code == 401
    assert client.post(f"/admin/users/{admin.id}/reset-totp", data=data).status_code == 403
    code = pyotp.TOTP(admin.totp_secret).now()
    assert client.post(path, data={**data, "current_code": code}, follow_redirects=False).status_code == 303
    assert begin(client, password="admin", current_code=code).status_code == 401


def test_non_admin_cannot_reset(client, db_session):
    user = new_user(db_session)
    login(client)
    assert client.get(f"/admin/users/{user.id}/reset-totp").status_code == 403
    assert client.post(f"/admin/users/{user.id}/reset-totp", data={"password": PASSWORD}).status_code == 403


def test_cross_origin_mfa_posts_are_rejected(client, db_session):
    new_user(db_session)
    login(client)
    page = client.get("/auth/totp/setup")
    for headers in ({"Origin": "https://attacker.invalid"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "https://[invalid"}):
        assert client.post("/auth/totp/setup", data={"password": PASSWORD, "csrf_token": csrf(page)}, headers=headers).status_code == 403


def test_operator_recovery_only_for_admin_with_password_and_audit_ticket(client, db_session):
    user = new_user(db_session, enabled=True, secret=SECRET, role=UserRole.ADMIN)
    old_token = create_user_session(db_session, user, True)
    original = (user.hashed_password, user.role, user.is_active)
    with pytest.raises(HTTPException):
        recover_admin_totp(db_session, user.id, "wrong", "F04-TEST-1")
    db_session.refresh(user)
    assert user.totp_enabled
    recover_admin_totp(db_session, user.id, PASSWORD, "F04-TEST-1")
    db_session.refresh(user)
    assert (user.hashed_password, user.role, user.is_active) == original
    assert user.totp_required and not user.totp_enabled and not user.totp_secret
    assert db_session.query(AuditEvent).filter_by(action="MFA_OPERATOR_RECOVERY", resource_id=user.id).one().technical_details == {"ticket": "F04-TEST-1", "channel": "server_cli"}
    set_cookie(client, old_token)
    assert client.get("/admin/dashboard").status_code == 401
    assert login(client).headers["location"] == "/auth/totp/setup"
    start = begin(client)
    assert verify(client, start, pyotp.TOTP(secret_from(start)).now()).status_code == 303
    assert client.get("/admin/dashboard").status_code == 200


def test_operator_recovery_rejects_nonadmin_and_unstructured_ticket(db_session):
    user = new_user(db_session)
    with pytest.raises(ValueError):
        recover_admin_totp(db_session, user.id, PASSWORD, "F04-TEST-1")
    user.role = UserRole.ADMIN
    db_session.commit()
    with pytest.raises(ValueError):
        recover_admin_totp(db_session, user.id, PASSWORD, "ticket with personal data")


def test_totp_lifetime_is_one_30_second_step(client, db_session, monkeypatch):
    from app.core.security import matching_totp_counter
    new_user(db_session, enabled=True, secret=SECRET)
    # Un orologio esplicito verifica il confine senza attese.
    timestamp = 1800000015
    monkeypatch.setattr("app.core.mfa.matching_totp_counter",
                        lambda secret, code: matching_totp_counter(secret, code, now=timestamp))
    future = pyotp.TOTP(SECRET).at(timestamp + 30)
    assert login(client, future).status_code == 401
    code = pyotp.TOTP(SECRET).at(timestamp)
    assert login(client, code).status_code == 303
    assert login(client, code).status_code == 401
    timestamp += 30
    assert login(client, code).status_code == 401
    assert login(client, future).status_code == 303


def test_valid_fifth_enrollment_attempt_clears_budget_and_lock(client, db_session, deterministic_totp_clock):
    user = new_user(db_session)
    login(client)
    start = begin(client)
    secret = secret_from(start)
    for _ in range(4):
        assert verify(client, start, "bad-code").status_code == 401
    assert verify(client, start, pyotp.TOTP(secret).now()).status_code == 303
    db_session.refresh(user)
    assert user.mfa_failures == 0 and user.mfa_locked_until is None
    deterministic_totp_clock.now += 30
    assert login(client, pyotp.TOTP(secret).now()).status_code == 303


@pytest.mark.parametrize("confirmed", [True, False])
def test_operator_cli_requires_uuid_confirmation_and_keeps_password_out_of_output(db_session, monkeypatch, capsys, confirmed):
    from contextlib import nullcontext
    import app.cli.recover_totp as cli
    user = new_user(db_session, enabled=True, secret=SECRET, role=UserRole.ADMIN)
    token = create_user_session(db_session, user, True)
    monkeypatch.setattr("sys.argv", ["recover_totp", "--user-id", user.id, "--ticket", "F04-TEST-3"])
    monkeypatch.setattr("builtins.input", lambda _: user.id if confirmed else "not-confirmed")
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db_session))
    password_prompts = []
    def hidden_password(prompt):
        password_prompts.append(prompt)
        return PASSWORD
    monkeypatch.setattr(cli.getpass, "getpass", hidden_password)
    if confirmed:
        cli.main()
        assert len(password_prompts) == 1
    else:
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 1 and not password_prompts
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err and SECRET not in output.out + output.err
    db_session.refresh(user)
    assert user.totp_enabled == (not confirmed)
    assert db_session.query(AuthSession).filter_by(token_hash=hash_token(token)).count() == (0 if confirmed else 1)
