import unittest
import sqlite3
import re
import tempfile
import os
import concurrent.futures
from datetime import datetime, timedelta
from backend.app.seed import seed_seats_dbapi
from backend.app.seats_service import (
    create_hold_dbapi,
    confirm_hold_dbapi,
    release_hold_dbapi,
    get_seats_from_dbapi,
    get_bookings_dbapi,
    HoldNotFoundError,
    HoldExpiredError,
    HoldAlreadyReleasedError,
    HoldError,
    SeatUnavailableError,
)
from tests.test_schema import SCHEMA_SQL

class TestBookingsConfirmation(unittest.TestCase):
    """
    Tests proving:
    1. Successful confirmation creates exactly one booking and converts seats to BOOKED.
    2. Hold confirmed by hold ID (integer or numeric string) or token.
    3. Expired hold cannot be confirmed and cleans up seats to AVAILABLE.
    4. Released hold cannot be confirmed.
    5. Invalid hold returns 404 (HoldNotFoundError).
    6. Duplicate confirmation of the same hold is strictly prevented.
    7. Unique booking reference code generation (e.g. BK-XXXXXXXX).
    8. Concurrent attempts to confirm the same hold are handled safely (only 1 succeeds).
    9. Transaction safety: failure does not leave partially booked seats.
    10. All seats must still belong to that hold and have status HELD.
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

    def test_successful_confirmation_by_hold_id(self):
        """Proves: Confirming a hold by its ID succeeds, books seats, and creates 1 booking."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        seats_to_book = ["A1", "A2"]
        hold = create_hold_dbapi(self.conn, seats_to_book, user_id="alice", now_dt=t0)
        hold_id = hold["hold_id"]

        # Confirm using hold_id
        t_confirm = t0 + timedelta(minutes=2)
        booking = confirm_hold_dbapi(self.conn, hold_id=hold_id, user_id="alice", now_dt=t_confirm)

        # Assert response details
        self.assertEqual(booking["status"], "confirmed")
        self.assertEqual(booking["hold_id"], hold_id)
        self.assertEqual(booking["seats"], seats_to_book)
        self.assertTrue(booking["booking_reference"].startswith("BK-"))

        # Verify seats in DB are BOOKED
        self.cursor.execute("SELECT id, status FROM seats WHERE id IN ('A1', 'A2')")
        seat_rows = self.cursor.fetchall()
        self.assertEqual(len(seat_rows), 2)
        for row in seat_rows:
            self.assertEqual(row["status"], "BOOKED")

        # Verify exactly ONE booking was created in the bookings table
        self.cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE hold_id = ?", (hold_id,))
        count = self.cursor.fetchone()["count"]
        self.assertEqual(count, 1)

        # Verify booking_seats table entries
        self.cursor.execute("SELECT seat_id FROM booking_seats WHERE booking_id = ?", (booking["booking_id"],))
        booked_seat_rows = [r["seat_id"] for r in self.cursor.fetchall()]
        self.assertEqual(sorted(booked_seat_rows), sorted(seats_to_book))

        # Verify hold status in holds table is CONFIRMED
        self.cursor.execute("SELECT status FROM holds WHERE id = ?", (hold_id,))
        h_status = self.cursor.fetchone()["status"]
        self.assertEqual(h_status, "CONFIRMED")

    def test_successful_confirmation_by_hold_token(self):
        """Proves: Confirming a hold by token also succeeds seamlessly."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["B5", "B6"], user_id="bob", now_dt=t0)
        token = hold["hold_token"]

        t_confirm = t0 + timedelta(minutes=1)
        booking = confirm_hold_dbapi(self.conn, token, user_id="bob", now_dt=t_confirm)
        self.assertEqual(booking["status"], "confirmed")
        self.assertEqual(booking["seats"], ["B5", "B6"])

    def test_expired_hold_cannot_be_confirmed(self):
        """Proves: An expired hold cannot be confirmed and its seats become AVAILABLE."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["C1", "C2"], user_id="charlie", now_dt=t0)
        hold_id = hold["hold_id"]

        # Confirm attempted at 5 minutes and 1 second later
        t_expired = t0 + timedelta(minutes=5, seconds=1)
        with self.assertRaises(HoldExpiredError) as ctx:
            confirm_hold_dbapi(self.conn, hold_id=hold_id, user_id="charlie", now_dt=t_expired)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("expired", str(ctx.exception).lower())

        # Check seats are reverted to AVAILABLE
        self.cursor.execute("SELECT status FROM seats WHERE id IN ('C1', 'C2')")
        for row in self.cursor.fetchall():
            self.assertEqual(row["status"], "AVAILABLE")

        # Check no booking was created
        self.cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE hold_id = ?", (hold_id,))
        self.assertEqual(self.cursor.fetchone()["count"], 0)

        # Check hold marked EXPIRED
        self.cursor.execute("SELECT status FROM holds WHERE id = ?", (hold_id,))
        self.assertEqual(self.cursor.fetchone()["status"], "EXPIRED")

    def test_released_hold_cannot_be_confirmed(self):
        """Proves: A released hold cannot later be confirmed into a booking."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["D1", "D2"], user_id="dana", now_dt=t0)
        hold_id = hold["hold_id"]

        # Release hold
        release_hold_dbapi(self.conn, hold_id, now_dt=t0 + timedelta(minutes=1))

        # Attempt to confirm released hold
        with self.assertRaises(HoldAlreadyReleasedError) as ctx:
            confirm_hold_dbapi(self.conn, hold_id=hold_id, user_id="dana", now_dt=t0 + timedelta(minutes=2))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("released", str(ctx.exception).lower())

        # Verify no booking was created
        self.cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE hold_id = ?", (hold_id,))
        self.assertEqual(self.cursor.fetchone()["count"], 0)

        # Seats remain AVAILABLE
        self.cursor.execute("SELECT status FROM seats WHERE id IN ('D1', 'D2')")
        for row in self.cursor.fetchall():
            self.assertEqual(row["status"], "AVAILABLE")

    def test_invalid_hold_rejected(self):
        """Proves: Non-existent or empty hold IDs return 404 HoldNotFoundError."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)

        # Non-existent numeric ID
        with self.assertRaises(HoldNotFoundError) as ctx:
            confirm_hold_dbapi(self.conn, hold_id=99999, user_id="user", now_dt=t0)
        self.assertEqual(ctx.exception.status_code, 404)

        # Non-existent string token
        with self.assertRaises(HoldNotFoundError) as ctx:
            confirm_hold_dbapi(self.conn, hold_id="non-existent-hold-token", user_id="user", now_dt=t0)
        self.assertEqual(ctx.exception.status_code, 404)

        # Empty hold ID
        with self.assertRaises(HoldNotFoundError) as ctx:
            confirm_hold_dbapi(self.conn, hold_id="", user_id="user", now_dt=t0)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_duplicate_confirmation_prevented(self):
        """Proves: Preventing the same hold from being confirmed twice."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["E1", "E2"], user_id="evan", now_dt=t0)
        hold_id = hold["hold_id"]

        # First confirmation succeeds
        booking_1 = confirm_hold_dbapi(self.conn, hold_id=hold_id, user_id="evan", now_dt=t0 + timedelta(minutes=1))
        self.assertEqual(booking_1["status"], "confirmed")

        # Second confirmation of the same hold MUST be rejected
        with self.assertRaises(HoldError) as ctx:
            confirm_hold_dbapi(self.conn, hold_id=hold_id, user_id="evan", now_dt=t0 + timedelta(minutes=2))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("already been confirmed", str(ctx.exception).lower())

        # Verify only ONE booking exists for this hold
        self.cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE hold_id = ?", (hold_id,))
        self.assertEqual(self.cursor.fetchone()["count"], 1)

    def test_booking_reference_creation(self):
        """Proves: Generates unique, properly formatted booking reference codes."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        references = set()

        # Create and confirm multiple bookings across different seats
        seat_pairs = [
            ["F1", "F2"],
            ["F3", "F4"],
            ["F5", "F6"],
            ["F7", "F8"],
            ["F9", "F10"],
        ]

        ref_regex = re.compile(r"^BK-[0-9A-F]{8,12}$")

        for seats in seat_pairs:
            h = create_hold_dbapi(self.conn, seats, user_id="tester", now_dt=t0)
            b = confirm_hold_dbapi(self.conn, hold_id=h["hold_id"], user_id="tester", now_dt=t0 + timedelta(seconds=30))
            ref = b["booking_reference"]

            # Validate reference format
            self.assertTrue(ref_regex.match(ref), f"Booking reference {ref} does not match expected format")

            # Validate uniqueness
            self.assertNotIn(ref, references, f"Duplicate booking reference generated: {ref}")
            references.add(ref)

        self.assertEqual(len(references), len(seat_pairs))

    def test_failure_does_not_leave_partially_booked_seats(self):
        """Proves: If confirmation fails, transaction rollback leaves no partially booked seats."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        hold = create_hold_dbapi(self.conn, ["G1", "G2"], user_id="frank", now_dt=t0)
        hold_id = hold["hold_id"]

        # Simulate one seat becoming BOOKED or unavailable before confirmation
        self.cursor.execute("UPDATE seats SET status = 'BOOKED' WHERE id = 'G2'")
        self.conn.commit()

        # Attempt to confirm hold should fail because not all seats are HELD
        with self.assertRaises(SeatUnavailableError) as ctx:
            confirm_hold_dbapi(self.conn, hold_id=hold_id, user_id="frank", now_dt=t0 + timedelta(minutes=1))
        self.assertEqual(ctx.exception.status_code, 409)

        # G1 must NOT be marked as BOOKED (must remain HELD or as it was)
        self.cursor.execute("SELECT status FROM seats WHERE id = 'G1'")
        self.assertEqual(self.cursor.fetchone()["status"], "HELD")

        # No booking was created
        self.cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE hold_id = ?", (hold_id,))
        self.assertEqual(self.cursor.fetchone()["count"], 0)

        # Hold status should still be ACTIVE
        self.cursor.execute("SELECT status FROM holds WHERE id = ?", (hold_id,))
        self.assertEqual(self.cursor.fetchone()["status"], "ACTIVE")

    def test_concurrent_confirmations_same_hold(self):
        """
        Proves: Concurrent attempts to confirm the same hold are handled safely.
        Exactly one succeeds, others fail, and exactly one booking is created.
        """
        # Create a file-backed SQLite database to test multi-connection concurrency
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name

        try:
            init_conn = sqlite3.connect(db_path, timeout=10.0)
            init_conn.execute("PRAGMA foreign_keys = ON;")
            init_conn.execute("PRAGMA journal_mode = WAL;")
            init_conn.executescript(SCHEMA_SQL)
            seed_seats_dbapi(init_conn.cursor())
            init_conn.commit()

            t0 = datetime(2026, 9, 4, 12, 0, 0)
            hold = create_hold_dbapi(init_conn, ["H1", "H2"], user_id="grace", now_dt=t0)
            hold_id = hold["hold_id"]
            init_conn.close()

            results = []
            errors = []

            def worker():
                conn = sqlite3.connect(db_path, timeout=5.0)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON;")
                try:
                    res = confirm_hold_dbapi(conn, hold_id=hold_id, user_id="grace", now_dt=t0 + timedelta(minutes=1))
                    results.append(res)
                except Exception as e:
                    errors.append(e)
                finally:
                    conn.close()

            # Launch 4 concurrent threads trying to confirm the same hold
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(worker) for _ in range(4)]
                concurrent.futures.wait(futures)

            # Exactly ONE confirmation should succeed
            self.assertEqual(len(results), 1, f"Expected 1 success, got {len(results)}")
            self.assertEqual(len(errors), 3, f"Expected 3 failures, got {len(errors)}")

            # Check database state
            verify_conn = sqlite3.connect(db_path)
            verify_conn.row_factory = sqlite3.Row
            cur = verify_conn.cursor()

            cur.execute("SELECT COUNT(*) as count FROM bookings WHERE hold_id = ?", (hold_id,))
            self.assertEqual(cur.fetchone()["count"], 1)

            cur.execute("SELECT status FROM seats WHERE id IN ('H1', 'H2')")
            for r in cur.fetchall():
                self.assertEqual(r["status"], "BOOKED")

            cur.execute("SELECT status FROM holds WHERE id = ?", (hold_id,))
            self.assertEqual(cur.fetchone()["status"], "CONFIRMED")
            verify_conn.close()

        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_get_bookings_initially_empty(self):
        """Proves: GET /bookings returns an empty list when no bookings exist."""
        bookings = get_bookings_dbapi(self.conn)
        self.assertIsInstance(bookings, list)
        self.assertEqual(len(bookings), 0)

    def test_confirmed_hold_appears_in_get_bookings(self):
        """
        Proves: A confirmed hold appears in GET /bookings with:
        - booking ID (id / booking_id)
        - booking reference (booking_reference)
        - booked seats (seats / booked_seats)
        - booking creation timestamp (created_at)
        """
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        seats_to_hold = ["I1", "I2"]
        hold = create_hold_dbapi(self.conn, seats_to_hold, user_id="isabel", now_dt=t0)
        hold_id = hold["hold_id"]

        # Confirm the hold into a booking
        t_confirm = t0 + timedelta(minutes=1)
        confirmed_booking = confirm_hold_dbapi(self.conn, hold_id=hold_id, user_id="isabel", now_dt=t_confirm)
        booking_ref = confirmed_booking["booking_reference"]
        booking_id = confirmed_booking["booking_id"]

        # Retrieve all bookings
        bookings = get_bookings_dbapi(self.conn)
        self.assertIsInstance(bookings, list)
        self.assertEqual(len(bookings), 1)

        b = bookings[0]

        # 1. Booking ID
        self.assertEqual(b["id"], booking_id)
        self.assertEqual(b["booking_id"], booking_id)

        # 2. Booking Reference
        self.assertEqual(b["booking_reference"], booking_ref)
        self.assertTrue(b["booking_reference"].startswith("BK-"))

        # 3. Booked seats
        self.assertEqual(sorted(b["seats"]), sorted(seats_to_hold))
        self.assertEqual(sorted(b["booked_seats"]), sorted(seats_to_hold))

        # 4. Booking creation timestamp
        self.assertIn("created_at", b)
        self.assertIsNotNone(b["created_at"])
        self.assertTrue(len(b["created_at"]) > 0)
        # Verify timestamp contains the expected date/time ISO representation
        self.assertIn("2026-09-04", b["created_at"])

    def test_multiple_confirmed_holds_appear_in_get_bookings(self):
        """Proves: Multiple confirmed holds appear in GET /bookings with separate records."""
        t0 = datetime(2026, 9, 4, 12, 0, 0)
        
        # Booking 1
        h1 = create_hold_dbapi(self.conn, ["J1", "J2"], user_id="user_1", now_dt=t0)
        b1 = confirm_hold_dbapi(self.conn, hold_id=h1["hold_id"], user_id="user_1", now_dt=t0 + timedelta(seconds=10))

        # Booking 2
        h2 = create_hold_dbapi(self.conn, ["J3", "J4", "J5"], user_id="user_2", now_dt=t0 + timedelta(seconds=20))
        b2 = confirm_hold_dbapi(self.conn, hold_id=h2["hold_id"], user_id="user_2", now_dt=t0 + timedelta(seconds=30))

        bookings = get_bookings_dbapi(self.conn)
        self.assertEqual(len(bookings), 2)

        booking_refs = {b["booking_reference"] for b in bookings}
        self.assertIn(b1["booking_reference"], booking_refs)
        self.assertIn(b2["booking_reference"], booking_refs)

        # Map by reference
        by_ref = {b["booking_reference"]: b for b in bookings}
        self.assertEqual(sorted(by_ref[b1["booking_reference"]]["seats"]), ["J1", "J2"])
        self.assertEqual(sorted(by_ref[b2["booking_reference"]]["seats"]), ["J3", "J4", "J5"])

