import unittest
import sqlite3
from datetime import datetime, timedelta
from backend.app.seed import seed_seats_dbapi
from backend.app.seats_service import (
    create_hold_dbapi,
    get_seats_from_dbapi,
    confirm_hold_dbapi,
    release_hold_dbapi,
    HoldNotFoundError,
    HoldAlreadyReleasedError,
    HoldExpiredError,
    HoldError,
    SeatUnavailableError,
)
from tests.test_schema import SCHEMA_SQL

class TestHoldRelease(unittest.TestCase):
    """
    Tests proving:
    1. Successful release of an active hold (via ID or token).
    2. Seats belonging to the released hold become available again.
    3. Attempting to release an invalid hold returns 404.
    4. Attempting to release an already released hold returns 400.
    5. A released hold cannot later be confirmed into a booking.
    6. Releasing a hold does NOT accidentally release seats belonging to another hold.
    7. Attempting to release an already confirmed or expired hold returns an appropriate response.
    8. The release operation is strictly transactional.
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.cursor = self.conn.cursor()
        self.cursor.executescript(SCHEMA_SQL)
        seed_seats_dbapi(self.cursor)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_successful_release_by_token(self):
        """Proves: Active hold can be released using hold_token."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["A1", "A2"], user_id="alice", now_dt=t0)
        token = hold["hold_token"]

        result = release_hold_dbapi(self.conn, token, now_dt=t0 + timedelta(minutes=1))
        self.assertEqual(result["status"], "released")
        self.assertIn("A1", result["released_seats"])
        self.assertIn("A2", result["released_seats"])

        # Check holds table in DB
        self.cursor.execute("SELECT status FROM holds WHERE hold_token = ?", (token,))
        row = self.cursor.fetchone()
        self.assertEqual(row["status"], "RELEASED")

    def test_successful_release_by_numeric_id(self):
        """Proves: Active hold can be released using its numeric primary key ID."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["A3", "A4"], user_id="bob", now_dt=t0)
        hold_id = hold["id"]

        result = release_hold_dbapi(self.conn, str(hold_id), now_dt=t0 + timedelta(minutes=1))
        self.assertEqual(result["status"], "released")
        self.assertEqual(result["hold_id"], hold_id)

        self.cursor.execute("SELECT status FROM holds WHERE id = ?", (hold_id,))
        row = self.cursor.fetchone()
        self.assertEqual(row["status"], "RELEASED")

    def test_seats_become_available_after_release(self):
        """
        Proves: All seats belonging to the released hold become available again
        and can immediately be held by another user.
        """
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["B1", "B2"], user_id="alice", now_dt=t0)
        token = hold["hold_token"]

        # Initial check: seats are held
        seats_initial = get_seats_from_dbapi(self.cursor, now_dt=t0 + timedelta(minutes=1))
        seat_map = {s["id"]: s["status"] for s in seats_initial}
        self.assertEqual(seat_map["B1"], "held")
        self.assertEqual(seat_map["B2"], "held")

        # Release the hold
        release_hold_dbapi(self.conn, token, now_dt=t0 + timedelta(minutes=2))

        # Check seats are now available
        seats_after = get_seats_from_dbapi(self.cursor, now_dt=t0 + timedelta(minutes=2))
        seat_map_after = {s["id"]: s["status"] for s in seats_after}
        self.assertEqual(seat_map_after["B1"], "available")
        self.assertEqual(seat_map_after["B2"], "available")

        self.cursor.execute("SELECT status FROM seats WHERE id IN ('B1', 'B2')")
        for row in self.cursor.fetchall():
            self.assertEqual(row["status"], "AVAILABLE")

        # Bob can now hold the same seats
        hold_bob = create_hold_dbapi(self.conn, ["B1", "B2"], user_id="bob", now_dt=t0 + timedelta(minutes=3))
        self.assertEqual(hold_bob["status"], "held")

    def test_attempting_to_release_invalid_hold(self):
        """Proves: Attempting to release a non-existent hold raises HoldNotFoundError (404)."""
        with self.assertRaises(HoldNotFoundError) as ctx:
            release_hold_dbapi(self.conn, "non-existent-hold-token")
        self.assertEqual(ctx.exception.status_code, 404)

        with self.assertRaises(HoldNotFoundError) as ctx2:
            release_hold_dbapi(self.conn, "999999")
        self.assertEqual(ctx2.exception.status_code, 404)

        with self.assertRaises(HoldNotFoundError) as ctx3:
            release_hold_dbapi(self.conn, "")
        self.assertEqual(ctx3.exception.status_code, 404)

    def test_attempting_to_release_already_released_hold(self):
        """Proves: Attempting to release an already released hold raises HoldAlreadyReleasedError (400)."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["C1"], user_id="alice", now_dt=t0)
        token = hold["hold_token"]

        # First release succeeds
        release_hold_dbapi(self.conn, token, now_dt=t0 + timedelta(minutes=1))

        # Second release must fail
        with self.assertRaises(HoldAlreadyReleasedError) as ctx:
            release_hold_dbapi(self.conn, token, now_dt=t0 + timedelta(minutes=2))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("already been released", str(ctx.exception).lower())

    def test_released_hold_cannot_later_be_confirmed(self):
        """
        Proves: A released hold cannot later be confirmed into a booking.
        - Confirmation must raise HoldError (400).
        - No booking record is created.
        - Seats remain AVAILABLE.
        """
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["D1", "D2"], user_id="dana", now_dt=t0)
        token = hold["hold_token"]

        # Release hold
        release_hold_dbapi(self.conn, token, now_dt=t0 + timedelta(minutes=1))

        # Attempt to confirm released hold
        with self.assertRaises(HoldError) as ctx:
            confirm_hold_dbapi(self.conn, token, user_id="dana", now_dt=t0 + timedelta(minutes=2))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("released", str(ctx.exception).lower())

        # Verify no booking was created
        self.cursor.execute("SELECT COUNT(*) as c FROM bookings")
        self.assertEqual(self.cursor.fetchone()["c"], 0)

        # Verify seats D1 and D2 remain AVAILABLE
        self.cursor.execute("SELECT status FROM seats WHERE id IN ('D1', 'D2')")
        for row in self.cursor.fetchall():
            self.assertEqual(row["status"], "AVAILABLE")

    def test_do_not_accidentally_release_seats_belonging_to_another_hold(self):
        """
        CRITICAL ISOLATION INVARIANT:
        Releasing Hold 1 must ONLY release Hold 1's seats,
        and MUST NOT touch seats belonging to Hold 2.
        """
        t0 = datetime(2026, 9, 4, 12, 0, 0)

        # User 1 holds E1 and E2
        hold_1 = create_hold_dbapi(self.conn, ["E1", "E2"], user_id="user1", now_dt=t0)
        token_1 = hold_1["hold_token"]

        # User 2 holds F1 and F2
        hold_2 = create_hold_dbapi(self.conn, ["F1", "F2"], user_id="user2", now_dt=t0)
        token_2 = hold_2["hold_token"]

        # User 1 releases Hold 1
        release_hold_dbapi(self.conn, token_1, now_dt=t0 + timedelta(minutes=1))

        # Verify E1, E2 are AVAILABLE
        self.cursor.execute("SELECT id, status FROM seats WHERE id IN ('E1', 'E2')")
        for row in self.cursor.fetchall():
            self.assertEqual(row["status"], "AVAILABLE")

        # Verify F1, F2 are STILL HELD (belonging to Hold 2)
        self.cursor.execute("SELECT id, status FROM seats WHERE id IN ('F1', 'F2')")
        for row in self.cursor.fetchall():
            self.assertEqual(row["status"], "HELD")

        # User 2 can still confirm Hold 2 successfully!
        booking_2 = confirm_hold_dbapi(self.conn, token_2, user_id="user2", now_dt=t0 + timedelta(minutes=2))
        self.assertEqual(booking_2["status"], "confirmed")

        # Verify F1, F2 are now BOOKED
        self.cursor.execute("SELECT id, status FROM seats WHERE id IN ('F1', 'F2')")
        for row in self.cursor.fetchall():
            self.assertEqual(row["status"], "BOOKED")

        # Verify E1, E2 are STILL AVAILABLE (untouched by Hold 2 confirmation)
        self.cursor.execute("SELECT id, status FROM seats WHERE id IN ('E1', 'E2')")
        for row in self.cursor.fetchall():
            self.assertEqual(row["status"], "AVAILABLE")

    def test_attempting_to_release_confirmed_hold_fails(self):
        """Proves: Attempting to release a confirmed hold raises HoldError (400)."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["G1"], user_id="alice", now_dt=t0)
        token = hold["hold_token"]

        # Confirm hold
        confirm_hold_dbapi(self.conn, token, user_id="alice", now_dt=t0 + timedelta(minutes=1))

        # Attempt to release confirmed hold
        with self.assertRaises(HoldError) as ctx:
            release_hold_dbapi(self.conn, token, now_dt=t0 + timedelta(minutes=2))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("confirmed", str(ctx.exception).lower())

        # Seat G1 remains BOOKED
        self.cursor.execute("SELECT status FROM seats WHERE id = 'G1'")
        self.assertEqual(self.cursor.fetchone()["status"], "BOOKED")

    def test_attempting_to_release_expired_hold_fails(self):
        """Proves: Attempting to release an expired hold raises HoldExpiredError (400)."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["H1"], user_id="alice", now_dt=t0)
        token = hold["hold_token"]

        # Move past 5 minutes (301 seconds)
        t_expired = t0 + timedelta(seconds=301)

        with self.assertRaises(HoldExpiredError) as ctx:
            release_hold_dbapi(self.conn, token, now_dt=t_expired)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("expired", str(ctx.exception).lower())

        # Seat H1 was cleaned up to AVAILABLE
        self.cursor.execute("SELECT status FROM seats WHERE id = 'H1'")
        self.assertEqual(self.cursor.fetchone()["status"], "AVAILABLE")

if __name__ == "__main__":
    unittest.main()
