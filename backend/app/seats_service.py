import uuid
import datetime
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.app.models import Seat, Hold, HoldSeat, Booking, BookingSeat
from backend.app.config import settings

VALID_ROWS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
SEATS_PER_ROW = 12

def cleanup_expired_holds(db: Session) -> int:
    """
    Finds all active holds that have passed their expires_at timestamp,
    marks them as EXPIRED, and sets their held seats back to available
    (unless booked or in another active hold).
    """
    now = datetime.datetime.utcnow()
    expired_holds = (
        db.query(Hold)
        .filter(Hold.status == "ACTIVE", Hold.expires_at <= now)
        .with_for_update()
        .all()
    )

    if not expired_holds:
        return 0

    cleaned_count = len(expired_holds)
    seats_to_check = set()

    for hold in expired_holds:
        hold.status = "EXPIRED"
        for hs in hold.hold_seats:
            seats_to_check.add(hs.seat_id)

    if seats_to_check:
        sorted_seats = sorted(list(seats_to_check))
        locked_seats = (
            db.query(Seat)
            .filter(Seat.id.in_(sorted_seats))
            .with_for_update()
            .all()
        )
        for seat in locked_seats:
            if seat.status == "held":
                # Check if seat is part of any other active hold
                other_active = (
                    db.query(HoldSeat)
                    .join(Hold, HoldSeat.hold_id == Hold.id)
                    .filter(
                        HoldSeat.seat_id == seat.id,
                        Hold.status == "ACTIVE",
                        Hold.expires_at > now,
                    )
                    .first()
                )
                if not other_active:
                    seat.status = "available"

    db.commit()
    return cleaned_count


def get_all_seats(db: Session) -> List[dict]:
    """
    Returns the complete list of 120 seats with current status.
    Runs lazy expiration cleanup first.
    """
    cleanup_expired_holds(db)

    seats = db.query(Seat).all()

    # Sort naturally by row (A-J) and seat_number (1-12)
    row_order = {r: i for i, r in enumerate(VALID_ROWS)}
    seats.sort(key=lambda s: (row_order.get(s.row_letter, 99), s.seat_number))

    return [
        {
            "id": s.id,
            "row": s.row_letter,
            "seat_number": s.seat_number,
            "status": s.status,
        }
        for s in seats
    ]


def create_hold(db: Session, seat_ids: List[str], user_id: str = "default_user") -> dict:
    """
    Atomically creates a hold on 1 to 4 seats using row-level locking (SELECT ... FOR UPDATE).
    Enforces deterministic ascending ordering of seat IDs to prevent deadlocks.
    All-or-nothing: fails if any seat is unavailable, invalid, or missing.
    """
    cleanup_expired_holds(db)

    if not seat_ids or len(seat_ids) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one seat must be specified",
        )

    # Normalize and deduplicate
    clean_seat_ids = sorted(list(set(s.strip().upper() for s in seat_ids if s.strip())))

    if len(clean_seat_ids) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one seat must be specified",
        )

    if len(clean_seat_ids) > settings.MAX_HOLD_SEATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum of {settings.MAX_HOLD_SEATS} seats can be held at once",
        )

    # 1. Deterministic row-level locking with SELECT ... FOR UPDATE
    # Sorting seat_ids ensures deadlock-free ordering across concurrent requests
    locked_seats = (
        db.query(Seat)
        .filter(Seat.id.in_(clean_seat_ids))
        .order_by(Seat.id.asc())
        .with_for_update()
        .all()
    )

    found_ids = {s.id for s in locked_seats}
    missing = [sid for sid in clean_seat_ids if sid not in found_ids]
    if missing:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid seat ID(s): {', '.join(missing)}",
        )

    # Check availability of every requested seat
    unavailable = [s.id for s in locked_seats if s.status != "available"]
    if unavailable:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "One or more requested seats are unavailable",
                "unavailable_seats": unavailable,
            },
        )

    # All seats are available -> atomically mark them held
    now = datetime.datetime.utcnow()
    expires_at = now + datetime.timedelta(seconds=settings.HOLD_DURATION_SECONDS)
    hold_token = str(uuid.uuid4())

    new_hold = Hold(
        hold_token=hold_token,
        user_id=user_id or "default_user",
        status="ACTIVE",
        expires_at=expires_at,
        created_at=now,
    )
    db.add(new_hold)
    db.flush()  # Flush to get new_hold.id

    for seat in locked_seats:
        seat.status = "held"
        hold_seat = HoldSeat(hold_id=new_hold.id, seat_id=seat.id, created_at=now)
        db.add(hold_seat)

    db.commit()

    return {
        "id": new_hold.id,
        "hold_id": new_hold.id,
        "hold_token": new_hold.hold_token,
        "seats": clean_seat_ids,
        "expires_at": new_hold.expires_at,
        "expires_in_seconds": settings.HOLD_DURATION_SECONDS,
        "status": "held",
        "user_id": new_hold.user_id,
    }


def release_hold(db: Session, hold_identifier: str) -> dict:
    """
    Releases an active hold by hold_id or hold_token.
    Transitions hold to RELEASED and returns seats to available.
    """
    cleanup_expired_holds(db)

    hold_query = db.query(Hold).with_for_update()
    if hold_identifier.isdigit():
        hold = hold_query.filter(Hold.id == int(hold_identifier)).first()
    else:
        hold = hold_query.filter(Hold.hold_token == hold_identifier).first()

    if not hold:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hold not found",
        )

    if hold.status == "RELEASED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hold has already been released and cannot be confirmed",
        )

    if hold.status == "CONFIRMED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hold has already been confirmed and cannot be released",
        )

    now = datetime.datetime.utcnow()
    if hold.status == "EXPIRED" or hold.expires_at <= now:
        hold.status = "EXPIRED"
        # Release seats
        for hs in hold.hold_seats:
            seat = db.query(Seat).filter(Seat.id == hs.seat_id).with_for_update().first()
            if seat and seat.status == "held":
                seat.status = "available"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hold has expired and cannot be released",
        )

    hold.status = "RELEASED"
    released_seats = []
    sorted_seat_ids = sorted([hs.seat_id for hs in hold.hold_seats])

    locked_seats = (
        db.query(Seat)
        .filter(Seat.id.in_(sorted_seat_ids))
        .with_for_update()
        .all()
    )

    for seat in locked_seats:
        if seat.status == "held":
            seat.status = "available"
        released_seats.append(seat.id)

    db.commit()

    return {
        "status": "released",
        "hold_id": hold.id,
        "message": "Hold released successfully",
        "released_seats": released_seats,
    }


def confirm_hold_and_create_booking(
    db: Session,
    hold_identifier: str,
    user_id: Optional[str] = None,
) -> dict:
    """
    Confirms an active hold, marks seats as 'booked', and creates a Booking with a unique reference.
    """
    cleanup_expired_holds(db)

    hold_query = db.query(Hold).with_for_update()
    if str(hold_identifier).isdigit():
        hold = hold_query.filter(Hold.id == int(hold_identifier)).first()
    else:
        hold = hold_query.filter(Hold.hold_token == str(hold_identifier)).first()

    if not hold:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hold not found",
        )

    if hold.status == "RELEASED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hold has already been released and cannot be confirmed",
        )

    if hold.status == "CONFIRMED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hold has already been confirmed",
        )

    now = datetime.datetime.utcnow()
    if hold.status == "EXPIRED" or hold.expires_at <= now:
        hold.status = "EXPIRED"
        for hs in hold.hold_seats:
            seat = db.query(Seat).filter(Seat.id == hs.seat_id).with_for_update().first()
            if seat and seat.status == "held":
                seat.status = "available"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hold has expired and cannot be confirmed",
        )

    seat_ids = sorted([hs.seat_id for hs in hold.hold_seats])
    locked_seats = (
        db.query(Seat)
        .filter(Seat.id.in_(seat_ids))
        .order_by(Seat.id.asc())
        .with_for_update()
        .all()
    )

    unavailable = [s.id for s in locked_seats if s.status != "held"]
    if unavailable:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "One or more seats are unavailable",
                "unavailable_seats": unavailable,
            },
        )

    # Transition seats from held to booked
    for seat in locked_seats:
        seat.status = "booked"

    hold.status = "CONFIRMED"

    booking_ref = f"BK-{uuid.uuid4().hex[:8].upper()}"
    booking = Booking(
        booking_reference=booking_ref,
        hold_id=hold.id,
        user_id=user_id or hold.user_id or "default_user",
        status="confirmed",
        created_at=now,
    )
    db.add(booking)
    db.flush()

    for seat in locked_seats:
        booking_seat = BookingSeat(
            booking_id=booking.id,
            seat_id=seat.id,
            created_at=now,
        )
        db.add(booking_seat)

    db.commit()

    return {
        "id": booking.id,
        "booking_id": booking.id,
        "booking_reference": booking.booking_reference,
        "hold_id": hold.id,
        "seats": seat_ids,
        "booked_seats": seat_ids,
        "user_id": booking.user_id,
        "status": "confirmed",
        "created_at": booking.created_at,
    }


def get_all_bookings(db: Session) -> List[dict]:
    """
    Returns list of all confirmed bookings.
    """
    bookings = db.query(Booking).order_by(Booking.created_at.desc()).all()
    result = []
    for b in bookings:
        seats = [bs.seat_id for bs in b.booking_seats]
        result.append({
            "id": b.id,
            "booking_id": b.id,
            "booking_reference": b.booking_reference,
            "hold_id": b.hold_id,
            "seats": seats,
            "booked_seats": seats,
            "user_id": b.user_id,
            "status": b.status,
            "created_at": b.created_at,
        })
    return result
