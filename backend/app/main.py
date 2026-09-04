"""
FastAPI application definition and router endpoints.
"""
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from backend.app.config import settings
from backend.app.database import get_db

app = FastAPI(
    title="Seat Booking System API",
    description="Backend API for single-event seat booking system (10 rows x 12 seats = 120 total seats)",
    version="1.0.0",
)

class HoldRequest(BaseModel):
    """Payload for requesting temporary seat holds."""
    seats: Optional[List[str]] = Field(default=None, description="List of seat IDs to hold (max 4)")
    seat_ids: Optional[List[str]] = Field(default=None, description="Alternative key for seat IDs list")
    user_id: Optional[str] = Field(default="default_user", description="Identifier for holding user")

# CORS configuration to enable communication between React frontend and FastAPI backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    """Root endpoint providing basic API status and seat configuration specifications."""
    return {
        "message": "Seat Booking System API is running",
        "event_spec": {
            "total_rows": settings.TOTAL_ROWS,
            "seats_per_row": settings.SEATS_PER_ROW,
            "total_seats": settings.TOTAL_SEATS,
        },
        "status": "ready",
    }

@app.get("/api/health")
def health_check():
    """Health check endpoint for monitoring service status."""
    return {
        "status": "ok",
        "service": "seat-booking-backend",
        "environment": settings.APP_ENV,
    }

@app.get("/api/event/info")
def get_event_info():
    """Returns fixed event map metadata without booking logic."""
    return {
        "event_id": 1,
        "name": "Main Event",
        "seat_map": {
            "rows": settings.TOTAL_ROWS,
            "seats_per_row": settings.SEATS_PER_ROW,
            "total_seats": settings.TOTAL_SEATS,
        },
    }

@app.get("/seats")
def get_seats(db = Depends(get_db)):
    """
    Returns the complete 10 x 12 seat map (exactly 120 seats).
    
    Each seat includes:
    - id: seat ID (e.g. 'A1', 'J12')
    - row: row identifier ('A' through 'J')
    - seat_number: number within row (1 through 12)
    - status: 'available' | 'held' | 'booked'
    
    The database is the source of truth.
    Expired holds are dynamically evaluated and reflected as 'available'.
    """
    from backend.app.seats_service import get_seats_from_orm
    try:
        seats = get_seats_from_orm(db)
        return seats
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve seats from database: {str(e)}",
        )

@app.post("/holds", status_code=status.HTTP_201_CREATED)
def create_hold(payload: HoldRequest, db = Depends(get_db)):
    """
    Creates a temporary 5-minute hold for up to 4 seats atomically.

    Concurrency Protection & Row Locking:
    - Starts a single database transaction.
    - Validates requested seats (1 to 4 seats maximum).
    - Locks requested seat rows in consistent ascending ID order using SELECT ... FOR UPDATE.
    - Evaluates expired holds and cleans them up before availability verification.
    - Enforces all-or-nothing: if any seat is unavailable (booked or actively held),
      rolls back the transaction completely with HTTP 409 Conflict.
    - If all seats are available, registers the hold, links all seats, marks them HELD,
      and commits the transaction.
    """
    from backend.app.seats_service import (
        create_hold_orm,
        InvalidSeatRequestError,
        SeatUnavailableError,
    )

    requested_seats = payload.seats or payload.seat_ids or []
    if not requested_seats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one seat must be specified",
        )

    try:
        hold_result = create_hold_orm(
            session=db,
            seat_ids=requested_seats,
            user_id=payload.user_id or "default_user",
        )
        return hold_result
    except InvalidSeatRequestError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.message,
        )
    except SeatUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": e.message,
                "unavailable_seats": e.unavailable_seats,
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create seat hold: {str(e)}",
        )

