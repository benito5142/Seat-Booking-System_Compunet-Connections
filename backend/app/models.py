from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from backend.app.database import Base


class Seat(Base):
    __tablename__ = "seats"

    id = Column(String(10), primary_key=True)  # e.g., 'A1', 'B12'
    row_label = Column(String(5), nullable=False)
    seat_number = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="available")  # 'available', 'held', 'booked'
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_seats_status", "status"),
        Index("idx_seats_row_num", "row_label", "seat_number"),
    )

    @property
    def row(self) -> str:
        return self.row_label

    def to_dict(self):
        return {
            "id": self.id,
            "row": self.row_label,
            "seat_number": self.seat_number,
            "status": self.status,
        }


class Hold(Base):
    __tablename__ = "holds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hold_token = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(String(100), nullable=False, default="default_user")
    status = Column(String(20), nullable=False, default="ACTIVE")  # 'ACTIVE', 'RELEASED', 'EXPIRED', 'CONFIRMED'
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    hold_seats = relationship("HoldSeat", back_populates="hold", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_holds_status_expires", "status", "expires_at"),
    )

    @property
    def seats(self):
        return [hs.seat_id for hs in self.hold_seats]


class HoldSeat(Base):
    __tablename__ = "hold_seats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hold_id = Column(Integer, ForeignKey("holds.id", ondelete="CASCADE"), nullable=False)
    seat_id = Column(String(10), ForeignKey("seats.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    hold = relationship("Hold", back_populates="hold_seats")
    seat = relationship("Seat")

    __table_args__ = (
        UniqueConstraint("hold_id", "seat_id", name="uq_hold_seat"),
        Index("idx_hold_seats_seat", "seat_id"),
    )


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    booking_reference = Column(String(64), nullable=False, unique=True, index=True)
    hold_id = Column(Integer, ForeignKey("holds.id"), nullable=False)
    user_id = Column(String(100), nullable=False, default="default_user")
    status = Column(String(20), nullable=False, default="confirmed")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    hold = relationship("Hold")
    booking_seats = relationship("BookingSeat", back_populates="booking", cascade="all, delete-orphan")

    @property
    def seats(self):
        return [bs.seat_id for bs in self.booking_seats]


class BookingSeat(Base):
    __tablename__ = "booking_seats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    seat_id = Column(String(10), ForeignKey("seats.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    booking = relationship("Booking", back_populates="booking_seats")
    seat = relationship("Seat")

    __table_args__ = (
        UniqueConstraint("booking_id", "seat_id", name="uq_booking_seat"),
        Index("idx_booking_seats_seat", "seat_id"),
    )
