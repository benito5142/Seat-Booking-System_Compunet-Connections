import concurrent.futures
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models import Seat


def test_concurrent_overlapping_holds():
    """
    Simulates two users simultaneously attempting to hold overlapping seats:
    User 1: ['I1', 'I2']
    User 2: ['I2', 'I3']
    Exactly one request must succeed (HTTP 201), and the other must fail (HTTP 409).
    The seat map must never be corrupted with partial reservations.
    """
    client1 = TestClient(app)
    client2 = TestClient(app)

    # Ensure seats I1, I2, I3 are clean and available
    client1.post("/holds/cleanup")
    db = SessionLocal()
    try:
        seats = db.query(Seat).filter(Seat.id.in_(["I1", "I2", "I3"])).all()
        for s in seats:
            s.status = "available"
        db.commit()
    finally:
        db.close()

    def attempt_hold_1():
        return client1.post("/holds", json={"seats": ["I1", "I2"], "user_id": "user_1"})

    def attempt_hold_2():
        return client2.post("/holds", json={"seats": ["I2", "I3"], "user_id": "user_2"})

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(attempt_hold_1)
        f2 = executor.submit(attempt_hold_2)
        res1 = f1.result()
        res2 = f2.result()

    statuses = [res1.status_code, res2.status_code]
    assert 201 in statuses, f"At least one request should succeed: {statuses}"
    assert 409 in statuses, f"The conflicting request should receive 409: {statuses}"

    # Verify database state
    db = SessionLocal()
    try:
        seat_i2 = db.query(Seat).filter(Seat.id == "I2").first()
        assert seat_i2.status == "held"
        if res1.status_code == 201:
            # User 1 won: I1 & I2 must be held, I3 must remain available
            seat_i1 = db.query(Seat).filter(Seat.id == "I1").first()
            seat_i3 = db.query(Seat).filter(Seat.id == "I3").first()
            assert seat_i1.status == "held"
            assert seat_i3.status == "available"
        else:
            # User 2 won: I2 & I3 must be held, I1 must remain available
            seat_i1 = db.query(Seat).filter(Seat.id == "I1").first()
            seat_i3 = db.query(Seat).filter(Seat.id == "I3").first()
            assert seat_i1.status == "available"
            assert seat_i3.status == "held"
    finally:
        db.close()
