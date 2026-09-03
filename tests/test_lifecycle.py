"""Driver pings move a trip through en_route, arrived, in_trip and completed."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from rideloop_common import trips
from rideloop_common.db import Driver, Trip
from rideloop_common.eta import PICKUP_OVERHEAD_S, pickup_eta_s
from rideloop_common.geo import manhattan_m, offset_m
from rideloop_common.models import Coordinate, DriverStatus, RideRequest, TripStatus
from services.driver_location import main as location_main
from services.ride_request import main as ride_main
from sim.city import DRIVER_SPEED_MPS, SimDriver, to_latlng

CENTER = (37.7749, -122.4194)
PICKUP = offset_m(*CENTER, 600, 0)
DROPOFF = offset_m(*CENTER, 600, 900)


def location_client(store, session_factory) -> TestClient:
    location_main.app.dependency_overrides[location_main.get_store] = lambda: store
    location_main.app.dependency_overrides[location_main.get_session_factory] = lambda: (
        session_factory
    )
    return TestClient(location_main.app)


def ride_client(store, session_factory) -> TestClient:
    def override_session():
        with session_factory() as s:
            yield s

    ride_main.app.dependency_overrides[ride_main.get_session] = override_session
    ride_main.app.dependency_overrides[ride_main.get_store] = lambda: store
    return TestClient(ride_main.app)


def matched_trip(store, session_factory, driver_id: str, driver_at) -> uuid.UUID:
    """A trip from PICKUP to DROPOFF already matched to a driver standing at driver_at."""
    pos = store.put_position(driver_id, *driver_at)
    with session_factory() as s, s.begin():
        req = RideRequest(
            rider_id="rider",
            pickup=Coordinate(lat=PICKUP[0], lng=PICKUP[1]),
            dropoff=Coordinate(lat=DROPOFF[0], lng=DROPOFF[1]),
        )
        trip = trips.create_trip(s, req)
        assert store.try_mark_busy(pos.cell, driver_id, str(trip.id))
        trips.mark_matched(s, trip, driver_id)
        return trip.id


def post(client: TestClient, driver_id: str, point) -> dict:
    resp = client.post(f"/drivers/{driver_id}/position", json={"lat": point[0], "lng": point[1]})
    assert resp.status_code == 200
    return resp.json()


def test_pings_drive_the_trip_through_every_state(store, session_factory):
    client = location_client(store, session_factory)
    trip_id = matched_trip(store, session_factory, "d1", offset_m(*CENTER, 0, 0))

    assert post(client, "d1", offset_m(*CENTER, 200, 0))["status"] == "busy"
    with session_factory() as s:
        assert s.get(Trip, trip_id).status == TripStatus.EN_ROUTE

    post(client, "d1", offset_m(*PICKUP, 10, 5))
    with session_factory() as s:
        row = s.get(Trip, trip_id)
        assert row.status == TripStatus.ARRIVED
        assert row.arrived_at is not None
        assert row.pickup_eta_s == 0

    # still parked at the pickup: nothing changes
    post(client, "d1", offset_m(*PICKUP, 12, 5))
    with session_factory() as s:
        assert s.get(Trip, trip_id).status == TripStatus.ARRIVED

    post(client, "d1", offset_m(*PICKUP, 0, 300))
    with session_factory() as s:
        row = s.get(Trip, trip_id)
        assert row.status == TripStatus.IN_TRIP
        assert row.started_at is not None

    body = post(client, "d1", offset_m(*DROPOFF, 5, -5))
    assert body["status"] == "available"
    assert body["trip_id"] is None
    with session_factory() as s:
        row = trips.get_trip(s, trip_id)
        assert row.status == TripStatus.COMPLETED
        assert row.completed_at is not None
        assert [e.event for e in row.events] == [
            "requested",
            "matched",
            "en_route",
            "arrived",
            "in_trip",
            "completed",
        ]
        assert s.get(Driver, "d1").status == "available"
    assert store.get_driver("d1").status == DriverStatus.AVAILABLE
    assert store.get_driver("d1").trip_id is None


def test_pings_from_a_free_driver_or_for_another_trip_are_ignored(store, session_factory):
    client = location_client(store, session_factory)
    trip_id = matched_trip(store, session_factory, "d2", offset_m(*CENTER, 0, 0))
    post(client, "bystander", PICKUP)
    # a stale trip_id that does not belong to this driver is left alone
    other = store.put_position("d3", *CENTER)
    assert store.try_mark_busy(other.cell, "d3", str(trip_id))
    post(client, "d3", PICKUP)
    with session_factory() as s:
        assert s.get(Trip, trip_id).status == TripStatus.MATCHED


def test_rider_transitions_respect_the_new_states(store, session_factory):
    client = ride_client(store, session_factory)
    trip_id = matched_trip(store, session_factory, "d4", PICKUP)
    with session_factory() as s, s.begin():
        trip = s.get(Trip, trip_id)
        assert trips.advance_from_position(s, trip, *PICKUP, 0.0) == TripStatus.ARRIVED
        assert [e.event for e in trip.events][-2:] == ["en_route", "arrived"]
    assert client.post(f"/rides/{trip_id}/start").status_code == 409
    assert client.post(f"/rides/{trip_id}/cancel").json()["status"] == "cancelled"

    trip_id = matched_trip(store, session_factory, "d5", PICKUP)
    with session_factory() as s, s.begin():
        trip = s.get(Trip, trip_id)
        trips.advance_from_position(s, trip, *PICKUP, 0.0)
        assert trips.advance_from_position(s, trip, *offset_m(*PICKUP, 50, 0), 0.0) is None
        assert trips.advance_from_position(s, trip, *offset_m(*PICKUP, 200, 0), 0.0) == (
            TripStatus.IN_TRIP
        )
    assert client.post(f"/rides/{trip_id}/cancel").status_code == 409
    assert client.post(f"/rides/{trip_id}/complete").json()["status"] == "completed"


def test_get_ride_reports_driver_position_and_eta(store, session_factory):
    client = ride_client(store, session_factory)
    start = offset_m(*CENTER, 0, 0)
    trip_id = matched_trip(store, session_factory, "d6", start)
    assert client.get(f"/rides/{trip_id}").json()["driver_position"]["speed_mps"] == 0

    # two pings ten seconds apart, 110 m closer: the driver is doing 11 m/s
    t0 = datetime.now(UTC)
    store.put_position("d6", *offset_m(*CENTER, 0, 0), now=t0)
    store.put_position("d6", *offset_m(*CENTER, 110, 0), now=t0 + timedelta(seconds=10))
    body = client.get(f"/rides/{trip_id}").json()
    pos = body["driver_position"]
    assert abs(pos["speed_mps"] - 11) < 0.5
    assert abs(pos["distance_to_pickup_m"] - 490) < 5
    assert body["pickup_eta_s"] == pickup_eta_s(pos["distance_to_pickup_m"], pos["speed_mps"])
    assert 55 <= body["pickup_eta_s"] <= 65

    done = client.post(f"/rides/{trip_id}/complete").json()
    assert done["driver_position"] is None
    assert done["pickup_eta_s"] is None
    assert client.get("/rides").json()[0]["driver_position"] is None


def test_eta_is_within_tolerance_on_a_synthetic_grid_drive(store, session_factory):
    """A simulated driver drives the grid to the pickup; the ETA taken after a few
    pings must land within 15% of the time it actually took."""
    driver = SimDriver.spawn("grid", rng=__import__("random").Random(1))
    driver.north_m, driver.east_m = -1200.0, 800.0
    driver.set_target(0.0, 0.0)
    pickup = to_latlng(0.0, 0.0)
    t0 = datetime.now(UTC)
    estimates: dict[int, int] = {}
    arrived_at_step = None
    for step in range(600):
        lat, lng, _ = driver.step(1.0)
        pos = store.put_position("grid", lat, lng, now=t0 + timedelta(seconds=step))
        if step in (3, 60):
            estimates[step] = pickup_eta_s(manhattan_m(lat, lng, *pickup), pos.speed_mps)
        if manhattan_m(lat, lng, *pickup) <= trips.ARRIVAL_RADIUS_M:
            arrived_at_step = step
            break
    assert arrived_at_step is not None
    assert abs(pos.speed_mps - DRIVER_SPEED_MPS) < 1.0
    for step, eta in estimates.items():
        actual = arrived_at_step - step + PICKUP_OVERHEAD_S
        assert abs(eta - actual) <= 0.15 * actual, f"step {step}: eta {eta}s, actual {actual}s"


def test_eta_falls_back_to_a_crawl_when_the_driver_is_stopped():
    assert pickup_eta_s(0, 0) == 0
    assert pickup_eta_s(300, 0.0) == 100 + PICKUP_OVERHEAD_S
    assert pickup_eta_s(300, 10.0) == 30 + PICKUP_OVERHEAD_S
