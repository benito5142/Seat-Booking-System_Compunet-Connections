import unittest
import sqlite3
from datetime import datetime, timedelta
from backend.app.seed import seed_seats_dbapi, TOTAL_SEATS
from backend.app.seats_service import get_seats_from_dbapi
from tests.test_schema import SCHEMA_SQL

class TestSeatsEndpoint(unittest.TestCase):
    """
    Validates GET /seats requirements:
    1. Returns complete 10 x 12 seat map (exactly 120 seats).
    2. Each seat contains: id, row, seat_number, status.
    3. Status is strictly one of: 'available', 'held', 'booked'.
    4. Expired holds (expires_at <= now) correctly reflect as 'available'.
    5. Active holds (expires_at > now) reflect as 'held'.
    6. Confirmed/booked seats reflect as 'booked'.
    7. Database remains the source of truth.
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

    def test_get_seats_returns_exactly_120_seats(self):
        """Validates that GET /seats returns exactly 120 seats."""
        seats = get_seats_from_dbapi(self.cursor)
        self.assertEqual(len(seats), 120)
        self.assertEqual(len(seats), TOTAL_SEATS)

        # Check required fields for every seat
        valid_statuses = {"available", "held", "booked"}
        for seat in seats:
            self.assertIn("id", seat)
            self.assertIn("row", seat)
            self.assertIn("seat_number", seat)
            self.assertIn("status", seat)
            self.assertIn(seat["status"], valid_statuses)
            self.assertTrue(seat["row"] in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"])
            self.assertTrue(1 <= seat["seat_number"] <= 12)
            self.assertEqual(seat["id"], f"{seat['row']}{seat['seat_number']}")

    def test_all_seats_initially_available(self):
        """Validates that with clean seed data, all 120 seats are available."""
        seats = get_seats_from_dbapi(self.cursor)
        self.assertEqual(len(seats), 120)
        for seat in seats:
            self.assertEqual(seat["status"], "available")

    def test_seat_map_layout_dimensions(self):
        """Validates 10 rows (A-J) and 12 seats per row (1-12)."""
        seats = get_seats_from_dbapi(self.cursor)
        rows_seen = set()
        seats_by_row = {}
        for s in seats:
            r = s["row"]
            rows_seen.add(r)
            seats_by_row.setdefault(r, []).append(s["seat_number"])

        expected_rows = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
        self.assertEqual(sorted(list(rows_seen)), expected_rows)
        for r in expected_rows:
            self.assertEqual(sorted(seats_by_row[r]), list(range(1, 13)))

    def test_booked_seats_status(self):
        """Validates that booked seats have status 'booked'."""
        # Mark A1 and B5 as BOOKED
        self.cursor.execute("UPDATE seats SET status = 'BOOKED' WHERE id IN ('A1', 'B5')")
        self.cursor.execute("INSERT INTO bookings (booking_reference) VALUES ('BK-TEST-1')")
        booking_id = self.cursor.lastrowid
        self.cursor.execute("INSERT INTO booking_seats (booking_id, seat_id) VALUES (?, 'A1')", (booking_id,))
        self.cursor.execute("INSERT INTO booking_seats (booking_id, seat_id) VALUES (?, 'B5')", (booking_id,))
        self.conn.commit()

        seats = get_seats_from_dbapi(self.cursor)
        self.assertEqual(len(seats), 120)

        seat_map = {s["id"]: s for s in seats}
        self.assertEqual(seat_map["A1"]["status"], "booked")
        self.assertEqual(seat_map["B5"]["status"], "booked")
        self.assertEqual(seat_map["A2"]["status"], "available")

    def test_active_hold_status_is_held(self):
        """Validates that seats under an active hold (expires_at > now) return 'held'."""
        now = datetime.utcnow()
        active_expiry = (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

        self.cursor.execute("UPDATE seats SET status = 'HELD' WHERE id = 'C3'")
        self.cursor.execute(
            "INSERT INTO holds (hold_token, status, expires_at) VALUES ('tok-active-1', 'ACTIVE', ?)",
            (active_expiry,),
        )
        hold_id = self.cursor.lastrowid
        self.cursor.execute("INSERT INTO hold_seats (hold_id, seat_id) VALUES (?, 'C3')", (hold_id,))
        self.conn.commit()

        seats = get_seats_from_dbapi(self.cursor, now_dt=now)
        seat_map = {s["id"]: s for s in seats}
        self.assertEqual(seat_map["C3"]["status"], "held")

    def test_expired_hold_reflects_as_available(self):
        """
        Validates that seats under an expired hold (expires_at <= now)
        correctly reflect as 'available' according to the expiration strategy.
        """
        now = datetime.utcnow()
        expired_time = (now - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")

        # Seat D4 was marked HELD with a hold that has now expired
        self.cursor.execute("UPDATE seats SET status = 'HELD' WHERE id = 'D4'")
        self.cursor.execute(
            "INSERT INTO holds (hold_token, status, expires_at) VALUES ('tok-expired-1', 'ACTIVE', ?)",
            (expired_time,),
        )
        hold_id = self.cursor.lastrowid
        self.cursor.execute("INSERT INTO hold_seats (hold_id, seat_id) VALUES (?, 'D4')", (hold_id,))
        self.conn.commit()

        # Query seats at current time `now`
        seats = get_seats_from_dbapi(self.cursor, now_dt=now)
        seat_map = {s["id"]: s for s in seats}

        # Seat D4 must reflect as 'available' because the hold has expired!
        self.assertEqual(
            seat_map["D4"]["status"],
            "available",
            "Expired hold must be reflected as available",
        )

        # Database is updated / source of truth maintained
        self.cursor.execute("SELECT status FROM holds WHERE id = ?", (hold_id,))
        hold_row = self.cursor.fetchone()
        self.assertEqual(hold_row["status"], "EXPIRED")

    def test_mixed_seat_states(self):
        """Validates a map with available, active holds, expired holds, and booked seats."""
        now = datetime.utcnow()
        active_time = (now + timedelta(minutes=4)).strftime("%Y-%m-%d %H:%M:%S")
        expired_time = (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Booked seat: A1
        self.cursor.execute("UPDATE seats SET status = 'BOOKED' WHERE id = 'A1'")
        self.cursor.execute("INSERT INTO bookings (booking_reference) VALUES ('BK-REF-A1')")
        b_id = self.cursor.lastrowid
        self.cursor.execute("INSERT INTO booking_seats (booking_id, seat_id) VALUES (?, 'A1')", (b_id,))

        # 2. Active held seat: B2
        self.cursor.execute("UPDATE seats SET status = 'HELD' WHERE id = 'B2'")
        self.cursor.execute("INSERT INTO holds (hold_token, status, expires_at) VALUES ('tok-b2', 'ACTIVE', ?)", (active_time,))
        h_active = self.cursor.lastrowid
        self.cursor.execute("INSERT INTO hold_seats (hold_id, seat_id) VALUES (?, 'B2')", (h_active,))

        # 3. Expired held seat: C3
        self.cursor.execute("UPDATE seats SET status = 'HELD' WHERE id = 'C3'")
        self.cursor.execute("INSERT INTO holds (hold_token, status, expires_at) VALUES ('tok-c3', 'ACTIVE', ?)", (expired_time,))
        h_expired = self.cursor.lastrowid
        self.cursor.execute("INSERT INTO hold_seats (hold_id, seat_id) VALUES (?, 'C3')", (h_expired,))

        self.conn.commit()

        seats = get_seats_from_dbapi(self.cursor, now_dt=now)
        self.assertEqual(len(seats), 120)
        seat_map = {s["id"]: s for s in seats}

        self.assertEqual(seat_map["A1"]["status"], "booked")
        self.assertEqual(seat_map["B2"]["status"], "held")
        self.assertEqual(seat_map["C3"]["status"], "available")  # Expired hold -> available
        self.assertEqual(seat_map["J12"]["status"], "available")  # Untouched -> available

if __name__ == "__main__":
    unittest.main()
