"""Trip persistence shared by the ride_request and dispatch services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from rideloop_common.db import Driver, RideEvent, Trip
from rideloop_common.eta import eta_to_point
from rideloop_common.geo import manhattan_m
from rideloop_common.models import RideRequest, TripStatus

# Within this route distance of the pickup or dropoff the driver counts as there.
ARRIVAL_RADIUS_M = 40.0
# Once an arrived driver is this far from the pickup again the rider is aboard.
DEPART_RADIUS_M = 120.0

# States in which the driver is still on the way to the rider.
APPROACHING = {TripStatus.MATCHED, TripStatus.EN_ROUTE}
# States in which a driver is assigned and the trip is not over.
ACTIVE = {TripStatus.MATCHED, TripStatus.EN_ROUTE, TripStatus.ARRIVED, TripStatus.IN_TRIP}


class TripNotFound(LookupError):
    pass


class InvalidTransition(ValueError):
    pass


def create_trip(
    session: Session,
    request: RideRequest,
    now: datetime | None = None,
    pickup_cell: str | None = None,
    surge_multiplier: float = 1.0,
) -> Trip:
    """Insert a trip in ``requested`` state. The row itself is the dispatch queue entry."""
    now = now or datetime.now(UTC)
    trip = Trip(
        id=uuid.uuid4(),
        rider_id=request.rider_id,
        pickup_lat=request.pickup.lat,
        pickup_lng=request.pickup.lng,
        dropoff_lat=request.dropoff.lat,
        dropoff_lng=request.dropoff.lng,
        status=TripStatus.REQUESTED,
        requested_at=now,
        next_attempt_at=now,
        pickup_cell=pickup_cell,
        surge_multiplier=surge_multiplier,
    )
    trip.events.append(RideEvent(event="requested", at=now))
    session.add(trip)
    session.flush()
    return trip


def get_trip(session: Session, trip_id: uuid.UUID) -> Trip:
    trip = session.scalar(select(Trip).options(selectinload(Trip.events)).where(Trip.id == trip_id))
    if trip is None:
        raise TripNotFound(f"trip {trip_id} not found")
    return trip


def list_trips(session: Session, status: TripStatus | None = None, limit: int = 50) -> list[Trip]:
    query = select(Trip).options(selectinload(Trip.events)).order_by(Trip.requested_at.desc())
    if status is not None:
        query = query.where(Trip.status == status)
    return list(session.scalars(query.limit(limit)))


def claim_pending(session: Session, batch_size: int, now: datetime | None = None) -> list[Trip]:
    """Lock a batch of requested trips for this dispatcher.

    ``FOR UPDATE SKIP LOCKED`` lets several dispatcher processes sweep the same
    table without handing the same trip to two of them.
    """
    now = now or datetime.now(UTC)
    query = (
        select(Trip)
        .where(Trip.status == TripStatus.REQUESTED, Trip.next_attempt_at <= now)
        .order_by(Trip.requested_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    return list(session.scalars(query))


def mark_matched(session: Session, trip: Trip, driver_id: str, now: datetime | None = None) -> Trip:
    now = now or datetime.now(UTC)
    if trip.status != TripStatus.REQUESTED:
        raise InvalidTransition(f"trip {trip.id} is {trip.status.value}, not requested")
    trip.status = TripStatus.MATCHED
    trip.driver_id = driver_id
    trip.matched_at = now
    trip.match_latency_ms = int((now - trip.requested_at).total_seconds() * 1000)
    trip.dispatch_attempts += 1
    session.add(RideEvent(trip_id=trip.id, event="matched", at=now))
    _mirror_driver_status(session, driver_id, "busy")
    return trip


def defer_trip(session: Session, trip: Trip, retry_after: timedelta, now: datetime | None = None):
    """No driver was found; leave the trip requested and retry a little later."""
    now = now or datetime.now(UTC)
    trip.dispatch_attempts += 1
    trip.next_attempt_at = now + retry_after
    session.add(RideEvent(trip_id=trip.id, event="no_driver", at=now))


def transition(
    session: Session, trip: Trip, target: TripStatus, now: datetime | None = None
) -> Trip:
    """Apply a rider-side transition (en_route, completed, cancelled)."""
    now = now or datetime.now(UTC)
    allowed = {
        TripStatus.EN_ROUTE: {TripStatus.MATCHED},
        TripStatus.COMPLETED: ACTIVE,
        TripStatus.CANCELLED: (ACTIVE - {TripStatus.IN_TRIP}) | {TripStatus.REQUESTED},
    }
    if target not in allowed or trip.status not in allowed[target]:
        raise InvalidTransition(f"cannot move trip {trip.id} from {trip.status.value} to {target}")
    _set_status(session, trip, target, now)
    return trip


def _set_status(session: Session, trip: Trip, target: TripStatus, now: datetime) -> None:
    trip.status = target
    if target == TripStatus.ARRIVED:
        trip.arrived_at = now
        trip.pickup_eta_s = 0
    elif target == TripStatus.IN_TRIP:
        trip.started_at = now
    elif target in (TripStatus.COMPLETED, TripStatus.CANCELLED):
        trip.completed_at = now
        if trip.driver_id:
            _mirror_driver_status(session, trip.driver_id, "available")
    trip.events.append(RideEvent(event=target.value, at=now))


def advance_from_position(
    session: Session,
    trip: Trip,
    lat: float,
    lng: float,
    speed_mps: float,
    now: datetime | None = None,
) -> TripStatus | None:
    """Move the trip along from where its driver just reported being.

    matched -> en_route on the first ping after the match, en_route -> arrived
    inside ARRIVAL_RADIUS_M of the pickup, arrived -> in_trip once the car has
    pulled DEPART_RADIUS_M away from it, in_trip -> completed inside
    ARRIVAL_RADIUS_M of the dropoff. Returns the new status, or None if the
    ping did not change anything. The pickup ETA is refreshed while approaching.
    """
    now = now or datetime.now(UTC)
    to_pickup = manhattan_m(lat, lng, trip.pickup_lat, trip.pickup_lng)
    to_dropoff = manhattan_m(lat, lng, trip.dropoff_lat, trip.dropoff_lng)
    target: TripStatus | None = None
    if trip.status == TripStatus.MATCHED:
        target = TripStatus.ARRIVED if to_pickup <= ARRIVAL_RADIUS_M else TripStatus.EN_ROUTE
    elif trip.status == TripStatus.EN_ROUTE and to_pickup <= ARRIVAL_RADIUS_M:
        target = TripStatus.ARRIVED
    elif trip.status == TripStatus.ARRIVED and to_pickup >= DEPART_RADIUS_M:
        target = TripStatus.IN_TRIP
    elif trip.status == TripStatus.IN_TRIP and to_dropoff <= ARRIVAL_RADIUS_M:
        target = TripStatus.COMPLETED

    if target is TripStatus.EN_ROUTE or (target is None and trip.status in APPROACHING):
        _, trip.pickup_eta_s = eta_to_point(lat, lng, trip.pickup_lat, trip.pickup_lng, speed_mps)
    if target is None:
        return None
    if target == TripStatus.ARRIVED and trip.status == TripStatus.MATCHED:
        # a driver that was already at the pickup skips straight past en_route
        _set_status(session, trip, TripStatus.EN_ROUTE, now)
    _set_status(session, trip, target, now)
    return target


def _mirror_driver_status(session: Session, driver_id: str, status: str) -> None:
    driver = session.get(Driver, driver_id)
    if driver is None:
        driver = Driver(id=driver_id, name=driver_id, status=status)
        session.add(driver)
    else:
        driver.status = status


def match_stats(session: Session, window: timedelta = timedelta(minutes=1)) -> dict:
    """Aggregate counts and latency percentiles straight from PostgreSQL."""
    now = datetime.now(UTC)
    matched_total = session.scalar(
        select(func.count()).select_from(Trip).where(Trip.matched_at.is_not(None))
    )
    pending = session.scalar(
        select(func.count()).select_from(Trip).where(Trip.status == TripStatus.REQUESTED)
    )
    recent = select(Trip.match_latency_ms).where(Trip.matched_at >= now - window).subquery()
    matches_last_minute = session.scalar(select(func.count()).select_from(recent))
    p50, p95 = session.execute(
        select(
            func.percentile_cont(0.5).within_group(recent.c.match_latency_ms),
            func.percentile_cont(0.95).within_group(recent.c.match_latency_ms),
        )
    ).one()
    return {
        "matched_total": matched_total or 0,
        "pending": pending or 0,
        "matches_last_minute": matches_last_minute or 0,
        "matches_per_minute": float(matches_last_minute or 0) / (window.total_seconds() / 60),
        "p50_match_latency_ms": float(p50) if p50 is not None else None,
        "p95_match_latency_ms": float(p95) if p95 is not None else None,
    }
