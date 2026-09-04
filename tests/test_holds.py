import unittest
import sqlite3
import threading
import tempfile
import os
from datetime import datetime, timedelta
from backend.app.seed import seed_seats_dbapi, TOTAL_SEATS
from backend.app.seats_service import (
    create_hold_dbapi,
    get_seats_from_dbapi,
    InvalidSeatRequestError,
    SeatUnavailableError,
)
from tests.test_schema import SCHEMA_SQL

class TestHolds(unittest.TestCase):
    """
    Validates POST /holds requirements:
    1. Maximum 4 seats per hold request.
    2. Hold lasts exactly 5 minutes (300 seconds).
    3. Atomicity: all requested seats held together; if any is unavailable, entire request fails.
    4. No partial holds left behind.
    5. Held seats immediately become unavailable to subsequent requests.
    6. Concurrency:
       - Request A -> A1 and Request B -> A1: exactly one succeeds, second fails.
       - Request A -> A1, A2 and Request B -> A2, A3: all-or-nothing enforced, A3 remains available.
    7. Expired hold accounting: expired holds are cleaned up and the seat can be re-held.
    8. Error responses: 400 for bad requests (>4 seats, empty, invalid), 409 for unavailable seats.
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

    def test_single_seat_hold_success(self):
        """User can successfully hold 1 seat for exactly 5 minutes."""
        now = datetime.utcnow()
        result = create_hold_dbapi(self.conn, ["A1"], user_id="user_123", now_dt=now)

        self.assertIn("hold_token", result)
        self.assertEqual(result["seats"], ["A1"])
        self.assertEqual(result["expires_in_seconds"], 300)
        self.assertEqual(result["status"], "held")

        # Verify hold duration is exactly 5 minutes
        expected_expiry = (now + timedelta(minutes=5)).isoformat() + "Z"
        self.assertEqual(result["expires_at"], expected_expiry)

        # Verify DB state: seat A1 is now HELD
        self.cursor.execute("SELECT status FROM seats WHERE id = 'A1'")
        row = self.cursor.fetchone()
        self.assertEqual(row["status"], "HELD")

        # Verify hold record created
        self.cursor.execute("SELECT * FROM holds WHERE hold_token = ?", (result["hold_token"],))
        hold_row = self.cursor.fetchone()
        self.assertIsNotNone(hold_row)
        self.assertEqual(hold_row["status"], "ACTIVE")

    def test_multi_seat_hold_up_to_4_seats(self):
        """User can successfully hold up to 4 seats atomically."""
        now = datetime.utcnow()
        seats_to_hold = ["B1", "B2", "B3", "B4"]
        result = create_hold_dbapi(self.conn, seats_to_hold, user_id="user_abc", now_dt=now)

        self.assertEqual(result["seats"], ["B1", "B2", "B3", "B4"])
        self.assertEqual(result["expires_in_seconds"], 300)

        # All 4 seats must be HELD
        for sid in seats_to_hold:
            self.cursor.execute("SELECT status FROM seats WHERE id = ?", (sid,))
            row = self.cursor.fetchone()
            self.assertEqual(row["status"], "HELD")

        # Verify 4 hold_seats links
        self.cursor.execute("SELECT COUNT(*) as count FROM hold_seats WHERE hold_id = (SELECT id FROM holds WHERE hold_token = ?)", (result["hold_token"],))
        count = self.cursor.fetchone()["count"]
        self.assertEqual(count, 4)

    def test_more_than_4_seats_rejected(self):
        """Requesting more than 4 seats must fail with status 400."""
        with self.assertRaises(InvalidSeatRequestError) as ctx:
            create_hold_dbapi(self.conn, ["A1", "A2", "A3", "A4", "A5"])
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Maximum of 4 seats", str(ctx.exception))

    def test_empty_seat_request_rejected(self):
        """Requesting 0 seats or empty list must fail with status 400."""
        with self.assertRaises(InvalidSeatRequestError) as ctx:
            create_hold_dbapi(self.conn, [])
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_seat_id_rejected(self):
        """Requesting non-existent seat ID (e.g. Z99) must fail with status 400."""
        with self.assertRaises(InvalidSeatRequestError) as ctx:
            create_hold_dbapi(self.conn, ["Z99"])
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Z99", str(ctx.exception))

    def test_all_or_nothing_when_one_seat_is_already_held(self):
        """
        If even one requested seat is unavailable, the entire request must fail
        and NO partial hold may remain.
        """
        # User 1 holds A1
        create_hold_dbapi(self.conn, ["A1"], user_id="user_1")

        # Count holds before second request
        self.cursor.execute("SELECT COUNT(*) as c FROM holds")
        holds_before = self.cursor.fetchone()["c"]

        # User 2 requests A1 and A2
        with self.assertRaises(SeatUnavailableError) as ctx:
            create_hold_dbapi(self.conn, ["A1", "A2"], user_id="user_2")

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("A1", ctx.exception.unavailable_seats)

        # Seat A2 MUST remain AVAILABLE (no partial hold!)
        self.cursor.execute("SELECT status FROM seats WHERE id = 'A2'")
        self.assertEqual(self.cursor.fetchone()["status"], "AVAILABLE")

        # No new hold record should have been created
        self.cursor.execute("SELECT COUNT(*) as c FROM holds")
        holds_after = self.cursor.fetchone()["c"]
        self.assertEqual(holds_after, holds_before)

    def test_all_or_nothing_when_one_seat_is_booked(self):
        """If a seat is booked, holding it alongside available seats fails completely."""
        # Book A1
        self.cursor.execute("UPDATE seats SET status = 'BOOKED' WHERE id = 'A1'")
        self.conn.commit()

        # Request A1 and A2
        with self.assertRaises(SeatUnavailableError) as ctx:
            create_hold_dbapi(self.conn, ["A1", "A2"], user_id="user_2")

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("A1", ctx.exception.unavailable_seats)

        # A2 must still be AVAILABLE
        self.cursor.execute("SELECT status FROM seats WHERE id = 'A2'")
        self.assertEqual(self.cursor.fetchone()["status"], "AVAILABLE")

    def test_held_seat_immediately_unavailable_to_others(self):
        """Held seat must immediately become unavailable to other requests."""
        create_hold_dbapi(self.conn, ["C1"], user_id="user_1")

        # GET /seats should immediately show C1 as held
        seats = get_seats_from_dbapi(self.cursor)
        seat_map = {s["id"]: s for s in seats}
        self.assertEqual(seat_map["C1"]["status"], "held")

        # Another hold on C1 must fail immediately
        with self.assertRaises(SeatUnavailableError):
            create_hold_dbapi(self.conn, ["C1"], user_id="user_2")

    def test_expired_hold_is_cleaned_up_and_can_be_reheld(self):
        """
        A hold that expired (> 5 minutes ago) is cleaned up and the seat
        can be held by a new request.
        """
        now = datetime.utcnow()
        past_time = now - timedelta(minutes=6)

        # Create hold that was created in the past and is now expired
        res1 = create_hold_dbapi(self.conn, ["D1"], user_id="user_old", now_dt=past_time)

        # Now, at time `now`, new user requests D1
        res2 = create_hold_dbapi(self.conn, ["D1"], user_id="user_new", now_dt=now)

        self.assertIsNotNone(res2["hold_token"])
        self.assertNotEqual(res1["hold_token"], res2["hold_token"])

        # Seat D1 is successfully held under the new hold token
        self.cursor.execute("SELECT status FROM holds WHERE hold_token = ?", (res1["hold_token"],))
        self.assertEqual(self.cursor.fetchone()["status"], "EXPIRED")

        self.cursor.execute("SELECT status FROM holds WHERE hold_token = ?", (res2["hold_token"],))
        self.assertEqual(self.cursor.fetchone()["status"], "ACTIVE")

    def test_concurrent_case_1_identical_seat(self):
        """
        Consider this concurrent case:
        Request A -> A1
        Request B -> A1
        Exactly one request must succeed. The second must fail after the first
        transaction has reserved the seat.
        """
        now = datetime.utcnow()

        # Simulate Request A executing and committing
        result_a = create_hold_dbapi(self.conn, ["A1"], user_id="req_a", now_dt=now)
        self.assertIsNotNone(result_a["hold_token"])

        # Request B attempts to hold A1
        with self.assertRaises(SeatUnavailableError) as ctx:
            create_hold_dbapi(self.conn, ["A1"], user_id="req_b", now_dt=now)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("A1", ctx.exception.unavailable_seats)

    def test_concurrent_case_2_overlapping_seats_all_or_nothing(self):
        """
        Consider this concurrent case:
        Request A -> A1, A2
        Request B -> A2, A3
        The all-or-nothing requirement must remain correct:
        Request A holds A1 and A2.
        Request B fails completely because A2 is held, leaving A3 available.
        """
        now = datetime.utcnow()

        # Request A holds A1 and A2
        result_a = create_hold_dbapi(self.conn, ["A1", "A2"], user_id="req_a", now_dt=now)
        self.assertEqual(result_a["seats"], ["A1", "A2"])

        # Request B requests A2 and A3
        with self.assertRaises(SeatUnavailableError) as ctx:
            create_hold_dbapi(self.conn, ["A2", "A3"], user_id="req_b", now_dt=now)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("A2", ctx.exception.unavailable_seats)

        # Verify A3 was NOT held (all-or-nothing requirement!)
        self.cursor.execute("SELECT status FROM seats WHERE id = 'A3'")
        self.assertEqual(self.cursor.fetchone()["status"], "AVAILABLE")

        # Verify GET /seats shows A1: held, A2: held, A3: available
        seats = get_seats_from_dbapi(self.cursor)
        seat_map = {s["id"]: s for s in seats}
        self.assertEqual(seat_map["A1"]["status"], "held")
        self.assertEqual(seat_map["A2"]["status"], "held")
        self.assertEqual(seat_map["A3"]["status"], "available")

    def test_multithreaded_concurrency_race(self):
        """
        Real multithreaded test running concurrent threads attempting to hold
        the exact same seat on a file-based SQLite database.
        Validates that exactly 1 thread succeeds and others fail with 409.
        """
        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "concurrent_test.db")

        # Initialize DB
        init_conn = sqlite3.connect(db_path)
        init_conn.execute("PRAGMA foreign_keys = ON;")
        init_conn.executescript(SCHEMA_SQL)
        seed_seats_dbapi(init_conn.cursor())
        init_conn.commit()
        init_conn.close()

        successes = []
        failures = []
        errors = []

        def worker(thread_id):
            try:
                conn = sqlite3.connect(db_path, timeout=5.0)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON;")
                result = create_hold_dbapi(conn, ["E5"], user_id=f"thread_{thread_id}")
                successes.append((thread_id, result))
                conn.close()
            except SeatUnavailableError as e:
                failures.append((thread_id, e))
                try:
                    conn.close()
                except Exception:
                    pass
            except Exception as e:
                errors.append((thread_id, e))
                try:
                    conn.close()
                except Exception:
                    pass

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 1 thread must succeed
        self.assertEqual(len(successes), 1, f"Expected 1 success, got {len(successes)}")
        # The remaining 4 threads must receive SeatUnavailableError or busy serialization
        self.assertEqual(len(failures) + len(errors), 4)

        # Cleanup temp file
        if os.path.exists(db_path):
            os.remove(db_path)
        if os.path.exists(temp_dir):
            os.rmdir(temp_dir)

if __name__ == "__main__":
    unittest.main()
