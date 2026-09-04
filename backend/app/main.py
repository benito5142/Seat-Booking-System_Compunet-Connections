import asyncio
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import engine, get_db, Base, SessionLocal
from backend.app.seed import seed_seats
from backend.app.schemas import (
    SeatOut,
    HoldCreateRequest,
    HoldResponse,
    HoldReleaseResponse,
    BookingCreateRequest,
    BookingResponse,
    HealthResponse,
    EventInfoResponse,
    SeatMapSpec,
)
from backend.app.seats_service import (
    get_all_seats,
    create_hold,
    release_hold,
    confirm_hold_and_create_booking,
    get_all_bookings,
    cleanup_expired_holds,
)

async def periodic_hold_cleanup():
    """Background task to automatically expire holds older than 5 minutes."""
    while True:
        try:
            db = SessionLocal()
            try:
                cleanup_expired_holds(db)
            finally:
                db.close()
        except Exception as e:
            print(f"Error during background hold cleanup: {e}")
        await asyncio.sleep(15)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables exist and seed predefined 120 seats
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_seats(db)
    finally:
        db.close()

    # Start background cleanup worker
    cleanup_task = asyncio.create_task(periodic_hold_cleanup())
    yield
    # Shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="Seat Booking System",
    description="FastAPI + MySQL Seat Booking API for a 120-seat event with row-level locking",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Configuration
origins = settings.cors_origins_list
if not origins or "*" in origins:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins != ["*"] else ["*"],
    allow_credentials=True if origins != ["*"] else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    try:
        # Check DB connection
        db.execute(Base.metadata.tables["seats"].select().limit(1))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "ok",
        "service": "seat-booking-backend",
        "database": db_status,
        "environment": settings.APP_ENV,
    }

@app.get("/api/event/info", response_model=EventInfoResponse)
def event_info():
    return {
        "event_id": 1,
        "name": "Main Event",
        "seat_map": {
            "rows": settings.TOTAL_ROWS,
            "seats_per_row": settings.SEATS_PER_ROW,
            "total_seats": settings.TOTAL_SEATS,
        },
    }

@app.get("/seats", response_model=List[SeatOut])
def list_seats(db: Session = Depends(get_db)):
    """Returns all 120 seats with current status (available, held, booked)."""
    return get_all_seats(db)

@app.post("/holds", response_model=HoldResponse, status_code=status.HTTP_201_CREATED)
def make_hold(request: HoldCreateRequest, db: Session = Depends(get_db)):
    """
    Atomically holds 1-4 seats using SELECT ... FOR UPDATE.
    All-or-nothing: fails if any seat is unavailable.
    """
    return create_hold(db, seat_ids=request.seats, user_id=request.user_id or "default_user")

@app.delete("/holds/{id}", response_model=HoldReleaseResponse)
def release_seat_hold(id: str, db: Session = Depends(get_db)):
    """Releases an active hold, returning its seats to available."""
    return release_hold(db, hold_identifier=id)

@app.post("/holds/{hold_token}/confirm", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def confirm_hold_by_token(hold_token: str, request: Optional[BookingCreateRequest] = None, db: Session = Depends(get_db)):
    """Confirms hold identified by token parameter."""
    user_id = request.user_id if request else "default_user"
    return confirm_hold_and_create_booking(db, hold_identifier=hold_token, user_id=user_id)

@app.post("/bookings", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_booking(request: BookingCreateRequest, db: Session = Depends(get_db)):
    """Confirms active hold and creates a booking."""
    identifier = request.hold_id or request.hold_token
    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hold_id is required to create a booking",
        )
    return confirm_hold_and_create_booking(db, hold_identifier=str(identifier), user_id=request.user_id)

@app.get("/bookings", response_model=List[BookingResponse])
def list_bookings(db: Session = Depends(get_db)):
    """Lists all confirmed bookings."""
    return get_all_bookings(db)

@app.post("/holds/cleanup")
def trigger_cleanup(db: Session = Depends(get_db)):
    """Manually triggers expiration sweep."""
    cleaned = cleanup_expired_holds(db)
    return {"status": "ok", "cleaned_holds": cleaned}
