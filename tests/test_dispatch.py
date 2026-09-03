import threading
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from rideloop_common import trips
from rideloop_common.db import Driver, RideEvent, Trip
from rideloop_common.geo import offset_m
from rideloop_common.models import Coordinate, DriverStatus, RideRequest, TripStatus
from services.dispatch import main as dispatch_main
from services.dispatch.matcher import Matcher

CENTER = (37.7749, -122.4194)


def request_at(lat, lng, rider="rider") -> RideRequest:
    return RideRequest(
        rider_id=rider,
        pickup=Coordinate(lat=lat, lng=lng),
        dropoff=Coordinate(lat=lat + 0.01, lng=lng + 0.01),
    )


def make_matcher(store, session_factory, **kwargs) -> Matcher:
    kwargs.setdefault("initial_radius_m", 500)
    kwargs.setdefault("max_radius_m", 4000)
    return Matcher(store, session_factory, **kwargs)


def test_sweep_matches_requested_trips(store, session_factory):
    lat, lng = CENTER
    store.put_position("d-near", *offset_m(lat, lng, 100, 0))
    store.put_position("d-far", *offset_m(lat, lng, 900, 0))
    with session_factory() as s, s.begin():
        trip = trips.create_trip(
            s, request_at(lat, lng), now=datetime.now(UTC) - timedelta(seconds=2)
        )
        trip_id = trip.id

    matcher = make_matcher(store, session_factory)
    assert matcher.run_once() == 1

    with session_factory() as s:
        row = s.get(Trip, trip_id)
        assert row.status == TripStatus.MATCHED
        assert row.driver_id == "d-near"
        assert row.matched_at is not None
        assert 1900 <= row.match_latency_ms <= 10_000
        assert row.dispatch_attempts == 1
        events = [e.event for e in s.scalars(select(RideEvent).where(RideEvent.trip_id == trip_id))]
        assert events == ["requested", "matched"]
        assert s.get(Driver, "d-near").status == "busy"
    assert store.get_driver("d-near").status == DriverStatus.BUSY
    assert store.get_driver("d-near").trip_id == str(trip_id)
    assert store.get_driver("d-far").status == DriverStatus.AVAILABLE
    assert matcher.stats.matched == 1
    assert matcher.stats.sweeps == 1


def test_no_driver_leaves_trip_requested_and_retries_later(store, session_factory):
    lat, lng = CENTER
    with session_factory() as s, s.begin():
        trip_id = trips.create_trip(s, request_at(lat, lng)).id

    matcher = make_matcher(store, session_factory, retry_delay_s=0.5)
    assert matcher.run_once() == 0
    with session_factory() as s:
        row = s.get(Trip, trip_id)
        assert row.status == TripStatus.REQUESTED
        assert row.driver_id is None
        assert row.dispatch_attempts == 1
        assert row.next_attempt_at > datetime.now(UTC)
        events = [e.event for e in s.scalars(select(RideEvent).where(RideEvent.trip_id == trip_id))]
        assert events == ["requested", "no_driver"]

    # not retried until the backoff has elapsed
    assert matcher.run_once() == 0
    with session_factory() as s:
        assert s.get(Trip, trip_id).dispatch_attempts == 1

    # a driver shows up and the backoff passes
    store.put_position("late", *offset_m(lat, lng, 50, 0))
    with session_factory() as s, s.begin():
        s.get(Trip, trip_id).next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    assert matcher.run_once() == 1
    with session_factory() as s:
        row = s.get(Trip, trip_id)
        assert row.status == TripStatus.MATCHED
        assert row.driver_id == "late"
        assert row.dispatch_attempts == 2


def test_concurrent_matchers_never_double_assign_a_driver(store, session_factory):
    """Many trips, one driver, several matchers racing: exactly one trip gets the driver."""
    lat, lng = CENTER
    store.put_position("only", *offset_m(lat, lng, 30, 0))
    with session_factory() as s, s.begin():
        for i in range(12):
            trips.create_trip(s, request_at(*offset_m(lat, lng, 10 * i, 0), rider=f"r{i}"))

    matchers = [make_matcher(store, session_factory, batch_size=1) for _ in range(6)]
    barrier = threading.Barrier(len(matchers))
    errors: list[BaseException] = []

    def worker(m: Matcher):
        try:
            barrier.wait()
            for _ in range(4):
                m.run_once()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(m,)) for m in matchers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors

    with session_factory() as s:
        matched = s.scalars(select(Trip).where(Trip.status == TripStatus.MATCHED)).all()
        assert len(matched) == 1
        assert matched[0].driver_id == "only"
        requested = s.scalar(select(Trip.id).where(Trip.status == TripStatus.REQUESTED).limit(1))
        assert requested is not None
    assert store.get_driver("only").trip_id == str(matched[0].id)


def test_direct_conditional_claim_is_exclusive(store):
    lat, lng = CENTER
    pos = store.put_position("d", lat, lng)
    wins = []
    barrier = threading.Barrier(16)

    def claim(i):
        barrier.wait()
        wins.append(store.try_mark_busy(pos.cell, "d", f"trip-{i}"))

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(wins) == 1
    assert store.try_mark_busy(pos.cell, "d", "late") is False


def test_expired_driver_cannot_be_claimed(store):
    lat, lng = CENTER
    pos = store.put_position("ghost", lat, lng, now=datetime.now(UTC) - timedelta(seconds=120))
    assert store.try_mark_busy(pos.cell, "ghost", "trip") is False


def test_stats_endpoint_reports_throughput_and_latency(store, session_factory):
    lat, lng = CENTER
    for i in range(5):
        store.put_position(f"d{i}", *offset_m(lat, lng, 20 * i, 0))
    with session_factory() as s, s.begin():
        for _ in range(5):
            trips.create_trip(s, request_at(lat, lng), now=datetime.now(UTC) - timedelta(seconds=1))
        trips.create_trip(s, request_at(*offset_m(lat, lng, 30_000, 0)))
    matcher = make_matcher(store, session_factory)
    assert matcher.run_once() == 5

    dispatch_main._state.update(matcher=matcher, session_factory=session_factory)
    client = TestClient(dispatch_main.app)
    body = client.get("/dispatch/stats").json()
    assert body["matched_total"] == 5
    assert body["pending"] == 1
    assert body["matches_last_minute"] == 5
    assert body["matches_per_minute"] == 5.0
    assert body["p50_match_latency_ms"] >= 900
    assert body["p95_match_latency_ms"] >= body["p50_match_latency_ms"]
    assert body["sweeps"] == 1
    assert client.get("/healthz").json() == {"service": "dispatch", "status": "ok"}


def test_skip_locked_claims_do_not_overlap(store, session_factory):
    lat, lng = CENTER
    with session_factory() as s, s.begin():
        for _ in range(4):
            trips.create_trip(s, request_at(lat, lng))
    with session_factory() as s1, s1.begin():
        first = {t.id for t in trips.claim_pending(s1, 2)}
        assert len(first) == 2
        with session_factory() as s2, s2.begin():
            second = {t.id for t in trips.claim_pending(s2, 10)}
        assert len(second) == 2
        assert first.isdisjoint(second)
    assert isinstance(next(iter(first)), uuid.UUID)
