"""
FastAPI application definition and router endpoints.
"""
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from backend.app.config import settings
from backend.app.database import get_db

app = FastAPI(
    title="Seat Booking System API",
    description="Backend API for single-event seat booking system (10 rows x 12 seats = 120 total seats)",
    version="1.0.0",
)

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
