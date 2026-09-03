from rideloop_common.geo import offset_m
from rideloop_common.models import DriverStatus
from services.dispatch.matcher import Matcher, expanding_radii

CENTER = (37.7749, -122.4194)


def matcher_for(store) -> Matcher:
    return Matcher(store, session_factory=None, initial_radius_m=500, max_radius_m=4000)


def test_expanding_radii_double_until_cap():
    assert expanding_radii(500, 4000) == [500, 1000, 2000, 4000]
    assert expanding_radii(300, 1000) == [300, 600, 1000]
    assert expanding_radii(1000, 1000) == [1000]


def test_picks_the_nearest_available_driver(store):
    lat, lng = CENTER
    store.put_position("far", *offset_m(lat, lng, 400, 0))
    store.put_position("nearest", *offset_m(lat, lng, 120, 90))
    store.put_position("mid", *offset_m(lat, lng, -250, 0))
    outcome = matcher_for(store).find_driver(lat, lng, "trip-1")
    assert outcome.driver.driver_id == "nearest"
    assert outcome.radius_m == 500
    assert outcome.candidates_seen == 1
    assert store.get_driver("nearest").status == DriverStatus.BUSY
    assert store.get_driver("nearest").trip_id == "trip-1"
    assert store.get_driver("far").status == DriverStatus.AVAILABLE


def test_skips_busy_and_offline_drivers(store):
    lat, lng = CENTER
    busy = store.put_position("busy", *offset_m(lat, lng, 50, 0))
    assert store.try_mark_busy(busy.cell, "busy", "other-trip")
    store.put_position("offline", *offset_m(lat, lng, 60, 0))
    store.set_status("offline", DriverStatus.OFFLINE)
    store.put_position("free", *offset_m(lat, lng, 300, 0))
    outcome = matcher_for(store).find_driver(lat, lng, "trip-2")
    assert outcome.driver.driver_id == "free"
    assert store.get_driver("busy").trip_id == "other-trip"


def test_expands_radius_until_a_driver_is_found(store):
    lat, lng = CENTER
    store.put_position("distant", *offset_m(lat, lng, 0, 2500))
    outcome = matcher_for(store).find_driver(lat, lng, "trip-3")
    assert outcome.driver.driver_id == "distant"
    assert outcome.radius_m == 4000


def test_gives_up_past_the_radius_cap(store):
    lat, lng = CENTER
    store.put_position("too-far", *offset_m(lat, lng, 4500, 0))
    outcome = matcher_for(store).find_driver(lat, lng, "trip-4")
    assert outcome.driver is None
    assert outcome.radius_m is None
    assert store.get_driver("too-far").status == DriverStatus.AVAILABLE


def test_falls_through_to_next_candidate_when_claim_is_lost(store):
    """If the nearest driver is claimed between the query and the update, take the next one."""
    lat, lng = CENTER
    nearest = store.put_position("nearest", *offset_m(lat, lng, 100, 0))
    store.put_position("second", *offset_m(lat, lng, 200, 0))
    matcher = matcher_for(store)

    original_nearby = store.nearby

    def nearby_then_steal(*args, **kwargs):
        result = original_nearby(*args, **kwargs)
        store.try_mark_busy(nearest.cell, "nearest", "rival-trip")
        return result

    store.nearby = nearby_then_steal
    outcome = matcher.find_driver(lat, lng, "trip-5")
    assert outcome.driver.driver_id == "second"
    assert outcome.candidates_seen == 2
    assert store.get_driver("nearest").trip_id == "rival-trip"
