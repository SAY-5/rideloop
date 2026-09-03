"""End-to-end demo: seed a fleet, submit rides for a minute, print what happened.

Every number printed here comes from the running system: the rider records
collected by the load generator and the dispatch service's own stats endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from datetime import datetime

import httpx

from rideloop_common.config import get_settings
from sim.city import CITY_CENTER
from sim.drivers import DriverFleet
from sim.riders import RiderLoad

MAP_RADIUS_M = 4500.0


async def wait_healthy(client: httpx.AsyncClient, urls: list[str], timeout_s: float = 120) -> None:
    deadline = time.monotonic() + timeout_s
    pending = set(urls)
    while pending and time.monotonic() < deadline:
        for url in list(pending):
            try:
                if (await client.get(f"{url}/healthz")).status_code == 200:
                    pending.discard(url)
            except httpx.HTTPError:
                pass
        if pending:
            await asyncio.sleep(1)
    if pending:
        raise SystemExit(f"services not healthy: {sorted(pending)}")


async def visible_drivers(client: httpx.AsyncClient, location_url: str) -> set[str]:
    resp = await client.get(
        f"{location_url}/drivers/nearby",
        params={
            "lat": CITY_CENTER[0],
            "lng": CITY_CENTER[1],
            "radius_m": MAP_RADIUS_M,
            "limit": 1000,
        },
    )
    resp.raise_for_status()
    return {d["driver_id"] for d in resp.json()}


def percentile(values: list[int], pct: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return float(ordered[index])


async def run(drivers: int, rate: float, duration: float) -> int:
    settings = get_settings()
    loc, ride, dispatch = (
        settings.driver_location_url,
        settings.ride_request_url,
        settings.dispatch_url,
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        print("waiting for services...")
        await wait_healthy(client, [loc, ride, dispatch])

        print(f"seeding {drivers} drivers...")
        fleet = DriverFleet(loc, ride, drivers)
        await fleet.start()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            seen = await visible_drivers(client, loc)
            if len(seen) >= drivers * 0.95:
                break
            await asyncio.sleep(1)
        print(f"{len(seen)} drivers visible on the map")

        # TTL evidence: one driver goes quiet; it must vanish once its ttl passes.
        probe = fleet.drivers[0].driver_id
        fleet.pause(probe)
        probe_item = (await client.get(f"{loc}/drivers/{probe}")).json()
        stopped_at = time.time()
        ttl_epoch = int(probe_item["ttl"])
        ttl_window = ttl_epoch - int(stopped_at)
        print(f"driver {probe} stopped pinging (ttl in {ttl_window}s)")

        print(f"submitting rides at {rate:g}/s for {duration:g}s...")
        load = RiderLoad(ride, rate, duration)
        rider_task = asyncio.create_task(load.run())

        await asyncio.sleep(3)
        probe_visible_early = probe in await visible_drivers(client, loc)
        wait_for = ttl_epoch + 2 - time.time()
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        probe_visible_late = probe in await visible_drivers(client, loc)

        records = await rider_task
        stats = (await client.get(f"{dispatch}/dispatch/stats")).json()
        await fleet.stop()

    matched = [r for r in records if r.matched_at is not None]
    latencies = [r.match_latency_ms for r in matched if r.match_latency_ms is not None]
    completed = sum(1 for r in records if r.final_status == "completed")
    if matched:
        first_submit = min(r.submitted_at for r in records)
        last_match = max(r.matched_at for r in matched)
        window_s = max(last_match - first_submit, 1e-6)
        per_minute = len(matched) / (window_s / 60)
    else:
        window_s = 0.0
        per_minute = 0.0

    ttl_ok = probe_visible_early and not probe_visible_late
    stamp = datetime.fromtimestamp(stopped_at).strftime("%H:%M:%S")
    print()
    print("================ RideLoop demo summary ================")
    print(
        f"drivers seeded            {drivers} ({fleet.posts} position posts, {fleet.errors} errors)"
    )
    print(f"rides submitted           {len(records)} ({rate:g}/s for {duration:g}s)")
    print(f"rides matched             {len(matched)} ({len(matched) / max(len(records), 1):.1%})")
    print(f"rides completed           {completed}")
    print(f"rides left requested      {len(records) - len(matched)}")
    print(f"matches per minute        {per_minute:.0f} (over {window_s:.1f}s)")
    if latencies:
        print(
            f"match latency p50 / p95   {percentile(latencies, 50):.0f} ms / "
            f"{percentile(latencies, 95):.0f} ms (mean {statistics.mean(latencies):.0f} ms)"
        )
    print(
        f"dispatch service stats    matched_total={stats['matched_total']} "
        f"last_minute={stats['matches_last_minute']} "
        f"p50={stats['p50_match_latency_ms']} p95={stats['p95_match_latency_ms']} "
        f"sweeps={stats['sweeps']}"
    )
    print(
        f"ttl expiry                driver {probe} stopped at {stamp}; "
        f"visible after 3s: {'yes' if probe_visible_early else 'no'}; "
        f"visible after ttl ({ttl_window}s): {'yes' if probe_visible_late else 'no'} "
        f"-> {'expired as expected' if ttl_ok else 'UNEXPECTED'}"
    )
    print("=======================================================")
    return 0 if (ttl_ok and matched) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="run the full RideLoop demo")
    parser.add_argument("--drivers", type=int, default=300)
    parser.add_argument("--rate", type=float, default=10.0)
    parser.add_argument("--duration", type=float, default=60.0)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.drivers, args.rate, args.duration)))


if __name__ == "__main__":
    main()
