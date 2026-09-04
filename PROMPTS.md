# Seat Booking System - Assessment Prompts Log

This document tracks the prompts and requirements completed for the Seat Booking System coding assessment.

## Completed Prompts (1 through 8)

### Prompt 1: Project Initialization & Configuration
- Set up repository structure with Python FastAPI backend, MySQL database, and React + Vite frontend.
- Defined environment variables (`.env.example`) for database credentials, ports, and CORS origins.
- Configured fixed single event specifications: 10 rows (A-J) x 12 seats per row = 120 predefined seats.
- Created health check (`/api/health`) and event info (`/api/event/info`) endpoints.

### Prompt 2: MySQL Schema Design
- Created DDL schema in `backend/schema.sql`:
  - `seats`: Fixed 120 seats with status (`available`, `held`, `booked`).
  - `holds`: Temporary reservations with unique UUID `hold_token`, status, and 5-minute TTL (`expires_at`).
  - `hold_seats`: Junction table linking holds to reserved seat IDs.
  - `bookings`: Confirmed reservations with unique reference code.
  - `booking_seats`: Junction table linking bookings to confirmed seat IDs.

### Prompt 3: Seat Map Seeding
- Implemented database seeder (`backend/app/seed.py`) to initialize exactly 120 seats:
  - Rows: A through J
  - Seat Numbers: 1 through 12
  - Initial Status: `available`

### Prompt 4: Seat Map API
- Implemented `GET /seats` endpoint returning the complete list of 120 seats with their current status.
- Included automatic expiration sweep for holds exceeding 5-minute TTL.

### Prompt 5: Atomic Seat Holds & Concurrency Protection
- Implemented `POST /holds` endpoint supporting 1 to 4 seats.
- Enforced row-level locking (`SELECT ... FOR UPDATE`) in deterministic ascending order (`ORDER BY id ASC`).
- Enforced strict all-or-nothing transactional atomicity: if any requested seat is unavailable or invalid, the entire transaction rolls back and returns `HTTP 409 Conflict` (or `400 Bad Request`).
- Implemented 5-minute hold TTL.

### Prompt 6: Hold Expiration & Sweeper
- Automatic background worker and on-demand sweep (`POST /holds/cleanup`) to expire holds past 5 minutes.
- Released seats returned to `available` state unless confirmed or active under another hold.

### Prompt 7: Hold Release API
- Implemented `DELETE /holds/{id}` endpoint to cancel an active hold and immediately release its seats back to `available`.

### Prompt 8: Booking Confirmation
- Implemented `POST /bookings` and `POST /holds/{hold_token}/confirm` to confirm active holds.
- Transitions held seats to `booked` status and creates booking records with unique booking references.

---

## Next Up: Prompt 9
- Ready for Prompt 9 implementation.
