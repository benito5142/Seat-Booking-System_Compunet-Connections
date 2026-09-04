from sqlalchemy.orm import Session
from backend.app.database import SessionLocal, engine, Base
from backend.app.models import Seat
from backend.app.seats_service import VALID_ROWS, SEATS_PER_ROW

def seed_seats(db: Session) -> int:
    """
    Seeds exactly 120 seats: A1-A12 through J1-J12.
    Idempotent: inserts missing seats, preserves existing ones.
    """
    existing_seats = {s.id: s for s in db.query(Seat).all()}
    created_count = 0

    for row in VALID_ROWS:
        for num in range(1, SEATS_PER_ROW + 1):
            seat_id = f"{row}{num}"
            if seat_id not in existing_seats:
                new_seat = Seat(
                    id=seat_id,
                    row_letter=row,
                    seat_number=num,
                    status="available",
                )
                db.add(new_seat)
                created_count += 1

    if created_count > 0:
        db.commit()

    return created_count

def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        count = seed_seats(db)
        total = db.query(Seat).count()
        print(f"Seeded {count} new seats. Total seats in database: {total}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
