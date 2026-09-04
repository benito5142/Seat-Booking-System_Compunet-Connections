from typing import List, Optional, Union, Any, Dict
from pydantic import BaseModel, Field


class SeatResponse(BaseModel):
    id: str
    row: str
    seat_number: int
    status: str

    class Config:
        from_attributes = True


class HoldRequest(BaseModel):
    seats: Optional[List[str]] = None
    seat_ids: Optional[List[str]] = None
    user_id: Optional[str] = "default_user"


class HoldResponse(BaseModel):
    id: int
    hold_id: int
    hold_token: str
    seats: List[str]
    expires_at: str
    expires_in_seconds: int
    status: str
    user_id: Optional[str] = "default_user"


class BookingRequest(BaseModel):
    hold_id: Optional[Union[int, str]] = None
    holdId: Optional[Union[int, str]] = None
    hold_token: Optional[str] = None
    user_id: Optional[str] = "default_user"


class BookingResponse(BaseModel):
    id: int
    booking_id: int
    booking_reference: str
    hold_id: int
    seats: List[str]
    booked_seats: List[str]
    user_id: str
    status: str
    created_at: str


class ReleaseResponse(BaseModel):
    status: str
    hold_id: int
    message: str
    released_seats: List[str]


class HealthResponse(BaseModel):
    status: str
    service: str
    database: str
    environment: str


class EventInfoResponse(BaseModel):
    event_id: int
    name: str
    seat_map: Dict[str, Any]
