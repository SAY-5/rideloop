"""Surge pricing: demand against supply per geohash cell.

Demand is the recent ride requests whose pickup falls in the cell, each one
weighted by how long ago it was made (exponential decay with a configurable
half-life), so a burst of requests pushes the multiplier up and it drifts back
down on its own as the burst ages out. Supply is the number of available,
unexpired drivers in the cell right now. Both come straight from the stores;
there is no counter to keep in sync.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from rideloop_common import geohash
from rideloop_common.config import Settings, get_settings
from rideloop_common.db import Trip
from rideloop_common.dynamo import DriverPositionStore
from rideloop_common.models import SurgeCell

# Requests older than this many half-lives contribute too little to fetch.
WINDOW_HALF_LIVES = 5


def multiplier_for(demand: float, supply: int, settings: Settings | None = None) -> float:
    """1.0 while supply covers demand; above that, `step` per unit of excess ratio, capped."""
    settings = settings or get_settings()
    if demand <= supply:
        return 1.0
    ratio = demand / max(supply, 1)
    return round(min(1.0 + settings.surge_step * (ratio - 1.0), settings.surge_max_multiplier), 2)


def decayed_demand(requested_ats: list[datetime], now: datetime, half_life_s: float) -> float:
    total = 0.0
    for at in requested_ats:
        age = max((now - at).total_seconds(), 0.0)
        total += math.pow(0.5, age / half_life_s)
    return round(total, 3)


def demand_by_cell(
    session: Session, now: datetime, half_life_s: float, cells: list[str] | None = None
) -> dict[str, float]:
    """Decayed request counts per pickup cell over the last few half-lives."""
    since = now - timedelta(seconds=half_life_s * WINDOW_HALF_LIVES)
    query = select(Trip.pickup_cell, Trip.requested_at).where(
        Trip.pickup_cell.is_not(None), Trip.requested_at >= since
    )
    if cells is not None:
        query = query.where(Trip.pickup_cell.in_(cells))
    grouped: dict[str, list[datetime]] = {}
    for cell, at in session.execute(query):
        grouped.setdefault(cell, []).append(at)
    return {cell: decayed_demand(ats, now, half_life_s) for cell, ats in grouped.items()}


def cell_for(lat: float, lng: float, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return geohash.encode(lat, lng, settings.cell_precision)


def surge_for_cell(
    session: Session,
    store: DriverPositionStore,
    cell: str,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> SurgeCell:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    demand = demand_by_cell(session, now, settings.surge_half_life_s, [cell]).get(cell, 0.0)
    supply = store.count_available(cell, now=now)
    lat, lng = geohash.decode(cell)
    return SurgeCell(
        cell=cell,
        demand=demand,
        supply=supply,
        multiplier=multiplier_for(demand, supply, settings),
        lat=lat,
        lng=lng,
    )


def heatmap(
    session: Session,
    store: DriverPositionStore,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[SurgeCell]:
    """Every cell with recent demand or available supply, hottest first."""
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    demand = demand_by_cell(session, now, settings.surge_half_life_s)
    supply = store.available_by_cell(now=now)
    cells = []
    for cell in set(demand) | set(supply):
        lat, lng = geohash.decode(cell)
        cells.append(
            SurgeCell(
                cell=cell,
                demand=demand.get(cell, 0.0),
                supply=supply.get(cell, 0),
                multiplier=multiplier_for(demand.get(cell, 0.0), supply.get(cell, 0), settings),
                lat=lat,
                lng=lng,
            )
        )
    cells.sort(key=lambda c: (-c.multiplier, -c.demand, c.cell))
    return cells
