# AI-Assisted Development

This document provides a comprehensive, transparent record of the prompts, architectural iterations, and corrections used during the development of the **Seat Booking System**.

---

## Project Architecture

### Initial Scaffolding Prompt
> "Build a ticket booking application for a single event with a fixed seat map using Python (FastAPI), React with Vite, and MySQL. The core requirement is that a seat can never be sold twice. The venue consists of a 10 × 12 seat map (120 total seats). Users should be able to hold up to 4 seats for 5 minutes, release holds, or confirm holds into bookings with a unique reference code. The frontend should poll for updates and handle stale seat selections."

### Architecture Decisions & Outcomes
- **Backend Service**: Chose **FastAPI** over Django for asynchronous request handling, native Pydantic type validation, and direct integration with SQLAlchemy connection pools.
- **Frontend SPA**: React 18 with Vite, TypeScript, and Tailwind CSS for responsive layout, interactive seat selection, and dynamic hold countdowns.
- **Relational Persistence**: MySQL 8.0 for production with ACID transactional semantics, row-level locking (`SELECT ... FOR UPDATE`), and relational foreign key constraints. SQLite is configured with thread-safety hooks for seamless automated test execution.

---

## Database

### Schema Definition Prompt
> "Design a relational schema for seats, holds, hold_seats, bookings, and booking_seats. Enforce constraints at the database level: a seat cannot be booked more than once, a hold can only be converted into a single booking, and row/column numbers must be unique. Include a seed utility for exactly 120 seats (Rows A–J, Columns 1–12)."

### Implemented Schema & Integrity Guarantees
1. **`seats`**: `id` (PK, e.g. `'A1'`), `row_label`, `seat_number`, `status` (`'AVAILABLE'`, `'HELD'`, `'BOOKED'`), `version` (integer counter for optimistic checks). `UNIQUE(row_label, seat_number)` prevents coordinate duplication.
2. **`holds`**: `id` (PK), `hold_token` (UUID, UNIQUE), `status` (`'ACTIVE'`, `'EXPIRED'`, `'RELEASED'`, `'CONFIRMED'`), `user_id`, `expires_at` (TIMESTAMP), `created_at`, `updated_at`.
3. **`hold_seats`**: `id` (PK), `hold_id` (FK to holds), `seat_id` (FK to seats). `UNIQUE(hold_id, seat_id)` prevents assigning the same seat multiple times to a hold.
4. **`bookings`**: `id` (PK), `booking_reference` (VARCHAR, UNIQUE), `hold_id` (FK to holds, UNIQUE). `UNIQUE(hold_id)` guarantees that a hold cannot be converted into multiple bookings.
5. **`booking_seats`**: `id` (PK), `booking_id` (FK to bookings), `seat_id` (FK to seats, UNIQUE). `UNIQUE(seat_id)` provides physical storage-engine proof against double-booking.

---

## Backend

### 1. `GET /seats`
- **Prompt**:
  > "Implement `GET /seats` to return all 120 seats with current status (`available`, `held`, `booked`). Ensure that any hold whose `expires_at` has passed is evaluated as expired so expired seats immediately appear available."
- **Outcome**:
  `GET /seats` queries all seats ordered by row and seat number, lazily expiring active holds with `expires_at <= NOW()`, ensuring zero stale-hold exposure to users.

### 2. `POST /holds`
- **Prompt**:
  > "Implement `POST /holds` accepting a list of up to 4 seat IDs. Acquire row-level locks on requested seats in sorted order, verify availability, set status to `HELD`, and return a hold object with an exact 5-minute TTL. If any seat is unavailable, roll back the entire operation."
- **Outcome**:
  All-or-nothing hold placement implemented with `SELECT ... FOR UPDATE` (or SQLite atomic conditional updates) on alphabetically sorted seat IDs (`ORDER BY id ASC`), returning `HTTP 201 Created` or `HTTP 409 Conflict`.

### 3. Expiration Cleanup
- **Prompt**:
  > "Implement hold expiration. Expired holds must actually be cleaned up. Combine lazy expiration on request with an automated background worker running during the server lifespan."
- **Outcome**:
  Two-tier expiration strategy:
  - **Lazy cleanup**: Integrated into `GET /seats` and `POST /holds`.
  - **Background task**: An asynchronous worker executing in FastAPI `lifespan` sweeps stale holds every 15 seconds.
  - Expired holds cannot be confirmed (`HTTP 400 Bad Request`).

### 4. `DELETE /holds/{id}`
- **Prompt**:
  > "Implement `DELETE /holds/{id}` to allow users to release their active hold. Revert only the seats associated with this hold back to `AVAILABLE`. Return 404 if not found and 400 if already confirmed or expired."
- **Outcome**:
  Transitions hold to `'RELEASED'` and resets seat statuses within a single atomic transaction.

### 5. `POST /bookings` & `POST /holds/{hold_token}/confirm`
- **Prompt**:
  > "Implement booking confirmation. Given a hold ID or token, verify it is active and unexpired, transition hold to `CONFIRMED`, record a booking with a unique reference code (`BK-...`), and mark all seats `BOOKED` atomically."
- **Outcome**:
  Enforces all-or-nothing confirmation, marks seats `BOOKED`, and populates `bookings` and `booking_seats` with strict transaction rollback on any error.

### 6. `GET /bookings`
- **Prompt**:
  > "Implement `GET /bookings` to return all confirmed bookings, including booking reference codes, seat lists, and timestamps."
- **Outcome**:
  Returns all confirmed bookings with full seat associations and ISO-8601 timestamps.

---

## Validation

### Prompt
> "Implement strict input validation for seat requests. Reject requests with empty seat lists, more than 4 seats, duplicate seat IDs (e.g. `['A1', 'A1']`), empty strings, null values, or nonexistent seat IDs like `'Z99'`. Return clean 400 Bad Request responses with explanatory error messages."

### Implemented Error Handlers
- Pydantic models with `@validator` enforcing non-empty, non-null, deduplicated seat lists capped at 4 items.
- Custom FastAPI exception handler for `RequestValidationError` converting internal validation traces into clean, structured JSON payloads.

---

## Testing

### Prompt
> "Create a comprehensive functional test suite covering 22 scenarios including: 120 seats existence, 10x12 grid verification, 1-4 seat hold success, >4 seat rejection, duplicate seat ID rejection, nonexistent seat rejection, already held/booked seat conflict (409), all-or-nothing rollback, hold release, 5-minute expiration, expired hold confirmation prevention, successful booking confirmation with unique reference code, duplicate confirmation prevention, and GET /bookings verification."

### Outcome
- All 22 functional scenarios implemented in `tests/test_functional_suite.py` passing 100%.
- Additional test modules created: `tests/test_main.py`, `tests/test_bookings.py`, `tests/test_expiration.py`, and `tests/test_config.py`.

---

## Concurrency

### Concurrency Strategy Prompt
> "Write a genuine multi-threaded test that fires two simultaneous hold requests at the exact same seat at the exact same millisecond. Use `threading.Barrier` to ensure true concurrency. Assert that exactly one request succeeds (HTTP 201) and exactly one fails (HTTP 409). Verify the database state has exactly one hold and zero double-bookings."

### Concurrency Implementation & Test Details
- **Test File**: `tests/test_concurrency.py`.
- **Harness**: Uses `concurrent.futures.ThreadPoolExecutor` and a `threading.Barrier(2)` synchronization point before dispatching requests via Starlette `TestClient`.
- **Scenarios Tested**:
  1. Concurrent holds on identical seats (`A1` vs `A1`).
  2. Concurrent holds on overlapping seats (`A1, A2` vs `A2, A3`) verifying all-or-nothing rollback for the loser.
  3. Reverse-order deadlock prevention (`B1, B2` vs `B2, B1`).
  4. Concurrent confirmations of the same hold.
- **Pass Rate**: 100% passing across all concurrent execution scenarios.

---

## Frontend

### Implementation Prompts
1. **Seat Map**:
   > "Create an interactive 10 × 12 seat map in React. Display visual indicators for Available (emerald), Selected (blue), Held by User (amber with lock), Held by Others (muted amber), and Booked (slate). Enforce a 4-seat selection maximum with warning banners."
2. **Hold & Countdown**:
   > "When a user holds seats, display an active hold banner with a real-time countdown timer derived from the backend `expires_at` timestamp. Add 'Release Hold' and 'Confirm Booking' action buttons. If the timer reaches zero, notify the user and refresh the seat map."
3. **Polling & Stale-Seat Handling**:
   > "Implement polling every 3 seconds to fetch `GET /seats`. Guard against overlapping in-flight requests. If a seat selected by the user is taken by another user during polling, automatically prune it from the selection and display a warning banner."

### Implemented Frontend Experience
- Modern single-screen UI centered on the venue layout.
- Real-time seat inventory counters (Available, Held, Booked).
- Booking confirmation card with copyable reference code and seat badges.
- Dynamic error banners for network or conflict issues.

---

## Problems and Corrections

Here are the real engineering challenges encountered during development and how they were resolved:

### 1. Unsafe Check-Then-Act Race Condition
- **Problem**:
  An early draft of the hold logic queried `session.query(Seat).filter(Seat.id.in_(seat_ids), Seat.status == 'AVAILABLE').all()` and then separately issued an update. Under concurrent requests, two threads read `AVAILABLE` simultaneously before either updated the row.
- **Why it was wrong**:
  Classic Time-of-Check to Time-of-Use (TOCTOU) race condition resulting in duplicate holds on the same seat.
- **Prompt / Correction Used**:
  > "Wrap seat reservation in an explicit transaction using `with_for_update()` on ordered seat IDs: `session.query(Seat).filter(Seat.id.in_(sorted_ids)).with_for_update().all()`. Validate that all requested rows are returned and that every row is currently `AVAILABLE`. If not, immediately abort and rollback."
- **Result**:
  All competing requests block on row locks. The first thread commits; the second thread unblocks, detects the seat is no longer `AVAILABLE`, and safely rolls back with `409 Conflict`.

### 2. Partial Multi-Seat Holds
- **Problem**:
  When requesting multiple seats (e.g. `['A1', 'A2']`), if `A2` was unavailable, an earlier version marked `A1` as held before encountering the error on `A2`.
- **Why it was wrong**:
  Violated the strict all-or-nothing requirement and left orphan held seats.
- **Prompt / Correction Used**:
  > "Ensure all seat validations occur before any seat status is modified, and enclose all updates in a `try...except` block that explicitly issues `db.rollback()` on any failure."
- **Result**:
  If any seat is unavailable, zero seats are modified. Confirmed by `test_12_multiseat_hold_is_all_or_nothing`.

### 3. Expiration Cleanup Gap
- **Problem**:
  Holds had an `expires_at` timestamp, but if no background job ran, expired seats remained marked `HELD` in the database indefinitely until an explicit sweep.
- **Why it was wrong**:
  Users looking at the seat map would see seats as held long after the 5-minute window had elapsed.
- **Prompt / Correction Used**:
  > "Add lazy expiration to `GET /seats` and `POST /holds` so that any hold past its `expires_at` is immediately marked `EXPIRED` and its seats reset to `AVAILABLE` inside the reading transaction, alongside a 15-second background task in FastAPI lifespan."
- **Result**:
  Expired holds are guaranteed to be released instantly upon the next read or hold attempt, with background cleanup keeping table records tidy.

### 4. Sequential Concurrency Test Misconception
- **Problem**:
  An initial test fired Request A, awaited its response, and then fired Request B. Both assertions passed, but no actual concurrent database contention took place.
- **Why it was wrong**:
  A sequential test cannot detect race conditions or verify locking behavior.
- **Prompt / Correction Used**:
  > "Rewrite the concurrency test to use Python's `threading.Barrier(2)` and `ThreadPoolExecutor`. Have both worker threads wait at the barrier until both are ready, then release them simultaneously to issue concurrent HTTP requests to FastAPI."
- **Result**:
  Genuine simultaneous execution verified with real row-level lock contention.

### 5. Stale Frontend State & Selection Drift
- **Problem**:
  If User 1 selected `A1` and sat on the page, and User 2 held `A1`, User 1's UI still showed `A1` as selected. When User 1 clicked "Hold", they received an unexpected 409 error.
- **Why it was wrong**:
  Degraded user experience due to un-reconciled client state.
- **Prompt / Correction Used**:
  > "In the 3-second polling callback, compare the current selected seat IDs against the fresh seat list from `GET /seats`. If any currently selected seat has its status changed to `HELD` or `BOOKED`, remove it from `selectedSeats` and show a toast warning to the user."
- **Result**:
  The frontend dynamically removes taken seats from the user's selection in real time without wiping the rest of their valid selections.

### 6. The Automated Node Migration Rollback
- **Problem**:
  During AI Studio platform operations, an automated migration attempt generated an Express/Node.js backend with an in-memory array store (commit `f4f4649`), abandoning the requested Python/FastAPI stack and real relational database locking.
- **Why it was wrong**:
  Directly violated the core project requirements for Python, FastAPI, relational database locking, and genuine concurrency verification.
- **Prompt / Correction Used**:
  > "Stop all Node migration efforts. Revert immediately to commit `a59c928`. Restore Python FastAPI, SQLAlchemy models, schema.sql, and the multi-threaded Pytest concurrency test suite."
- **Result**:
  Clean restoration of the Python FastAPI backend, database models, and test harness, passing 66 / 66 tests.

---

## Final Review

The final system was verified using:
1. **Automated Pytest Suite**: 66 passed in ~0.9s (`pytest -v`), covering schema constraints, business rules, expiration, hold release, booking confirmation, and multi-threaded concurrency.
2. **Frontend Type & Lint Checks**: TypeScript compilation succeeded with zero errors (`tsc --noEmit`).
3. **Frontend Production Build**: Vite production build succeeded (`npm run build`).
4. **End-to-End API Verification**: Verified `GET /seats`, `POST /holds`, `DELETE /holds/{id}`, `POST /bookings`, and `GET /bookings` via live HTTP requests against the running FastAPI service.
5. **UI & Polling Verification**: Verified 120-seat interactive grid, 4-seat selection cap, 5-minute countdown, stale-seat pruning, and booking receipt display on `http://localhost:3000`.
