def test_release_hold_success(client):
    hold_res = client.post("/holds", json={"seats": ["G1", "G2"]})
    assert hold_res.status_code == 201
    hold_id = hold_res.json()["id"]

    release_res = client.delete(f"/holds/{hold_id}")
    assert release_res.status_code == 200
    assert release_res.json()["status"] == "released"

    # Seats should be available again
    seats_res = client.get("/seats")
    seat_map = {s["id"]: s["status"] for s in seats_res.json()}
    assert seat_map["G1"] == "available"
    assert seat_map["G2"] == "available"


def test_release_nonexistent_hold(client):
    res = client.delete("/holds/999999")
    assert res.status_code == 404
