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
import multiprocessing
import random
import time
from dataclasses import dataclass, field
from itertools import pairwise

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
        recorder=None,
        first_index: int = 0,
        clock_start: float | None = None,
    ):
        self.location_url = location_url.rstrip("/")
        self.ride_url = ride_url.rstrip("/")
        self.interval_s = interval_s
        self.decline_rate = decline_rate
        self.recorder = recorder
        self.started_at = clock_start if clock_start is not None else time.monotonic()
        self.accepted = 0
        self.declined = 0
        rng = random.Random(seed)
        self._rng = random.Random(rng.random())
        self.drivers = [
            SimDriver.spawn(f"{prefix}-{i:03d}", random.Random(rng.random()))
            for i in range(first_index, first_index + count)
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
                    if self.recorder is not None:
                        self.recorder.position(
                            now - self.started_at, driver.driver_id, lat, lng, heading
                        )
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
        if trip_id is None:
            driver.trip_id = None
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
            # leave trip_id unset so the next ping answers the offer again
            driver.clear_target()
            return
        driver.trip_id = trip_id
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


@dataclass
class FleetReport:
    posts: int = 0
    errors: int = 0
    accepted: int = 0
    declined: int = 0
    events: list = field(default_factory=list)

    def merge(self, other: FleetReport) -> None:
        self.posts += other.posts
        self.errors += other.errors
        self.accepted += other.accepted
        self.declined += other.declined
        self.events.extend(other.events)


def _fleet_worker(conn, kwargs: dict, record: bool) -> None:
    """Entry point of one fleet process: run a slice of the fleet until told to stop."""
    from sim.replay import Recorder

    async def main() -> None:
        recorder = Recorder() if record else None
        fleet = DriverFleet(recorder=recorder, **kwargs)
        await fleet.start()
        conn.send(("started", [d.driver_id for d in fleet.drivers]))
        loop = asyncio.get_running_loop()
        while True:
            command, arg = await loop.run_in_executor(None, conn.recv)
            if command == "pause":
                fleet.pause(arg)
            elif command == "stop":
                break
        await fleet.stop()
        conn.send(
            (
                "report",
                FleetReport(
                    posts=fleet.posts,
                    errors=fleet.errors,
                    accepted=fleet.accepted,
                    declined=fleet.declined,
                    events=recorder.events if recorder else [],
                ),
            )
        )

    asyncio.run(main())


class FleetProcesses:
    """Run a DriverFleet split across worker processes.

    Three hundred drivers posting every second plus the rider load is more
    than one Python process can drive without starving itself, and a starved
    fleet shows up as late pings and expired offers. Each worker owns a slice
    of the drivers and its own event loop; the parent only sends pause/stop
    commands and collects the counters and recorded events at the end.
    """

    def __init__(
        self,
        location_url: str,
        ride_url: str,
        count: int,
        workers: int = 3,
        decline_rate: float = 0.0,
        record: bool = False,
        clock_start: float | None = None,
    ):
        self.count = count
        self.clock_start = clock_start if clock_start is not None else time.monotonic()
        self.driver_ids: list[str] = []
        self._workers: list[tuple[multiprocessing.Process, object]] = []
        ctx = multiprocessing.get_context("spawn")
        workers = max(1, min(workers, count))
        bounds = [round(i * count / workers) for i in range(workers + 1)]
        for index, (first, last) in enumerate(pairwise(bounds)):
            parent, child = ctx.Pipe()
            kwargs = {
                "location_url": location_url,
                "ride_url": ride_url,
                "count": last - first,
                "first_index": first,
                "seed": 42 + index,
                "decline_rate": decline_rate,
                "clock_start": self.clock_start,
            }
            proc = ctx.Process(
                target=_fleet_worker,
                args=(child, kwargs, record),
                name=f"fleet-{index}",
                daemon=True,
            )
            self._workers.append((proc, parent))

    def start(self) -> None:
        for proc, _ in self._workers:
            proc.start()
        for _, conn in self._workers:
            command, ids = conn.recv()
            assert command == "started"
            self.driver_ids.extend(ids)

    def pause(self, driver_id: str) -> None:
        for _, conn in self._workers:
            conn.send(("pause", driver_id))

    def stop(self) -> FleetReport:
        report = FleetReport()
        for _, conn in self._workers:
            conn.send(("stop", None))
        for proc, conn in self._workers:
            command, part = conn.recv()
            assert command == "report"
            report.merge(part)
            proc.join(timeout=10)
        return report


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
