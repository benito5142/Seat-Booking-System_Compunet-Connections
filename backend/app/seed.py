import logging
from sqlalchemy import text
from backend.app.database import engine, Base
from backend.app.models import Seat

logger = logging.getLogger("seat_booking.seed")

ROW_LABELS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
SEATS_PER_ROW = 12
TOTAL_SEATS = 120


def seed_seats():
    """Initializes tables and seeds the 120 predefined seats if not present."""
    logger.info("Initializing database schema...")
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM seats"))
        count = result.scalar()
        if count == 0:
            logger.info(f"Seeding {TOTAL_SEATS} seats...")
            values = []
            for row in ROW_LABELS:
                for num in range(1, SEATS_PER_ROW + 1):
                    seat_id = f"{row}{num}"
                    values.append({
                        "id": seat_id,
                        "row_label": row,
                        "seat_number": num,
                        "status": "available",
                    })
            
            insert_stmt = text(
                "INSERT INTO seats (id, row_label, seat_number, status) "
                "VALUES (:id, :row_label, :seat_number, :status)"
            )
            conn.execute(insert_stmt, values)
            conn.commit()
            logger.info(f"Successfully seeded {len(values)} seats.")
        else:
            logger.info(f"Database already contains {count} seats.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_seats()
