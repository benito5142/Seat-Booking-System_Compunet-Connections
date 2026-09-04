-- Seat Booking System MySQL Database Schema
-- Fixed Event: 10 rows (A-J) x 12 seats = 120 predefined seats

CREATE DATABASE IF NOT EXISTS seat_booking;
USE seat_booking;

-- Drop tables if needed in reverse dependency order
DROP TABLE IF EXISTS booking_seats;
DROP TABLE IF EXISTS bookings;
DROP TABLE IF EXISTS hold_seats;
DROP TABLE IF EXISTS holds;
DROP TABLE IF EXISTS seats;

-- Predefined seats table
CREATE TABLE seats (
    id VARCHAR(10) NOT NULL PRIMARY KEY,
    row_label VARCHAR(5) NOT NULL,
    seat_number INT NOT NULL,
    status ENUM('available', 'held', 'booked') NOT NULL DEFAULT 'available',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_seats_status (status),
    INDEX idx_seats_row_num (row_label, seat_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Temporary holds table (5-minute TTL)
CREATE TABLE holds (
    id INT AUTO_INCREMENT PRIMARY KEY,
    hold_token VARCHAR(64) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL DEFAULT 'default_user',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, RELEASED, EXPIRED, CONFIRMED
    expires_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_holds_status_expires (status, expires_at),
    INDEX idx_holds_token (hold_token)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Junction table linking holds to reserved seats
CREATE TABLE hold_seats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    hold_id INT NOT NULL,
    seat_id VARCHAR(10) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_hold_seats_hold FOREIGN KEY (hold_id) REFERENCES holds(id) ON DELETE CASCADE,
    CONSTRAINT fk_hold_seats_seat FOREIGN KEY (seat_id) REFERENCES seats(id) ON DELETE CASCADE,
    UNIQUE KEY uq_hold_seat (hold_id, seat_id),
    INDEX idx_hold_seats_seat (seat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Confirmed bookings table
CREATE TABLE bookings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_reference VARCHAR(64) NOT NULL UNIQUE,
    hold_id INT NOT NULL,
    user_id VARCHAR(100) NOT NULL DEFAULT 'default_user',
    status VARCHAR(20) NOT NULL DEFAULT 'confirmed',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_bookings_hold FOREIGN KEY (hold_id) REFERENCES holds(id),
    INDEX idx_bookings_ref (booking_reference),
    INDEX idx_bookings_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Junction table linking bookings to booked seats
CREATE TABLE booking_seats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    seat_id VARCHAR(10) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_booking_seats_booking FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
    CONSTRAINT fk_booking_seats_seat FOREIGN KEY (seat_id) REFERENCES seats(id) ON DELETE CASCADE,
    UNIQUE KEY uq_booking_seat (booking_id, seat_id),
    INDEX idx_booking_seats_seat (seat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Seed the exact 120 predefined seats (Rows A-J, Seats 1-12)
INSERT INTO seats (id, row_label, seat_number, status) VALUES
('A1', 'A', 1, 'available'), ('A2', 'A', 2, 'available'), ('A3', 'A', 3, 'available'), ('A4', 'A', 4, 'available'),
('A5', 'A', 5, 'available'), ('A6', 'A', 6, 'available'), ('A7', 'A', 7, 'available'), ('A8', 'A', 8, 'available'),
('A9', 'A', 9, 'available'), ('A10', 'A', 10, 'available'), ('A11', 'A', 11, 'available'), ('A12', 'A', 12, 'available'),

('B1', 'B', 1, 'available'), ('B2', 'B', 2, 'available'), ('B3', 'B', 3, 'available'), ('B4', 'B', 4, 'available'),
('B5', 'B', 5, 'available'), ('B6', 'B', 6, 'available'), ('B7', 'B', 7, 'available'), ('B8', 'B', 8, 'available'),
('B9', 'B', 9, 'available'), ('B10', 'B', 10, 'available'), ('B11', 'B', 11, 'available'), ('B12', 'B', 12, 'available'),

('C1', 'C', 1, 'available'), ('C2', 'C', 2, 'available'), ('C3', 'C', 3, 'available'), ('C4', 'C', 4, 'available'),
('C5', 'C', 5, 'available'), ('C6', 'C', 6, 'available'), ('C7', 'C', 7, 'available'), ('C8', 'C', 8, 'available'),
('C9', 'C', 9, 'available'), ('C10', 'C', 10, 'available'), ('C11', 'C', 11, 'available'), ('C12', 'C', 12, 'available'),

('D1', 'D', 1, 'available'), ('D2', 'D', 2, 'available'), ('D3', 'D', 3, 'available'), ('D4', 'D', 4, 'available'),
('D5', 'D', 5, 'available'), ('D6', 'D', 6, 'available'), ('D7', 'D', 7, 'available'), ('D8', 'D', 8, 'available'),
('D9', 'D', 9, 'available'), ('D10', 'D', 10, 'available'), ('D11', 'D', 11, 'available'), ('D12', 'D', 12, 'available'),

('E1', 'E', 1, 'available'), ('E2', 'E', 2, 'available'), ('E3', 'E', 3, 'available'), ('E4', 'E', 4, 'available'),
('E5', 'E', 5, 'available'), ('E6', 'E', 6, 'available'), ('E7', 'E', 7, 'available'), ('E8', 'E', 8, 'available'),
('E9', 'E', 9, 'available'), ('E10', 'E', 10, 'available'), ('E11', 'E', 11, 'available'), ('E12', 'E', 12, 'available'),

('F1', 'F', 1, 'available'), ('F2', 'F', 2, 'available'), ('F3', 'F', 3, 'available'), ('F4', 'F', 4, 'available'),
('F5', 'F', 5, 'available'), ('F6', 'F', 6, 'available'), ('F7', 'F', 7, 'available'), ('F8', 'F', 8, 'available'),
('F9', 'F', 9, 'available'), ('F10', 'F', 10, 'available'), ('F11', 'F', 11, 'available'), ('F12', 'F', 12, 'available'),

('G1', 'G', 1, 'available'), ('G2', 'G', 2, 'available'), ('G3', 'G', 3, 'available'), ('G4', 'G', 4, 'available'),
('G5', 'G', 5, 'available'), ('G6', 'G', 6, 'available'), ('G7', 'G', 7, 'available'), ('G8', 'G', 8, 'available'),
('G9', 'G', 9, 'available'), ('G10', 'G', 10, 'available'), ('G11', 'G', 11, 'available'), ('G12', 'G', 12, 'available'),

('H1', 'H', 1, 'available'), ('H2', 'H', 2, 'available'), ('H3', 'H', 3, 'available'), ('H4', 'H', 4, 'available'),
('H5', 'H', 5, 'available'), ('H6', 'H', 6, 'available'), ('H7', 'H', 7, 'available'), ('H8', 'H', 8, 'available'),
('H9', 'H', 9, 'available'), ('H10', 'H', 10, 'available'), ('H11', 'H', 11, 'available'), ('H12', 'H', 12, 'available'),

('I1', 'I', 1, 'available'), ('I2', 'I', 2, 'available'), ('I3', 'I', 3, 'available'), ('I4', 'I', 4, 'available'),
('I5', 'I', 5, 'available'), ('I6', 'I', 6, 'available'), ('I7', 'I', 7, 'available'), ('I8', 'I', 8, 'available'),
('I9', 'I', 9, 'available'), ('I10', 'I', 10, 'available'), ('I11', 'I', 11, 'available'), ('I12', 'I', 12, 'available'),

('J1', 'J', 1, 'available'), ('J2', 'J', 2, 'available'), ('J3', 'J', 3, 'available'), ('J4', 'J', 4, 'available'),
('J5', 'J', 5, 'available'), ('J6', 'J', 6, 'available'), ('J7', 'J', 7, 'available'), ('J8', 'J', 8, 'available'),
('J9', 'J', 9, 'available'), ('J10', 'J', 10, 'available'), ('J11', 'J', 11, 'available'), ('J12', 'J', 12, 'available')
ON DUPLICATE KEY UPDATE row_label = VALUES(row_label);
