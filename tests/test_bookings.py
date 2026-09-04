def test_confirm_booking_success(client):
    # Hold F1, F2
    hold_res = client.post("/holds", json={"seats": ["F1", "F2"]})
    assert hold_res.status_code == 201
    hold_data = hold_res.json()
    hold_id = hold_data["id"]

    # Confirm via /bookings
    booking_res = client.post("/bookings", json={"hold_id": hold_id, "user_id": "test_user"})
    assert booking_res.status_code == 201
    booking_data = booking_res.json()
    assert booking_data["hold_id"] == hold_id
    assert booking_data["status"] == "confirmed"
    assert "BK-" in booking_data["booking_reference"]
    assert sorted(booking_data["seats"]) == ["F1", "F2"]

    # Verify seats are now booked in GET /seats
    seats_res = client.get("/seats")
    seat_map = {s["id"]: s["status"] for s in seats_res.json()}
    assert seat_map["F1"] == "booked"
    assert seat_map["F2"] == "booked"


def test_cannot_book_without_hold(client):
    res = client.post("/bookings", json={"hold_id": 999999})
    assert res.status_code == 404
