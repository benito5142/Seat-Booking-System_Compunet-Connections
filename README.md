# Seat Booking System

A coding assessment project for a **single event** seat booking system with a fixed seat map:
- **10 Rows**
- **12 Seats per Row**
- **120 Total Seats**

---

## Project Structure

```text
seat-booking-system/
├── backend/                  # Python FastAPI Backend
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py         # Environment-based DB & app configuration
│   │   ├── database.py       # SQLAlchemy MySQL engine & session management
│   │   ├── main.py           # FastAPI entry point & CORS configuration
│   │   ├── models.py         # SQLAlchemy ORM models (seats, holds, bookings)
│   │   ├── seed.py           # Fixed 120-seat seeder (A1-A12 to J1-J12)
│   │   └── seats_service.py  # Seat retrieval & hold expiration logic
│   ├── .env.example          # Backend environment variables template
│   ├── pytest.ini            # Pytest test runner configuration
│   ├── requirements.txt      # Python dependencies
│   └── schema.sql            # MySQL schema DDL & 120-seat seed script
├── frontend/                 # React Frontend
│   ├── src/
│   │   ├── api/
│   │   │   └── client.ts     # API client for backend communication
│   │   ├── App.tsx           # Application entry point
│   │   └── config.ts         # Frontend API & seat map configuration
│   └── package.json          # Frontend dependencies & scripts
├── tests/                    # Backend Test Suite
│   ├── __init__.py
│   ├── conftest.py           # Pytest fixtures and TestClient setup
│   ├── test_config.py        # Tests for configuration and specifications
│   ├── test_main.py          # API route tests
│   ├── test_schema.py        # Schema, constraints, and concurrency tests
│   ├── test_seats.py         # 120-seat map & hold expiration tests
│   └── test_holds.py         # POST /holds atomicity, 5-min TTL & concurrency tests
├── pytest.ini                # Root pytest configuration
└── README.md                 # Project documentation
```

---

## Running the Application

### 1. Backend (FastAPI + MySQL)

#### Prerequisites
- Python 3.10+
- MySQL Server 8.0+

#### Setup & Execution
1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate   # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure environment variables:
   ```bash
   cp .env.example .env
   # Update DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME in .env
   ```
5. Start the FastAPI development server:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   The API will be available at `http://localhost:8000`. Interactive API documentation (Swagger UI) is accessible at `http://localhost:8000/docs`.

---

### 2. Frontend (React)

#### Prerequisites
- Node.js 18+
- npm or yarn

#### Setup & Execution
1. Navigate to the project root:
   ```bash
   npm install
   ```
2. Start the Vite development server:
   ```bash
   npm run dev
   ```
   The application will be accessible at `http://localhost:3000`.

---

### 3. Running Tests

Run the test suite using `pytest`:
```bash
pytest
```
Or run using Python's standard unittest runner:
```bash
python3 -m unittest discover tests
```

---

## Concurrency & Hold Architecture (`POST /holds`)

### Transaction Boundaries & Row-Level Locking
To prevent race conditions where two concurrent requests see the same seat as available, `POST /holds` strictly enforces:
1. **Single Transaction Boundary**: The entire validation, locking, expiration check, and reservation execute inside a single atomic database transaction.
2. **Deterministic Lock Ordering**: Seat IDs are sorted in ascending order (`ORDER BY id ASC`, e.g., `A1` before `A2`) before acquiring locks. This eliminates AB-BA deadlocks between concurrent requests acquiring intersecting sets of seats.
3. **Pessimistic Row-Level Locks (`SELECT ... FOR UPDATE`)**: Acquires exclusive row locks on requested seats before evaluating availability.
4. **Lazy Expired Hold Accounting**: Any active hold with `expires_at <= now` is lazily marked `EXPIRED` and its seats returned to `AVAILABLE` prior to deciding availability.
5. **Strict All-or-Nothing Guarantee**: If even one requested seat is unavailable (booked or under a non-expired hold), the transaction issues an immediate `ROLLBACK`. Zero partial holds remain.
6. **Atomic Reservation**: When all requested seats are available, the hold is created with an exact 5-minute TTL, linked in `hold_seats`, and the seats' status is updated to `HELD` with an incremented version number before `COMMIT`.

### Concurrent Request Scenarios
- **Scenario 1 (Request A -> A1, Request B -> A1)**: Request A acquires exclusive row lock on `A1`. Request B blocks waiting for the row lock. Request A verifies `A1` is available, marks it `HELD`, and commits. Request B unblocks, reads `A1` as `HELD`, immediately rolls back, and returns `HTTP 409 Conflict`. Exactly one request succeeds.
- **Scenario 2 (Request A -> A1, A2; Request B -> A2, A3)**: Request A locks `A1` and `A2`. Request B waits on `A2`. Request A marks `A1` and `A2` as `HELD` and commits. Request B unblocks, discovers `A2` is `HELD`. Because of all-or-nothing atomicity, Request B rolls back without holding `A3`. `A3` remains untouched and `AVAILABLE`. Request B returns `HTTP 409 Conflict`.

