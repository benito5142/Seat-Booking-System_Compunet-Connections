import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from backend.app.main import app
from backend.app.database import engine


@pytest.fixture(autouse=True)
def reset_db_state():
    """Resets seat statuses to 'available' and removes holds/bookings before each test."""
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM booking_seats"))
        conn.execute(text("DELETE FROM bookings"))
        conn.execute(text("DELETE FROM hold_seats"))
        conn.execute(text("DELETE FROM holds"))
        conn.execute(text("UPDATE seats SET status = 'available'"))
        conn.commit()
    yield


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
