from typing import List, Dict, Any

ROW_LABELS: List[str] = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
SEATS_PER_ROW: int = 12
TOTAL_SEATS: int = len(ROW_LABELS) * SEATS_PER_ROW  # 10 x 12 = 120

def generate_seat_definitions() -> List[Dict[str, Any]]:
    """
    Generates predictable seat definitions for the 120-seat fixed venue:
    Rows A through J (10 rows), seats 1 through 12 per row (A1-A12, ..., J1-J12).
    """
    seats_data = []
    for row in ROW_LABELS:
        for seat_num in range(1, SEATS_PER_ROW + 1):
            seat_id = f"{row}{seat_num}"
            seats_data.append({
                "id": seat_id,
                "row_label": row,
                "seat_number": seat_num,
                "status": "AVAILABLE",
                "version": 0,
            })
    return seats_data

def seed_seats_dbapi(cursor) -> int:
    """
    Seeds seats using standard Python DB-API cursor (e.g. sqlite3 or pymysql).
    Returns count of inserted seats.
    """
    cursor.execute("SELECT COUNT(*) FROM seats")
    row = cursor.fetchone()
    count = row[0] if row else 0
    if count >= TOTAL_SEATS:
        return 0

    inserted = 0
    seats_data = generate_seat_definitions()
    for seat in seats_data:
        cursor.execute(
            "INSERT OR IGNORE INTO seats (id, row_label, seat_number, status, version) VALUES (?, ?, ?, ?, ?)",
            (seat["id"], seat["row_label"], seat["seat_number"], seat["status"], seat["version"]),
        )
        inserted += 1
    return inserted

def seed_seats(db) -> int:
    """
    Seeds the database with exactly 120 seats using an active SQLAlchemy Session.
    Returns the count of seats seeded.
    """
    try:
        from backend.app.models import Seat, SeatStatus
        existing_count = db.query(Seat).count()
        if existing_count >= TOTAL_SEATS:
            return 0

        seats_data = generate_seat_definitions()
        created_count = 0
        for data in seats_data:
            existing = db.query(Seat).filter(Seat.id == data["id"]).first()
            if not existing:
                seat = Seat(
                    id=data["id"],
                    row_label=data["row_label"],
                    seat_number=data["seat_number"],
                    status=SeatStatus.AVAILABLE,
                    version=data["version"],
                )
                db.add(seat)
                created_count += 1
        db.commit()
        return created_count
    except ImportError:
        return 0

if __name__ == "__main__":
    from backend.app.database import engine, SessionLocal, Base
    if engine and Base and SessionLocal:
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            count = seed_seats(session)
            print(f"Seeded {count} seats.")
    else:
        print("Database engine not initialized. Please ensure dependencies are installed.")
