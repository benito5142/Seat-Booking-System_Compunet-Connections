# Seat Booking System

A robust, concurrency-safe ticket booking web application for a single event featuring a fixed 10 × 12 (120-seat) seating arrangement.

The core engineering guarantee of this system: **a seat can never be sold twice**, enforced via database row-level locking, deterministic lock ordering, transactional atomicity, and storage engine constraints.

---

## Technology Stack

- **Backend**: Python 3.10+, FastAPI, SQLAlchemy, Pydantic
- **Frontend**: React 18, Vite, TypeScript, Tailwind CSS, Lucide Icons
- **Database**: MySQL 8.0 (with SQLite supported for zero-configuration local test runs)
- **Concurrency & Testing**: Pytest, Starlette `TestClient`, multi-threaded execution harness using `threading.Barrier`

---

## Features

- **Fixed 10 × 12 Seat Map**: Exactly 120 seats structured in 10 rows (A through J) with 12 seats per row (1 through 12).
- **Seat States**: Visual and transactional status indicators: `available`, `held`, and `booked`.
- **4-Seat Limit**: Strict validation preventing users from selecting or holding more than 4 seats simultaneously.
- **5-Minute Holds**: Temporary reservation window with an exact 300-second time-to-live (TTL).
- **All-or-Nothing Holds**: Multi-seat holds are strictly atomic. If even one seat is unavailable, the entire transaction rolls back cleanly.
- **Hold Release**: Dedicated endpoint (`DELETE /holds/{id}`) allowing users to release active holds immediately.
- **Booking Confirmation**: Converts an active hold into a confirmed booking, generating a unique booking reference code (`BK-...`).
- **Expiration Cleanup**: Two-tier expiration cleanup strategy combining lazy evaluation on read with an automated background worker.
- **Polling & Stale-Seat Reconciliation**: Periodic 3-second polling that keeps the seat map synchronized across browser sessions without clobbering in-progress local selections unless a conflicting claim occurs.
- **Concurrency Protection**: Multi-layered defense preventing check-then-act race conditions, double-holds, and double-bookings.

---

## Architecture

```text
React (Vite Frontend)
        │
        │ HTTP / REST (JSON)
        ▼
FastAPI (Python Backend Service)
        │
        │ SQLAlchemy ORM / Raw DBAPI Transactions
        ▼
MySQL 8.0 (Relational Database Engine)
```

1. **React Frontend**: Renders the dynamic 120-seat interactive grid, tracks selection state (capped at 4 seats), manages real-time countdown timers, executes periodic background polling, and gracefully reconciles stale seat data.
2. **FastAPI Backend**: Enforces input validation, handles lifespan database seeding, runs background hold cleanup tasks, coordinates transaction boundaries, and guarantees atomic status transitions.
3. **MySQL Database**: Acts as the single source of truth, enforcing physical uniqueness constraints, relational foreign keys, and pessimistic row-level locking (`SELECT ... FOR UPDATE`).

---

## Database Schema

The database consists of 5 relational tables:

```text
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│      seats      │◄──────┤   hold_seats    │──────►│      holds      │
│─────────────────│       │─────────────────│       │─────────────────│
│ id (PK)         │       │ id (PK)         │       │ id (PK)         │
│ row_label       │       │ hold_id (FK)    │       │ hold_token (UQ) │
│ seat_number     │       │ seat_id (FK)    │       │ status          │
│ status          │       │ created_at      │       │ expires_at      │
│ version         │       └─────────────────┘       │ user_id         │
│ created_at      │                                 │ created_at      │
│ updated_at      │       ┌─────────────────┐       │ updated_at      │
│ UQ(row, number) │◄──────┤  booking_seats  │       └────────┬────────┘
└─────────────────┘       │─────────────────│                │
                          │ id (PK)         │                │
                          │ booking_id (FK) │                │
                          │ seat_id (FK, UQ)│                ▼
                          │ created_at      │       ┌─────────────────┐
                          └────────▲────────┘       │    bookings     │
                                   │                │─────────────────│
                                   └────────────────┤ id (PK)         │
                                                    │ reference (UQ)  │
                                                    │ hold_id (FK, UQ)│
                                                    │ status          │
                                                    │ confirmed_at    │
                                                    └─────────────────┘
```

### Table Breakdown

1. **`seats`**:
   - `id VARCHAR(10) PRIMARY KEY`: Unique identifier (e.g., `'A1'`, `'J12'`).
   - `row_label VARCHAR(2) NOT NULL`: Row identifier (`A` through `J`).
   - `seat_number INTEGER NOT NULL`: Column number (`1` through `12`).
   - `status VARCHAR(20) NOT NULL`: Current state (`'AVAILABLE'`, `'HELD'`, `'BOOKED'`).
   - `version INTEGER NOT NULL DEFAULT 0`: Optimistic concurrency control counter.
   - `CONSTRAINT uq_seats_row_seat UNIQUE (row_label, seat_number)`: Enforces uniqueness of row/column coordinates.

2. **`holds`**:
   - `id INTEGER PRIMARY KEY AUTO_INCREMENT`: Internal surrogate key.
   - `hold_token VARCHAR(64) UNIQUE NOT NULL`: Secure client token for confirmation and release.
   - `status VARCHAR(20) NOT NULL`: Status (`'ACTIVE'`, `'EXPIRED'`, `'RELEASED'`, `'CONFIRMED'`).
   - `user_id VARCHAR(100)`: Identifier for the holder.
   - `expires_at TIMESTAMP NOT NULL`: Expiration deadline (created_at + 300 seconds).

3. **`hold_seats`**:
   - `id INTEGER PRIMARY KEY AUTO_INCREMENT`.
   - `hold_id INTEGER NOT NULL REFERENCES holds(id) ON DELETE CASCADE`.
   - `seat_id VARCHAR(10) NOT NULL REFERENCES seats(id) ON DELETE RESTRICT`.
   - `CONSTRAINT uq_hold_seats_hold_seat UNIQUE (hold_id, seat_id)`: Prevents assigning the same seat multiple times within a single hold.

4. **`bookings`**:
   - `id INTEGER PRIMARY KEY AUTO_INCREMENT`.
   - `booking_reference VARCHAR(32) UNIQUE NOT NULL`: External confirmation code (`BK-...`).
   - `hold_id INTEGER UNIQUE REFERENCES holds(id)`: **Crucial constraint**: Ensures that a hold can only be converted into a booking exactly once.
   - `status VARCHAR(20) NOT NULL DEFAULT 'CONFIRMED'`.
   - `confirmed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`.

5. **`booking_seats`**:
   - `id INTEGER PRIMARY KEY AUTO_INCREMENT`.
   - `booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE`.
   - `seat_id VARCHAR(10) NOT NULL UNIQUE REFERENCES seats(id)`: **Storage engine guarantee**: The `UNIQUE(seat_id)` constraint ensures that no seat can ever be recorded in more than one booking, guaranteeing no double-booking at the hardware storage layer.

---

## Setup & Running the Application

### 1. Prerequisites
- Python 3.10 or higher
- Node.js 18 or higher (with npm)
- MySQL Server 8.0+ (Optional: defaults to SQLite if MySQL is not configured)

### 2. Clone the Repository
```bash
git clone <repository_url>
cd seat-booking-system
```

### 3. Create MySQL Database (Optional for MySQL mode)
```sql
CREATE DATABASE seat_booking CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 4. Configure Environment Variables
Copy `.env.example` to create your local `.env`:
```bash
cp .env.example .env
```
Default parameters configured in `.env`:
```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=seat_user
DB_PASSWORD=secret_password
DB_NAME=seat_booking
PORT=8001
HOLD_DURATION_SECONDS=300
```
*Note: If MySQL connection fails or is not supplied, the backend seamlessly falls back to a local SQLite database for effortless evaluation.*

### 5. Install Python Dependencies
```bash
pip install -r backend/requirements.txt
```

### 6. Initialize & Seed Database
Database tables and the 120 initial seats (`A1` to `J12`) are automatically created and seeded during FastAPI application startup (`lifespan` handler). Alternatively, run manually:
```bash
python3 -c "from backend.app.database import engine, Base; import backend.app.models; Base.metadata.create_all(bind=engine); from backend.app.seed import seed_seats, SessionLocal; seed_seats(SessionLocal())"
```

### 7. Start FastAPI Backend
```bash
python3 start_backend.py
```
Or directly with uvicorn:
```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8001 --reload
```
The API is available at `http://127.0.0.1:8001`. Interactive Swagger documentation is at `http://127.0.0.1:8001/docs`.

### 8. Install Frontend Dependencies
```bash
npm install
```

### 9. Start React / Vite Development Server
```bash
npm run dev
```
The frontend connects via Vite reverse proxy on `http://localhost:3000`.

### 10. Access the Application
Open your browser and navigate to:
```text
http://localhost:3000
```

---

## API Documentation

### 1. `GET /seats`
Retrieves all 120 seats with their current status (`available`, `held`, `booked`). Expired holds are evaluated dynamically so stale holds never appear held.

**Response `200 OK`**:
```json
[
  {
    "id": "A1",
    "row": "A",
    "seat_number": 1,
    "status": "available"
  },
  {
    "id": "A2",
    "row": "A",
    "seat_number": 2,
    "status": "held"
  },
  {
    "id": "A3",
    "row": "A",
    "seat_number": 3,
    "status": "booked"
  }
]
```

---

### 2. `POST /holds`
Atomically holds 1 to 4 seats for 5 minutes (300 seconds).

**Request Body**:
```json
{
  "seats": ["B1", "B2"],
  "user_id": "user_42"
}
```

**Success Response `201 Created`**:
```json
{
  "id": 12,
  "hold_token": "a8f192b0-4ce2-4e92-9b2f-9817a56114bc",
  "seats": ["B1", "B2"],
  "status": "held",
  "expires_at": "2026-09-05T12:05:00Z"
}
```

**Conflict Response `409 Conflict` (Seat already held/booked)**:
```json
{
  "detail": "Seats not available: B1"
}
```

**Validation Error `400 Bad Request` (> 4 seats or duplicates)**:
```json
{
  "detail": "Maximum 4 seats can be held at once"
}
```

---

### 3. `DELETE /holds/{id}`
Explicitly releases an active hold by hold ID or token, returning its seats to `available`.

**Success Response `200 OK`**:
```json
{
  "message": "Hold successfully released",
  "hold_id": 12,
  "status": "released",
  "released_seats": ["B1", "B2"]
}
```

**Error Response `404 Not Found`**:
```json
{
  "detail": "Hold not found"
}
```

---

### 4. `POST /bookings`
Confirms an active hold into a permanent booking.

**Request Body**:
```json
{
  "hold_id": 12
}
```
*(Or via token: `POST /holds/{hold_token}/confirm`)*

**Success Response `201 Created`**:
```json
{
  "booking_reference": "BK-A729E10B",
  "hold_id": 12,
  "seats": ["B1", "B2"],
  "status": "confirmed",
  "confirmed_at": "2026-09-05T12:02:15Z"
}
```

**Error Response `400 Bad Request` (Expired or already confirmed hold)**:
```json
{
  "detail": "Hold is expired and cannot be confirmed"
}
```

---

### 5. `GET /bookings`
Retrieves all confirmed bookings in the system.

**Response `200 OK`**:
```json
[
  {
    "id": 1,
    "booking_reference": "BK-A729E10B",
    "hold_id": 12,
    "status": "confirmed",
    "seats": ["B1", "B2"],
    "created_at": "2026-09-05T12:02:15Z"
  }
]
```

---

## Hold Expiration Strategy

### The 5-Minute TTL Lifecycle
Every hold is created with `expires_at = CURRENT_TIMESTAMP + 300 SECONDS`.

### Two-Tier Expiration Strategy
1. **Lazy Expiry on Read (`GET /seats`, `POST /holds`)**:
   - Before evaluating seat availability or rendering the seat map, the application executes a query checking if any active hold has `expires_at <= NOW()`.
   - If found, those holds are lazily transitioned to `'EXPIRED'` and their associated seats reset to `'AVAILABLE'` inside the same transaction.
   - **Why this matters**: Guarantees zero latency window. Even if a background cron job is delayed, an expired hold never blocks a prospective buyer.
2. **Background Worker Cleanup**:
   - A non-blocking asynchronous task runs every 15 seconds in the FastAPI server lifespan.
   - It performs batch sweeping of stale holds, releasing orphan hold-seat associations and keeping the database clean.
3. **Why Expired Holds Cannot Be Confirmed**:
   - `POST /bookings` verifies:
     ```python
     if hold.expires_at <= datetime.utcnow():
         raise HTTPException(status_code=400, detail="Hold is expired and cannot be confirmed")
     ```
   - The transaction locks the hold row and seat rows simultaneously, preventing late confirmations from slipping in while an expired hold is being recycled.

---

## Concurrency Strategy

### The Flaw of Naive Check-Then-Act
In naive implementations, reservations suffer from Time-of-Check to Time-of-Use (TOCTOU) race conditions:

```text
Request A                          Request B
   │                                  │
   ├─► Check: Is seat A1 free?        │
   │   (DB returns: YES)              ├─► Check: Is seat A1 free?
   │                                  │   (DB returns: YES)
   ├─► INSERT hold for A1             │
   │   (Seat A1 held by A)            ├─► INSERT hold for A1
   ▼                                  ▼   (Seat A1 held by B!) ──► DOUBLE OWNERSHIP!
```
When Request A and Request B check availability at the same millisecond, both read `status = 'AVAILABLE'` before either has written. Both proceed to create holds, resulting in double-allocation.

### The Realized Concurrency Architecture
Our implementation prevents this at both the application and database layers:

```text
               Client Request
                     │
                     ▼
         BEGIN EXCLUSIVE TRANSACTION
                     │
                     ▼
     SORT SEAT IDs ASCENDING (A1, A2, ...)
                     │
                     ▼
       SELECT seats ... FOR UPDATE
     (Acquires exclusive row-level locks)
                     │
         ┌───────────┴───────────┐
         │                       │
If ANY seat != AVAILABLE   ALL seats == AVAILABLE
         │                       │
         ▼                       ▼
      ROLLBACK              CREATE HOLD
  HTTP 409 Conflict         UPDATE seats SET status='HELD'
                                 │
                                 ▼
                              COMMIT
                         HTTP 201 Created
```

1. **Deterministic Lock Ordering**:
   - All seat IDs in multi-seat requests are sorted alphabetically (`ORDER BY id ASC`) before executing `SELECT ... FOR UPDATE`.
   - **Deadlock Prevention**: If Request A asks for `["B2", "B1"]` and Request B asks for `["B1", "B2"]`, both transactions request lock `B1` first, then `B2`. This completely eliminates circular wait deadlocks (AB-BA deadlocks).
2. **Pessimistic Row-Level Locking (`SELECT FOR UPDATE`)**:
   - Request A acquires exclusive locks on the requested rows.
   - When Request B attempts to lock the same rows, the database forces Request B to block and wait until Request A commits or rolls back.
   - Once Request A commits, Request B unblocks, reads the newly updated status (`HELD`), detects the conflict, immediately rolls back, and returns `409 Conflict`. Exactly one request wins.
3. **Atomic Multi-Seat Guarantee**:
   - If a user requests `["C1", "C2", "C3"]` and `C2` is already held, the entire transaction rolls back. Neither `C1` nor `C3` is modified.
4. **Storage Engine Unique Constraints**:
   - Even if application code were somehow bypassed, `UNIQUE(seat_id)` on `booking_seats` physically prevents the database engine from ever persisting duplicate bookings for the same seat.

---

## Genuine Concurrent Test

The test suite in `tests/test_concurrency.py` verifies real concurrent behavior:

- **True Concurrency via `threading.Barrier`**:
  - Two threads are launched using `concurrent.futures.ThreadPoolExecutor(max_workers=2)`.
  - Both threads synchronize on a `threading.Barrier(2)` right before issuing their HTTP requests to FastAPI, releasing them simultaneously at the exact same millisecond.
- **Why Sequential Tests Are Insufficient**:
  - Sequential tests execute Request A to completion, then run Request B. Sequential tests test business logic, but completely miss race conditions, lock contention, and transaction isolation bugs.
- **Assertions Made**:
  1. Exactly one thread receives `HTTP 201 Created` with a valid hold ID.
  2. The competing thread receives `HTTP 409 Conflict` reporting the unavailable seat.
  3. The final database state contains exactly one active hold and zero duplicate assignments.

---

## Polling & Stale-Seat Handling

- **Polling Interval**: **3.0 seconds**.
- **Rationale**:
  - **Optimal Responsiveness**: Under human interaction timescales, 3 seconds feels near-instantaneous for seat grid updates.
  - **Low Overhead**: Generating ~20 requests per minute per active user produces negligible load on FastAPI and MySQL.
  - **Simplicity & Resilience**: Eliminates the operational complexity of maintaining persistent WebSocket connections or handling reconnect drops.
- **Stale-Seat Reconciliation**:
  - If a user has `A1` selected on their screen, but another user holds `A1` before the first user clicks "Hold", the background poll immediately detects that `A1` is now `HELD`.
  - The frontend automatically prunes `A1` from the user's active selection and displays an explanatory warning notification: *"Some selected seats were taken by another user and removed."*

---

## System Limitations

1. **Single Event Scope**: Designed strictly around one event with 120 seats as specified by the requirements. Multi-event scaling would require an `event_id` column and compound indexing.
2. **Polling vs WebSockets**: Polling introduces up to 3 seconds of visual delay for remote seat changes. At massive venue scale (e.g., 50,000 seats), Server-Sent Events (SSE) or WebSockets would be preferable.
3. **Simulated Payment**: Checkout completes immediately upon confirmation without an external payment gateway webhook flow.

---

## What I Would Improve With More Time

1. **Server-Sent Events (SSE) / WebSockets**: Replace 3-second HTTP polling with a real-time event stream (`redis.pubsub` or SSE) to achieve sub-100ms visual synchronization across thousands of clients.
2. **Distributed Redis Caching**: Cache the 120-seat map state in Redis with bitmap representations (`bitfield`), serving `GET /seats` directly from memory while maintaining MySQL as the durable transaction authority.
3. **Payment Gateway Webhook Integration**: Implement Stripe/checkout webhooks with asynchronous idempotency keys, allowing holds to transition to `BOOKED` upon cryptographically verified payment success.
4. **User Authentication & Multi-Event Venues**: Introduce JWT-based authentication and a multi-tenant schema supporting diverse venue layouts, tier-based pricing, and personal booking histories.



