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

@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient fixture for running integration and endpoint tests."""
    with TestClient(app) as test_client:
        yield test_client

@pytest.fixture(scope="session")
def app_settings():
    """Provides access to configured application settings in tests."""
    return settings
