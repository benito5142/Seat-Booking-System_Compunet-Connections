from datetime import datetime
from typing import List, Dict, Any, Optional

def get_seats_from_dbapi(cursor, now_dt: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Fetches all 120 seats from the database and determines their effective status.
    
    Status calculation rules:
    1. If seat is booked, status is 'booked'.
    2. If seat is held, check if the hold has expired:
       - If there is an active hold with expires_at > now, status is 'held'.
       - If hold has expired (expires_at <= now), status is 'available'.
    3. Otherwise, status is 'available'.
    
    Database is the source of truth.
    Expired holds also trigger lazy cleanup of expired hold records and seat status.
    """
    if now_dt is None:
        now_dt = datetime.utcnow()
    
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Step 1: Query seats joined with active holds
    # A seat is held if there is an associated hold with status 'ACTIVE'
    query = """
    SELECT 
        s.id,
        s.row_label,
        s.seat_number,
        s.status AS db_status,
        h.id AS hold_id,
        h.status AS hold_status,
        h.expires_at AS hold_expires_at
    FROM seats s
    LEFT JOIN hold_seats hs ON s.id = hs.seat_id
    LEFT JOIN holds h ON hs.hold_id = h.id AND h.status = 'ACTIVE'
    ORDER BY s.row_label ASC, s.seat_number ASC
    """
    cursor.execute(query)
    rows = cursor.fetchall()

    expired_hold_ids = set()
    seats_result = []

    for row in rows:
        # Support both tuple/list access and sqlite3.Row / dict-like access
        if isinstance(row, (tuple, list)):
            seat_id, row_label, seat_number, db_status, hold_id, hold_status, hold_expires_at = row[:7]
        else:
            seat_id = row["id"]
            row_label = row["row_label"]
            seat_number = row["seat_number"]
            db_status = row["db_status"]
            hold_id = row["hold_id"]
            hold_status = row["hold_status"]
            hold_expires_at = row["hold_expires_at"]

        # Parse hold_expires_at if present
        is_hold_active = False
        if hold_id and hold_status == "ACTIVE" and hold_expires_at:
            if isinstance(hold_expires_at, str):
                try:
                    # Support ISO formats and standard SQL datetime
                    exp_dt = datetime.fromisoformat(hold_expires_at.replace("Z", "+00:00").split("+")[0])
                except ValueError:
                    exp_dt = datetime.strptime(hold_expires_at[:19], "%Y-%m-%d %H:%M:%S")
            elif isinstance(hold_expires_at, datetime):
                exp_dt = hold_expires_at
            else:
                exp_dt = None

            if exp_dt:
                if exp_dt > now_dt:
                    is_hold_active = True
                else:
                    expired_hold_ids.add(hold_id)

        # Compute effective status ('available', 'held', 'booked')
        db_status_upper = str(db_status).upper() if db_status else "AVAILABLE"
        if db_status_upper == "BOOKED":
            effective_status = "booked"
        elif is_hold_active or (db_status_upper == "HELD" and not hold_id):
            # If seat marked held and hold is currently active
            if is_hold_active:
                effective_status = "held"
            else:
                effective_status = "available"
        else:
            effective_status = "available"

        seats_result.append({
            "id": seat_id,
            "row": row_label,
            "seat_number": seat_number,
            "status": effective_status,
        })

    # Step 2: Lazy expiration update in DB if expired holds were detected
    if expired_hold_ids:
        try:
            placeholders = ",".join(["?"] * len(expired_hold_ids))
            # Mark holds as EXPIRED
            cursor.execute(
                f"UPDATE holds SET status = 'EXPIRED' WHERE id IN ({placeholders})",
                list(expired_hold_ids),
            )
            # Find seats associated with expired holds that are not booked and revert to AVAILABLE
            cursor.execute(
                f"""
                UPDATE seats 
                SET status = 'AVAILABLE' 
                WHERE status = 'HELD' 
                  AND id IN (
                      SELECT seat_id FROM hold_seats WHERE hold_id IN ({placeholders})
                  )
                """,
                list(expired_hold_ids),
            )
        except Exception:
            # Tolerant to read-only or concurrent transitions
            pass

    return seats_result

def get_seats_from_orm(session, now_dt: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Fetches seats and effective status using an active SQLAlchemy ORM session.
    """
    from backend.app.models import Seat, Hold, HoldSeat, SeatStatus, HoldStatus

    if now_dt is None:
        now_dt = datetime.utcnow()

    # Query seats
    seats = session.query(Seat).order_by(Seat.row_label.asc(), Seat.seat_number.asc()).all()

    # Query active holds and their held seats
    active_holds = (
        session.query(Hold)
        .filter(Hold.status == HoldStatus.ACTIVE)
        .all()
    )

    active_seat_ids = set()
    expired_holds = []

    for hold in active_holds:
        if hold.expires_at > now_dt:
            for hs in hold.hold_seats:
                active_seat_ids.add(hs.seat_id)
        else:
            expired_holds.append(hold)

    # Lazy update expired holds in the database
    if expired_holds:
        for hold in expired_holds:
            hold.status = HoldStatus.EXPIRED
            for hs in hold.hold_seats:
                if hs.seat and hs.seat.status == SeatStatus.HELD:
                    hs.seat.status = SeatStatus.AVAILABLE
        try:
            session.commit()
        except Exception:
            session.rollback()

    results = []
    for seat in seats:
        if seat.status == SeatStatus.BOOKED:
            status_str = "booked"
        elif seat.id in active_seat_ids:
            status_str = "held"
        else:
            status_str = "available"

        results.append({
            "id": seat.id,
            "row": seat.row_label,
            "seat_number": seat.seat_number,
            "status": status_str,
        })

    return results
