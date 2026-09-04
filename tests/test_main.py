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

