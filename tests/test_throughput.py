"""In-process throughput check: the matcher must sustain 500+ matches per minute."""

import random
import time
from datetime import UTC, datetime

from sqlalchemy import select

from rideloop_common import trips
from rideloop_common.db import Trip
from rideloop_common.geo import offset_m
from rideloop_common.models import Coordinate, DriverStatus, RideRequest, TripStatus
from services.dispatch.matcher import Matcher

CENTER = (37.7749, -122.4194)
DRIVERS = 300
RIDES = 500
CITY_HALF_M = 3000


def random_point(rng: random.Random):
    return offset_m(
        *CENTER, rng.uniform(-CITY_HALF_M, CITY_HALF_M), rng.uniform(-CITY_HALF_M, CITY_HALF_M)
    )


def test_matcher_sustains_500_matches_per_minute(store, session_factory):
    rng = random.Random(7)
    for i in range(DRIVERS):
        store.put_position(f"drv-{i:03d}", *random_point(rng), ttl_seconds=600)

    now = datetime.now(UTC)
    with session_factory() as s, s.begin():
        for i in range(RIDES):
            lat, lng = random_point(rng)
            req = RideRequest(
                rider_id=f"rider-{i}",
                pickup=Coordinate(lat=lat, lng=lng),
                dropoff=Coordinate(lat=lat, lng=lng),
            )
            trips.create_trip(s, req, now=now)

    matcher = Matcher(
        store, session_factory, initial_radius_m=500, max_radius_m=4000, batch_size=100
    )
    started = time.perf_counter()
    matched = 0
    while matched < RIDES:
        got = matcher.run_once()
        matched += got
        # riders finish quickly in this model: release the drivers so the pool is reused
        with session_factory() as s, s.begin():
            done = s.scalars(select(Trip).where(Trip.status == TripStatus.MATCHED)).all()
            for trip in done:
                trips.transition(s, trip, TripStatus.COMPLETED)
                store.set_status(trip.driver_id, DriverStatus.AVAILABLE)
        assert time.perf_counter() - started < 120, f"only {matched} matched"
    elapsed = time.perf_counter() - started

    per_minute = matched / (elapsed / 60)
    print(f"\nmatched {matched} rides in {elapsed:.1f}s = {per_minute:.0f} matches/min")
    assert matched == RIDES
    assert per_minute >= 500

    with session_factory() as s:
        latencies = s.scalars(select(Trip.match_latency_ms)).all()
    assert all(latency >= 0 for latency in latencies)
    assert len(latencies) == RIDES
