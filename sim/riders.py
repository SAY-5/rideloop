"""Simulated riders that request trips at a steady rate and ride them to completion."""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

import httpx

from rideloop_common.config import get_settings
from sim.city import random_point

log = logging.getLogger("sim.riders")

PICKUP_TO_START_S = 3.0
START_TO_COMPLETE_S = 4.0
MATCH_TIMEOUT_S = 20.0


@dataclass
class RideRecord:
    trip_id: str
    submitted_at: float
    matched_at: float | None = None
    match_latency_ms: int | None = None
    driver_id: str | None = None
    final_status: str = "requested"
    events: list[str] = field(default_factory=list)
    trip: dict = field(default_factory=dict)


class RiderLoad:
    def __init__(self, ride_url: str, rate_per_s: float, duration_s: float, seed: int = 7):
        self.ride_url = ride_url.rstrip("/")
        self.rate = rate_per_s
        self.duration = duration_s
        self.rng = random.Random(seed)
        self.records: list[RideRecord] = []
        self.submit_errors = 0

    async def run(self) -> list[RideRecord]:
        limits = httpx.Limits(max_connections=64, max_keepalive_connections=64)
        async with httpx.AsyncClient(timeout=5.0, limits=limits) as client:
            followers: list[asyncio.Task] = []
            total = int(self.rate * self.duration)
            gap = 1.0 / self.rate
            started = time.monotonic()
            for i in range(total):
                target = started + i * gap
                delay = target - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                record = await self._submit(client, i)
                if record is not None:
                    followers.append(asyncio.create_task(self._follow(client, record)))
            await asyncio.gather(*followers)
        return self.records

    async def _submit(self, client: httpx.AsyncClient, i: int) -> RideRecord | None:
        pickup = random_point(self.rng)
        dropoff = random_point(self.rng)
        body = {
            "rider_id": f"rider-{i:04d}",
            "pickup": {"lat": pickup[0], "lng": pickup[1]},
            "dropoff": {"lat": dropoff[0], "lng": dropoff[1]},
        }
        try:
            resp = await client.post(f"{self.ride_url}/rides", json=body)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            self.submit_errors += 1
            log.warning("submit failed: %s", exc)
            return None
        record = RideRecord(trip_id=resp.json()["id"], submitted_at=time.time())
        self.records.append(record)
        return record

    async def _follow(self, client: httpx.AsyncClient, record: RideRecord) -> None:
        deadline = time.monotonic() + MATCH_TIMEOUT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            try:
                trip = (await client.get(f"{self.ride_url}/rides/{record.trip_id}")).json()
            except (httpx.HTTPError, ValueError):
                continue
            if trip["status"] == "matched":
                record.matched_at = time.time()
                record.match_latency_ms = trip["match_latency_ms"]
                record.driver_id = trip["driver_id"]
                break
        else:
            record.final_status = "requested"
            return
        await asyncio.sleep(PICKUP_TO_START_S)
        await self._post(client, record, "start")
        await asyncio.sleep(START_TO_COMPLETE_S)
        trip = await self._post(client, record, "complete")
        if trip is not None:
            record.final_status = trip["status"]
            record.events = [e["event"] for e in trip.get("events", [])]
            record.trip = trip

    async def _post(self, client: httpx.AsyncClient, record: RideRecord, action: str):
        try:
            resp = await client.post(f"{self.ride_url}/rides/{record.trip_id}/{action}")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            log.debug("%s %s failed: %s", record.trip_id, action, exc)
            return None


def main() -> None:
    parser = argparse.ArgumentParser(description="submit ride requests at a fixed rate")
    parser.add_argument("--rate", type=float, default=10.0, help="rides per second")
    parser.add_argument("--duration", type=float, default=60.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    load = RiderLoad(get_settings().ride_request_url, args.rate, args.duration)
    records = asyncio.run(load.run())
    matched = sum(1 for r in records if r.matched_at)
    print(f"submitted={len(records)} matched={matched} errors={load.submit_errors}")


if __name__ == "__main__":
    main()
