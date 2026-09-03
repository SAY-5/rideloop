import pytest

from rideloop_common.geo import haversine_m, offset_m


def test_haversine_zero_for_same_point():
    assert haversine_m(37.7749, -122.4194, 37.7749, -122.4194) == 0.0


def test_haversine_known_distance():
    # Paris to London is about 343.5 km
    assert haversine_m(48.8566, 2.3522, 51.5074, -0.1278) == pytest.approx(343_500, rel=0.005)


def test_haversine_is_symmetric():
    a = haversine_m(37.7749, -122.4194, 34.0522, -118.2437)
    b = haversine_m(34.0522, -118.2437, 37.7749, -122.4194)
    assert a == pytest.approx(b)


def test_offset_round_trips_through_haversine():
    lat, lng = 37.7749, -122.4194
    north = offset_m(lat, lng, 1000, 0)
    east = offset_m(lat, lng, 0, 1000)
    assert haversine_m(lat, lng, *north) == pytest.approx(1000, rel=1e-3)
    assert haversine_m(lat, lng, *east) == pytest.approx(1000, rel=1e-3)
