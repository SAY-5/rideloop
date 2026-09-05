"""Ride request service: creates trips and exposes their lifecycle."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from rideloop_common import __version__, trips
from rideloop_common.config import get_settings
from rideloop_common.db import make_engine, make_session_factory
from rideloop_common.dynamo import DriverPositionStore
from rideloop_common.eta import eta_to_point
from rideloop_common.models import DriverLocation, DriverStatus, RideRequest, TripDetail, TripStatus
from services.common import add_common_routes


@lru_cache
def get_session_factory():
    return make_session_factory(make_engine(get_settings()))


@lru_cache
def get_store() -> DriverPositionStore:
    return DriverPositionStore(get_settings())


def get_session() -> Iterator[Session]:
    with get_session_factory()() as session:
        yield session


DB = Annotated[Session, Depends(get_session)]
Store = Annotated[DriverPositionStore, Depends(get_store)]

app = FastAPI(title="RideLoop ride request", version=__version__)
add_common_routes(app, "ride_request")


def _detail(trip) -> TripDetail:
    return TripDetail.model_validate(trip)


def _with_driver(trip, store: DriverPositionStore) -> TripDetail:
    """The trip plus where its driver is and how far out, read live from DynamoDB."""
    detail = _detail(trip)
    if trip.status not in trips.ACTIVE or not trip.driver_id:
        return detail
    pos = store.get_driver(trip.driver_id)
    if pos is None:
        return detail
    distance, eta = eta_to_point(pos.lat, pos.lng, trip.pickup_lat, trip.pickup_lng, pos.speed_mps)
    detail.driver_position = DriverLocation(
        lat=pos.lat,
        lng=pos.lng,
        heading=pos.heading,
        speed_mps=pos.speed_mps,
        distance_to_pickup_m=distance,
        updated_at=pos.updated_at,
    )
    if trip.status in trips.APPROACHING:
        detail.pickup_eta_s = eta
    return detail


def _load(session: Session, trip_id: uuid.UUID):
    try:
        return trips.get_trip(session, trip_id)
    except trips.TripNotFound:
        raise HTTPException(status_code=404, detail="trip not found") from None


@app.post("/rides", response_model=TripDetail, status_code=201)
def create_ride(request: RideRequest, session: DB) -> TripDetail:
    trip = trips.create_trip(session, request)
    session.commit()
    return _detail(trips.get_trip(session, trip.id))


@app.get("/rides", response_model=list[TripDetail])
def list_rides(
    session: DB,
    status: TripStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[TripDetail]:
    return [_detail(t) for t in trips.list_trips(session, status=status, limit=limit)]


@app.get("/rides/{trip_id}", response_model=TripDetail)
def get_ride(trip_id: uuid.UUID, session: DB, store: Store) -> TripDetail:
    return _with_driver(_load(session, trip_id), store)


def _apply(session: Session, store: DriverPositionStore, trip_id: uuid.UUID, target: TripStatus):
    trip = _load(session, trip_id)
    try:
        trips.transition(session, trip, target)
    except trips.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    session.commit()
    if target in (TripStatus.COMPLETED, TripStatus.CANCELLED) and trip.driver_id:
        store.set_status(trip.driver_id, DriverStatus.AVAILABLE)
    return _detail(trips.get_trip(session, trip_id))


@app.post("/rides/{trip_id}/start", response_model=TripDetail)
def start_ride(trip_id: uuid.UUID, session: DB, store: Store) -> TripDetail:
    return _apply(session, store, trip_id, TripStatus.EN_ROUTE)


@app.post("/rides/{trip_id}/complete", response_model=TripDetail)
def complete_ride(trip_id: uuid.UUID, session: DB, store: Store) -> TripDetail:
    return _apply(session, store, trip_id, TripStatus.COMPLETED)


@app.post("/rides/{trip_id}/cancel", response_model=TripDetail)
def cancel_ride(trip_id: uuid.UUID, session: DB, store: Store) -> TripDetail:
    return _apply(session, store, trip_id, TripStatus.CANCELLED)
