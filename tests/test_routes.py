"""Test per gli endpoint HTTP, la homepage, il redirect e lo stato di salute."""

from fastapi.testclient import TestClient


def test_homepage_rendering(client: TestClient):
    """Verifica il corretto rendering della nuova homepage istituzionale."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Verifica intestazione istituzionale
    assert "Scuole di Psicoterapia Cognitiva" in html
    assert "Artificial Intelligence Platform" in html
    assert "(AIP)" in html

    # REQUISITO FONDAMENTALE: Eliminare la dicitura 'Psychometrica' dall'interfaccia
    assert "Psychometrica" not in html

    # Verifica presenza delle due sole card principali
    assert "Accesso Paziente" in html
    assert "Area Terapeuta" in html
    assert "Accedi ai questionari" in html
    assert "Accedi all'area riservata" in html

    # Verifica presenza del logo istituzionale
    assert "logo-spc.png" in html

    # Verifica collegamenti del footer
    assert "Accesso Ricercatore" in html
    assert "Accesso Amministratore" in html

    # Verifica header di sicurezza impostati dal middleware
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"


def test_healthcheck_endpoint(client: TestClient):
    """Verifica che l'endpoint di stato /health funzioni e risponda con esito positivo."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert "version" in data


def test_login_routes_redirects(client: TestClient):
    """Verifica che gli accessi reindirizzino alla schermata di autenticazione protetta."""
    for path, expected_role in [
        ("/therapist/login", "THERAPIST"),
        ("/researcher/login", "RESEARCHER"),
        ("/admin/login", "ADMIN"),
    ]:
        res = client.get(path, follow_redirects=False)
        assert res.status_code == 303
        assert f"/auth/login?role={expected_role}" in res.headers.get("location")

        # Con redirect seguito, mostra la pagina di login
        res_followed = client.get(path, follow_redirects=True)
        assert res_followed.status_code == 200
        assert "Accesso Operatori" in res_followed.text


def test_patient_verify_submission(client: TestClient):
    """Verifica l'invio del codice personale del paziente dalla homepage."""
    # 1. Invio con codice valido reindirizza a /p/{code}
    res = client.post("/patient/verify", data={"access_code": "SPC-TEST-1234"}, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers.get("location") == "/p/SPC-TEST-1234"

    # 2. Invio con codice vuoto reindirizza alla home
    res_empty = client.post("/patient/verify", data={"access_code": "   "}, follow_redirects=False)
    assert res_empty.status_code == 303
    assert res_empty.headers.get("location") == "/"
