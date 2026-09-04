def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "Seat Booking System API" in data["message"]
    assert data["event_spec"]["total_seats"] == 120


def test_health_check(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


def test_event_info(client):
    response = client.get("/api/event/info")
    assert response.status_code == 200
    data = response.json()
    assert data["seat_map"]["total_seats"] == 120
    assert data["seat_map"]["rows"] == 10
    assert data["seat_map"]["seats_per_row"] == 12


def test_get_seats(client):
    response = client.get("/seats")
    assert response.status_code == 200
    seats = response.json()
    assert len(seats) == 120
    seat_ids = [s["id"] for s in seats]
    assert "A1" in seat_ids
    assert "J12" in seat_ids
