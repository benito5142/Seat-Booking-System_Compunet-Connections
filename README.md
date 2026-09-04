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
│   │   └── seed.py           # Fixed 120-seat seeder (A1-A12 to J1-J12)
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
│   └── test_schema.py        # Schema, constraints, and concurrency tests
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
