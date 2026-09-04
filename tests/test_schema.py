import unittest
import sqlite3
from datetime import datetime, timedelta
from backend.app.seed import (
    generate_seat_definitions,
    seed_seats_dbapi,
    ROW_LABELS,
    SEATS_PER_ROW,
    TOTAL_SEATS,
)

SCHEMA_SQL = """
CREATE TABLE seats (
    id VARCHAR(10) PRIMARY KEY,
    row_label VARCHAR(2) NOT NULL,
    seat_number INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE',
    version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_seats_row_seat UNIQUE (row_label, seat_number)
);

CREATE TABLE holds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hold_token VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE hold_seats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hold_id INTEGER NOT NULL,
    seat_id VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (hold_id) REFERENCES holds(id) ON DELETE CASCADE,
    FOREIGN KEY (seat_id) REFERENCES seats(id) ON DELETE RESTRICT,
    CONSTRAINT uq_hold_seats_hold_seat UNIQUE (hold_id, seat_id)
);

CREATE TABLE bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_reference VARCHAR(32) NOT NULL UNIQUE,
    hold_id INTEGER UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'CONFIRMED',
    confirmed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (hold_id) REFERENCES holds(id) ON DELETE SET NULL
);

CREATE TABLE booking_seats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER NOT NULL,
    seat_id VARCHAR(10) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
    FOREIGN KEY (seat_id) REFERENCES seats(id) ON DELETE RESTRICT,
    CONSTRAINT uq_booking_seats_booking_seat UNIQUE (booking_id, seat_id)
);
"""

class TestDatabaseSchemaAndConcurrency(unittest.TestCase):
    """
    Validates MySQL/relational schema tables, constraints, relationships,
    exact 120-seat seeding, and concurrency invariants.
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.cursor = self.conn.cursor()
        self.cursor.executescript(SCHEMA_SQL)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_seed_exactly_120_seats(self):
        """Validates that exactly 120 seats are generated with predictable IDs (A1-J12)."""
        inserted = seed_seats_dbapi(self.cursor)
        self.conn.commit()
        self.assertEqual(inserted, 120)

        # Check total count in database
        self.cursor.execute("SELECT COUNT(*) FROM seats")
        total = self.cursor.fetchone()[0]
        self.assertEqual(total, TOTAL_SEATS)

        # Check row labels (A-J) and seat numbers (1-12)
        for row in ROW_LABELS:
            for num in range(1, SEATS_PER_ROW + 1):
                expected_id = f"{row}{num}"
                self.cursor.execute(
                    "SELECT id, row_label, seat_number, status, version FROM seats WHERE id = ?",
                    (expected_id,),
                )
                row_data = self.cursor.fetchone()
                self.assertIsNotNone(row_data, f"Seat {expected_id} must exist")
                self.assertEqual(row_data[0], expected_id)
                self.assertEqual(row_data[1], row)
                self.assertEqual(row_data[2], num)
                self.assertEqual(row_data[3], "AVAILABLE")
                self.assertEqual(row_data[4], 0)

        # Idempotency check: seeding again inserts 0 new seats
        reseed = seed_seats_dbapi(self.cursor)
        self.assertEqual(reseed, 0)

    def test_seat_row_and_number_unique_constraint(self):
        """Validates that duplicate row and seat number cannot exist in seats table."""
        self.cursor.execute(
            "INSERT INTO seats (id, row_label, seat_number) VALUES ('A1', 'A', 1)"
        )
        self.conn.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute(
                "INSERT INTO seats (id, row_label, seat_number) VALUES ('A1_DUP', 'A', 1)"
            )
            self.conn.commit()

    def test_hold_and_hold_seats_creation(self):
        """Validates hold creation with 5-minute duration and associated seats."""
        self.cursor.execute("INSERT INTO seats (id, row_label, seat_number, status) VALUES ('A1', 'A', 1, 'HELD')")
        now = datetime.utcnow()
        expires_at = (now + timedelta(minutes=5)).isoformat()

        self.cursor.execute(
            "INSERT INTO holds (hold_token, status, expires_at) VALUES (?, 'ACTIVE', ?)",
            ("token-xyz-123", expires_at),
        )
        hold_id = self.cursor.lastrowid

        self.cursor.execute(
            "INSERT INTO hold_seats (hold_id, seat_id) VALUES (?, 'A1')",
            (hold_id,),
        )
        self.conn.commit()

        # Query back
        self.cursor.execute("SELECT seat_id FROM hold_seats WHERE hold_id = ?", (hold_id,))
        seats = self.cursor.fetchall()
        self.assertEqual(len(seats), 1)
        self.assertEqual(seats[0][0], "A1")

    def test_hold_seats_duplicate_prevention(self):
        """Validates that a hold cannot hold the same seat twice."""
        self.cursor.execute("INSERT INTO seats (id, row_label, seat_number) VALUES ('B1', 'B', 1)")
        self.cursor.execute("INSERT INTO holds (hold_token, expires_at) VALUES ('token-b1', datetime('now', '+5 minutes'))")
        hold_id = self.cursor.lastrowid

        self.cursor.execute("INSERT INTO hold_seats (hold_id, seat_id) VALUES (?, 'B1')", (hold_id,))
        self.conn.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute("INSERT INTO hold_seats (hold_id, seat_id) VALUES (?, 'B1')", (hold_id,))
            self.conn.commit()

    def test_booking_unique_reference_constraint(self):
        """Validates that duplicate booking references are rejected."""
        self.cursor.execute("INSERT INTO bookings (booking_reference) VALUES ('BK-UNIQUE-101')")
        self.conn.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute("INSERT INTO bookings (booking_reference) VALUES ('BK-UNIQUE-101')")
            self.conn.commit()

    def test_hold_single_confirmation_constraint(self):
        """Validates that a hold can only be converted into a booking once (UNIQUE hold_id)."""
        self.cursor.execute("INSERT INTO holds (hold_token, expires_at) VALUES ('single-use-token', datetime('now', '+5 minutes'))")
        hold_id = self.cursor.lastrowid

        self.cursor.execute("INSERT INTO bookings (booking_reference, hold_id) VALUES ('BK-1', ?)", (hold_id,))
        self.conn.commit()

        # Attempting a second booking referencing the same hold must fail
        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute("INSERT INTO bookings (booking_reference, hold_id) VALUES ('BK-2', ?)", (hold_id,))
            self.conn.commit()

    def test_concurrency_prevention_seat_double_booking(self):
        """
        CRITICAL CONCURRENCY INVARIANT:
        Validates that two bookings CANNOT both book the same seat.
        The UNIQUE(seat_id) constraint in booking_seats guarantees this at the DB level.
        """
        self.cursor.execute("INSERT INTO seats (id, row_label, seat_number, status) VALUES ('C1', 'C', 1, 'BOOKED')")
        self.cursor.execute("INSERT INTO bookings (booking_reference) VALUES ('BK-CLIENT-1')")
        booking_1_id = self.cursor.lastrowid
        self.cursor.execute("INSERT INTO bookings (booking_reference) VALUES ('BK-CLIENT-2')")
        booking_2_id = self.cursor.lastrowid
        self.conn.commit()

        # First booking claims seat C1
        self.cursor.execute(
            "INSERT INTO booking_seats (booking_id, seat_id) VALUES (?, 'C1')",
            (booking_1_id,),
        )
        self.conn.commit()

        # Second concurrent booking attempts to claim the same seat C1
        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute(
                "INSERT INTO booking_seats (booking_id, seat_id) VALUES (?, 'C1')",
                (booking_2_id,),
            )
            self.conn.commit()

if __name__ == "__main__":
    unittest.main()
