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
