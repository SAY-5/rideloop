"""A small synthetic city: a square road grid centered on one coordinate."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from rideloop_common.geo import offset_m

CITY_CENTER = (37.7749, -122.4194)
CITY_HALF_M = 3000.0
BLOCK_M = 250.0
DRIVER_SPEED_MPS = 11.0

HEADINGS = (0.0, 90.0, 180.0, 270.0)


def to_latlng(north_m: float, east_m: float) -> tuple[float, float]:
    return offset_m(*CITY_CENTER, north_m, east_m)


def random_point(rng: random.Random) -> tuple[float, float]:
    return to_latlng(rng.uniform(-CITY_HALF_M, CITY_HALF_M), rng.uniform(-CITY_HALF_M, CITY_HALF_M))


def snap(value: float) -> float:
    return round(value / BLOCK_M) * BLOCK_M


@dataclass
class SimDriver:
    """Drives along the grid; wanders randomly or heads for a target when given one."""

    driver_id: str
    rng: random.Random
    north_m: float = 0.0
    east_m: float = 0.0
    heading: float = 0.0
    target: tuple[float, float] | None = None
    trip_id: str | None = None
    speed_mps: float = DRIVER_SPEED_MPS
    _turn_at: float = field(default=0.0, repr=False)

    @classmethod
    def spawn(cls, driver_id: str, rng: random.Random) -> SimDriver:
        d = cls(
            driver_id=driver_id,
            rng=rng,
            north_m=snap(rng.uniform(-CITY_HALF_M, CITY_HALF_M)),
            east_m=snap(rng.uniform(-CITY_HALF_M, CITY_HALF_M)),
            heading=rng.choice(HEADINGS),
        )
        d._turn_at = d._next_turn()
        return d

    def _next_turn(self) -> float:
        return self.rng.choice((BLOCK_M, 2 * BLOCK_M, 3 * BLOCK_M))

    def set_target(self, north_m: float, east_m: float) -> None:
        self.target = (north_m, east_m)

    def clear_target(self) -> None:
        self.target = None

    def _steer(self) -> None:
        if self.target is not None:
            dn = self.target[0] - self.north_m
            de = self.target[1] - self.east_m
            if abs(dn) < 1.0 and abs(de) < 1.0:
                return
            if abs(dn) >= abs(de):
                self.heading = 0.0 if dn > 0 else 180.0
            else:
                self.heading = 90.0 if de > 0 else 270.0
            return
        if self._turn_at <= 0:
            self.heading = self.rng.choice(HEADINGS)
            self._turn_at = self._next_turn()
        if abs(self.north_m) >= CITY_HALF_M and self.heading in (0.0, 180.0):
            self.heading = 180.0 if self.north_m > 0 else 0.0
        if abs(self.east_m) >= CITY_HALF_M and self.heading in (90.0, 270.0):
            self.heading = 270.0 if self.east_m > 0 else 90.0

    def step(self, dt_s: float) -> tuple[float, float, float]:
        """Advance the simulation and return (lat, lng, heading)."""
        self._steer()
        dist = self.speed_mps * dt_s
        if self.target is not None:
            dn = self.target[0] - self.north_m
            de = self.target[1] - self.east_m
            remaining = math.hypot(dn, de)
            if remaining <= dist:
                self.north_m, self.east_m = self.target
                return (*self.latlng(), self.heading)
        rad = math.radians(self.heading)
        self.north_m += math.cos(rad) * dist
        self.east_m += math.sin(rad) * dist
        self.north_m = max(-CITY_HALF_M, min(CITY_HALF_M, self.north_m))
        self.east_m = max(-CITY_HALF_M, min(CITY_HALF_M, self.east_m))
        self._turn_at -= dist
        return (*self.latlng(), self.heading)

    def latlng(self) -> tuple[float, float]:
        return to_latlng(self.north_m, self.east_m)


def latlng_to_local(lat: float, lng: float) -> tuple[float, float]:
    """Inverse of to_latlng, good enough at city scale."""
    from rideloop_common.geo import EARTH_RADIUS_M

    north = math.radians(lat - CITY_CENTER[0]) * EARTH_RADIUS_M
    east = (
        math.radians(lng - CITY_CENTER[1]) * EARTH_RADIUS_M * math.cos(math.radians(CITY_CENTER[0]))
    )
    return north, east
