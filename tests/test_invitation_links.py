"""Regressioni F03: dati sintetici, rendering HTTP e copia in un browser isolato."""

import json
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
from urllib.parse import parse_qs, quote, unquote, urlsplit

import pytest

from app.db.models.test_engine import TestDefinition


PAYLOADS = [
    "');window.__f03_xss=1;//",
    '\");window.__f03_xss=1;//',
    '\"><img src=x onerror="window.__f03_xss=1">',
    "</script><script>window.__f03_xss=1</script>",
    "&#39;);window.__f03_xss=1;//",
    "a/b?next=1&x=2#fragment%27\\\n\u2028\u2029",
]


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def by_id(self, element_id):
        return next(attrs for _, attrs in self.tags if attrs.get("id") == element_id)


@pytest.fixture
def patient_page(client):
    # Account demo creato esclusivamente nel database SQLite in memoria della suite.
    login = client.post("/auth/login", data={"email": "terapeuta@spc.it", "password": "terapeuta"})
    assert login.status_code == 200
    response = client.post(
        "/therapist/patients/new",
        data={"first_name": "Sintetico", "last_name": "F03", "gdpr_clinical": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"]


@pytest.mark.parametrize("token", PAYLOADS + ["token_sintetico-123"])
def test_untrusted_invitation_token_is_data(client, patient_page, token):
    response = client.get(patient_page, params={"invited_token": token})
    assert response.status_code == 200
    elements = Elements(response.text)
    expected = f"http://testserver/p/{quote(token, safe='')}"
    assert elements.by_id("invite-url-field")["value"] == expected
    assert "onclick" not in elements.by_id("copy-invite-link")
    assert not any("__f03_xss" in value for _, attrs in elements.tags
                   for name, value in attrs.items() if name.startswith("on"))
    assert not any(tag in {"img", "script"} and "__f03_xss" in str(attrs)
                   for tag, attrs in elements.tags)
    whatsapp = next(attrs["href"] for tag, attrs in elements.tags
                    if tag == "a" and attrs.get("href", "").startswith("https://wa.me/"))
    assert parse_qs(urlsplit(whatsapp).query)["text"][0].endswith(expected)
    # Il token non può aggiungere query, frammenti o segmenti al link.
    url = urlsplit(expected)
    assert not url.query and not url.fragment
    assert unquote(url.path.removeprefix("/p/")) == token
    assert 'src="/static/js/invitation-link.js" defer' in response.text
    assert client.get("/static/js/invitation-link.js").status_code == 200


def test_generated_invitation_still_opens_questionnaire(client, db_session, patient_page):
    definition = db_session.query(TestDefinition).filter_by(code="BDI-II").one()
    response = client.post(
        f"{patient_page}/assign-test", data={"test_id": definition.id, "days_valid": 7},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    token = parse_qs(urlsplit(location).query)["invited_token"][0]
    detail = client.get(location)
    link = Elements(detail.text).by_id("invite-url-field")["value"]
    assert link == f"http://testserver/p/{token}"
    client.cookies.clear()
    portal = client.get(link)
    assert portal.status_code == 200
    assert "Beck Depression Inventory" in portal.text


def test_invitation_copy_in_browser(client, db_session, patient_page):
    """Opzionale: Node.js, Playwright e Chromium; nessuna richiesta esce dal browser."""
    node = shutil.which("node")
    if not node or subprocess.run(
        [node, "-e", "require.resolve('playwright')"], capture_output=True,
    ).returncode:
        pytest.skip("Test browser: installare Node.js e Playwright (vedere docs/sicurezza_f03.md).")

    cases = []
    definition = db_session.query(TestDefinition).filter_by(code="BDI-II").one()
    assigned = client.post(f"{patient_page}/assign-test", data={"test_id": definition.id}, follow_redirects=False)
    assert assigned.status_code == 303
    generated = client.get(assigned.headers["location"])
    cases.append({"html": generated.text, "expected": Elements(generated.text).by_id("invite-url-field")["value"]})
    for token in PAYLOADS:
        response = client.get(patient_page, params={"invited_token": token})
        cases.append({"html": response.text, "expected": f"http://testserver/p/{quote(token, safe='')}"})

    # Verifica anche l'escaping del template senza dipendere dall'URL encoding del router.
    from app.routers.therapist import templates
    context = dict(generated.context)
    for token in PAYLOADS:
        raw_link = f"http://testserver/p/{token}"
        context.update(invited_token=token, invite_url=raw_link, whatsapp_url=None)
        # Gli input type=text eliminano CR/LF letterali; il router li codifica come %0D/%0A.
        cases.append({"html": templates.get_template("therapist/patient_detail.html").render(context),
                      "expected": raw_link.replace("\r", "").replace("\n", "")})
    cases.append({"html": client.get(patient_page).text, "expected": None})
    result = subprocess.run(
        [node, str(Path(__file__).parent / "browser" / "invitation_links.cjs")],
        input=json.dumps({"cases": cases, "script": client.get("/static/js/invitation-link.js").text}),
        text=True, capture_output=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "browser checks passed" in result.stdout
