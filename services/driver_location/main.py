"""Driver location service: ingests positions and answers nearby queries."""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from rideloop_common.config import get_settings
from rideloop_common.dynamo import DriverPositionStore, ensure_table_with_retry
from rideloop_common.models import DriverPosition, DriverStatus, NearbyDriver, PositionUpdate
from services.common import add_common_routes


@lru_cache
def get_store() -> DriverPositionStore:
    return DriverPositionStore(get_settings())


Store = Annotated[DriverPositionStore, Depends(get_store)]


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.dynamodb_auto_create:
        ensure_table_with_retry(settings)
    yield


app = FastAPI(title="RideLoop driver location", version="0.1.0", lifespan=lifespan)
add_common_routes(app, "driver_location")


@app.post("/drivers/{driver_id}/position", response_model=DriverPosition)
def post_position(driver_id: str, update: PositionUpdate, store: Store) -> DriverPosition:
    return store.put_position(driver_id, update.lat, update.lng, update.heading)


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
