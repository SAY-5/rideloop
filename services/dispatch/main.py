"""Dispatch service: runs the matcher loop and reports throughput."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from rideloop_common import __version__, surge, trips
from rideloop_common.config import get_settings
from rideloop_common.db import make_engine, make_session_factory
from rideloop_common.dynamo import DriverPositionStore
from rideloop_common.models import DispatchStats, Heatmap
from services.common import add_common_routes
from services.dispatch.matcher import Matcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

_state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    session_factory = make_session_factory(make_engine(settings))
    store = DriverPositionStore(settings)
    matcher = Matcher(
        store,
        session_factory,
        initial_radius_m=settings.dispatch_initial_radius_m,
        max_radius_m=settings.dispatch_max_radius_m,
        retry_delay_s=settings.dispatch_retry_delay_s,
        batch_size=settings.dispatch_batch_size,
        offer_timeout_s=settings.dispatch_offer_timeout_s,
    )
    stop = threading.Event()
    worker = threading.Thread(
        target=matcher.run_forever,
        args=(settings.dispatch_poll_interval_s, stop),
        name="dispatch-loop",
        daemon=True,
    )
    worker.start()
    _state.update(
        matcher=matcher, session_factory=session_factory, store=store, stop=stop, worker=worker
    )
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=5)


app = FastAPI(title="RideLoop dispatch", version=__version__, lifespan=lifespan)
add_common_routes(app, "dispatch")


@app.get("/dispatch/stats", response_model=DispatchStats)
def dispatch_stats() -> DispatchStats:
    matcher: Matcher = _state["matcher"]
    with _state["session_factory"]() as session:
        aggregates = trips.match_stats(session)
    return DispatchStats(
        **aggregates,
        sweeps=matcher.stats.sweeps,
        uptime_s=round(time.monotonic() - matcher.stats.started_at, 1),
    )


@app.get("/dispatch/heatmap", response_model=Heatmap)
def dispatch_heatmap() -> Heatmap:
    """Demand, supply and surge multiplier for every cell with activity."""
    now = datetime.now(UTC)
    with _state["session_factory"]() as session:
        cells = surge.heatmap(session, _state["store"], now=now)
    return Heatmap(at=now, half_life_s=get_settings().surge_half_life_s, cells=cells)
