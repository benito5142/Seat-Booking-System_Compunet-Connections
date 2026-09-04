from datetime import datetime, timedelta
from backend.app.database import SessionLocal
from backend.app.models import Hold, Seat
from backend.app.seats_service import cleanup_expired_holds


def test_hold_expiration_and_cleanup(client):
    # Create hold on H1
    res = client.post("/holds", json={"seats": ["H1"]})
    assert res.status_code == 201
    hold_id = res.json()["id"]

    # Verify H1 is held
    seats_res = client.get("/seats")
    seat_map = {s["id"]: s["status"] for s in seats_res.json()}
    assert seat_map["H1"] == "held"

    # Fast-forward expiration in DB
    db = SessionLocal()
    try:
        hold = db.query(Hold).filter(Hold.id == hold_id).first()
        hold.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    # Call GET /seats which triggers cleanup
    seats_res2 = client.get("/seats")
    seat_map2 = {s["id"]: s["status"] for s in seats_res2.json()}
    assert seat_map2["H1"] == "available"

    # Verify hold status in DB is EXPIRED
    db = SessionLocal()
    try:
        hold = db.query(Hold).filter(Hold.id == hold_id).first()
        assert hold.status == "EXPIRED"
    finally:
        db.close()


def test_cannot_confirm_expired_hold(client):
    # Create hold on H2
    res = client.post("/holds", json={"seats": ["H2"]})
    assert res.status_code == 201
    hold_id = res.json()["id"]

    # Fast-forward expiration in DB
    db = SessionLocal()
    try:
        hold = db.query(Hold).filter(Hold.id == hold_id).first()
        hold.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    # Attempt to confirm
    confirm_res = client.post("/bookings", json={"hold_id": hold_id})
    assert confirm_res.status_code == 400
    assert "expired" in confirm_res.json()["detail"].lower()
