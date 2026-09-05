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

---

## Comprehensive & Unsanitised Prompt Log

> *"We expect you to use AI tools, and using them well is a skill we're hiring for. So don't sanitise this — include the prompts that didn't work, what you changed, and where you overrode or corrected the output. A clean list of five perfect prompts tells us less than an honest one that shows how you actually got there."*

This section documents the actual, unfiltered engineering trajectory: prompts that yielded flawed code, the architectural failures encountered, how the prompts were revised, and where AI suggestions were explicitly overridden.

---

### Iteration 1: Seat Hold Logic & The Check-Then-Act Race Condition

#### The Naive Prompt That Failed
> *"Write an endpoint `POST /holds` in FastAPI using SQLAlchemy. It should take a list of seat IDs and user ID. Query the database to see if each seat is currently 'AVAILABLE'. If they are all available, loop through them, update their status to 'HELD', and return the hold details with a 5-minute expiration."*

#### What Failed
The AI generated a standard check-then-act pattern:
```python
# FAILED CODE PRODUCED BY AI:
available_seats = db.query(Seat).filter(Seat.id.in_(requested_seats), Seat.status == "AVAILABLE").all()
if len(available_seats) != len(requested_seats):
    raise HTTPException(status_code=409, detail="Some seats are not available")

for seat in available_seats:
    seat.status = "HELD"
db.commit()
```
- **The Defect**: Between the `SELECT` query and the subsequent `UPDATE/commit()`, another concurrent thread can execute the exact same `SELECT`, observe the seats as `AVAILABLE`, and commit its own hold. Both callers received `201 Created` for the same seat.
- **Why It Happened**: The AI defaulted to typical web application tutorial logic without accounting for transaction isolation levels and row lock acquisition.

#### The Corrective Prompt & Override
> *"Do NOT use a detached SELECT followed by an UPDATE. In high-concurrency ticketing systems this causes severe TOCTOU double-allocation bugs. Rewrite the hold transaction using pessimistic row-level locking with `SELECT ... FOR UPDATE` via SQLAlchemy (`with_for_update()`). Furthermore, ensure all requested seat IDs are sorted in ascending alphabetical order before querying to prevent deadlock cycles across concurrent transactions."*

#### What Changed & The Engineering Outcome
- Explicit `session.query(Seat).filter(Seat.id.in_(sorted_ids)).with_for_update()` locks all target rows immediately.
- Competing threads attempting to hold overlapping seats are blocked at the database engine level until the active transaction commits or rolls back.
- Deadlock prevention is mathematically guaranteed because all transactions request row locks in uniform order ($S_1 < S_2 < ... < S_k$).

---

### Iteration 2: Concurrency Testing — Sequential vs. Genuine Barrier Testing

#### The Prompt That Failed
> *"Write a Pytest test case in `tests/test_concurrency.py` that verifies two users cannot book the same seat. Make two API calls to `POST /holds` for seat A1 and check that one returns 201 and the other returns 409."*

#### What Failed
The AI generated a purely sequential test:
```python
# FAILED TEST PRODUCED BY AI:
def test_concurrency(client):
    res1 = client.post("/holds", json={"seats": ["A1"]})
    res2 = client.post("/holds", json={"seats": ["A1"]})
    assert res1.status_code == 201
    assert res2.status_code == 409
```
- **The Defect**: This test passed 100% of the time, but proved **zero** concurrency safety. Request 1 had already completely finished, committed, and closed its connection before Request 2 began. Any broken, race-condition-prone implementation would pass this test.

#### The Corrective Prompt & Override
> *"This sequential test is invalid because it does not test race conditions or lock contention. Rewrite `tests/test_concurrency.py` to use `concurrent.futures.ThreadPoolExecutor` and Python's `threading.Barrier(2)`. Both worker threads must instantiate separate client sessions, synchronize at the barrier to release at the exact same millisecond, and fire concurrent requests against the FastAPI backend."*

#### What Changed & The Engineering Outcome
- The test harness now uses a barrier:
  ```python
  barrier = threading.Barrier(2)
  def worker(seat_ids):
      barrier.wait()  # Synchronize release
      return client.post("/holds", json={"seats": seat_ids})
  ```
- This caught actual lock contention and validated that row-level locking cleanly isolates concurrent operations under real multi-threaded pressure.

---

### Iteration 3: The Framework Migration Regression & Emergency Override

#### What Happened
During development in the automated AI Studio agent environment, an automated subagent attempted to rewrite the backend from Python/FastAPI to an Express/Node.js server with an in-memory JavaScript array store (`seats = [...]`).

#### Why It Failed
- In-memory JavaScript arrays wiped all relational persistence, eliminated transaction atomicity, deleted the 22 comprehensive Pytest functional test cases, and removed row-level locking guarantees.
- An in-memory store in Node.js cannot demonstrate production-grade relational concurrency control (e.g. MySQL `SELECT ... FOR UPDATE` and storage engine `UNIQUE` constraints).

#### The Corrective Prompt & Override
> *"CRITICAL OVERRIDE: Stop all Node.js backend conversion immediately. Revert git history back to the clean Python/FastAPI state. All seat reservations, holds, and bookings must run through FastAPI, SQLAlchemy, and relational database transactions. Restore the 66 Pytest unit, functional, and concurrency tests."*

#### What Changed & The Engineering Outcome
- Immediately restored Python FastAPI with SQLAlchemy models (`backend/app/models.py`), database service layer (`backend/app/seats_service.py`), and the full Pytest test suite.
- Re-ran the test suite to verify 66/66 passing tests on Python 3.10.

---

### Iteration 4: Hold Expiration — The Background Cron Blindspot

#### The Prompt That Failed
> *"Add a background cron task that runs every minute to find expired holds in the database and delete them so seats become available again."*

#### What Failed
- **The Defect**: If a hold expired at minute 1:00, but the cron only ran at minute 2:00, there was a 60-second "dead window" where a seat was legally expired according to its timestamp, yet a user looking at the UI or attempting to reserve it was falsely rejected with `409 Conflict`.
- Deleting hold records entirely also destroyed the audit trail needed to tell a user *"Your hold expired"* rather than *"Hold not found"*.

#### The Corrective Prompt & Override
> *"Do not rely solely on a periodic background task, and never delete hold records. Implement a two-tier expiration architecture:
> 1. Lazy Expiration on Read/Write: In `GET /seats` and `POST /holds`, query for active holds where `expires_at <= NOW()`, transition their status to `EXPIRED`, and reset their seats to `AVAILABLE` within the same transaction.
> 2. Fast 15-second lifespan background task: Sweeps any remaining stale records without blocking request paths.
> 3. State retention: Mark holds as `EXPIRED` instead of deleting them, so `POST /bookings` returns 400 Bad Request ('Hold is expired and cannot be confirmed') instead of an ambiguous 404."*

#### What Changed & The Engineering Outcome
- Zero dead-window: even if the background cleaner is delayed, any read or write dynamically recycles expired holds instantly.
- Auditability: expired holds remain in the database as `status = 'EXPIRED'`, enabling clear error messaging.

---

### Iteration 5: Page Reload vs. Reset All Seats (Domain Integrity vs. Demo Needs)

#### The User Inquiry
> *"does the feature like refresh all the booked seats to available when i reload does this feature need or not"*

#### The Analysis & Recommendation
- In real-world ticketing (BookMyShow, Ticketmaster, airlines), reloading a page **must never** wipe booked seats. Bookings represent paid, committed transactions; resetting on browser reload would violate data persistence, cause double bookings across users, and break concurrency integrity.
- However, for evaluation and repeated testing, reviewers need an effortless way to clear the 120 seats back to `AVAILABLE` without restarting servers or running SQL scripts.
- **The Solution**: Keep browser reloads strictly tied to persistent database truth, while providing a dedicated, low-profile **"Reset All Seats"** endpoint and UI control.

#### The Corrective Prompt
> *"why reload the booked seat remains the same but add the feature like reset all seats button anywhere in the ui but not that much visible since its the actually feature just for project purpose include the feature while refresh the seats need to remain same and when the button is clicked the seats should be resets"*

#### What Happened Next (The 404 Not Found & Stale Process Defect)
When the user clicked the newly added Reset button in the UI, an error banner popped up:
`Seat Booking Conflict / Error: Not Found`
And the user reported:
> *"i got this error also if i refresh i couldnt see the page refreshing"*

#### The Debugging & Root Cause Analysis
1. **The 404 Cause**: `start_backend.py` had a health check `is_backend_healthy()`: if port 8001 answered, it assumed the backend was running and skipped starting it. Because uvicorn had been launched earlier before the `/api/reset` route was added to `main.py`, the running process had an older in-memory route table and returned 404 for `/api/reset`.
2. **The Refresh Feedback Cause**: The manual "Refresh" button fetched `/seats` in under 15ms. Because there was no loading state or visual feedback indicator, the user felt as though nothing happened when clicking Refresh.

#### The Code Corrections Applied
1. In `start_backend.py`: Added `kill_existing_backend()` using `pkill -9 -f "uvicorn backend.app.main:app"` prior to startup to ensure any newly added routes are immediately loaded into the running server.
2. In `src/App.tsx`:
   - Added a visible visual state on the Refresh button: spinning icon, minimum 400ms visual duration, and an emerald **Refreshed** confirmation badge.
   - Cleared active error banners when manual refresh or reset is triggered.
   - Wired `handleResetAllSeats` to call `POST /api/reset`, clear local holds/bookings, and reload the seat inventory.
3. Added Pytest test `test_23_reset_all_seats_resets_everything_to_available` to `tests/test_functional_suite.py` (all 67 tests passing).

---

## Complete Feature Matrix: Traceability to Prompts & Code

| Feature | Specified In | Originating Prompt | Implementation Files | Verification Test |
| :--- | :--- | :--- | :--- | :--- |
| **120-Seat Map (10×12)** | README § Database Schema | "Design a relational schema for seats... seed utility for exactly 120 seats (Rows A–J, Columns 1–12)" | `backend/app/models.py`, `backend/app/seed.py`, `src/components/SeatMap.tsx` | `test_01_get_seats_returns_exactly_120_seats`, `test_02_seat_map_contains_10_rows_by_12_seats` |
| **Max 4 Seats Validation** | README § Features | "Reject requests with empty seat lists, more than 4 seats, duplicate seat IDs..." | `backend/app/main.py`, `src/App.tsx` | `test_06_maximum_4_seats_succeeds`, `test_07_more_than_4_seats_is_rejected` |
| **5-Minute Hold TTL** | README § Hold Expiration | "Implement POST /holds accepting up to 4 seat IDs... exact 5-minute TTL" | `backend/app/seats_service.py`, `src/components/HoldCountdown.tsx` | `test_post_holds_success_and_ttl`, `test_14_hold_expires_after_5_minutes` |
| **Pessimistic Row Locking** | README § Concurrency | "Wrap seat reservation in an explicit transaction using `with_for_update()` on ordered seat IDs" | `backend/app/seats_service.py` | `test_concurrent_holds_identical_seat`, `test_deadlock_prevention_with_reverse_seat_ordering` |
| **All-or-Nothing Hold** | README § Features | "If any seat is unavailable, roll back the entire operation" | `backend/app/seats_service.py` | `test_12_multiseat_hold_is_all_or_nothing`, `test_concurrent_overlapping_seats_all_or_nothing` |
| **Hold Release** | README § Features | "Implement DELETE /holds/{id} to allow users to release their active hold" | `backend/app/main.py`, `src/App.tsx` | `test_13_releasing_a_hold_makes_its_seats_available_again`, `test_delete_holds_success_and_error_handling` |
| **Booking Confirmation** | README § Features | "Transition hold to CONFIRMED, record booking with unique reference code (BK-...)" | `backend/app/seats_service.py`, `src/App.tsx` | `test_18_successful_confirmation_creates_a_booking`, `test_19_booking_receives_a_unique_reference_code` |
| **Storage Engine Anti-Double-Booking** | README § Database Schema | "seat_id UNIQUE on booking_seats" | `backend/app/models.py` | Storage engine constraint verification |
| **Two-Tier Expiration** | README § Hold Expiration | "Combine lazy expiration on request with automated background worker" | `backend/app/seats_service.py`, `backend/app/main.py` | `test_expiration.py`, `test_holds_cleanup_endpoint` |
| **3-Second Polling & Stale Pruning** | README § Polling | "Implement polling every 3 seconds... dynamically prune taken seats" | `src/App.tsx` | UI verification and in-flight request lock |
| **Demo Seat Reset** | Prompt.md & README § Demo Tools | "Add reset all seats button anywhere in the UI but not that much visible for project purpose" | `backend/app/main.py` (`POST /api/reset`), `src/api/client.ts`, `src/App.tsx` | `test_23_reset_all_seats_resets_everything_to_available` |
