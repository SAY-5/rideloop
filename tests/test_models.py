import pytest
from pydantic import ValidationError

from rideloop_common.models import PositionUpdate, RideRequest, TripStatus


def test_ride_request_valid():
    req = RideRequest(
        rider_id="r1",
        pickup={"lat": 37.78, "lng": -122.41},
        dropoff={"lat": 37.79, "lng": -122.40},
    )
    assert req.pickup.lat == 37.78


@pytest.mark.parametrize(
    "pickup",
    [
        {"lat": 91, "lng": 0},
        {"lat": 0, "lng": -181},
        {"lat": "north", "lng": 0},
        {"lat": 0},
    ],
)
def test_ride_request_rejects_bad_coordinates(pickup):
    with pytest.raises(ValidationError):
        RideRequest(rider_id="r1", pickup=pickup, dropoff={"lat": 0, "lng": 0})


def test_ride_request_rejects_empty_rider_and_extra_fields():
    with pytest.raises(ValidationError):
        RideRequest(rider_id="", pickup={"lat": 0, "lng": 0}, dropoff={"lat": 0, "lng": 0})
    with pytest.raises(ValidationError):
        RideRequest(
            rider_id="r1",
            pickup={"lat": 0, "lng": 0},
            dropoff={"lat": 0, "lng": 0},
            surge=2,
        )


def test_position_update_heading_range():
    assert PositionUpdate(lat=1, lng=2, heading=359.9).heading == 359.9
    with pytest.raises(ValidationError):
        PositionUpdate(lat=1, lng=2, heading=360)
    with pytest.raises(ValidationError):
        PositionUpdate(lat=1, lng=2, heading=-1)


def test_trip_status_values():
    assert [s.value for s in TripStatus] == [
        "requested",
        "matched",
        "en_route",
        "arrived",
        "in_trip",
        "completed",
        "cancelled",
    ]
