"""Driver location service: ingests positions and answers nearby queries.

A ping from a busy driver also moves its trip along (en_route, arrived,
in_trip, completed) and refreshes the pickup ETA, so the trip lifecycle is
driven by where the car actually is rather than by button presses.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import sessionmaker

from rideloop_common import trips
from rideloop_common.config import get_settings
from rideloop_common.db import make_engine, make_session_factory
from rideloop_common.dynamo import DriverPositionStore, ensure_table_with_retry
from rideloop_common.models import (
    DriverPosition,
    DriverStatus,
    NearbyDriver,
    PositionUpdate,
    TripStatus,
)
from services.common import add_common_routes

log = logging.getLogger("rideloop.driver_location")


@lru_cache
def get_store() -> DriverPositionStore:
    return DriverPositionStore(get_settings())


@lru_cache
def get_session_factory() -> sessionmaker:
    return make_session_factory(make_engine(get_settings()))


Store = Annotated[DriverPositionStore, Depends(get_store)]
Sessions = Annotated[sessionmaker, Depends(get_session_factory)]


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.dynamodb_auto_create:
        ensure_table_with_retry(settings)
    yield


app = FastAPI(title="RideLoop driver location", version="0.1.0", lifespan=lifespan)
add_common_routes(app, "driver_location")


def report_progress(
    sessions: sessionmaker, store: DriverPositionStore, pos: DriverPosition
) -> TripStatus | None:
    """Apply a busy driver's ping to its trip; release the driver when it completes."""
    try:
        trip_id = uuid.UUID(pos.trip_id or "")
    except ValueError:
        return None
    with sessions() as session, session.begin():
        try:
            trip = trips.get_trip(session, trip_id)
        except trips.TripNotFound:
            return None
        if trip.driver_id != pos.driver_id:
            return None
        changed = trips.advance_from_position(
            session, trip, pos.lat, pos.lng, pos.speed_mps, now=pos.updated_at
        )
    if changed == TripStatus.COMPLETED:
        store.set_status(pos.driver_id, DriverStatus.AVAILABLE)
    return changed


@app.post("/drivers/{driver_id}/position", response_model=DriverPosition)
def post_position(
    driver_id: str, update: PositionUpdate, store: Store, sessions: Sessions
) -> DriverPosition:
    pos = store.put_position(driver_id, update.lat, update.lng, update.heading)
    if pos.status == DriverStatus.BUSY and pos.trip_id:
        try:
            changed = report_progress(sessions, store, pos)
        except Exception:
            # the ping itself is stored; a trip database hiccup must not fail it
            log.exception("could not advance trip %s for %s", pos.trip_id, driver_id)
        else:
            if changed == TripStatus.COMPLETED:
                return pos.model_copy(update={"status": DriverStatus.AVAILABLE, "trip_id": None})
    return pos


@app.get("/drivers/nearby", response_model=list[NearbyDriver])
def nearby(
    store: Store,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    radius_m: Annotated[float, Query(gt=0, le=10_000)] = 1000.0,
    status: DriverStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[NearbyDriver]:
    statuses = {status} if status else None
    return store.nearby(lat, lng, radius_m, statuses=statuses, limit=limit)


@app.get("/drivers/{driver_id}", response_model=DriverPosition)
def get_driver(driver_id: str, store: Store) -> DriverPosition:
    pos = store.get_driver(driver_id)
    if pos is None:
        raise HTTPException(status_code=404, detail="driver not found")
    return pos


@app.put("/drivers/{driver_id}/status", response_model=DriverPosition)
def put_status(driver_id: str, status: DriverStatus, store: Store) -> DriverPosition:
    pos = store.set_status(driver_id, status)
    if pos is None:
        raise HTTPException(status_code=404, detail="driver not found")
    return pos


@app.delete("/drivers/{driver_id}", status_code=204)
def delete_driver(driver_id: str, store: Store) -> None:
    if not store.delete_driver(driver_id):
        raise HTTPException(status_code=404, detail="driver not found")
