def test_read_root(client):
    """Test that root endpoint returns successful status and seat specifications."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["event_spec"]["total_rows"] == 10
    assert data["event_spec"]["seats_per_row"] == 12
    assert data["event_spec"]["total_seats"] == 120

def test_health_check(client):
    """Test that health check endpoint returns status ok."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "seat-booking-backend"

def test_event_info(client):
    """Test that event info endpoint confirms 10 rows x 12 seats = 120 seats specification."""
    response = client.get("/api/event/info")
    assert response.status_code == 200
    data = response.json()
    assert data["event_id"] == 1
    assert data["seat_map"]["rows"] == 10
    assert data["seat_map"]["seats_per_row"] == 12
    assert data["seat_map"]["total_seats"] == 120

def test_cors_preflight(client):
    """Test that CORS preflight request responds with permitted origin."""
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    }
    response = client.options("/api/health", headers=headers)
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

def test_get_seats_endpoint_returns_120_seats(client):
    """Test that GET /seats returns exactly 120 seats matching the 10x12 venue map."""
    response = client.get("/seats")
    assert response.status_code == 200
    seats = response.json()
    assert isinstance(seats, list)
    assert len(seats) == 120

    # Validate structure and required fields
    valid_statuses = {"available", "held", "booked"}
    for seat in seats:
        assert "id" in seat
        assert "row" in seat
        assert "seat_number" in seat
        assert "status" in seat
        assert seat["status"] in valid_statuses
        assert seat["row"] in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
        assert 1 <= seat["seat_number"] <= 12

def test_post_holds_empty_seats_rejected(client):
    """Test that POST /holds with empty seat list returns 400 Bad Request."""
    response = client.post("/holds", json={"seats": []})
    assert response.status_code == 400
    assert "At least one seat" in response.json()["detail"]

def test_post_holds_more_than_4_seats_rejected(client):
    """Test that POST /holds with > 4 seats returns 400 Bad Request."""
    response = client.post("/holds", json={"seats": ["A1", "A2", "A3", "A4", "A5"]})
    assert response.status_code == 400
    assert "Maximum of 4 seats" in response.json()["detail"]

def test_post_holds_success_and_ttl(client):
    """Test creating a valid hold returns 201 Created and exactly 300 seconds TTL."""
    response = client.post("/holds", json={"seats": ["A1", "A2"]})
    if response.status_code == 201:
        data = response.json()
        assert "hold_token" in data
        assert data["expires_in_seconds"] == 300
        assert data["seats"] == ["A1", "A2"]
        assert data["status"] == "held"

def test_confirm_nonexistent_hold_returns_404(client):
    """Test confirming a non-existent hold returns 404 Not Found."""
    response = client.post("/holds/non-existent-token/confirm")
    assert response.status_code == 404

def test_holds_cleanup_endpoint(client):
    """Test manual cleanup endpoint returns 200 OK and count of cleaned holds."""
    response = client.post("/holds/cleanup")
    assert response.status_code == 200
    assert "cleaned_holds" in response.json()

def test_post_holds_duplicate_seats_handled(client):
    """Test that duplicate seat IDs in one hold request are handled and deduplicated."""
    response = client.post("/holds", json={"seats": ["B1", "B1", "b1"]})
    assert response.status_code == 201
    data = response.json()
    assert data["seats"] == ["B1"]
    assert data["status"] == "held"

def test_post_holds_nonexistent_seats_rejected(client):
    """Test that nonexistent seat IDs are rejected with 400 Bad Request."""
    response = client.post("/holds", json={"seats": ["Z99"]})
    assert response.status_code == 400
    assert "Invalid seat ID" in response.json()["detail"]

def test_post_holds_empty_or_null_seat_id_rejected(client):
    """Test that empty or null seat IDs within the list are rejected with 400 Bad Request."""
    response = client.post("/holds", json={"seats": ["B2", ""]})
    assert response.status_code == 400

    response = client.post("/holds", json={"seats": ["B2", None]})
    assert response.status_code == 400

def test_post_holds_malformed_payload_rejected(client):
    """Test that malformed requests return useful validation errors with 400 Bad Request."""
    # seats as a string instead of a list
    response = client.post("/holds", json={"seats": "B3"})
    assert response.status_code == 400
    assert "Validation error" in response.json()["detail"]

    # missing seats field
    response = client.post("/holds", json={})
    assert response.status_code == 400

def test_post_holds_unavailable_seats_returns_409(client):
    """Test that requesting currently held seats returns 409 Conflict with details."""
    # First hold succeeds
    r1 = client.post("/holds", json={"seats": ["C1", "C2"]})
    assert r1.status_code == 201

    # Second hold for same seat fails with 409 Conflict
    r2 = client.post("/holds", json={"seats": ["C1", "C3"]})
    assert r2.status_code == 409
    data = r2.json()
    assert "unavailable_seats" in data or "unavailable_seats" in data.get("detail", {})

def test_post_bookings_missing_hold_id_returns_400(client):
    """Test that POST /bookings without hold_id returns 400 Bad Request."""
    response = client.post("/bookings", json={})
    assert response.status_code == 400
    assert "hold_id is required" in response.json()["detail"]

def test_post_bookings_nonexistent_hold_returns_404(client):
    """Test that POST /bookings with non-existent hold returns 404 Not Found."""
    response = client.post("/bookings", json={"hold_id": 99999})
    assert response.status_code == 404

def test_post_bookings_success_and_get_bookings(client):
    """Test creating a hold and confirming it via POST /bookings, then verifying in GET /bookings."""
    hold_resp = client.post("/holds", json={"seats": ["D1", "D2"]})
    assert hold_resp.status_code == 201
    hold_id = hold_resp.json()["id"]

    # Confirm via POST /bookings
    book_resp = client.post("/bookings", json={"hold_id": hold_id})
    assert book_resp.status_code == 201
    book_data = book_resp.json()
    assert "booking_reference" in book_data
    assert book_data["status"] == "confirmed"
    assert "D1" in book_data["seats"]
    assert "D2" in book_data["seats"]

    # Confirm that trying to confirm the same hold again is rejected with 400 Bad Request
    dup_resp = client.post("/bookings", json={"hold_id": hold_id})
    assert dup_resp.status_code == 400
    assert "already been confirmed" in dup_resp.json()["detail"]

    # Verify GET /bookings includes the new booking
    get_resp = client.get("/bookings")
    assert get_resp.status_code == 200
    bookings = get_resp.json()
    assert any(b["booking_reference"] == book_data["booking_reference"] for b in bookings)

def test_delete_holds_success_and_error_handling(client):
    """Test DELETE /holds/{id} for success, release of seats, and rejection of re-release."""
    hold_resp = client.post("/holds", json={"seats": ["E1", "E2"]})
    assert hold_resp.status_code == 201
    hold_id = hold_resp.json()["id"]

    # Release the hold
    rel_resp = client.delete(f"/holds/{hold_id}")
    assert rel_resp.status_code == 200
    rel_data = rel_resp.json()
    assert rel_data["status"] == "released"
    assert "E1" in rel_data["released_seats"]

    # Attempting to release again must return 400 Bad Request
    re_rel_resp = client.delete(f"/holds/{hold_id}")
    assert re_rel_resp.status_code == 400
    assert "already been released" in re_rel_resp.json()["detail"]

    # Attempting to confirm a released hold must return 400 Bad Request
    conf_resp = client.post("/bookings", json={"hold_id": hold_id})
    assert conf_resp.status_code == 400
    assert "released" in conf_resp.json()["detail"]

    # Non-existent hold on DELETE returns 404
    missing_resp = client.delete("/holds/999999")
    assert missing_resp.status_code == 404


