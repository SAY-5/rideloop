"""Surge: demand against supply per cell, rising with requests and decaying with time."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from rideloop_common import surge, trips
from rideloop_common.config import Settings
from rideloop_common.db import Trip
from rideloop_common.geo import offset_m
from rideloop_common.models import Coordinate, RideRequest
from services.dispatch import main as dispatch_main
from services.ride_request.main import app, get_session, get_store

CENTER = (37.7749, -122.4194)
CELL = "9q8yy"
FAR = offset_m(*CENTER, 12_000, 0)


def client_for(session_factory, store) -> TestClient:
    def override_session():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def ride_at(lat, lng) -> dict:
    return {
        "rider_id": "rider",
        "pickup": {"lat": lat, "lng": lng},
        "dropoff": {"lat": lat + 0.01, "lng": lng + 0.01},
    }


def test_multiplier_is_flat_until_demand_outruns_supply():
    settings = Settings(surge_step=0.5, surge_max_multiplier=3.0)
    assert surge.multiplier_for(0, 0, settings) == 1.0
    assert surge.multiplier_for(3, 3, settings) == 1.0
    assert surge.multiplier_for(2, 5, settings) == 1.0
    assert surge.multiplier_for(4, 2, settings) == 1.5
    assert surge.multiplier_for(6, 2, settings) == 2.0
    assert surge.multiplier_for(3, 0, settings) == 2.0
    assert surge.multiplier_for(40, 2, settings) == 3.0


def test_demand_decays_with_the_half_life():
    now = datetime.now(UTC)
    ages = [0, 60, 120]
    ats = [now - timedelta(seconds=a) for a in ages]
    assert surge.decayed_demand(ats, now, half_life_s=60) == 1.75
    assert surge.decayed_demand(ats, now + timedelta(seconds=600), half_life_s=60) < 0.01
    assert surge.decayed_demand([], now, 60) == 0.0


def test_requests_in_a_cell_raise_the_multiplier_and_it_decays(store, session_factory):
    client = client_for(session_factory, store)
    lat, lng = CENTER
    store.put_position("d1", *offset_m(lat, lng, 100, 0))
    store.put_position("d2", *offset_m(lat, lng, 200, 0))
    store.put_position("elsewhere", *FAR)

    quote = client.get("/rides/surge", params={"lat": lat, "lng": lng}).json()
    assert quote == {
        "cell": CELL,
        "demand": 0.0,
        "supply": 2,
        "multiplier": 1.0,
        "lat": quote["lat"],
        "lng": quote["lng"],
    }

    multipliers = []
    for i in range(6):
        body = client.post("/rides", json=ride_at(*offset_m(lat, lng, 10 * i, 0))).json()
        assert body["pickup_cell"] == CELL
        multipliers.append(body["surge_multiplier"])
    # the first two requests are covered by the two drivers, then it climbs
    assert multipliers[:2] == [1.0, 1.0]
    assert multipliers[2:] == sorted(multipliers[2:])
    assert multipliers[-1] > multipliers[2]
    # the quote now counts all six requests against the two drivers
    quote = client.get("/rides/surge", params={"lat": lat, "lng": lng}).json()
    assert quote["multiplier"] == surge.multiplier_for(6, 2) == 2.0
    assert quote["multiplier"] > multipliers[-1]
    # a different cell is unaffected
    assert (
        client.get("/rides/surge", params={"lat": FAR[0], "lng": FAR[1]}).json()["multiplier"]
        == 1.0
    )

    with session_factory() as s:
        assert (
            s.scalar(
                __import__("sqlalchemy")
                .select(Trip.surge_multiplier)
                .order_by(Trip.requested_at.desc())
            )
            == multipliers[-1]
        )
        later = datetime.now(UTC) + timedelta(minutes=10)
        cooled = surge.surge_for_cell(s, store, CELL, now=later)
        assert cooled.multiplier == 1.0
        assert cooled.demand < 0.1
        assert cooled.supply == 0  # driver items expired by then


def test_heatmap_lists_every_active_cell_hottest_first(store, session_factory):
    lat, lng = CENTER
    store.put_position("only", *FAR)
    now = datetime.now(UTC)
    with session_factory() as s, s.begin():
        for _ in range(4):
            req = RideRequest(
                rider_id="r",
                pickup=Coordinate(lat=lat, lng=lng),
                dropoff=Coordinate(lat=lat, lng=lng),
            )
            trips.create_trip(s, req, now=now, pickup_cell=CELL, surge_multiplier=1.0)
        cells = surge.heatmap(s, store, now=now)
    assert [c.cell for c in cells] == [CELL, store.get_driver("only").cell]
    assert cells[0].demand == 4.0 and cells[0].supply == 0 and cells[0].multiplier == 2.5
    assert cells[1].demand == 0.0 and cells[1].supply == 1 and cells[1].multiplier == 1.0

    dispatch_main._state.update(session_factory=session_factory, store=store)
    body = TestClient(dispatch_main.app).get("/dispatch/heatmap").json()
    assert body["half_life_s"] == 60.0
    assert [c["cell"] for c in body["cells"]] == [c.cell for c in cells]
    assert body["cells"][0]["multiplier"] == 2.5
