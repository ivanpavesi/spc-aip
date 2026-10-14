"""Configurazione fixture e ambiente di test per pytest."""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Configura le variabili d'ambiente di test PRIMA di importare l'applicazione
os.environ["ENVIRONMENT"] = "testing"
os.environ["DEBUG"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["APP_SECRET_KEY"] = "test-secret-key-32-chars-minimum-spc-platform"
os.environ["APP_ENCRYPTION_KEY"] = "EnJr5iK_Y0dfCXOmqEspSzmTk8QL1eRIkg3XIkm7ync="

import sys
from pathlib import Path

# Assicura che la root del progetto sia nel sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
import app.db.models  # noqa: F401
from app.main import app

# Database SQLite in memoria isolato per i test
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    bind=test_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Crea tutte le tabelle nel database in-memory per l'intera sessione di test e applica i seed."""
    from app.db.seeds import seed_database
    Base.metadata.create_all(bind=test_engine)
    with TestingSessionLocal() as session:
        seed_database(session)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session() -> Session:
    """Fixture che fornisce una sessione di database isolata con rollback automatico."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session: Session) -> TestClient:
    """Fixture che fornisce un TestClient FastAPI con database in memoria iniettato."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
