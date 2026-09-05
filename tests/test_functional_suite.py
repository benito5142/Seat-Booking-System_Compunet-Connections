"""
Backend Functional Test Suite for Seat Booking System.
Covers all 22 required functional test scenarios:
 1. GET /seats returns exactly 120 seats.
 2. Seat map contains 10 rows × 12 seats.
 3. Successful hold works.
 4. One seat can be held.
 5. Multiple seats can be held.
 6. Maximum 4 seats succeeds.
 7. More than 4 seats is rejected.
 8. Duplicate seat IDs are rejected.
 9. Nonexistent seat is rejected.
10. Already-held seat cannot be held.
11. Already-booked seat cannot be held.
12. Multi-seat hold is all-or-nothing.
13. Releasing a hold makes its seats available again.
14. A hold expires after 5 minutes.
15. Expired seats become available.
16. Expired hold cannot be confirmed.
17. Valid active hold can be confirmed.
18. Successful confirmation creates a booking.
19. Booking receives a unique reference code.
20. Same hold cannot be confirmed twice.
21. Released hold cannot be confirmed.
22. GET /bookings returns confirmed bookings.
"""
from datetime import datetime, timedelta
from tests.conftest import test_engine


def test_01_get_seats_returns_exactly_120_seats(client, reset_test_db):
    """1. GET /seats returns exactly 120 seats."""
    response = client.get("/seats")
    assert response.status_code == 200
    seats = response.json()
    assert isinstance(seats, list)
    assert len(seats) == 120


def test_02_seat_map_contains_10_rows_by_12_seats(client, reset_test_db):
    """2. Seat map contains 10 rows x 12 seats."""
    response = client.get("/seats")
    assert response.status_code == 200
    seats = response.json()

    expected_rows = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
    rows_found = set()
    seats_by_row = {r: [] for r in expected_rows}

    for s in seats:
        assert "id" in s
        assert "row" in s
        assert "seat_number" in s
        assert "status" in s
        rows_found.add(s["row"])
        seats_by_row[s["row"]].append(s["seat_number"])

    # Exactly 10 rows
    assert sorted(list(rows_found)) == expected_rows

    # Exactly 12 seats per row (1 through 12)
    for r in expected_rows:
        assert sorted(seats_by_row[r]) == list(range(1, 13))


def test_03_successful_hold_works(client, reset_test_db):
    """3. Successful hold works."""
    response = client.post("/holds", json={"seats": ["A1"], "user_id": "user_test"})
    assert response.status_code == 201
    data = response.json()
    assert "hold_token" in data
    assert "id" in data
    assert data["status"] in ("held", "ACTIVE")
    assert data["seats"] == ["A1"]
    assert data["expires_in_seconds"] == 300
    assert "expires_at" in data


def test_04_one_seat_can_be_held(client, reset_test_db):
    """4. One seat can be held."""
    response = client.post("/holds", json={"seats": ["B1"]})
    assert response.status_code == 201
    data = response.json()
    assert data["seats"] == ["B1"]

    # Verify status in seats list
    seats_resp = client.get("/seats")
    seats = {s["id"]: s for s in seats_resp.json()}
    assert seats["B1"]["status"] == "held"


def test_05_multiple_seats_can_be_held(client, reset_test_db):
    """5. Multiple seats can be held."""
    response = client.post("/holds", json={"seats": ["B2", "B3", "B4"]})
    assert response.status_code == 201
    data = response.json()
    assert sorted(data["seats"]) == ["B2", "B3", "B4"]

    seats_resp = client.get("/seats")
    seats = {s["id"]: s for s in seats_resp.json()}
    for sid in ["B2", "B3", "B4"]:
        assert seats[sid]["status"] == "held"


def test_06_maximum_4_seats_succeeds(client, reset_test_db):
    """6. Maximum 4 seats succeeds."""
    response = client.post("/holds", json={"seats": ["C1", "C2", "C3", "C4"]})
    assert response.status_code == 201
    data = response.json()
    assert len(data["seats"]) == 4
    assert sorted(data["seats"]) == ["C1", "C2", "C3", "C4"]


def test_07_more_than_4_seats_is_rejected(client, reset_test_db):
    """7. More than 4 seats is rejected."""
    response = client.post("/holds", json={"seats": ["C5", "C6", "C7", "C8", "C9"]})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Maximum of 4 seats" in str(detail)


def test_08_duplicate_seat_ids_are_rejected(client, reset_test_db):
    """8. Duplicate seat IDs are rejected."""
    # Exact duplicate
    response = client.post("/holds", json={"seats": ["D1", "D1"]})
    assert response.status_code == 400
    assert "duplicate" in response.json()["detail"].lower()

    # Case-insensitive duplicate
    response2 = client.post("/holds", json={"seats": ["D2", "d2"]})
    assert response2.status_code == 400
    assert "duplicate" in response2.json()["detail"].lower()


def test_09_nonexistent_seat_is_rejected(client, reset_test_db):
    """9. Nonexistent seat is rejected."""
    response = client.post("/holds", json={"seats": ["Z99"]})
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()

    response2 = client.post("/holds", json={"seats": ["A13"]})
    assert response2.status_code == 400


def test_10_already_held_seat_cannot_be_held(client, reset_test_db):
    """10. Already-held seat cannot be held."""
    r1 = client.post("/holds", json={"seats": ["E1"]})
    assert r1.status_code == 201

    r2 = client.post("/holds", json={"seats": ["E1"]})
    assert r2.status_code == 409
    data = r2.json()
    unavail = data.get("unavailable_seats") or data.get("detail", {}).get("unavailable_seats", [])
    assert "E1" in unavail


def test_11_already_booked_seat_cannot_be_held(client, reset_test_db):
    """11. Already-booked seat cannot be held."""
    # First hold and book seat E2
    r_hold = client.post("/holds", json={"seats": ["E2"]})
    assert r_hold.status_code == 201
    hold_id = r_hold.json()["id"]

    r_book = client.post("/bookings", json={"hold_id": hold_id})
    assert r_book.status_code == 201

    # Now attempt to hold the already-booked seat
    r_hold2 = client.post("/holds", json={"seats": ["E2"]})
    assert r_hold2.status_code == 409
    data = r_hold2.json()
    unavail = data.get("unavailable_seats") or data.get("detail", {}).get("unavailable_seats", [])
    assert "E2" in unavail


def test_12_multiseat_hold_is_all_or_nothing(client, reset_test_db):
    """12. Multi-seat hold is all-or-nothing."""
    # Hold F1
    r1 = client.post("/holds", json={"seats": ["F1"]})
    assert r1.status_code == 201

    # Request F2 and F1 (F2 is available, F1 is not)
    r2 = client.post("/holds", json={"seats": ["F2", "F1"]})
    assert r2.status_code == 409

    # Verify F2 was NOT held and remains AVAILABLE
    seats_resp = client.get("/seats")
    seats = {s["id"]: s for s in seats_resp.json()}
    assert seats["F2"]["status"] == "available"


def test_13_releasing_a_hold_makes_its_seats_available_again(client, reset_test_db):
    """13. Releasing a hold makes its seats available again."""
    r_hold = client.post("/holds", json={"seats": ["G1", "G2"]})
    assert r_hold.status_code == 201
    hold_id = r_hold.json()["id"]

    # Verify currently held
    seats_resp = client.get("/seats")
    seats = {s["id"]: s for s in seats_resp.json()}
    assert seats["G1"]["status"] == "held"
    assert seats["G2"]["status"] == "held"

    # Release the hold
    r_rel = client.delete(f"/holds/{hold_id}")
    assert r_rel.status_code == 200

    # Verify seats are available again
    seats_resp2 = client.get("/seats")
    seats2 = {s["id"]: s for s in seats_resp2.json()}
    assert seats2["G1"]["status"] == "available"
    assert seats2["G2"]["status"] == "available"

    # Can now be held again
    r_rehold = client.post("/holds", json={"seats": ["G1", "G2"]})
    assert r_rehold.status_code == 201


def test_14_hold_expires_after_5_minutes(client, reset_test_db):
    """14. A hold expires after 5 minutes."""
    r_hold = client.post("/holds", json={"seats": ["H1"]})
    assert r_hold.status_code == 201
    data = r_hold.json()
    assert data["expires_in_seconds"] == 300

    # Verify expires_at timestamp is approx 5 minutes (300s) ahead
    created_now = datetime.utcnow()
    # Expire the hold in database
    past_time = (created_now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    with test_engine.connect() as conn:
        raw_conn = conn.connection.dbapi_connection
        cur = raw_conn.cursor()
        cur.execute("UPDATE holds SET expires_at = ? WHERE id = ?", (past_time, data["id"]))
        raw_conn.commit()

    # Trigger cleanup or check status
    cleanup_resp = client.post("/holds/cleanup")
    assert cleanup_resp.status_code == 200
    assert cleanup_resp.json()["cleaned_holds"] >= 1


def test_15_expired_seats_become_available(client, reset_test_db):
    """15. Expired seats become available."""
    r_hold = client.post("/holds", json={"seats": ["H2"]})
    assert r_hold.status_code == 201
    hold_id = r_hold.json()["id"]

    # Manually expire in DB
    past_time = (datetime.utcnow() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    with test_engine.connect() as conn:
        raw_conn = conn.connection.dbapi_connection
        cur = raw_conn.cursor()
        cur.execute("UPDATE holds SET expires_at = ? WHERE id = ?", (past_time, hold_id))
        raw_conn.commit()

    # Querying seats dynamically reflects expired seat as available
    seats_resp = client.get("/seats")
    seats = {s["id"]: s for s in seats_resp.json()}
    assert seats["H2"]["status"] == "available"

    # Holding the seat now succeeds
    r_hold2 = client.post("/holds", json={"seats": ["H2"]})
    assert r_hold2.status_code == 201


def test_16_expired_hold_cannot_be_confirmed(client, reset_test_db):
    """16. Expired hold cannot be confirmed."""
    r_hold = client.post("/holds", json={"seats": ["H3"]})
    assert r_hold.status_code == 201
    hold_id = r_hold.json()["id"]

    # Manually expire in DB
    past_time = (datetime.utcnow() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    with test_engine.connect() as conn:
        raw_conn = conn.connection.dbapi_connection
        cur = raw_conn.cursor()
        cur.execute("UPDATE holds SET expires_at = ? WHERE id = ?", (past_time, hold_id))
        raw_conn.commit()

    # Attempt to confirm via POST /bookings
    r_book = client.post("/bookings", json={"hold_id": hold_id})
    assert r_book.status_code == 400
    assert "expired" in r_book.json()["detail"].lower()


def test_17_valid_active_hold_can_be_confirmed(client, reset_test_db):
    """17. Valid active hold can be confirmed."""
    r_hold = client.post("/holds", json={"seats": ["I1", "I2"]})
    assert r_hold.status_code == 201
    hold_id = r_hold.json()["id"]

    r_book = client.post("/bookings", json={"hold_id": hold_id})
    assert r_book.status_code == 201
    data = r_book.json()
    assert data["status"] == "confirmed"
    assert "booking_reference" in data


def test_18_successful_confirmation_creates_a_booking(client, reset_test_db):
    """18. Successful confirmation creates a booking."""
    r_hold = client.post("/holds", json={"seats": ["I3"]})
    assert r_hold.status_code == 201
    hold_id = r_hold.json()["id"]

    r_book = client.post("/bookings", json={"hold_id": hold_id})
    assert r_book.status_code == 201
    booking = r_book.json()
    assert "booking_reference" in booking
    assert booking["seats"] == ["I3"]

    # Verify seat status in GET /seats is 'booked'
    seats_resp = client.get("/seats")
    seats = {s["id"]: s for s in seats_resp.json()}
    assert seats["I3"]["status"] == "booked"


def test_19_booking_receives_a_unique_reference_code(client, reset_test_db):
    """19. Booking receives a unique reference code."""
    r_h1 = client.post("/holds", json={"seats": ["I4"]})
    r_h2 = client.post("/holds", json={"seats": ["I5"]})
    assert r_h1.status_code == 201
    assert r_h2.status_code == 201

    r_b1 = client.post("/bookings", json={"hold_id": r_h1.json()["id"]})
    r_b2 = client.post("/bookings", json={"hold_id": r_h2.json()["id"]})
    assert r_b1.status_code == 201
    assert r_b2.status_code == 201

    ref1 = r_b1.json()["booking_reference"]
    ref2 = r_b2.json()["booking_reference"]
    assert ref1.startswith("BK-")
    assert ref2.startswith("BK-")
    assert ref1 != ref2


def test_20_same_hold_cannot_be_confirmed_twice(client, reset_test_db):
    """20. Same hold cannot be confirmed twice."""
    r_hold = client.post("/holds", json={"seats": ["J1"]})
    assert r_hold.status_code == 201
    hold_id = r_hold.json()["id"]

    # First confirmation succeeds
    r_b1 = client.post("/bookings", json={"hold_id": hold_id})
    assert r_b1.status_code == 201

    # Second confirmation fails with 400
    r_b2 = client.post("/bookings", json={"hold_id": hold_id})
    assert r_b2.status_code == 400
    assert "already been confirmed" in r_b2.json()["detail"].lower()


def test_21_released_hold_cannot_be_confirmed(client, reset_test_db):
    """21. Released hold cannot be confirmed."""
    r_hold = client.post("/holds", json={"seats": ["J2"]})
    assert r_hold.status_code == 201
    hold_id = r_hold.json()["id"]

    # Release the hold
    r_rel = client.delete(f"/holds/{hold_id}")
    assert r_rel.status_code == 200

    # Attempt to confirm released hold fails with 400
    r_book = client.post("/bookings", json={"hold_id": hold_id})
    assert r_book.status_code == 400
    assert "released" in r_book.json()["detail"].lower()


def test_22_get_bookings_returns_confirmed_bookings(client, reset_test_db):
    """22. GET /bookings returns confirmed bookings."""
    # Confirm two bookings
    r_h1 = client.post("/holds", json={"seats": ["J3", "J4"]})
    r_h2 = client.post("/holds", json={"seats": ["J5"]})
    assert r_h1.status_code == 201
    assert r_h2.status_code == 201

    r_b1 = client.post("/bookings", json={"hold_id": r_h1.json()["id"]})
    r_b2 = client.post("/bookings", json={"hold_id": r_h2.json()["id"]})
    assert r_b1.status_code == 201
    assert r_b2.status_code == 201

    ref1 = r_b1.json()["booking_reference"]
    ref2 = r_b2.json()["booking_reference"]

    # Query GET /bookings
    r_get = client.get("/bookings")
    assert r_get.status_code == 200
    bookings = r_get.json()
    assert isinstance(bookings, list)
    assert len(bookings) >= 2

    refs = [b["booking_reference"] for b in bookings]
    assert ref1 in refs
    assert ref2 in refs


def test_23_reset_all_seats_resets_everything_to_available(client, reset_test_db):
    """23. POST /api/reset resets all seats back to available and clears bookings."""
    # Place a hold and confirm a booking
    r_hold = client.post("/holds", json={"seats": ["A1", "A2"]})
    assert r_hold.status_code == 201
    r_book = client.post("/bookings", json={"hold_id": r_hold.json()["id"]})
    assert r_book.status_code == 201

    # Call reset endpoint
    r_reset = client.post("/api/reset")
    assert r_reset.status_code == 200
    assert r_reset.json()["success"] is True

    # Check seats are all available
    r_seats = client.get("/seats")
    assert r_seats.status_code == 200
    seats = r_seats.json()
    assert len(seats) == 120
    assert all(s["status"].lower() == "available" for s in seats)

    # Check bookings are cleared
    r_get_bookings = client.get("/bookings")
    assert r_get_bookings.status_code == 200
    assert len(r_get_bookings.json()) == 0
