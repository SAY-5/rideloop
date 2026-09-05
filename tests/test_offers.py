"""Offers: the matched driver accepts or declines, declines re-queue with that driver excluded."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from rideloop_common import trips
from rideloop_common.db import Driver, Trip
from rideloop_common.geo import offset_m
from rideloop_common.models import Coordinate, DriverStatus, RideRequest, TripStatus
from services.dispatch import main as dispatch_main
from services.dispatch.matcher import Matcher
from services.driver_location import main as location_main
from services.ride_request import main as ride_main

CENTER = (37.7749, -122.4194)


def ride_client(store, session_factory) -> TestClient:
    def override_session():
        with session_factory() as s:
            yield s

    ride_main.app.dependency_overrides[ride_main.get_session] = override_session
    ride_main.app.dependency_overrides[ride_main.get_store] = lambda: store
    return TestClient(ride_main.app)


def location_client(store, session_factory) -> TestClient:
    location_main.app.dependency_overrides[location_main.get_store] = lambda: store
    location_main.app.dependency_overrides[location_main.get_session_factory] = lambda: (
        session_factory
    )
    return TestClient(location_main.app)


def new_trip(session_factory, now=None) -> uuid.UUID:
    lat, lng = CENTER
    with session_factory() as s, s.begin():
        req = RideRequest(
            rider_id="rider",
            pickup=Coordinate(lat=lat, lng=lng),
            dropoff=Coordinate(lat=lat + 0.01, lng=lng),
        )
        return trips.create_trip(s, req, now=now).id


def matcher_for(store, session_factory, **kwargs) -> Matcher:
    kwargs.setdefault("initial_radius_m", 500)
    kwargs.setdefault("max_radius_m", 4000)
    return Matcher(store, session_factory, **kwargs)


def events_of(session_factory, trip_id) -> list[str]:
    with session_factory() as s:
        return [e.event for e in trips.get_trip(s, trip_id).events]


def test_offer_must_be_accepted_before_pings_move_the_trip(store, session_factory):
    lat, lng = CENTER
    store.put_position("near", *offset_m(lat, lng, 100, 0))
    trip_id = new_trip(session_factory)
    assert matcher_for(store, session_factory).run_once() == 1
    rides = ride_client(store, session_factory)
    pings = location_client(store, session_factory)

    body = rides.get(f"/rides/{trip_id}").json()
    assert body["status"] == "matched"
    assert body["driver_id"] == "near"
    assert body["offered_at"] is not None
    assert body["accepted_at"] is None

    # a ping before acceptance refreshes the ETA but does not start the trip
    pings.post("/drivers/near/position", json={"lat": lat, "lng": lng})
    body = rides.get(f"/rides/{trip_id}").json()
    assert body["status"] == "matched"
    assert body["pickup_eta_s"] is not None

    # only the offered driver can answer
    resp = rides.post(f"/rides/{trip_id}/accept", params={"driver_id": "someone-else"})
    assert resp.status_code == 409
    resp = rides.post(f"/rides/{trip_id}/accept", params={"driver_id": "near"})
    assert resp.status_code == 200
    assert resp.json()["accepted_at"] is not None
    assert resp.json()["driver_position"]["distance_to_pickup_m"] == 0
    # accepting twice is harmless, declining after accepting is not allowed
    assert rides.post(f"/rides/{trip_id}/accept", params={"driver_id": "near"}).status_code == 200
    assert rides.post(f"/rides/{trip_id}/decline", params={"driver_id": "near"}).status_code == 409

    pings.post("/drivers/near/position", json={"lat": lat, "lng": lng})
    body = rides.get(f"/rides/{trip_id}").json()
    assert body["status"] == "arrived"
    assert events_of(session_factory, trip_id) == [
        "requested",
        "matched",
        "accepted",
        "en_route",
        "arrived",
    ]

    acceptance = rides.get("/drivers/near/acceptance").json()
    assert acceptance == {
        "driver_id": "near",
        "offers": 1,
        "accepts": 1,
        "declines": 0,
        "acceptance_rate": 1.0,
    }
    assert rides.get("/drivers/nobody/acceptance").status_code == 404


def test_decline_releases_the_driver_and_rematches_without_it(store, session_factory):
    lat, lng = CENTER
    store.put_position("nearest", *offset_m(lat, lng, 50, 0))
    store.put_position("second", *offset_m(lat, lng, 300, 0))
    trip_id = new_trip(session_factory)
    matcher = matcher_for(store, session_factory)
    assert matcher.run_once() == 1
    rides = ride_client(store, session_factory)
    assert rides.get(f"/rides/{trip_id}").json()["driver_id"] == "nearest"

    resp = rides.post(f"/rides/{trip_id}/decline", params={"driver_id": "nearest"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "requested"
    assert body["driver_id"] is None
    assert body["matched_at"] is None
    assert body["declined_by"] == ["nearest"]
    assert store.get_driver("nearest").status == DriverStatus.AVAILABLE
    assert store.get_driver("nearest").trip_id is None
    with session_factory() as s:
        assert s.get(Driver, "nearest").status == "available"

    # the next sweep skips the decliner even though it is still the nearest
    assert matcher.run_once() == 1
    body = rides.get(f"/rides/{trip_id}").json()
    assert body["driver_id"] == "second"
    assert body["status"] == "matched"
    assert body["dispatch_attempts"] == 2
    assert store.get_driver("nearest").status == DriverStatus.AVAILABLE
    assert store.get_driver("second").status == DriverStatus.BUSY
    assert events_of(session_factory, trip_id) == ["requested", "matched", "declined", "matched"]

    assert rides.get("/drivers/nearest/acceptance").json() == {
        "driver_id": "nearest",
        "offers": 1,
        "accepts": 0,
        "declines": 1,
        "acceptance_rate": 0.0,
    }


def test_trip_waits_when_the_only_driver_declined(store, session_factory):
    lat, lng = CENTER
    store.put_position("only", *offset_m(lat, lng, 50, 0))
    trip_id = new_trip(session_factory)
    matcher = matcher_for(store, session_factory)
    assert matcher.run_once() == 1
    rides = ride_client(store, session_factory)
    rides.post(f"/rides/{trip_id}/decline", params={"driver_id": "only"})
    assert matcher.run_once() == 0
    with session_factory() as s:
        row = s.get(Trip, trip_id)
        assert row.status == TripStatus.REQUESTED
        assert row.driver_id is None
    assert store.get_driver("only").status == DriverStatus.AVAILABLE


def test_unanswered_offer_times_out_and_counts_as_a_decline(store, session_factory):
    lat, lng = CENTER
    store.put_position("slow", *offset_m(lat, lng, 50, 0))
    store.put_position("backup", *offset_m(lat, lng, 400, 0))
    trip_id = new_trip(session_factory)
    matcher = matcher_for(store, session_factory, offer_timeout_s=5)
    assert matcher.run_once() == 1
    with session_factory() as s:
        assert s.get(Trip, trip_id).driver_id == "slow"

    # not yet expired
    assert matcher.run_once() == 0
    assert matcher.stats.timed_out == 0
    with session_factory() as s, s.begin():
        s.get(Trip, trip_id).offered_at = datetime.now(UTC) - timedelta(seconds=6)

    # the same sweep expires the offer and rematches the trip
    assert matcher.run_once() == 1
    assert matcher.stats.timed_out == 1
    with session_factory() as s:
        row = s.get(Trip, trip_id)
        assert row.driver_id == "backup"
        assert row.declined_by == ["slow"]
        assert s.get(Driver, "slow").declines == 1
    assert store.get_driver("slow").status == DriverStatus.AVAILABLE
    assert store.get_driver("backup").trip_id == str(trip_id)
    assert events_of(session_factory, trip_id) == [
        "requested",
        "matched",
        "offer_timeout",
        "matched",
    ]

    dispatch_main._state.update(matcher=matcher, session_factory=session_factory, store=store)
    body = TestClient(dispatch_main.app).get("/dispatch/stats").json()
    assert body["offers_timed_out"] == 1
    assert body["offers_declined"] == 0


def test_release_claim_only_frees_the_driver_for_its_own_trip(store):
    lat, lng = CENTER
    pos = store.put_position("d", lat, lng)
    assert store.try_mark_busy(pos.cell, "d", "trip-a")
    assert store.release_claim("d", "trip-b") is False
    assert store.get_driver("d").status == DriverStatus.BUSY
    assert store.release_claim("d", "trip-a") is True
    assert store.get_driver("d").status == DriverStatus.AVAILABLE
    assert store.release_claim("d", "trip-a") is False
    assert store.release_claim("ghost", "trip-a") is False


def test_mark_matched_records_the_offer(session_factory):
    trip_id = new_trip(session_factory)
    with session_factory() as s, s.begin():
        trip = s.get(Trip, trip_id)
        trips.mark_matched(s, trip, "d1")
        assert trip.offered_at == trip.matched_at
        assert trip.accepted_at is None
        assert s.get(Driver, "d1").offers == 1
        assert trips.driver_acceptance(s, "d1").acceptance_rate == 0.0
        assert trips.driver_acceptance(s, "nobody") is None
    with session_factory() as s:
        assert s.scalar(select(Trip.declined_by).where(Trip.id == trip_id)) == []
