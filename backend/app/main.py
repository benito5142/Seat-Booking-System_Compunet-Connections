import asyncio
import logging
from contextlib import asynccontextmanager
from typing import List, Union

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import get_db, check_db_connection, SessionLocal
from backend.app.seed import seed_seats
from backend.app.schemas import (
    SeatResponse,
    HoldRequest,
    HoldResponse,
    BookingRequest,
    BookingResponse,
    ReleaseResponse,
    HealthResponse,
    EventInfoResponse,
)
from backend.app import seats_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("seat_booking.main")


async def background_hold_cleaner():
    """Background task running every 15 seconds to expire stale holds."""
    while True:
        try:
            await asyncio.sleep(15)
            db = SessionLocal()
            try:
                cleaned = seats_service.cleanup_expired_holds(db)
                if cleaned > 0:
                    logger.info(f"Background cleaner expired {cleaned} hold(s)")
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in background hold cleaner: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: seed tables and seats
    logger.info("Starting Seat Booking System backend...")
    try:
        seed_seats()
    except Exception as e:
        logger.error(f"Error during database initialization/seeding: {e}")

    # Launch background expiration cleaner
    cleaner_task = asyncio.create_task(background_hold_cleaner())
    yield
    # Shutdown
    cleaner_task.cancel()
    try:
        await cleaner_task
    except asyncio.CancelledError:
        pass
    logger.info("Backend shutdown complete.")


app = FastAPI(
    title="Seat Booking System API",
    description="FastAPI + MySQL backend for 120-seat event booking with strict concurrency protection.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "message": "Seat Booking System API is running",
        "backend": "FastAPI + Python",
        "database": "MySQL",
        "event_spec": {
            "total_rows": settings.total_rows,
            "seats_per_row": settings.seats_per_row,
            "total_seats": settings.total_seats,
        },
        "status": "ready",
    }


@app.get("/api/health", response_model=HealthResponse)
def health_check():
    db_ok = check_db_connection()
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "seat-booking-backend",
        "database": "connected" if db_ok else "disconnected",
        "environment": settings.app_env,
    }


@app.get("/api/event/info", response_model=EventInfoResponse)
def event_info():
    return {
        "event_id": 1,
        "name": "Main Event",
        "seat_map": {
            "rows": settings.total_rows,
            "seats_per_row": settings.seats_per_row,
            "total_seats": settings.total_seats,
        },
    }


@app.get("/seats", response_model=List[SeatResponse])
def list_seats(db: Session = Depends(get_db)):
    """Return the complete seat map with current status."""
    return seats_service.get_all_seats(db)


@app.post("/holds", response_model=HoldResponse, status_code=status.HTTP_201_CREATED)
def create_seat_hold(req: HoldRequest, db: Session = Depends(get_db)):
    """Create a hold on up to 4 seats atomically with row-level locking."""
    raw_seats = req.seats or req.seat_ids or []
    return seats_service.create_hold(db, seat_ids=raw_seats, user_id=req.user_id or "default_user")


@app.delete("/holds/{id}", response_model=ReleaseResponse)
def release_seat_hold(id: str, db: Session = Depends(get_db)):
    """Release an existing hold."""
    return seats_service.release_hold(db, identifier=id)


@app.post("/holds/{hold_token}/confirm", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def confirm_hold_by_token(hold_token: str, req: BookingRequest = BookingRequest(), db: Session = Depends(get_db)):
    """Confirm hold via token URL parameter."""
    return seats_service.confirm_hold(db, identifier=hold_token, user_id=req.user_id)


@app.post("/bookings", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_booking(req: BookingRequest, db: Session = Depends(get_db)):
    """Confirm an active hold and create a booking."""
    identifier = req.hold_id or req.holdId or req.hold_token
    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hold_id is required to create a booking",
        )
    return seats_service.confirm_hold(db, identifier=identifier, user_id=req.user_id)


@app.get("/bookings", response_model=List[BookingResponse])
def list_bookings(db: Session = Depends(get_db)):
    """List existing bookings."""
    return seats_service.get_all_bookings(db)


@app.post("/holds/cleanup")
def cleanup_holds_manual(db: Session = Depends(get_db)):
    """Manual cleanup trigger for expired holds."""
    cleaned = seats_service.cleanup_expired_holds(db)
    return {"status": "ok", "cleaned_holds": cleaned}
