import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from backend.app.main import app
from backend.app.config import settings
from backend.app.database import get_db
from backend.app.seed import seed_seats_dbapi
from tests.test_schema import SCHEMA_SQL
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

with test_engine.connect() as connection:
    raw_conn = connection.connection.dbapi_connection
    cursor = raw_conn.cursor()
    cursor.executescript(SCHEMA_SQL)
    seed_seats_dbapi(cursor)
    raw_conn.commit()

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient fixture for running integration and endpoint tests."""
    with TestClient(app) as test_client:
        yield test_client

@pytest.fixture(scope="session")
def app_settings():
    """Provides access to configured application settings in tests."""
    return settings
