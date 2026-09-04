-- ============================================================================
-- Seat Booking System - MySQL Database Schema & Seed Data
-- Fixed Event Venue: 10 Rows (A-J) x 12 Seats (1-12) = 120 Total Seats
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Table: seats
-- Purpose:
--   Represents the physical inventory of 120 fixed seats for the single event.
--   Maintains seat status (AVAILABLE, HELD, BOOKED) and an optimistic
--   concurrency version counter for conflict detection during updates.
-- Constraints:
--   - PRIMARY KEY (id): Predictable seat identifier (e.g., 'A1' through 'J12').
--   - UNIQUE KEY (row_label, seat_number): Precludes duplicate row/seat entries.
--   - INDEX (status): Accelerates retrieval of available seats.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seats (
    id VARCHAR(10) NOT NULL,
    row_label VARCHAR(2) NOT NULL,
    seat_number INT NOT NULL,
    status ENUM('AVAILABLE', 'HELD', 'BOOKED') NOT NULL DEFAULT 'AVAILABLE',
    version INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uq_seats_row_seat UNIQUE (row_label, seat_number),
    INDEX idx_seats_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 2. Table: holds
-- Purpose:
--   Manages temporary 5-minute reservations for one or more seats.
--   Each hold is issued a secure, unique hold_token that the client must
--   present to release the hold or confirm into a completed booking.
-- Constraints:
--   - PRIMARY KEY (id): Auto-incrementing internal surrogate key.
--   - UNIQUE KEY (hold_token): Prevents collisions across client hold tokens.
--   - INDEX (status, expires_at): Optimizes queries that detect expired holds.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS holds (
    id INT AUTO_INCREMENT NOT NULL,
    hold_token VARCHAR(64) NOT NULL,
    status ENUM('ACTIVE', 'RELEASED', 'EXPIRED', 'CONFIRMED') NOT NULL DEFAULT 'ACTIVE',
    expires_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uq_holds_token UNIQUE (hold_token),
    INDEX idx_holds_status_expires (status, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 3. Table: hold_seats
-- Purpose:
--   Junction table linking holds to individual reserved seats.
-- Constraints:
--   - PRIMARY KEY (id): Auto-incrementing identifier.
--   - FOREIGN KEY (hold_id): Cascades deletion if the parent hold is pruned.
--   - FOREIGN KEY (seat_id): RESTRICTs deletion of seats while referenced.
--   - UNIQUE KEY (hold_id, seat_id): Ensures a seat cannot be listed multiple
--     times within the same hold session.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hold_seats (
    id INT AUTO_INCREMENT NOT NULL,
    hold_id INT NOT NULL,
    seat_id VARCHAR(10) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_hold_seats_hold FOREIGN KEY (hold_id) REFERENCES holds (id) ON DELETE CASCADE,
    CONSTRAINT fk_hold_seats_seat FOREIGN KEY (seat_id) REFERENCES seats (id) ON DELETE RESTRICT,
    CONSTRAINT uq_hold_seats_hold_seat UNIQUE (hold_id, seat_id),
    INDEX idx_hold_seats_seat (seat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 4. Table: bookings
-- Purpose:
--   Stores confirmed event reservations with unique, human-readable booking
--   reference codes.
-- Constraints:
--   - PRIMARY KEY (id): Auto-incrementing identifier.
--   - UNIQUE KEY (booking_reference): Guarantees globally unique reference codes.
--   - UNIQUE KEY (hold_id): Enforces that a hold can ONLY be converted into
--     a booking ONCE. Prevents race conditions from generating duplicate bookings.
--   - FOREIGN KEY (hold_id): Links back to the hold session if applicable.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bookings (
    id INT AUTO_INCREMENT NOT NULL,
    booking_reference VARCHAR(32) NOT NULL,
    hold_id INT NULL,
    status ENUM('CONFIRMED', 'CANCELLED') NOT NULL DEFAULT 'CONFIRMED',
    confirmed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uq_bookings_reference UNIQUE (booking_reference),
    CONSTRAINT uq_bookings_hold_id UNIQUE (hold_id),
    CONSTRAINT fk_bookings_hold FOREIGN KEY (hold_id) REFERENCES holds (id) ON DELETE SET NULL,
    INDEX idx_bookings_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 5. Table: booking_seats
-- Purpose:
--   Junction table recording which seats belong to a confirmed booking.
--
-- CRITICAL CONCURRENCY INVARIANT:
--   - CONSTRAINT uq_booking_seats_seat_id UNIQUE (seat_id):
--     Since this application manages exactly ONE event, a seat can be booked
--     AT MOST ONCE in the event's history.
--     This unique constraint guarantees at the MySQL storage engine (InnoDB)
--     level that even if concurrent transactions bypass application checks,
--     the database will reject simultaneous duplicate bookings for the same seat
--     with a duplicate key error (ER_DUP_ENTRY).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS booking_seats (
    id INT AUTO_INCREMENT NOT NULL,
    booking_id INT NOT NULL,
    seat_id VARCHAR(10) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_booking_seats_booking FOREIGN KEY (booking_id) REFERENCES bookings (id) ON DELETE CASCADE,
    CONSTRAINT fk_booking_seats_seat FOREIGN KEY (seat_id) REFERENCES seats (id) ON DELETE RESTRICT,
    CONSTRAINT uq_booking_seats_seat_id UNIQUE (seat_id),
    CONSTRAINT uq_booking_seats_booking_seat UNIQUE (booking_id, seat_id),
    INDEX idx_booking_seats_booking (booking_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- SEED DATA: Exactly 120 fixed seats (10 rows A-J x 12 seats per row)
-- ============================================================================
INSERT INTO seats (id, row_label, seat_number, status, version) VALUES
-- Row A
('A1', 'A', 1, 'AVAILABLE', 0), ('A2', 'A', 2, 'AVAILABLE', 0), ('A3', 'A', 3, 'AVAILABLE', 0),
('A4', 'A', 4, 'AVAILABLE', 0), ('A5', 'A', 5, 'AVAILABLE', 0), ('A6', 'A', 6, 'AVAILABLE', 0),
('A7', 'A', 7, 'AVAILABLE', 0), ('A8', 'A', 8, 'AVAILABLE', 0), ('A9', 'A', 9, 'AVAILABLE', 0),
('A10', 'A', 10, 'AVAILABLE', 0), ('A11', 'A', 11, 'AVAILABLE', 0), ('A12', 'A', 12, 'AVAILABLE', 0),
-- Row B
('B1', 'B', 1, 'AVAILABLE', 0), ('B2', 'B', 2, 'AVAILABLE', 0), ('B3', 'B', 3, 'AVAILABLE', 0),
('B4', 'B', 4, 'AVAILABLE', 0), ('B5', 'B', 5, 'AVAILABLE', 0), ('B6', 'B', 6, 'AVAILABLE', 0),
('B7', 'B', 7, 'AVAILABLE', 0), ('B8', 'B', 8, 'AVAILABLE', 0), ('B9', 'B', 9, 'AVAILABLE', 0),
('B10', 'B', 10, 'AVAILABLE', 0), ('B11', 'B', 11, 'AVAILABLE', 0), ('B12', 'B', 12, 'AVAILABLE', 0),
-- Row C
('C1', 'C', 1, 'AVAILABLE', 0), ('C2', 'C', 2, 'AVAILABLE', 0), ('C3', 'C', 3, 'AVAILABLE', 0),
('C4', 'C', 4, 'AVAILABLE', 0), ('C5', 'C', 5, 'AVAILABLE', 0), ('C6', 'C', 6, 'AVAILABLE', 0),
('C7', 'C', 7, 'AVAILABLE', 0), ('C8', 'C', 8, 'AVAILABLE', 0), ('C9', 'C', 9, 'AVAILABLE', 0),
('C10', 'C', 10, 'AVAILABLE', 0), ('C11', 'C', 11, 'AVAILABLE', 0), ('C12', 'C', 12, 'AVAILABLE', 0),
-- Row D
('D1', 'D', 1, 'AVAILABLE', 0), ('D2', 'D', 2, 'AVAILABLE', 0), ('D3', 'D', 3, 'AVAILABLE', 0),
('D4', 'D', 4, 'AVAILABLE', 0), ('D5', 'D', 5, 'AVAILABLE', 0), ('D6', 'D', 6, 'AVAILABLE', 0),
('D7', 'D', 7, 'AVAILABLE', 0), ('D8', 'D', 8, 'AVAILABLE', 0), ('D9', 'D', 9, 'AVAILABLE', 0),
('D10', 'D', 10, 'AVAILABLE', 0), ('D11', 'D', 11, 'AVAILABLE', 0), ('D12', 'D', 12, 'AVAILABLE', 0),
-- Row E
('E1', 'E', 1, 'AVAILABLE', 0), ('E2', 'E', 2, 'AVAILABLE', 0), ('E3', 'E', 3, 'AVAILABLE', 0),
('E4', 'E', 4, 'AVAILABLE', 0), ('E5', 'E', 5, 'AVAILABLE', 0), ('E6', 'E', 6, 'AVAILABLE', 0),
('E7', 'E', 7, 'AVAILABLE', 0), ('E8', 'E', 8, 'AVAILABLE', 0), ('E9', 'E', 9, 'AVAILABLE', 0),
('E10', 'E', 10, 'AVAILABLE', 0), ('E11', 'E', 11, 'AVAILABLE', 0), ('E12', 'E', 12, 'AVAILABLE', 0),
-- Row F
('F1', 'F', 1, 'AVAILABLE', 0), ('F2', 'F', 2, 'AVAILABLE', 0), ('F3', 'F', 3, 'AVAILABLE', 0),
('F4', 'F', 4, 'AVAILABLE', 0), ('F5', 'F', 5, 'AVAILABLE', 0), ('F6', 'F', 6, 'AVAILABLE', 0),
('F7', 'F', 7, 'AVAILABLE', 0), ('F8', 'F', 8, 'AVAILABLE', 0), ('F9', 'F', 9, 'AVAILABLE', 0),
('F10', 'F', 10, 'AVAILABLE', 0), ('F11', 'F', 11, 'AVAILABLE', 0), ('F12', 'F', 12, 'AVAILABLE', 0),
-- Row G
('G1', 'G', 1, 'AVAILABLE', 0), ('G2', 'G', 2, 'AVAILABLE', 0), ('G3', 'G', 3, 'AVAILABLE', 0),
('G4', 'G', 4, 'AVAILABLE', 0), ('G5', 'G', 5, 'AVAILABLE', 0), ('G6', 'G', 6, 'AVAILABLE', 0),
('G7', 'G', 7, 'AVAILABLE', 0), ('G8', 'G', 8, 'AVAILABLE', 0), ('G9', 'G', 9, 'AVAILABLE', 0),
('G10', 'G', 10, 'AVAILABLE', 0), ('G11', 'G', 11, 'AVAILABLE', 0), ('G12', 'G', 12, 'AVAILABLE', 0),
-- Row H
('H1', 'H', 1, 'AVAILABLE', 0), ('H2', 'H', 2, 'AVAILABLE', 0), ('H3', 'H', 3, 'AVAILABLE', 0),
('H4', 'H', 4, 'AVAILABLE', 0), ('H5', 'H', 5, 'AVAILABLE', 0), ('H6', 'H', 6, 'AVAILABLE', 0),
('H7', 'H', 7, 'AVAILABLE', 0), ('H8', 'H', 8, 'AVAILABLE', 0), ('H9', 'H', 9, 'AVAILABLE', 0),
('H10', 'H', 10, 'AVAILABLE', 0), ('H11', 'H', 11, 'AVAILABLE', 0), ('H12', 'H', 12, 'AVAILABLE', 0),
-- Row I
('I1', 'I', 1, 'AVAILABLE', 0), ('I2', 'I', 2, 'AVAILABLE', 0), ('I3', 'I', 3, 'AVAILABLE', 0),
('I4', 'I', 4, 'AVAILABLE', 0), ('I5', 'I', 5, 'AVAILABLE', 0), ('I6', 'I', 6, 'AVAILABLE', 0),
('I7', 'I', 7, 'AVAILABLE', 0), ('I8', 'I', 8, 'AVAILABLE', 0), ('I9', 'I', 9, 'AVAILABLE', 0),
('I10', 'I', 10, 'AVAILABLE', 0), ('I11', 'I', 11, 'AVAILABLE', 0), ('I12', 'I', 12, 'AVAILABLE', 0),
-- Row J
('J1', 'J', 1, 'AVAILABLE', 0), ('J2', 'J', 2, 'AVAILABLE', 0), ('J3', 'J', 3, 'AVAILABLE', 0),
('J4', 'J', 4, 'AVAILABLE', 0), ('J5', 'J', 5, 'AVAILABLE', 0), ('J6', 'J', 6, 'AVAILABLE', 0),
('J7', 'J', 7, 'AVAILABLE', 0), ('J8', 'J', 8, 'AVAILABLE', 0), ('J9', 'J', 9, 'AVAILABLE', 0),
('J10', 'J', 10, 'AVAILABLE', 0), ('J11', 'J', 11, 'AVAILABLE', 0), ('J12', 'J', 12, 'AVAILABLE', 0)
ON DUPLICATE KEY UPDATE id=id;
