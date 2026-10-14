"""Test di integrazione per autenticazione, sessioni, 2FA e ruoli RBAC (STEP 2)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.core.security import hash_password, verify_totp_code
import pyotp
from app.db.models.user import Therapist, User, UserRole


def test_user_login_and_session(client: TestClient, db_session: Session):
    """Verifica flusso di login e rilascio del cookie di sessione HttpOnly."""
    user = User(
        email="laura.terapeuta@spc.it",
        hashed_password=hash_password("PasswordSicura2026!"),
        role=UserRole.THERAPIST,
    )
    db_session.add(user)
    db_session.commit()

    # Tentativo con password errata -> 401
    res_wrong = client.post(
        "/auth/login",
        data={"email": "laura.terapeuta@spc.it", "password": "PasswordSbagliata!"},
    )
    assert res_wrong.status_code == 401

    # Login corretto -> 303 Redirect e Set-Cookie
    res_ok = client.post(
        "/auth/login",
        data={"email": "laura.terapeuta@spc.it", "password": "PasswordSicura2026!"},
        follow_redirects=False,
    )
    assert res_ok.status_code == 303
    assert "aip_session" in res_ok.cookies
    assert res_ok.headers.get("location") == "/therapist/dashboard"


def test_rbac_access_control(client: TestClient, db_session: Session):
    """Verifica che un utente con ruolo Ricercatore non possa accedere alla dashboard Terapeuta."""
    # Creiamo un ricercatore
    res_user = User(
        email="ricercatore.test@spc.it",
        hashed_password=hash_password("Pass12345!"),
        role=UserRole.RESEARCHER,
    )
    db_session.add(res_user)
    db_session.commit()

    # Login come ricercatore
    client.post(
        "/auth/login",
        data={"email": "ricercatore.test@spc.it", "password": "Pass12345!"},
    )

    # Accesso a /researcher/dashboard -> 200
    res_research = client.get("/researcher/dashboard")
    assert res_research.status_code == 200
    assert "Area Ricerca Scientifica" in res_research.text

    # Accesso vietato a /therapist/dashboard -> 403 Forbidden
    res_therapist = client.get("/therapist/dashboard")
    assert res_therapist.status_code == 403


def test_totp_two_factor_workflow(client: TestClient, db_session: Session):
    """Verifica la generazione e validazione del token 2FA (TOTP)."""
    user = User(
        email="mfa.user@spc.it",
        hashed_password=hash_password("Pass12345!"),
        role=UserRole.THERAPIST,
    )
    db_session.add(user)
    db_session.commit()

    client.post("/auth/login", data={"email": "mfa.user@spc.it", "password": "Pass12345!"})

    # Pagina setup TOTP
    res_setup = client.get("/auth/totp/setup")
    assert res_setup.status_code == 200
    assert "Configurazione Autenticazione a Due Fattori" in res_setup.text

    # Recupera il segreto generato per l'utente dal database
    db_user = db_session.query(User).filter_by(email="mfa.user@spc.it").first()
    assert db_user.totp_secret is not None

    # Genera codice valido con pyotp
    totp = pyotp.TOTP(db_user.totp_secret)
    valid_code = totp.now()

    # Invia verifica
    res_verify = client.post("/auth/totp/verify", data={"code": valid_code}, follow_redirects=False)
    assert res_verify.status_code == 303

    # Verifica che totp_enabled sia diventato True
    db_session.refresh(db_user)
    assert db_user.totp_enabled is True


def test_simplified_shorthand_username_and_passwords(client: TestClient, db_session: Session):
    """Verifica che l'accesso funzioni con credenziali semplificate e username senza @spc.it."""
    # 1. Accesso Admin con shorthand 'admin' / 'admin'
    res_admin = client.post(
        "/auth/login",
        data={"email": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert res_admin.status_code == 303
    assert res_admin.headers["location"] == "/admin/dashboard"

    # 2. Accesso Terapeuta con shorthand 'terapeuta' / 'terapeuta'
    res_therapist = client.post(
        "/auth/login",
        data={"email": "terapeuta", "password": "terapeuta"},
        follow_redirects=False,
    )
    assert res_therapist.status_code == 303
    assert res_therapist.headers["location"] == "/therapist/dashboard"

    # 3. Accesso Ricercatore con shorthand 'ricercatore' / 'ricercatore'
    res_researcher = client.post(
        "/auth/login",
        data={"email": "ricercatore", "password": "ricercatore"},
        follow_redirects=False,
    )
    assert res_researcher.status_code == 303
    assert res_researcher.headers["location"] == "/researcher/dashboard"

