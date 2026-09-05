"""Simulated drivers that post a position every second.

A driver wanders the grid until the location service reports it as busy, then
looks up its trip and accepts it (or declines it, with ``decline_rate``
probability, to exercise the rematch path), heads for the pickup, waits for
the rider and drives on to the dropoff. The location service advances the
trip from those pings and releases the driver at the dropoff, after which it
wanders again.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import random
import threading
import time

import httpx

from rideloop_common.config import get_settings
from sim.city import SimDriver, latlng_to_local

log = logging.getLogger("sim.drivers")


class DriverFleet:
    def __init__(
        self,
        location_url: str,
        ride_url: str,
        count: int,
        interval_s: float = 1.0,
        seed: int = 42,
        prefix: str = "drv",
        decline_rate: float = 0.0,
    ):
        self.location_url = location_url.rstrip("/")
        self.ride_url = ride_url.rstrip("/")
        self.interval_s = interval_s
        self.decline_rate = decline_rate
        self.accepted = 0
        self.declined = 0
        rng = random.Random(seed)
        self._rng = random.Random(rng.random())
        self.drivers = [
            SimDriver.spawn(f"{prefix}-{i:03d}", random.Random(rng.random())) for i in range(count)
        ]
        self.paused: set[str] = set()
        self.posts = 0
        self.errors = 0
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._client: httpx.AsyncClient | None = None

    def pause(self, driver_id: str) -> None:
        """Stop a driver's pings without removing it: this is how TTL expiry is shown."""
        self.paused.add(driver_id)

    async def start(self) -> None:
        limits = httpx.Limits(max_connections=64, max_keepalive_connections=64)
        self._client = httpx.AsyncClient(timeout=5.0, limits=limits)
        for i, driver in enumerate(self.drivers):
            self._tasks.append(asyncio.create_task(self._run_driver(driver, i)))

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._client:
            await self._client.aclose()

    async def _run_driver(self, driver: SimDriver, index: int) -> None:
        assert self._client is not None
        # spread the fleet over the interval so posts are not bunched
        await asyncio.sleep((index % 50) / 50 * self.interval_s)
        last = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            lat, lng, heading = driver.step(now - last)
            last = now
            if driver.driver_id not in self.paused:
                try:
                    resp = await self._client.post(
                        f"{self.location_url}/drivers/{driver.driver_id}/position",
                        json={"lat": lat, "lng": lng, "heading": heading},
                    )
                    resp.raise_for_status()
                    self.posts += 1
                    await self._follow_assignment(driver, resp.json())
                except httpx.HTTPError as exc:
                    self.errors += 1
                    log.debug("%s post failed: %s", driver.driver_id, exc)
            await asyncio.sleep(self.interval_s)

    async def _follow_assignment(self, driver: SimDriver, body: dict) -> None:
        assert self._client is not None
        trip_id = body.get("trip_id") if body.get("status") == "busy" else None
        if trip_id == driver.trip_id:
            return
        driver.trip_id = trip_id
        if trip_id is None:
            driver.clear_target()
            return
        answer = "decline" if self._rng.random() < self.decline_rate else "accept"
        try:
            resp = await self._client.post(
                f"{self.ride_url}/rides/{trip_id}/{answer}",
                params={"driver_id": driver.driver_id},
            )
            resp.raise_for_status()
            trip = resp.json()
        except (httpx.HTTPError, ValueError):
            driver.clear_target()
            return
        if answer == "decline":
            self.declined += 1
            driver.trip_id = None
            driver.clear_target()
            return
        self.accepted += 1
        driver.set_route(
            latlng_to_local(trip["pickup_lat"], trip["pickup_lng"]),
            latlng_to_local(trip["dropoff_lat"], trip["dropoff_lng"]),
        )


class FleetThread:
    """Run a DriverFleet on its own event loop in a background thread.

    The demo drives riders from the main loop; keeping the fleet's 300 posts per
    second on a separate loop stops the two workloads from starving each other.
    """

    def __init__(self, fleet: DriverFleet):
        self.fleet = fleet
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="driver-fleet", daemon=True)
        self._started = threading.Event()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.fleet.start())
        self._started.set()
        self.loop.run_forever()

    def start(self) -> None:
        self._thread.start()
        self._started.wait(timeout=30)

    def pause(self, driver_id: str) -> None:
        self.loop.call_soon_threadsafe(self.fleet.pause, driver_id)

    def stop(self) -> None:
        future = asyncio.run_coroutine_threadsafe(self.fleet.stop(), self.loop)
        future.result(timeout=30)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=10)


async def run(count: int, duration_s: float, interval_s: float, decline_rate: float) -> None:
    settings = get_settings()
    fleet = DriverFleet(
        settings.driver_location_url,
        settings.ride_request_url,
        count,
        interval_s,
        decline_rate=decline_rate,
    )
    await fleet.start()
    try:
        await asyncio.sleep(duration_s)
    finally:
        await fleet.stop()
    print(
        f"drivers={count} posts={fleet.posts} errors={fleet.errors} "
        f"accepted={fleet.accepted} declined={fleet.declined}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="simulate drivers posting positions")
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--decline-rate", type=float, default=0.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(args.count, args.duration, args.interval, args.decline_rate))


if __name__ == "__main__":
    main()
