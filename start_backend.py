"""
Background service launcher for FastAPI backend in the development container.
Ensures database is initialized and uvicorn is running on port 8001.
"""
import os
import sys
import time
import sqlite3
import subprocess
import urllib.request

def init_sqlite_if_needed():
    db_path = "/tmp/seat_booking.db"
    try:
        from tests.test_schema import SCHEMA_SQL
        from backend.app.seed import seed_seats_dbapi
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='seats'")
        if not cur.fetchone():
            conn.executescript(SCHEMA_SQL)
            seed_seats_dbapi(cur)
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database init check: {e}")

def is_backend_healthy():
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=1)
        return req.getcode() == 200
    except Exception:
        return False

def start_backend():
    init_sqlite_if_needed()
    if is_backend_healthy():
        print("Backend already running on port 8001.")
        return

    env = os.environ.copy()
    env["USE_SQLITE"] = "true"
    env["SQLITE_URL"] = "sqlite:////tmp/seat_booking.db"

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8001"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"Spawned backend process PID {proc.pid}")

    # Wait up to 10 seconds for backend to become healthy
    for _ in range(20):
        time.sleep(0.5)
        if is_backend_healthy():
            print("Backend is healthy on http://127.0.0.1:8001")
            return
    print("Warning: Backend did not respond within timeout.")

if __name__ == "__main__":
    start_backend()
