import uuid
import secrets
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.app.models import Seat, Hold, HoldSeat, Booking, BookingSeat
from backend.app.config import settings


def cleanup_expired_holds(db: Session, now: Optional[datetime] = None) -> int:
    """
    Sweeps and expires active holds past their 5-minute TTL.
    Updates hold status to 'EXPIRED' and releases seats back to 'available'
    unless booked or held by another active hold.
    """
    if now is None:
        now = datetime.utcnow()

    # Find expired active holds
    expired_holds = (
        db.query(Hold)
        .filter(Hold.status == "ACTIVE", Hold.expires_at <= now)
        .with_for_update()
        .all()
    )

    if not expired_holds:
        return 0

    cleaned_count = len(expired_holds)
    expired_hold_ids = [h.id for h in expired_holds]

    for hold in expired_holds:
        hold.status = "EXPIRED"

    # Find seats associated with these expired holds
    hold_seats = (
        db.query(HoldSeat.seat_id)
        .filter(HoldSeat.hold_id.in_(expired_hold_ids))
        .distinct()
        .all()
    )
    seat_ids = [hs[0] for hs in hold_seats]

    if seat_ids:
        # Deterministically lock seats to avoid deadlocks
        sorted_seat_ids = sorted(seat_ids)
        seats = (
            db.query(Seat)
            .filter(Seat.id.in_(sorted_seat_ids))
            .order_by(Seat.id.asc())
            .with_for_update()
            .all()
        )

        for seat in seats:
            if seat.status == "held":
                # Check if this seat has any other active hold
                active_hold_count = (
                    db.query(HoldSeat)
                    .join(Hold, HoldSeat.hold_id == Hold.id)
                    .filter(
                        HoldSeat.seat_id == seat.id,
                        Hold.status == "ACTIVE",
                        Hold.expires_at > now,
                    )
                    .count()
                )
                if active_hold_count == 0:
                    seat.status = "available"

    db.commit()
    return cleaned_count


def get_all_seats(db: Session) -> List[Dict[str, Any]]:
    """
    Cleans up expired holds and returns the complete seat map with current status.
    """
    cleanup_expired_holds(db)
    seats = (
        db.query(Seat)
        .order_by(Seat.row_label.asc(), Seat.seat_number.asc())
        .all()
    )
    return [
        {
            "id": s.id,
            "row": s.row_label,
            "seat_number": s.seat_number,
            "status": s.status,
        }
        for s in seats
    ]


def create_hold(
    db: Session,
    seat_ids: List[str],
    user_id: str = "default_user",
) -> Dict[str, Any]:
    """
    Creates an atomic hold on 1-4 seats for 5 minutes using row-level locking (FOR UPDATE).
    Locking is performed in deterministic ascending order to prevent deadlocks.
    Fails completely (all-or-nothing) if even a single seat is unavailable.
    """
    cleanup_expired_holds(db)

    if not seat_ids or len(seat_ids) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one seat must be specified",
        )

    # Normalize and deduplicate seat IDs
    clean_seat_ids = sorted(list(set(str(s).strip().upper() for s in seat_ids if str(s).strip())))

    if len(clean_seat_ids) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one seat must be specified",
        )

    if len(clean_seat_ids) > settings.max_hold_seats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum of {settings.max_hold_seats} seats can be held at once",
        )

    # Execute in a single atomic transaction with deterministic row locks
    try:
        # Deterministic ORDER BY id ASC with SELECT ... FOR UPDATE
        locked_seats = (
            db.query(Seat)
            .filter(Seat.id.in_(clean_seat_ids))
            .order_by(Seat.id.asc())
            .with_for_update()
            .all()
        )

        found_seat_map = {s.id: s for s in locked_seats}

        # Validate that all requested seat IDs exist
        missing_seats = [sid for sid in clean_seat_ids if sid not in found_seat_map]
        if missing_seats:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid seat ID(s): {', '.join(missing_seats)}",
            )

        # Check availability: all requested seats must be 'available'
        unavailable = [
            sid for sid in clean_seat_ids if found_seat_map[sid].status != "available"
        ]

        if unavailable:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "One or more requested seats are unavailable",
                    "unavailable_seats": unavailable,
                },
            )

        # Atomically reserve all seats
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=settings.hold_duration_seconds)
        hold_token = str(uuid.uuid4())

        hold = Hold(
            hold_token=hold_token,
            user_id=user_id or "default_user",
            status="ACTIVE",
            expires_at=expires_at,
            created_at=now,
        )
        db.add(hold)
        db.flush()  # Generates hold.id

        for sid in clean_seat_ids:
            # Mark seat as held
            found_seat_map[sid].status = "held"
            # Link hold to seat
            hs = HoldSeat(hold_id=hold.id, seat_id=sid, created_at=now)
            db.add(hs)

        db.commit()
        db.refresh(hold)

        return {
            "id": hold.id,
            "hold_id": hold.id,
            "hold_token": hold.hold_token,
            "seats": clean_seat_ids,
            "expires_at": hold.expires_at.isoformat() + "Z",
            "expires_in_seconds": settings.hold_duration_seconds,
            "status": "held",
            "user_id": hold.user_id,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reserve seats: {str(e)}",
        )


def find_hold_by_identifier(db: Session, identifier: Any, for_update: bool = False) -> Optional[Hold]:
    """Finds a hold by its numeric ID or UUID token."""
    query = db.query(Hold)
    if for_update:
        query = query.with_for_update()

    raw_str = str(identifier).strip()
    if raw_str.isdigit():
        hold = query.filter(Hold.id == int(raw_str)).first()
        if hold:
            return hold

    return query.filter(Hold.hold_token == raw_str).first()


def confirm_hold(
    db: Session,
    identifier: Any,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Confirms an active hold and atomically creates a booking.
    Row-level locking is used for both the hold and the held seats.
    """
    cleanup_expired_holds(db)

    if not identifier or str(identifier).strip() == "":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hold_id is required to create a booking",
        )

    try:
        hold = find_hold_by_identifier(db, identifier, for_update=True)
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

        now = datetime.utcnow()
        if hold.status == "EXPIRED" or hold.expires_at <= now:
            hold.status = "EXPIRED"
            # Release seats
            seat_ids = [hs.seat_id for hs in hold.hold_seats]
            if seat_ids:
                seats = db.query(Seat).filter(Seat.id.in_(seat_ids)).all()
                for s in seats:
                    if s.status == "held":
                        s.status = "available"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Hold has expired and cannot be confirmed",
            )

        # Get and lock all seats for this hold in deterministic order
        hold_seat_ids = sorted([hs.seat_id for hs in hold.hold_seats])
        locked_seats = (
            db.query(Seat)
            .filter(Seat.id.in_(hold_seat_ids))
            .order_by(Seat.id.asc())
            .with_for_update()
            .all()
        )

        unavailable = [s.id for s in locked_seats if s.status != "held"]
        if unavailable:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "One or more seats are unavailable",
                    "unavailable_seats": unavailable,
                },
            )

        # Mark seats as booked
        for seat in locked_seats:
            seat.status = "booked"

        # Mark hold as CONFIRMED
        hold.status = "CONFIRMED"

        # Create booking reference code
        booking_ref = f"BK-{secrets.token_hex(4).upper()}"
        booking = Booking(
            booking_reference=booking_ref,
            hold_id=hold.id,
            user_id=user_id or hold.user_id or "default_user",
            status="confirmed",
            created_at=now,
        )
        db.add(booking)
        db.flush()

        for sid in hold_seat_ids:
            bs = BookingSeat(booking_id=booking.id, seat_id=sid, created_at=now)
            db.add(bs)

        db.commit()
        db.refresh(booking)

        return {
            "id": booking.id,
            "booking_id": booking.id,
            "booking_reference": booking.booking_reference,
            "hold_id": hold.id,
            "seats": hold_seat_ids,
            "booked_seats": hold_seat_ids,
            "user_id": booking.user_id,
            "status": "confirmed",
            "created_at": booking.created_at.isoformat() + "Z",
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to confirm booking: {str(e)}",
        )


def release_hold(db: Session, identifier: Any) -> Dict[str, Any]:
    """
    Releases an existing hold and makes its seats available again.
    """
    cleanup_expired_holds(db)

    if not identifier or str(identifier).strip() == "":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hold not found",
        )

    try:
        hold = find_hold_by_identifier(db, identifier, for_update=True)
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

        now = datetime.utcnow()
        if hold.status == "EXPIRED" or hold.expires_at <= now:
            hold.status = "EXPIRED"
            # Release seats
            seat_ids = [hs.seat_id for hs in hold.hold_seats]
            if seat_ids:
                seats = db.query(Seat).filter(Seat.id.in_(seat_ids)).all()
                for s in seats:
                    if s.status == "held":
                        s.status = "available"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Hold has expired and cannot be released",
            )

        # Release hold
        hold.status = "RELEASED"
        seat_ids = sorted([hs.seat_id for hs in hold.hold_seats])

        if seat_ids:
            seats = (
                db.query(Seat)
                .filter(Seat.id.in_(seat_ids))
                .order_by(Seat.id.asc())
                .with_for_update()
                .all()
            )
            for s in seats:
                if s.status == "held":
                    s.status = "available"

        db.commit()

        return {
            "status": "released",
            "hold_id": hold.id,
            "message": "Hold released successfully",
            "released_seats": seat_ids,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to release hold: {str(e)}",
        )


def get_all_bookings(db: Session) -> List[Dict[str, Any]]:
    """Lists all confirmed bookings."""
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
            "created_at": b.created_at.isoformat() + "Z",
        })
    return result
