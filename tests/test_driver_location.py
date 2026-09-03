import time
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from rideloop_common import geohash
from rideloop_common.geo import offset_m
from rideloop_common.models import DriverStatus
from services.driver_location.main import app, get_store

CENTER = (37.7749, -122.4194)


def client_for(store) -> TestClient:
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def test_ttl_is_enabled_on_the_table(store):
    desc = store.client.describe_time_to_live(TableName=store.table.name)
    assert desc["TimeToLiveDescription"] == {"TimeToLiveStatus": "ENABLED", "AttributeName": "ttl"}


def test_position_is_keyed_by_precision_5_cell_and_carries_ttl(store):
    before = int(time.time())
    pos = store.put_position("d1", *CENTER, heading=45)
    assert pos.cell == geohash.encode(*CENTER, 5) == "9q8yy"
    assert pos.geohash == geohash.encode(*CENTER, 6)
    item = store.table.get_item(Key={"cell": "9q8yy", "driver_id": "d1"})["Item"]
    assert int(item["ttl"]) >= before + store.settings.position_ttl_seconds
    assert int(item["ttl"]) <= int(time.time()) + store.settings.position_ttl_seconds + 1
    assert item["status"] == "available"
    assert float(item["heading"]) == 45


def test_post_position_endpoint_validates_input(store):
    client = client_for(store)
    resp = client.post("/drivers/d1/position", json={"lat": 37.78, "lng": -122.41, "heading": 90})
    assert resp.status_code == 200
    body = resp.json()
    assert body["cell"] == "9q8yy"
    assert body["ttl"] > int(time.time())

    assert client.post("/drivers/d1/position", json={"lat": 100, "lng": 0}).status_code == 422
    assert client.post("/drivers/d1/position", json={"lat": 0}).status_code == 422
    assert client.post("/drivers/d1/position", json={"lat": 0, "lng": 0, "x": 1}).status_code == 422


def test_nearby_filters_by_radius_and_orders_by_distance(store):
    client = client_for(store)
    lat, lng = CENTER
    store.put_position("near", *offset_m(lat, lng, 200, 0))
    store.put_position("mid", *offset_m(lat, lng, 0, 800))
    store.put_position("far", *offset_m(lat, lng, 3000, 0))

    resp = client.get("/drivers/nearby", params={"lat": lat, "lng": lng, "radius_m": 1000})
    assert resp.status_code == 200
    ids = [d["driver_id"] for d in resp.json()]
    assert ids == ["near", "mid"]
    assert resp.json()[0]["distance_m"] < resp.json()[1]["distance_m"]

    resp = client.get("/drivers/nearby", params={"lat": lat, "lng": lng, "radius_m": 4000})
    assert [d["driver_id"] for d in resp.json()] == ["near", "mid", "far"]


def test_nearby_spans_neighboring_cells(store):
    """A driver just across a cell boundary is still found."""
    lat, lng = CENTER
    lat_lo, lat_hi, lng_lo, lng_hi = geohash.decode_bbox(geohash.encode(lat, lng, 5))
    rider = (lat_hi - 0.0005, lng)
    driver = (lat_hi + 0.0005, lng)
    assert geohash.encode(*rider, 5) != geohash.encode(*driver, 5)
    store.put_position("across", *driver)
    found = store.nearby(*rider, radius_m=500)
    assert [d.driver_id for d in found] == ["across"]


def test_expired_positions_are_filtered_from_nearby(store):
    lat, lng = CENTER
    store.put_position("fresh", lat, lng)
    store.put_position("stale", *offset_m(lat, lng, 50, 0), ttl_seconds=1)
    assert {d.driver_id for d in store.nearby(lat, lng, 500)} == {"fresh", "stale"}

    later = datetime.now(UTC) + timedelta(seconds=2)
    assert [d.driver_id for d in store.nearby(lat, lng, 500, now=later)] == ["fresh"]


def test_driver_that_stops_pinging_disappears_after_ttl(store):
    lat, lng = CENTER
    store.put_position("quiet", lat, lng, ttl_seconds=1)
    assert store.nearby(lat, lng, 500)
    time.sleep(1.1)
    assert store.nearby(lat, lng, 500) == []


def test_ttl_is_refreshed_on_every_ping(store):
    lat, lng = CENTER
    first = store.put_position("d1", lat, lng, now=datetime.now(UTC) - timedelta(seconds=30))
    second = store.put_position("d1", lat, lng)
    assert second.ttl > first.ttl


def test_moving_across_cells_leaves_a_single_item(store):
    lat, lng = CENTER
    first = store.put_position("mover", lat, lng)
    far_lat, far_lng = offset_m(lat, lng, 12_000, 0)
    second = store.put_position("mover", far_lat, far_lng)
    assert first.cell != second.cell
    assert store.table.scan()["Count"] == 1
    assert store.get_driver("mover").cell == second.cell


def test_status_survives_a_cell_change(store):
    lat, lng = CENTER
    pos = store.put_position("busy-mover", lat, lng)
    assert store.try_mark_busy(pos.cell, "busy-mover", "trip-1")
    moved = store.put_position("busy-mover", *offset_m(lat, lng, 12_000, 0))
    assert moved.status == DriverStatus.BUSY
    assert moved.trip_id == "trip-1"
    assert store.nearby(moved.lat, moved.lng, 100, statuses={DriverStatus.AVAILABLE}) == []


def test_status_endpoints(store):
    client = client_for(store)
    lat, lng = CENTER
    client.post("/drivers/d1/position", json={"lat": lat, "lng": lng})
    resp = client.put("/drivers/d1/status", params={"status": "offline"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "offline"
    assert client.get("/drivers/nearby", params={"lat": lat, "lng": lng}).json()[0]["status"] == (
        "offline"
    )
    assert (
        client.get("/drivers/nearby", params={"lat": lat, "lng": lng, "status": "available"}).json()
        == []
    )
    assert client.get("/drivers/d1").status_code == 200
    assert client.delete("/drivers/d1").status_code == 204
    assert client.get("/drivers/d1").status_code == 404
    assert client.put("/drivers/d1/status", params={"status": "available"}).status_code == 404
