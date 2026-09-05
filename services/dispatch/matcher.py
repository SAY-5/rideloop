"""The dispatch matcher: pairs requested trips with the nearest available driver."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import sessionmaker

from rideloop_common import trips
from rideloop_common.db import Trip
from rideloop_common.dynamo import DriverPositionStore
from rideloop_common.models import DriverStatus, NearbyDriver

log = logging.getLogger("rideloop.dispatch")


def expanding_radii(initial_m: float, max_m: float) -> list[float]:
    """500, 1000, 2000, 4000: double until the cap, always ending at the cap."""
    radii: list[float] = []
    radius = initial_m
    while radius < max_m:
        radii.append(radius)
        radius *= 2
    radii.append(max_m)
    return radii


@dataclass
class MatchOutcome:
    trip_id: str
    driver: NearbyDriver | None
    radius_m: float | None
    candidates_seen: int


@dataclass
class MatcherStats:
    started_at: float = field(default_factory=time.monotonic)
    sweeps: int = 0
    matched: int = 0
    deferred: int = 0
    timed_out: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class Matcher:
    def __init__(
        self,
        store: DriverPositionStore,
        session_factory: sessionmaker,
        initial_radius_m: float = 500.0,
        max_radius_m: float = 4000.0,
        retry_delay_s: float = 1.0,
        batch_size: int = 50,
        offer_timeout_s: float = 15.0,
    ):
        self.store = store
        self.session_factory = session_factory
        self.radii = expanding_radii(initial_radius_m, max_radius_m)
        self.retry_delay = timedelta(seconds=retry_delay_s)
        self.batch_size = batch_size
        self.offer_timeout = timedelta(seconds=offer_timeout_s)
        self.stats = MatcherStats()

    def find_driver(
        self, lat: float, lng: float, trip_id: str, exclude: set[str] | None = None
    ) -> MatchOutcome:
        """Widen the search ring until a driver is claimed or the cap is reached.

        Candidates are ranked by haversine distance. The claim is a conditional
        update in DynamoDB, so two matchers racing for the same driver cannot both
        succeed: the loser simply moves on to the next nearest candidate. Drivers
        in ``exclude`` (those who already declined this trip) are never offered it.
        """
        seen = 0
        tried: set[str] = set(exclude or ())
        for radius in self.radii:
            candidates = self.store.nearby(lat, lng, radius, statuses={DriverStatus.AVAILABLE})
            for candidate in candidates:
                if candidate.driver_id in tried:
                    continue
                tried.add(candidate.driver_id)
                seen += 1
                if self.store.try_mark_busy(candidate.cell, candidate.driver_id, trip_id):
                    return MatchOutcome(trip_id, candidate, radius, seen)
        return MatchOutcome(trip_id, None, None, seen)

    def dispatch_trip(self, session, trip: Trip, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        outcome = self.find_driver(
            trip.pickup_lat, trip.pickup_lng, str(trip.id), exclude=set(trip.declined_by)
        )
        if outcome.driver is None:
            trips.defer_trip(session, trip, self.retry_delay, now=now)
            return False
        trips.mark_matched(session, trip, outcome.driver.driver_id, now=now)
        log.debug(
            "matched trip %s to %s at %.0fm after %d candidates",
            trip.id,
            outcome.driver.driver_id,
            outcome.driver.distance_m,
            outcome.candidates_seen,
        )
        return True

    def expire_offers(self, now: datetime | None = None) -> int:
        """Take back offers the driver never answered and free those drivers."""
        with self.session_factory() as session, session.begin():
            expired = [
                (trip.id, driver_id)
                for trip, driver_id in trips.expire_offers(session, self.offer_timeout, now=now)
            ]
        for trip_id, driver_id in expired:
            if not self.store.release_claim(driver_id, str(trip_id)):
                log.warning("driver %s was no longer claimed by trip %s", driver_id, trip_id)
        return len(expired)

    def run_once(self) -> int:
        """One sweep: expire stale offers, claim a batch of pending trips and try to
        match each. Returns matches."""
        timed_out = self.expire_offers()
        matched = 0
        deferred = 0
        with self.session_factory() as session, session.begin():
            for trip in trips.claim_pending(session, self.batch_size):
                if self.dispatch_trip(session, trip):
                    matched += 1
                else:
                    deferred += 1
        with self.stats.lock:
            self.stats.sweeps += 1
            self.stats.matched += matched
            self.stats.deferred += deferred
            self.stats.timed_out += timed_out
        return matched

    def run_forever(self, poll_interval_s: float, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                matched = self.run_once()
            except Exception:
                log.exception("dispatch sweep failed")
                matched = 0
            if matched == 0:
                stop.wait(poll_interval_s)
