import enum
from datetime import datetime

class SeatStatus(str, enum.Enum):
    """Lifecycle status of a seat."""
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    BOOKED = "BOOKED"

class HoldStatus(str, enum.Enum):
    """Lifecycle status of a temporary seat hold."""
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    CONFIRMED = "CONFIRMED"

class BookingStatus(str, enum.Enum):
    """Lifecycle status of a confirmed booking."""
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"

try:
    from sqlalchemy import (
        Column,
        Integer,
        String,
        DateTime,
        ForeignKey,
        Enum as SQLEnum,
        UniqueConstraint,
        Index,
    )
    from sqlalchemy.orm import relationship
    from backend.app.database import Base

    class Seat(Base):
        """
        Represents an individual physical seat for the event.
        There are exactly 120 seats: 10 rows (A-J) x 12 seats (1-12).
        """
        __tablename__ = "seats"

        id = Column(String(10), primary_key=True)  # e.g., 'A1', 'A2', ..., 'J12'
        row_label = Column(String(2), nullable=False)  # 'A' through 'J'
        seat_number = Column(Integer, nullable=False)  # 1 through 12
        status = Column(
            SQLEnum(SeatStatus),
            nullable=False,
            default=SeatStatus.AVAILABLE,
            server_default=SeatStatus.AVAILABLE.value,
        )
        # Optimistic concurrency control version counter
        version = Column(Integer, nullable=False, default=0, server_default="0")
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
        updated_at = Column(
            DateTime,
            nullable=False,
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
        )

        # Relationships
        hold_seats = relationship("HoldSeat", back_populates="seat")
        booking_seat = relationship("BookingSeat", back_populates="seat", uselist=False)

        __table_args__ = (
            UniqueConstraint("row_label", "seat_number", name="uq_seats_row_seat"),
            Index("idx_seats_status", "status"),
        )

        def __repr__(self) -> str:
            return f"<Seat id='{self.id}' status='{self.status}'>"

    class Hold(Base):
        """
        Represents a temporary reservation for one or more seats with a 5-minute TTL.
        """
        __tablename__ = "holds"

        id = Column(Integer, primary_key=True, autoincrement=True)
        hold_token = Column(String(64), nullable=False, unique=True, index=True)
        status = Column(
            SQLEnum(HoldStatus),
            nullable=False,
            default=HoldStatus.ACTIVE,
            server_default=HoldStatus.ACTIVE.value,
        )
        expires_at = Column(DateTime, nullable=False)
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
        updated_at = Column(
            DateTime,
            nullable=False,
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
        )

        # Relationships
        hold_seats = relationship(
            "HoldSeat",
            back_populates="hold",
            cascade="all, delete-orphan",
        )
        booking = relationship("Booking", back_populates="hold", uselist=False)

        __table_args__ = (
            Index("idx_holds_status_expires", "status", "expires_at"),
        )

        def __repr__(self) -> str:
            return f"<Hold id={self.id} token='{self.hold_token}' status='{self.status}'>"

    class HoldSeat(Base):
        """
        Associates held seats with a temporary hold.
        Prevents duplicate seat entries within the same hold session.
        """
        __tablename__ = "hold_seats"

        id = Column(Integer, primary_key=True, autoincrement=True)
        hold_id = Column(
            Integer,
            ForeignKey("holds.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
        seat_id = Column(
            String(10),
            ForeignKey("seats.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

        # Relationships
        hold = relationship("Hold", back_populates="hold_seats")
        seat = relationship("Seat", back_populates="hold_seats")

        __table_args__ = (
            UniqueConstraint("hold_id", "seat_id", name="uq_hold_seats_hold_seat"),
        )

        def __repr__(self) -> str:
            return f"<HoldSeat hold_id={self.hold_id} seat_id='{self.seat_id}'>"

    class Booking(Base):
        """
        Represents a confirmed reservation with a unique human-readable booking reference.
        """
        __tablename__ = "bookings"

        id = Column(Integer, primary_key=True, autoincrement=True)
        booking_reference = Column(String(32), nullable=False, unique=True, index=True)
        # UNIQUE hold_id constraint prevents the same hold from ever being confirmed twice
        hold_id = Column(
            Integer,
            ForeignKey("holds.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        )
        status = Column(
            SQLEnum(BookingStatus),
            nullable=False,
            default=BookingStatus.CONFIRMED,
            server_default=BookingStatus.CONFIRMED.value,
        )
        confirmed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
        updated_at = Column(
            DateTime,
            nullable=False,
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
        )

        # Relationships
        hold = relationship("Hold", back_populates="booking")
        booking_seats = relationship(
            "BookingSeat",
            back_populates="booking",
            cascade="all, delete-orphan",
        )

        __table_args__ = (
            Index("idx_bookings_status", "status"),
        )

        def __repr__(self) -> str:
            return f"<Booking id={self.id} ref='{self.booking_reference}'>"

    class BookingSeat(Base):
        """
        Associates confirmed booked seats with a booking.
        CRITICAL CONCURRENCY INVARIANT:
        `seat_id` has a UNIQUE constraint across all booking_seats.
        Since this is a single event, a seat can only be booked at most once.
        The database engine will reject any concurrent attempt to double-book a seat.
        """
        __tablename__ = "booking_seats"

        id = Column(Integer, primary_key=True, autoincrement=True)
        booking_id = Column(
            Integer,
            ForeignKey("bookings.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
        # UNIQUE constraint on seat_id guarantees database-level prevention of double booking
        seat_id = Column(
            String(10),
            ForeignKey("seats.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
            index=True,
        )
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

        # Relationships
        booking = relationship("Booking", back_populates="booking_seats")
        seat = relationship("Seat", back_populates="booking_seat")

        __table_args__ = (
            UniqueConstraint("booking_id", "seat_id", name="uq_booking_seats_booking_seat"),
        )

        def __repr__(self) -> str:
            return f"<BookingSeat booking_id={self.booking_id} seat_id='{self.seat_id}'>"

except ImportError:
    Seat = None
    Hold = None
    HoldSeat = None
    Booking = None
    BookingSeat = None
