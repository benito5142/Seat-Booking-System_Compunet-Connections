from datetime import datetime, timedelta
import uuid
from typing import List, Dict, Any, Optional

class HoldError(Exception):
    """Base exception for seat hold operations."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

class InvalidSeatRequestError(HoldError):
    """Raised when seat request validation fails (e.g. >4 seats, non-existent seat IDs)."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message, status_code)

class SeatUnavailableError(HoldError):
    """Raised when one or more requested seats are already held or booked."""
    def __init__(self, message: str, unavailable_seats: List[str]):
        super().__init__(message, status_code=409)
        self.unavailable_seats = unavailable_seats

class HoldExpiredError(HoldError):
    """Raised when an operation (such as confirmation) is attempted on an expired hold."""
    def __init__(self, message: str = "Hold has expired and cannot be confirmed", status_code: int = 400):
        super().__init__(message, status_code=status_code)

class HoldNotFoundError(HoldError):
    """Raised when a hold with the given ID or token is not found."""
    def __init__(self, message: str = "Hold not found", status_code: int = 404):
        super().__init__(message, status_code=status_code)

class HoldAlreadyReleasedError(HoldError):
    """Raised when an operation is attempted on an already released hold."""
    def __init__(self, message: str = "Hold has already been released", status_code: int = 400):
        super().__init__(message, status_code=status_code)

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

def create_hold_dbapi(
    conn_or_cursor,
    seat_ids: List[str],
    user_id: str = "default_user",
    now_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Atomically holds up to 4 seats using raw DBAPI / SQLite connection.

    Concurrency Protection:
    1. Validates requested seat count (1 to 4 seats).
    2. Sorts seat IDs in consistent ascending order to prevent deadlocks.
    3. Acquires row/table level lock on requested seats within a single transaction.
    4. Evaluates and cleans up any expired holds on the requested seats.
    5. Checks that every requested seat is currently AVAILABLE.
    6. If any seat is unavailable (booked or actively held), rolls back immediately.
    7. Atomically creates the hold (5-minute TTL), links hold seats, and updates seat status to HELD.
    8. Commits the transaction.
    """
    if now_dt is None:
        now_dt = datetime.utcnow()

    # Step 1: Input validation
    if not seat_ids:
        raise InvalidSeatRequestError("At least one seat must be specified", status_code=400)

    cleaned_ids = [str(s).strip().upper() for s in seat_ids if str(s).strip()]
    if not cleaned_ids:
        raise InvalidSeatRequestError("At least one seat must be specified", status_code=400)

    unique_seat_ids = list(dict.fromkeys(cleaned_ids))
    if len(unique_seat_ids) > 4:
        raise InvalidSeatRequestError("Maximum of 4 seats can be held at once", status_code=400)

    # Consistent locking order to prevent AB-BA deadlocks between concurrent requests
    sorted_seat_ids = sorted(unique_seat_ids)

    # Determine connection and cursor
    if hasattr(conn_or_cursor, "cursor"):
        conn = conn_or_cursor
        cursor = conn.cursor()
    else:
        cursor = conn_or_cursor
        conn = getattr(cursor, "connection", None)

    # Detect if sqlite or mysql
    is_sqlite = False
    if conn is not None and type(conn).__module__.startswith("sqlite3"):
        is_sqlite = True

    try:
        # Start transaction
        if conn and is_sqlite:
            try:
                cursor.execute("BEGIN IMMEDIATE")
            except Exception:
                # May already be in an open transaction
                pass

        # Step 2: Lock seat rows in consistent order
        placeholders = ",".join(["?"] * len(sorted_seat_ids))
        for_update_clause = "" if is_sqlite else " FOR UPDATE"
        query_seats = f"""
        SELECT id, row_label, seat_number, status, version 
        FROM seats 
        WHERE id IN ({placeholders}) 
        ORDER BY id ASC{for_update_clause}
        """
        cursor.execute(query_seats, sorted_seat_ids)
        seat_rows = cursor.fetchall()

        found_seat_map = {}
        for row in seat_rows:
            if isinstance(row, (tuple, list)):
                s_id, s_row, s_num, s_stat, s_ver = row[:5]
            else:
                s_id = row["id"]
                s_stat = row["status"]
            found_seat_map[s_id] = str(s_stat).upper()

        missing = [sid for sid in sorted_seat_ids if sid not in found_seat_map]
        if missing:
            raise InvalidSeatRequestError(f"Invalid seat ID(s): {', '.join(missing)}", status_code=400)

        # Step 3: Account for expired holds on requested seats
        query_active_holds = f"""
        SELECT h.id, h.status, h.expires_at, hs.seat_id
        FROM holds h
        JOIN hold_seats hs ON h.id = hs.hold_id
        WHERE hs.seat_id IN ({placeholders}) AND h.status = 'ACTIVE'{for_update_clause}
        """
        cursor.execute(query_active_holds, sorted_seat_ids)
        hold_rows = cursor.fetchall()

        expired_hold_ids = set()
        active_held_seat_ids = set()

        for row in hold_rows:
            if isinstance(row, (tuple, list)):
                h_id, h_status, h_expires_at, hs_seat_id = row[:4]
            else:
                h_id = row["id"]
                h_status = row["status"]
                h_expires_at = row["expires_at"]
                hs_seat_id = row["seat_id"]

            if isinstance(h_expires_at, str):
                try:
                    exp_dt = datetime.fromisoformat(h_expires_at.replace("Z", "+00:00").split("+")[0])
                except ValueError:
                    exp_dt = datetime.strptime(h_expires_at[:19], "%Y-%m-%d %H:%M:%S")
            elif isinstance(h_expires_at, datetime):
                exp_dt = h_expires_at
            else:
                exp_dt = None

            if exp_dt and exp_dt <= now_dt:
                expired_hold_ids.add(h_id)
            else:
                active_held_seat_ids.add(hs_seat_id)

        # Clean up detected expired holds
        if expired_hold_ids:
            exp_placeholders = ",".join(["?"] * len(expired_hold_ids))
            cursor.execute(
                f"UPDATE holds SET status = 'EXPIRED' WHERE id IN ({exp_placeholders})",
                list(expired_hold_ids),
            )
            cursor.execute(
                f"""
                UPDATE seats 
                SET status = 'AVAILABLE' 
                WHERE status = 'HELD' 
                  AND id IN (
                      SELECT seat_id FROM hold_seats WHERE hold_id IN ({exp_placeholders})
                  )
                """,
                list(expired_hold_ids),
            )
            for sid in sorted_seat_ids:
                if sid not in active_held_seat_ids and found_seat_map.get(sid) == "HELD":
                    found_seat_map[sid] = "AVAILABLE"

        # Step 4: Verify that EVERY requested seat is currently AVAILABLE
        unavailable_seats = []
        for sid in sorted_seat_ids:
            current_status = found_seat_map.get(sid, "AVAILABLE")
            if current_status == "BOOKED":
                unavailable_seats.append(sid)
            elif current_status == "HELD" or sid in active_held_seat_ids:
                unavailable_seats.append(sid)

        # All-or-nothing: if even one is unavailable, rollback and fail entire request!
        if unavailable_seats:
            if conn:
                conn.rollback()
            raise SeatUnavailableError(
                f"One or more requested seats are unavailable: {', '.join(unavailable_seats)}",
                unavailable_seats=unavailable_seats,
            )

        # Step 5: All requested seats are available -> create hold atomically
        hold_token = uuid.uuid4().hex
        expires_at = now_dt + timedelta(minutes=5)
        expires_at_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            """
            INSERT INTO holds (hold_token, status, expires_at, created_at, updated_at) 
            VALUES (?, 'ACTIVE', ?, ?, ?)
            """,
            (hold_token, expires_at_str, now_str, now_str),
        )
        hold_id = cursor.lastrowid

        for sid in sorted_seat_ids:
            cursor.execute(
                "INSERT INTO hold_seats (hold_id, seat_id, created_at) VALUES (?, ?, ?)",
                (hold_id, sid, now_str),
            )
            cursor.execute(
                "UPDATE seats SET status = 'HELD', version = version + 1, updated_at = ? WHERE id = ?",
                (now_str, sid),
            )

        if conn:
            conn.commit()

        return {
            "id": hold_id,
            "hold_id": hold_id,
            "hold_token": hold_token,
            "seats": sorted_seat_ids,
            "expires_at": expires_at.isoformat() + "Z",
            "expires_in_seconds": 300,
            "status": "held",
            "user_id": user_id,
        }

    except HoldError:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise e

def create_hold_orm(
    session,
    seat_ids: List[str],
    user_id: str = "default_user",
    now_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Atomically holds up to 4 seats using SQLAlchemy ORM with row-level locks.
    """
    from backend.app.models import Seat, Hold, HoldSeat, SeatStatus, HoldStatus

    if now_dt is None:
        now_dt = datetime.utcnow()

    # Step 1: Input validation
    if not seat_ids:
        raise InvalidSeatRequestError("At least one seat must be specified", status_code=400)

    cleaned_ids = [str(s).strip().upper() for s in seat_ids if str(s).strip()]
    if not cleaned_ids:
        raise InvalidSeatRequestError("At least one seat must be specified", status_code=400)

    unique_seat_ids = list(dict.fromkeys(cleaned_ids))
    if len(unique_seat_ids) > 4:
        raise InvalidSeatRequestError("Maximum of 4 seats can be held at once", status_code=400)

    # Consistent locking order
    sorted_seat_ids = sorted(unique_seat_ids)

    try:
        # Step 2: Lock seat rows in consistent order using SELECT ... FOR UPDATE
        seats = (
            session.query(Seat)
            .filter(Seat.id.in_(sorted_seat_ids))
            .order_by(Seat.id.asc())
            .with_for_update()
            .all()
        )

        found_seat_map = {s.id: s for s in seats}
        missing = [sid for sid in sorted_seat_ids if sid not in found_seat_map]
        if missing:
            raise InvalidSeatRequestError(f"Invalid seat ID(s): {', '.join(missing)}", status_code=400)

        # Step 3: Check active holds on these seats with row locks
        active_holds = (
            session.query(Hold)
            .join(HoldSeat)
            .filter(HoldSeat.seat_id.in_(sorted_seat_ids), Hold.status == HoldStatus.ACTIVE)
            .with_for_update()
            .all()
        )

        active_held_seat_ids = set()
        for hold in active_holds:
            if hold.expires_at <= now_dt:
                hold.status = HoldStatus.EXPIRED
                for hs in hold.hold_seats:
                    if hs.seat and hs.seat.status == SeatStatus.HELD:
                        hs.seat.status = SeatStatus.AVAILABLE
            else:
                for hs in hold.hold_seats:
                    if hs.seat_id in sorted_seat_ids:
                        active_held_seat_ids.add(hs.seat_id)

        # Step 4: Verify that EVERY requested seat is currently AVAILABLE
        unavailable_seats = []
        for sid in sorted_seat_ids:
            seat = found_seat_map[sid]
            if seat.status == SeatStatus.BOOKED:
                unavailable_seats.append(sid)
            elif seat.status == SeatStatus.HELD or sid in active_held_seat_ids:
                unavailable_seats.append(sid)

        # All-or-nothing: if any seat is unavailable, rollback immediately!
        if unavailable_seats:
            session.rollback()
            raise SeatUnavailableError(
                f"One or more requested seats are unavailable: {', '.join(unavailable_seats)}",
                unavailable_seats=unavailable_seats,
            )

        # Step 5: All requested seats are available -> create hold atomically
        hold_token = uuid.uuid4().hex
        expires_at = now_dt + timedelta(minutes=5)

        hold = Hold(
            hold_token=hold_token,
            status=HoldStatus.ACTIVE,
            expires_at=expires_at,
        )
        session.add(hold)
        session.flush()

        for sid in sorted_seat_ids:
            seat = found_seat_map[sid]
            session.add(HoldSeat(hold_id=hold.id, seat_id=seat.id))
            seat.status = SeatStatus.HELD
            seat.version += 1

        session.commit()

        return {
            "id": hold.id,
            "hold_id": hold.id,
            "hold_token": hold_token,
            "seats": sorted_seat_ids,
            "expires_at": expires_at.isoformat() + "Z",
            "expires_in_seconds": 300,
            "status": "held",
            "user_id": user_id,
        }

    except HoldError:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        raise e

def cleanup_expired_holds_dbapi(
    conn_or_cursor,
    now_dt: Optional[datetime] = None,
) -> int:
    """
    Finds and cleans up all active holds whose 5-minute expiration time has passed.

    Transaction Safety:
    - Runs in a single transaction with exclusive locks.
    - Updates holds: status -> 'EXPIRED'.
    - Updates seats: reverts status from 'HELD' -> 'AVAILABLE' only for seats
      currently in 'HELD' state (never reverts 'BOOKED' seats).
    - Increments seat version and updates timestamp.
    - Commits transaction.
    - Returns the count of expired holds cleaned up.
    """
    if now_dt is None:
        now_dt = datetime.utcnow()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Determine connection and cursor
    if hasattr(conn_or_cursor, "cursor"):
        conn = conn_or_cursor
        cursor = conn.cursor()
    else:
        cursor = conn_or_cursor
        conn = getattr(cursor, "connection", None)

    is_sqlite = False
    if conn is not None and type(conn).__module__.startswith("sqlite3"):
        is_sqlite = True

    try:
        if conn and is_sqlite:
            try:
                cursor.execute("BEGIN IMMEDIATE")
            except Exception:
                pass

        for_update = "" if is_sqlite else " FOR UPDATE"
        cursor.execute(
            f"SELECT id, expires_at FROM holds WHERE status = 'ACTIVE'{for_update}"
        )
        rows = cursor.fetchall()
        expired_ids = []
        for r in rows:
            if isinstance(r, (tuple, list)):
                h_id, exp_val = r[0], r[1]
            else:
                h_id = r["id"]
                exp_val = r["expires_at"]

            if isinstance(exp_val, str):
                try:
                    exp_dt = datetime.fromisoformat(exp_val.replace("Z", "+00:00").split("+")[0])
                except ValueError:
                    exp_dt = datetime.strptime(exp_val[:19], "%Y-%m-%d %H:%M:%S")
            elif isinstance(exp_val, datetime):
                exp_dt = exp_val
            else:
                exp_dt = None

            if exp_dt and exp_dt <= now_dt:
                expired_ids.append(h_id)

        if not expired_ids:
            return 0

        placeholders = ",".join(["?"] * len(expired_ids))
        cursor.execute(
            f"UPDATE holds SET status = 'EXPIRED', updated_at = ? WHERE id IN ({placeholders})",
            [now_str] + expired_ids,
        )
        cursor.execute(
            f"""
            UPDATE seats 
            SET status = 'AVAILABLE', version = version + 1, updated_at = ? 
            WHERE status = 'HELD' 
              AND id IN (
                  SELECT seat_id FROM hold_seats WHERE hold_id IN ({placeholders})
              )
            """,
            [now_str] + expired_ids,
        )

        if conn:
            conn.commit()

        return len(expired_ids)
    except Exception as e:
        if conn:
            conn.rollback()
        raise e

def cleanup_expired_holds_orm(
    session,
    now_dt: Optional[datetime] = None,
) -> int:
    """
    Cleans up expired active holds using SQLAlchemy ORM with row locks and transaction safety.
    """
    from backend.app.models import Seat, Hold, HoldSeat, SeatStatus, HoldStatus

    if now_dt is None:
        now_dt = datetime.utcnow()

    try:
        expired_holds = (
            session.query(Hold)
            .filter(Hold.status == HoldStatus.ACTIVE, Hold.expires_at <= now_dt)
            .with_for_update()
            .all()
        )

        if not expired_holds:
            return 0

        expired_count = len(expired_holds)
        for hold in expired_holds:
            hold.status = HoldStatus.EXPIRED
            for hs in hold.hold_seats:
                if hs.seat and hs.seat.status == SeatStatus.HELD:
                    hs.seat.status = SeatStatus.AVAILABLE
                    hs.seat.version += 1

        session.commit()
        return expired_count
    except Exception as e:
        session.rollback()
        raise e

def confirm_hold_dbapi(
    conn_or_cursor,
    hold_token: str,
    user_id: str = "default_user",
    now_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Atomically confirms an active seat hold into a completed booking.

    Guarantees & Constraints:
    1. An expired hold (expires_at <= now or status == 'EXPIRED') CANNOT be confirmed.
       Raises HoldExpiredError (HTTP 400).
    2. Expired holds trigger cleanup reverting held seats to 'AVAILABLE'.
    3. Non-existent hold raises InvalidSeatRequestError (HTTP 404).
    4. Already confirmed hold raises HoldError (HTTP 400).
    5. Valid active hold creates a unique booking reference (BK-XXXXXXXX),
       associates seats in booking_seats, sets seat status to 'BOOKED',
       and sets hold status to 'CONFIRMED'.
    """
    if now_dt is None:
        now_dt = datetime.utcnow()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    if not hold_token or not str(hold_token).strip():
        raise InvalidSeatRequestError("Hold token must be specified", status_code=400)

    clean_token = str(hold_token).strip()

    if hasattr(conn_or_cursor, "cursor"):
        conn = conn_or_cursor
        cursor = conn.cursor()
    else:
        cursor = conn_or_cursor
        conn = getattr(cursor, "connection", None)

    is_sqlite = False
    if conn is not None and type(conn).__module__.startswith("sqlite3"):
        is_sqlite = True

    try:
        if conn and is_sqlite:
            try:
                cursor.execute("BEGIN IMMEDIATE")
            except Exception:
                pass

        for_update = "" if is_sqlite else " FOR UPDATE"
        cursor.execute(
            f"SELECT id, hold_token, status, expires_at FROM holds WHERE hold_token = ?{for_update}",
            (clean_token,),
        )
        row = cursor.fetchone()
        if not row:
            raise InvalidSeatRequestError(f"Hold not found for token: {clean_token}", status_code=404)

        if isinstance(row, (tuple, list)):
            hold_id, h_tok, h_status, h_expires_at = row[:4]
        else:
            hold_id = row["id"]
            h_tok = row["hold_token"]
            h_status = row["status"]
            h_expires_at = row["expires_at"]

        # Parse expires_at
        if isinstance(h_expires_at, str):
            try:
                exp_dt = datetime.fromisoformat(h_expires_at.replace("Z", "+00:00").split("+")[0])
            except ValueError:
                exp_dt = datetime.strptime(h_expires_at[:19], "%Y-%m-%d %H:%M:%S")
        elif isinstance(h_expires_at, datetime):
            exp_dt = h_expires_at
        else:
            exp_dt = None

        # Check expiration
        is_expired = False
        if str(h_status).upper() == "EXPIRED":
            is_expired = True
        elif exp_dt and exp_dt <= now_dt:
            is_expired = True

        if is_expired:
            # Clean up the expired hold and its seats
            cursor.execute(
                "UPDATE holds SET status = 'EXPIRED', updated_at = ? WHERE id = ?",
                (now_str, hold_id),
            )
            cursor.execute(
                """
                UPDATE seats 
                SET status = 'AVAILABLE', version = version + 1, updated_at = ? 
                WHERE status = 'HELD' 
                  AND id IN (
                      SELECT seat_id FROM hold_seats WHERE hold_id = ?
                  )
                """,
                (now_str, hold_id),
            )
            if conn:
                conn.commit()
            raise HoldExpiredError("Hold has expired and cannot be confirmed", status_code=400)

        if str(h_status).upper() == "CONFIRMED":
            raise HoldError("Hold has already been confirmed into a booking", status_code=400)

        if str(h_status).upper() == "RELEASED":
            raise HoldError("Hold has been released and cannot be confirmed", status_code=400)

        if str(h_status).upper() != "ACTIVE":
            raise HoldError(f"Hold is not active (status: {h_status})", status_code=400)

        # Retrieve and lock the associated seats
        cursor.execute(
            f"""
            SELECT hs.seat_id, s.status 
            FROM hold_seats hs 
            JOIN seats s ON hs.seat_id = s.id 
            WHERE hs.hold_id = ? 
            ORDER BY s.id ASC{for_update}
            """,
            (hold_id,),
        )
        seat_rows = cursor.fetchall()
        if not seat_rows:
            raise InvalidSeatRequestError("No seats associated with this hold", status_code=400)

        seat_ids = []
        for sr in seat_rows:
            sid = sr[0] if isinstance(sr, (tuple, list)) else sr["seat_id"]
            stat = sr[1] if isinstance(sr, (tuple, list)) else sr["status"]
            if str(stat).upper() != "HELD":
                raise SeatUnavailableError(
                    f"Seat {sid} is no longer held (status: {stat})",
                    unavailable_seats=[sid],
                )
            seat_ids.append(sid)

        # Check if booking already exists for this hold
        cursor.execute("SELECT id FROM bookings WHERE hold_id = ?", (hold_id,))
        if cursor.fetchone():
            raise HoldError("Booking already exists for this hold", status_code=400)

        # Create confirmed booking
        booking_reference = f"BK-{uuid.uuid4().hex[:8].upper()}"
        cursor.execute(
            """
            INSERT INTO bookings (booking_reference, hold_id, status, confirmed_at, created_at, updated_at) 
            VALUES (?, ?, 'CONFIRMED', ?, ?, ?)
            """,
            (booking_reference, hold_id, now_str, now_str, now_str),
        )
        booking_id = cursor.lastrowid

        for sid in seat_ids:
            cursor.execute(
                "INSERT INTO booking_seats (booking_id, seat_id, created_at) VALUES (?, ?, ?)",
                (booking_id, sid, now_str),
            )
            cursor.execute(
                "UPDATE seats SET status = 'BOOKED', version = version + 1, updated_at = ? WHERE id = ?",
                (now_str, sid),
            )

        # Mark hold as CONFIRMED
        cursor.execute(
            "UPDATE holds SET status = 'CONFIRMED', updated_at = ? WHERE id = ?",
            (now_str, hold_id),
        )

        if conn:
            conn.commit()

        return {
            "booking_reference": booking_reference,
            "hold_token": clean_token,
            "seats": seat_ids,
            "status": "confirmed",
            "confirmed_at": now_dt.isoformat() + "Z",
            "user_id": user_id,
        }

    except HoldError:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise e

def confirm_hold_orm(
    session,
    hold_token: str,
    user_id: str = "default_user",
    now_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Atomically confirms an active seat hold into a completed booking using SQLAlchemy ORM.
    """
    from backend.app.models import (
        Seat,
        Hold,
        HoldSeat,
        Booking,
        BookingSeat,
        SeatStatus,
        HoldStatus,
        BookingStatus,
    )

    if now_dt is None:
        now_dt = datetime.utcnow()

    if not hold_token or not str(hold_token).strip():
        raise InvalidSeatRequestError("Hold token must be specified", status_code=400)

    clean_token = str(hold_token).strip()

    try:
        hold = (
            session.query(Hold)
            .filter(Hold.hold_token == clean_token)
            .with_for_update()
            .first()
        )
        if not hold:
            raise InvalidSeatRequestError(f"Hold not found for token: {clean_token}", status_code=404)

        # Check expiration
        is_expired = False
        if hold.status == HoldStatus.EXPIRED:
            is_expired = True
        elif hold.expires_at <= now_dt:
            is_expired = True

        if is_expired:
            hold.status = HoldStatus.EXPIRED
            for hs in hold.hold_seats:
                if hs.seat and hs.seat.status == SeatStatus.HELD:
                    hs.seat.status = SeatStatus.AVAILABLE
                    hs.seat.version += 1
            session.commit()
            raise HoldExpiredError("Hold has expired and cannot be confirmed", status_code=400)

        if hold.status == HoldStatus.CONFIRMED:
            raise HoldError("Hold has already been confirmed into a booking", status_code=400)

        if hold.status == HoldStatus.RELEASED:
            raise HoldError("Hold has been released and cannot be confirmed", status_code=400)

        if hold.status != HoldStatus.ACTIVE:
            raise HoldError(f"Hold is not active (status: {hold.status})", status_code=400)

        # Verify and lock seats
        hold_seats = hold.hold_seats
        if not hold_seats:
            raise InvalidSeatRequestError("No seats associated with this hold", status_code=400)

        seat_ids = sorted([hs.seat_id for hs in hold_seats])
        seats = (
            session.query(Seat)
            .filter(Seat.id.in_(seat_ids))
            .order_by(Seat.id.asc())
            .with_for_update()
            .all()
        )

        for s in seats:
            if s.status != SeatStatus.HELD:
                raise SeatUnavailableError(
                    f"Seat {s.id} is no longer held (status: {s.status})",
                    unavailable_seats=[s.id],
                )

        # Create booking
        booking_reference = f"BK-{uuid.uuid4().hex[:8].upper()}"
        booking = Booking(
            booking_reference=booking_reference,
            hold_id=hold.id,
            status=BookingStatus.CONFIRMED,
            confirmed_at=now_dt,
        )
        session.add(booking)
        session.flush()

        for s in seats:
            session.add(BookingSeat(booking_id=booking.id, seat_id=s.id))
            s.status = SeatStatus.BOOKED
            s.version += 1

        hold.status = HoldStatus.CONFIRMED
        session.commit()

        return {
            "booking_reference": booking_reference,
            "hold_token": clean_token,
            "seats": seat_ids,
            "status": "confirmed",
            "confirmed_at": now_dt.isoformat() + "Z",
            "user_id": user_id,
        }

    except HoldError:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        raise e

def release_hold_dbapi(
    conn_or_cursor,
    hold_identifier: str,
    now_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Atomically releases an active hold, making all its associated seats available again.

    Guarantees & Invariants:
    1. Transactional safety: runs in a single transaction with row-level locks.
    2. Idempotency & validation:
       - Invalid/non-existent hold raises HoldNotFoundError (HTTP 404).
       - Already released hold raises HoldAlreadyReleasedError (HTTP 400).
       - Already confirmed hold raises HoldError (HTTP 400).
       - Expired hold raises HoldExpiredError (HTTP 400).
    3. Releasing an active hold transitions hold status to 'RELEASED'.
    4. Only seats belonging to this specific hold that are currently 'HELD' are reverted to 'AVAILABLE'.
       Seats belonging to any other hold or already booked seats are NEVER modified.
    5. A released hold cannot later be confirmed into a booking.
    """
    if now_dt is None:
        now_dt = datetime.utcnow()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    if not hold_identifier or not str(hold_identifier).strip():
        raise HoldNotFoundError("Hold identifier must be specified", status_code=404)

    clean_id = str(hold_identifier).strip()

    if hasattr(conn_or_cursor, "cursor"):
        conn = conn_or_cursor
        cursor = conn.cursor()
    else:
        cursor = conn_or_cursor
        conn = getattr(cursor, "connection", None)

    is_sqlite = False
    if conn is not None and type(conn).__module__.startswith("sqlite3"):
        is_sqlite = True

    try:
        if conn and is_sqlite:
            try:
                cursor.execute("BEGIN IMMEDIATE")
            except Exception:
                pass

        for_update = "" if is_sqlite else " FOR UPDATE"

        is_numeric = clean_id.isdigit()
        if is_numeric:
            cursor.execute(
                f"SELECT id, hold_token, status, expires_at FROM holds WHERE id = ? OR hold_token = ?{for_update}",
                (int(clean_id), clean_id),
            )
        else:
            cursor.execute(
                f"SELECT id, hold_token, status, expires_at FROM holds WHERE hold_token = ?{for_update}",
                (clean_id,),
            )

        row = cursor.fetchone()
        if not row:
            raise HoldNotFoundError(f"Hold not found for identifier: {clean_id}", status_code=404)

        if isinstance(row, (tuple, list)):
            hold_id, h_tok, h_status, h_expires_at = row[:4]
        else:
            hold_id = row["id"]
            h_tok = row["hold_token"]
            h_status = row["status"]
            h_expires_at = row["expires_at"]

        # Parse expires_at if string
        if isinstance(h_expires_at, str):
            try:
                exp_dt = datetime.fromisoformat(h_expires_at.replace("Z", "+00:00").split("+")[0])
            except ValueError:
                exp_dt = datetime.strptime(h_expires_at[:19], "%Y-%m-%d %H:%M:%S")
        elif isinstance(h_expires_at, datetime):
            exp_dt = h_expires_at
        else:
            exp_dt = None

        status_upper = str(h_status).upper()
        if status_upper == "RELEASED":
            raise HoldAlreadyReleasedError(f"Hold {clean_id} has already been released", status_code=400)

        if status_upper == "CONFIRMED":
            raise HoldError(f"Hold {clean_id} has already been confirmed and cannot be released", status_code=400)

        if status_upper == "EXPIRED" or (exp_dt and exp_dt <= now_dt):
            cursor.execute("UPDATE holds SET status = 'EXPIRED', updated_at = ? WHERE id = ?", (now_str, hold_id))
            cursor.execute(
                """
                UPDATE seats 
                SET status = 'AVAILABLE', version = version + 1, updated_at = ? 
                WHERE status = 'HELD' 
                  AND id IN (
                      SELECT seat_id FROM hold_seats WHERE hold_id = ?
                  )
                """,
                (now_str, hold_id),
            )
            if conn:
                conn.commit()
            raise HoldExpiredError(f"Hold {clean_id} has expired and cannot be released", status_code=400)

        if status_upper != "ACTIVE":
            raise HoldError(f"Hold {clean_id} is not active (status: {h_status})", status_code=400)

        # Retrieve the seat IDs specifically belonging to this hold
        cursor.execute(
            f"""
            SELECT hs.seat_id, s.status 
            FROM hold_seats hs
            JOIN seats s ON hs.seat_id = s.id
            WHERE hs.hold_id = ?
            ORDER BY s.id ASC{for_update}
            """,
            (hold_id,),
        )
        seat_rows = cursor.fetchall()
        held_seat_ids = []
        for sr in seat_rows:
            sid = sr[0] if isinstance(sr, (tuple, list)) else sr["seat_id"]
            stat = sr[1] if isinstance(sr, (tuple, list)) else sr["status"]
            if str(stat).upper() == "HELD":
                held_seat_ids.append(sid)

        # Update seat statuses to AVAILABLE strictly for this hold's seats
        if held_seat_ids:
            placeholders = ",".join(["?"] * len(held_seat_ids))
            cursor.execute(
                f"""
                UPDATE seats 
                SET status = 'AVAILABLE', version = version + 1, updated_at = ? 
                WHERE status = 'HELD' AND id IN ({placeholders})
                """,
                [now_str] + held_seat_ids,
            )

        # Mark hold as RELEASED
        cursor.execute(
            "UPDATE holds SET status = 'RELEASED', updated_at = ? WHERE id = ?",
            (now_str, hold_id),
        )

        if conn:
            conn.commit()

        return {
            "message": "Hold successfully released",
            "hold_id": hold_id,
            "hold_token": h_tok,
            "status": "released",
            "released_seats": held_seat_ids,
        }

    except HoldError:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise e

def release_hold_orm(
    session,
    hold_identifier: str,
    now_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Atomically releases an active hold using SQLAlchemy ORM.
    """
    from backend.app.models import (
        Seat,
        Hold,
        HoldSeat,
        SeatStatus,
        HoldStatus,
    )
    from sqlalchemy import or_

    if now_dt is None:
        now_dt = datetime.utcnow()

    if not hold_identifier or not str(hold_identifier).strip():
        raise HoldNotFoundError("Hold identifier must be specified", status_code=404)

    clean_id = str(hold_identifier).strip()

    try:
        query = session.query(Hold)
        if clean_id.isdigit():
            query = query.filter(or_(Hold.id == int(clean_id), Hold.hold_token == clean_id))
        else:
            query = query.filter(Hold.hold_token == clean_id)

        hold = query.with_for_update().first()
        if not hold:
            raise HoldNotFoundError(f"Hold not found for identifier: {clean_id}", status_code=404)

        if hold.status == HoldStatus.RELEASED:
            raise HoldAlreadyReleasedError(f"Hold {clean_id} has already been released", status_code=400)

        if hold.status == HoldStatus.CONFIRMED:
            raise HoldError(f"Hold {clean_id} has already been confirmed and cannot be released", status_code=400)

        # Check expiration
        is_expired = False
        if hold.status == HoldStatus.EXPIRED:
            is_expired = True
        elif hold.expires_at <= now_dt:
            is_expired = True

        if is_expired:
            hold.status = HoldStatus.EXPIRED
            for hs in hold.hold_seats:
                if hs.seat and hs.seat.status == SeatStatus.HELD:
                    hs.seat.status = SeatStatus.AVAILABLE
                    hs.seat.version += 1
            session.commit()
            raise HoldExpiredError(f"Hold {clean_id} has expired and cannot be released", status_code=400)

        if hold.status != HoldStatus.ACTIVE:
            raise HoldError(f"Hold {clean_id} is not active (status: {hold.status})", status_code=400)

        # Revert seats to AVAILABLE strictly for this hold
        released_seats = []
        for hs in hold.hold_seats:
            if hs.seat and hs.seat.status == SeatStatus.HELD:
                hs.seat.status = SeatStatus.AVAILABLE
                hs.seat.version += 1
                released_seats.append(hs.seat.id)

        hold.status = HoldStatus.RELEASED
        session.commit()

        return {
            "message": "Hold successfully released",
            "hold_id": hold.id,
            "hold_token": hold.hold_token,
            "status": "released",
            "released_seats": sorted(released_seats),
        }

    except HoldError:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        raise e


