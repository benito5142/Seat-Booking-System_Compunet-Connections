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
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
import tempfile
import os

TEST_DB_FILE = os.path.join(tempfile.gettempdir(), "seat_booking_test.db")
if os.path.exists(TEST_DB_FILE):
    try:
        os.remove(TEST_DB_FILE)
    except Exception:
        pass

test_engine = create_engine(
    f"sqlite:///{TEST_DB_FILE}",
    connect_args={"check_same_thread": False, "timeout": 30.0},
)

@event.listens_for(test_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA busy_timeout = 30000;")
    cursor.close()

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

@pytest.fixture
def reset_test_db():
    """Resets database state between functional test runs."""
    with test_engine.connect() as connection:
        raw_conn = connection.connection.dbapi_connection
        cursor = raw_conn.cursor()
        cursor.execute("DELETE FROM booking_seats")
        cursor.execute("DELETE FROM bookings")
        cursor.execute("DELETE FROM hold_seats")
        cursor.execute("DELETE FROM holds")
        cursor.execute("UPDATE seats SET status = 'AVAILABLE', version = 0")
        raw_conn.commit()
    yield
