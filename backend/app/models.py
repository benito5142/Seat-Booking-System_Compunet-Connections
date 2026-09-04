import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from backend.app.database import Base

class Seat(Base):
    __tablename__ = "seats"

    id = Column(String(10), primary_key=True, index=True)
    row_letter = Column(String(5), nullable=False)
    seat_number = Column(Integer, nullable=False)
    status = Column(
        SQLEnum("available", "held", "booked", name="seat_status_enum"),
        nullable=False,
        default="available",
        index=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint("row_letter", "seat_number", name="uq_seat_row_number"),
    )

    hold_associations = relationship("HoldSeat", back_populates="seat", cascade="all, delete-orphan")
    booking_associations = relationship("BookingSeat", back_populates="seat", cascade="all, delete-orphan")

class Hold(Base):
    __tablename__ = "holds"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    hold_token = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(100), nullable=False, default="default_user")
    status = Column(
        SQLEnum("ACTIVE", "RELEASED", "EXPIRED", "CONFIRMED", name="hold_status_enum"),
        nullable=False,
        default="ACTIVE",
        index=True,
    )
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    hold_seats = relationship("HoldSeat", back_populates="hold", cascade="all, delete-orphan")
    booking = relationship("Booking", back_populates="hold", uselist=False)

class HoldSeat(Base):
    __tablename__ = "hold_seats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hold_id = Column(Integer, ForeignKey("holds.id", ondelete="CASCADE"), nullable=False)
    seat_id = Column(String(10), ForeignKey("seats.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("hold_id", "seat_id", name="uq_hold_seat"),
    )

    hold = relationship("Hold", back_populates="hold_seats")
    seat = relationship("Seat", back_populates="hold_associations")

class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    booking_reference = Column(String(64), unique=True, nullable=False, index=True)
    hold_id = Column(Integer, ForeignKey("holds.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(String(100), nullable=False, default="default_user")
    status = Column(
        SQLEnum("confirmed", "cancelled", name="booking_status_enum"),
        nullable=False,
        default="confirmed",
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    hold = relationship("Hold", back_populates="booking")
    booking_seats = relationship("BookingSeat", back_populates="booking", cascade="all, delete-orphan")

class BookingSeat(Base):
    __tablename__ = "booking_seats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    seat_id = Column(String(10), ForeignKey("seats.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("booking_id", "seat_id", name="uq_booking_seat"),
    )

    booking = relationship("Booking", back_populates="booking_seats")
    seat = relationship("Seat", back_populates="booking_associations")
