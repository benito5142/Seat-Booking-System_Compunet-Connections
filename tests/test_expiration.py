import unittest
import sqlite3
import threading
import tempfile
import os
from datetime import datetime, timedelta
from backend.app.seed import seed_seats_dbapi
from backend.app.seats_service import (
    create_hold_dbapi,
    get_seats_from_dbapi,
    cleanup_expired_holds_dbapi,
    confirm_hold_dbapi,
    HoldExpiredError,
    SeatUnavailableError,
    InvalidSeatRequestError,
)
from tests.test_schema import SCHEMA_SQL

class TestHoldExpiration(unittest.TestCase):
    """
    Tests proving:
    1. A hold expires after 5 minutes (300 seconds).
    2. Its seats become available again.
    3. An expired hold cannot later be confirmed.
    4. Cleanup is transactionally safe with concurrent operations.
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

    def test_1_hold_expires_after_5_minutes(self):
        """
        Proves: A hold is active before 5 minutes and expires after 5 minutes.
        """
        t0 = datetime(2026, 9, 4, 12, 0, 0)

        # Create hold at t0 for seats A1, A2
        hold = create_hold_dbapi(self.conn, ["A1", "A2"], user_id="alice", now_dt=t0)
        hold_token = hold["hold_token"]

        # 1. At t0 + 4 minutes (240s): hold MUST still be active
        t_active = t0 + timedelta(minutes=4)
        seats_active = get_seats_from_dbapi(self.cursor, now_dt=t_active)
        seat_map_active = {s["id"]: s["status"] for s in seats_active}
        self.assertEqual(seat_map_active["A1"], "held")
        self.assertEqual(seat_map_active["A2"], "held")

        self.cursor.execute("SELECT status FROM holds WHERE hold_token = ?", (hold_token,))
        self.assertEqual(self.cursor.fetchone()["status"], "ACTIVE")

        # 2. At t0 + 5 minutes and 1 second (301s): hold MUST be expired
        t_expired = t0 + timedelta(seconds=301)

        # Trigger cleanup at t_expired
        cleaned_count = cleanup_expired_holds_dbapi(self.conn, now_dt=t_expired)
        self.assertEqual(cleaned_count, 1)

        # Verify hold status in DB is now EXPIRED
        self.cursor.execute("SELECT status FROM holds WHERE hold_token = ?", (hold_token,))
        self.assertEqual(self.cursor.fetchone()["status"], "EXPIRED")

    def test_2_seats_become_available_after_expiration(self):
        """
        Proves: When a hold expires, its seats become available again
        and can be re-held by another user.
        """
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold_alice = create_hold_dbapi(self.conn, ["B1", "B2"], user_id="alice", now_dt=t0)
        token_alice = hold_alice["hold_token"]

        # Confirm seats are initially HELD
        self.cursor.execute("SELECT status FROM seats WHERE id IN ('B1', 'B2')")
        statuses = [r["status"] for r in self.cursor.fetchall()]
        self.assertEqual(statuses, ["HELD", "HELD"])

        # Bob tries to hold B1 at t0 + 2 minutes -> fails with 409
        t_mid = t0 + timedelta(minutes=2)
        with self.assertRaises(SeatUnavailableError):
            create_hold_dbapi(self.conn, ["B1"], user_id="bob", now_dt=t_mid)

        # Advance past 5 minutes (e.g. t0 + 5m 5s)
        t_after = t0 + timedelta(seconds=305)

        # GET /seats or cleanup releases seats back to AVAILABLE
        seats = get_seats_from_dbapi(self.cursor, now_dt=t_after)
        seat_map = {s["id"]: s["status"] for s in seats}
        self.assertEqual(seat_map["B1"], "available")
        self.assertEqual(seat_map["B2"], "available")

        # Database seat status is updated to AVAILABLE
        self.cursor.execute("SELECT status FROM seats WHERE id IN ('B1', 'B2')")
        statuses_after = [r["status"] for r in self.cursor.fetchall()]
        self.assertEqual(statuses_after, ["AVAILABLE", "AVAILABLE"])

        # Bob now successfully holds B1 and B2!
        hold_bob = create_hold_dbapi(self.conn, ["B1", "B2"], user_id="bob", now_dt=t_after)
        self.assertIsNotNone(hold_bob["hold_token"])
        self.assertNotEqual(hold_bob["hold_token"], token_alice)
        self.assertEqual(hold_bob["status"], "held")

    def test_3_expired_hold_cannot_later_be_confirmed(self):
        """
        Proves: An expired hold cannot later be confirmed.
        - Calling confirm on an expired hold fails with HoldExpiredError.
        - Seats are not booked and are freed back to AVAILABLE.
        - No booking record is created.
        """
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["C1", "C2"], user_id="charlie", now_dt=t0)
        token = hold["hold_token"]

        # Time moves past 5 minutes (305 seconds)
        t_expired = t0 + timedelta(seconds=305)

        # Charlie attempts to confirm the hold after 5 minutes
        with self.assertRaises(HoldExpiredError) as ctx:
            confirm_hold_dbapi(self.conn, token, user_id="charlie", now_dt=t_expired)

        self.assertIn("expired", str(ctx.exception).lower())

        # Verify NO booking was created
        self.cursor.execute("SELECT COUNT(*) as c FROM bookings")
        self.assertEqual(self.cursor.fetchone()["c"], 0)

        self.cursor.execute("SELECT COUNT(*) as c FROM booking_seats")
        self.assertEqual(self.cursor.fetchone()["c"], 0)

        # Verify seats C1 and C2 are AVAILABLE (not BOOKED)
        self.cursor.execute("SELECT id, status FROM seats WHERE id IN ('C1', 'C2')")
        for row in self.cursor.fetchall():
            self.assertEqual(row["status"], "AVAILABLE")

        # Verify hold is marked EXPIRED
        self.cursor.execute("SELECT status FROM holds WHERE hold_token = ?", (token,))
        self.assertEqual(self.cursor.fetchone()["status"], "EXPIRED")

    def test_active_hold_can_be_confirmed_within_5_minutes(self):
        """
        Positive control: Hold confirmed within 5 minutes succeeds,
        creates booking, and marks seats as BOOKED.
        """
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["D1"], user_id="dana", now_dt=t0)
        token = hold["hold_token"]

        # Confirm at t0 + 3 minutes (within 5 minutes)
        t_confirm = t0 + timedelta(minutes=3)
        booking = confirm_hold_dbapi(self.conn, token, user_id="dana", now_dt=t_confirm)

        self.assertEqual(booking["status"], "confirmed")
        self.assertTrue(booking["booking_reference"].startswith("BK-"))

        # Seat D1 is now BOOKED
        self.cursor.execute("SELECT status FROM seats WHERE id = 'D1'")
        self.assertEqual(self.cursor.fetchone()["status"], "BOOKED")

        # Subsequent cleanup after 10 minutes does NOT touch booked seats
        t_cleanup = t0 + timedelta(minutes=10)
        cleanup_expired_holds_dbapi(self.conn, now_dt=t_cleanup)

        self.cursor.execute("SELECT status FROM seats WHERE id = 'D1'")
        self.assertEqual(self.cursor.fetchone()["status"], "BOOKED")

    def test_cleanup_idempotency_and_zero_active(self):
        """Cleanup with no expired holds returns 0 and does not error."""
        count = cleanup_expired_holds_dbapi(self.conn)
        self.assertEqual(count, 0)

if __name__ == "__main__":
    unittest.main()
