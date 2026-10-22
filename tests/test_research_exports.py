"""F09 fase 1: HTTP e dati sintetici, nessuna connessione a servizi reali."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.core.auth import create_user_session
from app.core.security import hash_token
from app.db.models.audit import AuditEvent
from app.db.models.research import ResearchDataset, ResearchStudy
from app.db.models.user import AuthSession, User, UserRole


RESEARCH_PATHS = ("/researcher/dashboard", "/researcher/export/csv", "/researcher/export/excel")


@pytest.fixture
def legacy_research(db_session):
    """Anche flag positivi e studi attivi non sono autorizzazioni per operatore."""
    studies = [
        ResearchStudy(code="F09-SYNTH-A", title="F09 titolo riservato A", is_active=True),
        ResearchStudy(code="F09-SYNTH-B", title="F09 titolo riservato B", is_active=False),
    ]
    db_session.add_all(studies)
    db_session.flush()
    for index, study in enumerate(studies):
        db_session.add(ResearchDataset(
            study_id=study.id,
            pseudonym_code=f"F09-SYNTH-PRIVATE-{index}",
            test_code="F09-SYNTH-TEST",
            scores_data={"total": 12345 + index},
            consent_verified=index == 0,
        ))
    db_session.commit()
    return studies


def sign_in(client, db_session, role, **attributes):
    user = User(email=f"f09-{role.value.lower()}@example.test", hashed_password="synthetic-unused",
                role=role, **attributes)
    db_session.add(user)
    db_session.commit()
    token = create_user_session(db_session, user)
    client.cookies.set("aip_session", token)
    return user, token


@pytest.mark.parametrize("role", list(UserRole))
@pytest.mark.parametrize("path", RESEARCH_PATHS)
@pytest.mark.parametrize("filters", ["none", "matching", "other_study", "forged_authorization"])
def test_research_requires_explicit_authorization(client, db_session, legacy_research, role, path, filters):
    user, _ = sign_in(client, db_session, role)
    parameters = {
        "none": {},
        "matching": {"study_id": legacy_research[0].id, "test_code": "F09-SYNTH-TEST"},
        "other_study": {"study_id": legacy_research[1].id, "test_code": "F09-SYNTH-TEST"},
        "forged_authorization": {"study_id": legacy_research[0].id, "authorized": "true",
                                 "consent_verified": "true", "role": "ADMIN", "user_id": user.id},
    }[filters]
    statements = []
    bind = db_session.get_bind()

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(bind, "before_cursor_execute", capture)
    try:
        response = client.get(path, params=parameters)
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert "temporaneamente sospesa" in response.json()["detail"]
    assert "content-disposition" not in response.headers
    for marker in ("F09 titolo riservato", "F09-SYNTH-PRIVATE", "12345", "F09-SYNTH-TEST"):
        assert marker not in response.text
    assert not any("research_studies" in sql or "research_datasets" in sql for sql in statements)
    assert db_session.query(AuditEvent).filter(
        AuditEvent.actor_id == user.id,
        AuditEvent.action.in_(["RESEARCH_DATASET_EXPORT_CSV", "RESEARCH_DATASET_EXPORT_EXCEL"]),
    ).count() == 0


@pytest.mark.parametrize("path", RESEARCH_PATHS)
@pytest.mark.parametrize("session_state", ["anonymous", "expired", "inactive", "unverified_mfa"])
def test_research_keeps_authentication_enforcement(client, db_session, legacy_research, path, session_state):
    if session_state != "anonymous":
        user, token = sign_in(client, db_session, UserRole.RESEARCHER)
        if session_state == "expired":
            session = db_session.query(AuthSession).filter_by(token_hash=hash_token(token)).one()
            session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        elif session_state == "inactive":
            user.is_active = False
        else:
            user.totp_enabled = True
            user.totp_secret = "JBSWY3DPEHPK3PXP"  # sintetico, sessione priva di verifica MFA
        db_session.commit()

    response = client.get(path)
    assert response.status_code == 401
    assert "content-disposition" not in response.headers
    assert "F09-SYNTH-PRIVATE" not in response.text


def test_admin_governance_remains_accessible_without_research_data(client, db_session, legacy_research):
    sign_in(client, db_session, UserRole.ADMIN)
    response = client.get("/admin/dashboard")
    assert response.status_code == 200
    assert "F09-SYNTH-PRIVATE" not in response.text
    for path in RESEARCH_PATHS:
        assert client.get(path).status_code == 403


def test_research_role_change_does_not_grant_research_access(client, db_session, legacy_research):
    user, _ = sign_in(client, db_session, UserRole.RESEARCHER)
    assert client.get("/researcher/export/csv").status_code == 403
    user.role = UserRole.ADMIN
    db_session.commit()
    assert client.get("/admin/dashboard").status_code == 200
    assert client.get("/researcher/export/csv").status_code == 403


def test_research_denied_without_any_studies_or_datasets(client, db_session):
    sign_in(client, db_session, UserRole.RESEARCHER)
    for path in RESEARCH_PATHS:
        assert client.get(path).status_code == 403
