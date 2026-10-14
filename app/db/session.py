"""Gestione della connessione e delle sessioni del database con SQLAlchemy 2."""

from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from app.core.config import settings
from app.db.base import Base

# Configurazione argomenti di connessione specifici per driver
connect_args = {}
engine_kwargs = {
    "echo": settings.DEBUG and settings.ENVIRONMENT == "development",
}

if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    engine_kwargs["connect_args"] = connect_args
else:
    # Per PostgreSQL (Supabase / server dedicato): abilita pool_pre_ping per verificare la connessione
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

engine = create_engine(settings.DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Dependency FastAPI per ottenere una sessione del database per richiesta.

    Garantisce la chiusura della sessione al termine della richiesta HTTP
    e il rollback in caso di errore non gestito.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Crea le tabelle del database se non esistono (utilizzato in test o setup dev)."""
    # Import dei modelli per assicurarci che siano registrati nei metadata
    import app.db.models  # noqa: F401
    from app.db.seeds import seed_database
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
