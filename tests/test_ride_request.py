import uuid

from fastapi.testclient import TestClient

from rideloop_common.db import Driver, RideEvent, Trip
from rideloop_common.models import TripStatus
from services.ride_request.main import app, get_session, get_store

RIDE = {
    "rider_id": "rider-1",
    "pickup": {"lat": 37.78, "lng": -122.41},
    "dropoff": {"lat": 37.79, "lng": -122.40},
}


def client_for(session_factory, store) -> TestClient:
    def override_session():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def test_create_and_fetch_ride(session_factory, store):
    client = client_for(session_factory, store)
    resp = client.post("/rides", json=RIDE)
    assert resp.status_code == 201
    body = resp.json()
    trip_id = body["id"]
    assert body["status"] == "requested"
    assert body["driver_id"] is None
    assert [e["event"] for e in body["events"]] == ["requested"]

    resp = client.get(f"/rides/{trip_id}")
    assert resp.status_code == 200
    assert resp.json()["pickup_lat"] == 37.78

    with session_factory() as s:
        row = s.get(Trip, uuid.UUID(trip_id))
        assert row.status == TripStatus.REQUESTED
        assert row.requested_at is not None


def test_create_ride_validation(session_factory, store):
    client = client_for(session_factory, store)
    bad = {**RIDE, "pickup": {"lat": 95, "lng": 0}}
    assert client.post("/rides", json=bad).status_code == 422
    assert client.post("/rides", json={"rider_id": "x"}).status_code == 422
    assert client.get(f"/rides/{uuid.uuid4()}").status_code == 404
    assert client.get("/rides/not-a-uuid").status_code == 422


def test_full_lifecycle_records_events_and_frees_driver(session_factory, store):
    client = client_for(session_factory, store)
    trip_id = client.post("/rides", json=RIDE).json()["id"]

    # a rider cannot start or complete an unmatched trip
    assert client.post(f"/rides/{trip_id}/start").status_code == 409
    assert client.post(f"/rides/{trip_id}/complete").status_code == 409

    # simulate the dispatcher having matched a driver
    pos = store.put_position("driver-7", 37.78, -122.41)
    assert store.try_mark_busy(pos.cell, "driver-7", trip_id)
    with session_factory() as s, s.begin():
        from rideloop_common import trips

        trips.mark_matched(s, s.get(Trip, uuid.UUID(trip_id)), "driver-7")

    body = client.get(f"/rides/{trip_id}").json()
    assert body["status"] == "matched"
    assert body["driver_id"] == "driver-7"
    assert body["match_latency_ms"] >= 0

    assert client.post(f"/rides/{trip_id}/start").json()["status"] == "en_route"
    done = client.post(f"/rides/{trip_id}/complete").json()
    assert done["status"] == "completed"
    assert done["completed_at"] is not None
    assert [e["event"] for e in done["events"]] == ["requested", "matched", "en_route", "completed"]

    # the driver is released in DynamoDB and mirrored in PostgreSQL
    assert store.get_driver("driver-7").status == "available"
    assert store.get_driver("driver-7").trip_id is None
    with session_factory() as s:
        assert s.get(Driver, "driver-7").status == "available"
        events = s.query(RideEvent).filter_by(trip_id=uuid.UUID(trip_id)).count()
        assert events == 4

    # completed trips are terminal
    assert client.post(f"/rides/{trip_id}/cancel").status_code == 409


def test_cancel_requested_ride(session_factory, store):
    client = client_for(session_factory, store)
    trip_id = client.post("/rides", json=RIDE).json()["id"]
    body = client.post(f"/rides/{trip_id}/cancel").json()
    assert body["status"] == "cancelled"
    assert [e["event"] for e in body["events"]] == ["requested", "cancelled"]


def test_list_rides_by_status(session_factory, store):
    client = client_for(session_factory, store)
    ids = [client.post("/rides", json=RIDE).json()["id"] for _ in range(3)]
    client.post(f"/rides/{ids[0]}/cancel")
    requested = client.get("/rides", params={"status": "requested"}).json()
    assert {t["id"] for t in requested} == set(ids[1:])
    assert len(client.get("/rides").json()) == 3
