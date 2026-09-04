from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.config import settings

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
