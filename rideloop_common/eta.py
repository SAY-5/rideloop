"""Pickup ETA from the driver's route distance and observed speed."""

from __future__ import annotations

from rideloop_common.geo import manhattan_m

# A driver that is stopped or has just come online has no useful speed sample
# yet; assume a slow crawl rather than dividing by zero.
MIN_SPEED_MPS = 3.0
# Pull-over, rider walk-up and door time at the pickup.
PICKUP_OVERHEAD_S = 15


def pickup_eta_s(distance_m: float, speed_mps: float) -> int:
    """Seconds until pickup given remaining route distance and the driver's speed."""
    if distance_m <= 0:
        return 0
    speed = max(speed_mps, MIN_SPEED_MPS)
    return int(round(distance_m / speed)) + PICKUP_OVERHEAD_S


def eta_to_point(
    lat: float, lng: float, target_lat: float, target_lng: float, speed_mps: float
) -> tuple[float, int]:
    """Route distance and ETA from a position to a target point."""
    distance = manhattan_m(lat, lng, target_lat, target_lng)
    return round(distance, 1), pickup_eta_s(distance, speed_mps)
