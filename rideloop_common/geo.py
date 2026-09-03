"""Great-circle distance helpers."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance in meters between two WGS84 points along the sphere."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def offset_m(lat: float, lng: float, north_m: float, east_m: float) -> tuple[float, float]:
    """Move a point by the given meters north and east (small-distance approximation)."""
    dlat = north_m / EARTH_RADIUS_M
    dlng = east_m / (EARTH_RADIUS_M * math.cos(math.radians(lat)))
    return lat + math.degrees(dlat), lng + math.degrees(dlng)


def manhattan_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """North-south plus east-west distance in meters.

    A driver on a street grid cannot drive the great-circle line, so the L1
    distance is a better stand-in for route length than haversine at city scale.
    """
    north = haversine_m(lat1, lng1, lat2, lng1)
    east = haversine_m(lat1, lng1, lat1, lng2)
    return north + east
