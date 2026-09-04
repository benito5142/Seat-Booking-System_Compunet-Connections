from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

class SeatOut(BaseModel):
    id: str
    row: str = Field(..., description="Row letter, e.g., 'A'")
    seat_number: int = Field(..., description="Seat number, e.g., 1")
    status: str = Field(..., description="'available', 'held', or 'booked'")

    class Config:
        from_attributes = True

class HoldCreateRequest(BaseModel):
    seats: List[str] = Field(..., min_length=1, max_length=4, description="List of seat IDs to hold (1-4 seats)")
    user_id: Optional[str] = Field(default="default_user", description="User identifier")

class HoldResponse(BaseModel):
    id: int
    hold_id: int
    hold_token: str
    seats: List[str]
    expires_at: datetime
    expires_in_seconds: int
    status: str
    user_id: str

class HoldReleaseResponse(BaseModel):
    status: str
    hold_id: int
    message: str
    released_seats: List[str]

class BookingCreateRequest(BaseModel):
    hold_id: Optional[int] = None
    hold_token: Optional[str] = None
    user_id: Optional[str] = "default_user"

class BookingResponse(BaseModel):
    id: int
    booking_id: int
    booking_reference: str
    hold_id: Optional[int]
    seats: List[str]
    booked_seats: List[str]
    user_id: str
    status: str
    created_at: datetime

class HealthResponse(BaseModel):
    status: str
    service: str
    database: str
    environment: str

class SeatMapSpec(BaseModel):
    rows: int
    seats_per_row: int
    total_seats: int

class EventInfoResponse(BaseModel):
    event_id: int
    name: str
    seat_map: SeatMapSpec
