"""Entry point dell'applicazione FastAPI AIP.

Scuole di Psicoterapia Cognitiva (SPC/APC) — Artificial Intelligence Platform.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings
from app.db.session import init_db
from app.routers import admin, auth, patient, placeholders, public, researcher, therapist


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestione del ciclo di vita dell'applicazione: avvio e chiusura."""
    # Inizializza le tabelle del database all'avvio se non esistono
    init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Piattaforma professionale di psicometria e intelligenza artificiale per le Scuole di Psicoterapia Cognitiva (SPC/APC).",
    version="0.1.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware per l'impostazione degli header di sicurezza HTTP fondamentali."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


# Registrazione Middleware di sicurezza
app.add_middleware(SecurityHeadersMiddleware)

# Configurazione file statici (CSS, loghi, immagini)
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

from app.routers import admin, auth, patient, placeholders, public, researcher, therapist

# Registrazione dei Router
app.include_router(public.router)
app.include_router(auth.router)
app.include_router(therapist.router)
app.include_router(patient.router)
app.include_router(researcher.router)
app.include_router(admin.router)
app.include_router(placeholders.router)


@app.exception_handler(500)
async def internal_server_error_handler(request: Request, exc: Exception):
    """Gestore degli errori 500: evita di mostrare stack trace sensibili all'utente finale."""
    return HTMLResponse(
        status_code=500,
        content="""
        <!DOCTYPE html>
        <html lang="it">
        <head><meta charset="utf-8"><title>Errore del Server</title></head>
        <body style="font-family: sans-serif; background: #F8FAFC; color: #0F172A; padding: 40px; text-align: center;">
            <h2>Si è verificato un errore imprevisto</h2>
            <p>La richiesta non ha potuto essere elaborata. Nessun dato clinico è stato compromesso.</p>
            <p><a href="/" style="color: #0F766E;">Torna alla Home</a></p>
        </body>
        </html>
        """,
    )
