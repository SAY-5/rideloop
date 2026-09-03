"""SQLAlchemy 2.x schema for trips, drivers and the ride event audit trail."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from rideloop_common.config import Settings, get_settings
from rideloop_common.models import TripStatus

TRIP_STATUS_ENUM = Enum(
    TripStatus,
    name="trip_status",
    values_callable=lambda enum: [member.value for member in enum],
)


class Base(DeclarativeBase):
    pass


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="available")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pickup_lat: Mapped[float] = mapped_column(nullable=False)
    pickup_lng: Mapped[float] = mapped_column(nullable=False)
    dropoff_lat: Mapped[float] = mapped_column(nullable=False)
    dropoff_lng: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[TripStatus] = mapped_column(
        TRIP_STATUS_ENUM, nullable=False, default=TripStatus.REQUESTED
    )
    driver_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    match_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pickup_eta_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dispatch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    events: Mapped[list[RideEvent]] = relationship(
        back_populates="trip", cascade="all, delete-orphan", order_by="RideEvent.at"
    )

    __table_args__ = (
        Index("ix_trips_status", "status"),
        Index("ix_trips_requested_at", "requested_at"),
        Index("ix_trips_status_next_attempt", "status", "next_attempt_at"),
    )


class RideEvent(Base):
    __tablename__ = "ride_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    trip: Mapped[Trip] = relationship(back_populates="events")

    __table_args__ = (Index("ix_ride_events_trip_id", "trip_id"),)


def make_engine(settings: Settings | None = None, **kwargs) -> Engine:
    settings = settings or get_settings()
    kwargs.setdefault("pool_pre_ping", True)
    kwargs.setdefault("pool_size", 10)
    kwargs.setdefault("max_overflow", 20)
    return create_engine(settings.database_url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
