"""Pydantic models shared across the services and the simulators."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class TripStatus(StrEnum):
    REQUESTED = "requested"
    MATCHED = "matched"
    EN_ROUTE = "en_route"
    ARRIVED = "arrived"
    IN_TRIP = "in_trip"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DriverStatus(StrEnum):
    AVAILABLE = "available"
    BUSY = "busy"
    OFFLINE = "offline"


class Coordinate(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)


class RideRequest(BaseModel):
    """Payload a rider submits to request a trip."""

    model_config = ConfigDict(extra="forbid")

    rider_id: str = Field(min_length=1, max_length=64)
    pickup: Coordinate
    dropoff: Coordinate


class PositionUpdate(BaseModel):
    """Payload a driver client posts once a second."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    heading: float = Field(default=0.0, ge=0.0, lt=360.0)


class DriverPosition(BaseModel):
    """A driver's last known position as stored in DynamoDB."""

    driver_id: str
    cell: str
    geohash: str
    lat: float
    lng: float
    heading: float = 0.0
    status: DriverStatus = DriverStatus.AVAILABLE
    trip_id: str | None = None
    speed_mps: float = 0.0
    updated_at: datetime
    ttl: int


class NearbyDriver(DriverPosition):
    distance_m: float


class TripEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event: str
    at: datetime


class Trip(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rider_id: str
    pickup_lat: float
    pickup_lng: float
    dropoff_lat: float
    dropoff_lng: float
    status: TripStatus
    driver_id: str | None = None
    requested_at: datetime
    matched_at: datetime | None = None
    arrived_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    match_latency_ms: int | None = None
    pickup_eta_s: int | None = None
    dispatch_attempts: int = 0


class DriverLocation(BaseModel):
    """Where the assigned driver is right now, as reported by the location service."""

    lat: float
    lng: float
    heading: float
    speed_mps: float
    distance_to_pickup_m: float
    updated_at: datetime


class TripDetail(Trip):
    events: list[TripEvent] = Field(default_factory=list)
    driver_position: DriverLocation | None = None


class DispatchStats(BaseModel):
    matched_total: int
    pending: int
    matches_last_minute: int
    matches_per_minute: float
    p50_match_latency_ms: float | None
    p95_match_latency_ms: float | None
    sweeps: int
    uptime_s: float
