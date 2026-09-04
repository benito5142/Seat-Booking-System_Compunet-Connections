def test_create_valid_hold(client):
    # Release any existing hold on C1, C2 first if any
    client.post("/holds/cleanup")
    
    response = client.post("/holds", json={"seats": ["C1", "C2"]})
    assert response.status_code == 201
    data = response.json()
    assert "hold_token" in data
    assert data["seats"] == ["C1", "C2"]
    assert data["status"] == "held"
    assert data["expires_in_seconds"] == 300

    # Cleanup: release this hold
    release_res = client.delete(f"/holds/{data['id']}")
    assert release_res.status_code == 200


def test_hold_already_held_seat_conflict(client):
    # First hold
    res1 = client.post("/holds", json={"seats": ["D1"]})
    assert res1.status_code == 201
    hold_id = res1.json()["id"]

    # Second hold on the same seat
    res2 = client.post("/holds", json={"seats": ["D1"]})
    assert res2.status_code == 409

    # Cleanup
    client.delete(f"/holds/{hold_id}")


def test_hold_too_many_seats(client):
    response = client.post("/holds", json={"seats": ["E1", "E2", "E3", "E4", "E5"]})
    assert response.status_code == 400
    assert "Maximum of 4 seats" in response.json()["detail"]


def test_hold_invalid_seat_id(client):
    response = client.post("/holds", json={"seats": ["Z99"]})
    assert response.status_code == 400
    assert "Invalid seat ID" in response.json()["detail"]


def test_hold_empty_seats(client):
    response = client.post("/holds", json={"seats": []})
    assert response.status_code == 400
