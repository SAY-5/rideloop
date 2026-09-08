"""Every service exposes /metrics; the dispatcher's counters track what the matcher did."""

import threading
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from rideloop_common import metrics, trips
from rideloop_common.geo import offset_m
from rideloop_common.models import Coordinate, DriverStatus, RideRequest
from services.dispatch import main as dispatch_main
from services.dispatch.matcher import Matcher
from services.driver_location import main as location_main
from services.ride_request import main as ride_main

CENTER = (37.7749, -122.4194)


def scrape(client: TestClient) -> dict[tuple[str, tuple], float]:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    samples = {}
    for family in text_string_to_metric_families(resp.text):
        for sample in family.samples:
            samples[(sample.name, tuple(sorted(sample.labels.items())))] = sample.value
    return samples


def value(samples, name, **labels) -> float:
    return samples.get((name, tuple(sorted(labels.items()))), 0.0)


def request_at(lat, lng) -> RideRequest:
    return RideRequest(
        rider_id="r", pickup=Coordinate(lat=lat, lng=lng), dropoff=Coordinate(lat=lat, lng=lng)
    )


def test_every_service_serves_metrics_and_counts_requests(store, session_factory):
    location_main.app.dependency_overrides[location_main.get_store] = lambda: store
    location_main.app.dependency_overrides[location_main.get_session_factory] = lambda: (
        session_factory
    )
    ride_main.app.dependency_overrides[ride_main.get_store] = lambda: store

    def override_session():
        with session_factory() as s:
            yield s

    ride_main.app.dependency_overrides[ride_main.get_session] = override_session
    dispatch_main._state.update(session_factory=session_factory, store=store)

    location = TestClient(location_main.app)
    rides = TestClient(ride_main.app)
    dispatch = TestClient(dispatch_main.app)

    before = value(
        scrape(location),
        "rideloop_http_requests_total",
        service="driver_location",
        method="POST",
        path="/drivers/{driver_id}/position",
        status="200",
    )
    positions_before = value(scrape(location), "rideloop_positions_total")
    location.post("/drivers/m1/position", json={"lat": CENTER[0], "lng": CENTER[1]})
    location.post("/drivers/m1/position", json={"lat": CENTER[0], "lng": CENTER[1]})
    after = scrape(location)
    assert (
        value(
            after,
            "rideloop_http_requests_total",
            service="driver_location",
            method="POST",
            path="/drivers/{driver_id}/position",
            status="200",
        )
        == before + 2
    )
    assert value(after, "rideloop_positions_total") == positions_before + 2
    # /metrics and /healthz do not count themselves
    assert not any(
        k[0] == "rideloop_http_requests_total" and dict(k[1]).get("path") == "/metrics"
        for k in after
    )

    rides_before = value(scrape(rides), "rideloop_rides_total")
    rides.post(
        "/rides",
        json={
            "rider_id": "r",
            "pickup": {"lat": CENTER[0], "lng": CENTER[1]},
            "dropoff": {"lat": CENTER[0], "lng": CENTER[1]},
        },
    )
    assert value(scrape(rides), "rideloop_rides_total") == rides_before + 1
    assert dispatch.get("/metrics").status_code == 200


def test_matcher_counters_track_matches_latency_and_unmatched(store, session_factory):
    dispatch_main._state.update(session_factory=session_factory, store=store)
    client = TestClient(dispatch_main.app)
    lat, lng = CENTER
    before = scrape(client)
    store.put_position("d1", *offset_m(lat, lng, 100, 0))
    with session_factory() as s, s.begin():
        trips.create_trip(s, request_at(lat, lng), now=datetime.now(UTC) - timedelta(seconds=2))
        trips.create_trip(s, request_at(lat, lng))
        trips.create_trip(s, request_at(*offset_m(lat, lng, 30_000, 0)))
    matcher = Matcher(store, session_factory, initial_radius_m=500, max_radius_m=4000)
    assert matcher.run_once() == 1

    after = scrape(client)
    assert value(after, "rideloop_matches_total") == value(before, "rideloop_matches_total") + 1
    assert value(after, "rideloop_unmatched_total") == value(before, "rideloop_unmatched_total") + 2
    assert (
        value(after, "rideloop_match_latency_seconds_count")
        == value(before, "rideloop_match_latency_seconds_count") + 1
    )
    assert (
        value(after, "rideloop_match_latency_seconds_sum")
        >= value(before, "rideloop_match_latency_seconds_sum") + 1.9
    )
    assert (
        value(after, "rideloop_dispatch_sweeps_total")
        == value(before, "rideloop_dispatch_sweeps_total") + 1
    )
    assert value(after, "rideloop_matches_per_minute") == 1.0


def test_claim_conflicts_and_ttl_expiries_are_counted(store, session_factory):
    dispatch_main._state.update(session_factory=session_factory, store=store)
    client = TestClient(dispatch_main.app)
    lat, lng = CENTER
    before = scrape(client)

    pos = store.put_position("c", lat, lng)
    barrier = threading.Barrier(8)

    def claim(i):
        barrier.wait()
        store.try_mark_busy(pos.cell, "c", f"t{i}")

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert value(scrape(client), "rideloop_claim_conflicts_total") == (
        value(before, "rideloop_claim_conflicts_total") + 7
    )

    store.put_position("stale", *offset_m(lat, lng, 50, 0), ttl_seconds=1)
    later = datetime.now(UTC) + timedelta(seconds=5)
    assert [d.driver_id for d in store.nearby(lat, lng, 500, now=later)] == ["c"]
    after = scrape(client)
    assert (
        value(after, "rideloop_ttl_expiries_total")
        == value(before, "rideloop_ttl_expiries_total") + 1
    )
    # the expiry is stamped on the row, so a second read does not count it again
    store.nearby(lat, lng, 500, now=later)
    assert value(scrape(client), "rideloop_ttl_expiries_total") == value(
        after, "rideloop_ttl_expiries_total"
    )
    # the row itself is left for DynamoDB's sweep; a resumed driver keeps its status
    assert store.get_driver("stale") is not None
    pos = store.put_position("stale", *offset_m(lat, lng, 50, 0), ttl_seconds=1)
    assert store.try_mark_busy(pos.cell, "stale", "t")
    assert [d.driver_id for d in store.nearby(lat, lng, 500, now=later)] == ["c"]
    assert store.get_driver("stale").status == DriverStatus.BUSY


def test_trailing_minute_rate_drops_old_matches():
    from services.dispatch.matcher import MatcherStats

    stats = MatcherStats()
    assert stats.record_matches(3, at=100.0) == 3.0
    assert stats.record_matches(2, at=130.0) == 5.0
    assert stats.record_matches(0, at=161.0) == 2.0
    assert stats.record_matches(0, at=200.0) == 0.0
    assert metrics.render().startswith(b"# HELP")
