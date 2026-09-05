"""Record a ride stream and replay it deterministically for regression comparison.

A recording is a JSON lines file: a header, then driver position reports and
ride requests with a relative timestamp ``t`` in seconds, then an optional
summary. ``run`` replays the events in order against the matcher on a virtual
clock: positions go into the driver store stamped with the virtual time,
each ride request is inserted and followed by a dispatcher sweep at that same
instant, offers are accepted on the spot and rides complete a fixed
``RIDE_DURATION_S`` later so drivers cycle back into the pool. Given the same
file the matcher sees the same drivers in the same places at the same
moments, so the match count, the rider-to-driver assignments and the
latencies come out identical run after run; the summary's fingerprint makes
that a one-line check.

    uv run python -m sim.replay synth --seed 7 --out ride-stream.jsonl
    uv run python -m sim.replay run ride-stream.jsonl --write-summary
    uv run python -m sim.replay run ride-stream.jsonl            # compare against it

``make demo --record`` (``sim.demo --record path``) writes the live stream of
a demo run with the live match count as its summary.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import random
import sys
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from rideloop_common import trips
from rideloop_common.config import Settings, get_settings
from rideloop_common.db import Trip, make_engine, make_session_factory
from rideloop_common.dynamo import DriverPositionStore, ensure_table
from rideloop_common.models import Coordinate, DriverStatus, RideRequest, TripStatus
from services.dispatch.matcher import Matcher
from sim.city import SimDriver, random_point

FORMAT_VERSION = 1
RIDE_DURATION_S = 7.0
POSITION_TTL_S = 3600


@dataclass(order=True)
class Event:
    t: float
    seq: int
    kind: str = field(compare=False)
    data: dict[str, Any] = field(compare=False, default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "t": round(self.t, 3), **self.data}


@dataclass
class Summary:
    rides: int
    matched: int
    unmatched: int
    matches_per_minute: float
    p50_latency_ms: float
    p95_latency_ms: float
    fingerprint: str

    def to_json(self) -> dict[str, Any]:
        return {"kind": "summary", **asdict(self)}


class Recorder:
    """Collects events from a live run (or a synthesizer) and writes the file."""

    def __init__(self, seed: int | None = None, drivers: int = 0):
        self.events: list[Event] = []
        self.header = {
            "kind": "header",
            "version": FORMAT_VERSION,
            "seed": seed,
            "drivers": drivers,
        }
        self._seq = 0

    def position(self, t: float, driver_id: str, lat: float, lng: float, heading: float) -> None:
        self._add(t, "position", driver_id=driver_id, lat=lat, lng=lng, heading=heading)

    def ride(self, t: float, rider_id: str, pickup, dropoff) -> None:
        self._add(t, "ride", rider_id=rider_id, pickup=list(pickup), dropoff=list(dropoff))

    def _add(self, t: float, kind: str, **data) -> None:
        self.events.append(Event(t, self._seq, kind, data))
        self._seq += 1

    def write(self, path: Path, summary: Summary | None = None) -> None:
        with path.open("w") as fh:
            fh.write(json.dumps(self.header) + "\n")
            for event in sorted(self.events):
                fh.write(json.dumps(event.to_json()) + "\n")
            if summary is not None:
                fh.write(json.dumps(summary.to_json()) + "\n")


def synthesize(seed: int, drivers: int, rate: float, duration: float) -> Recorder:
    """A deterministic stream: drivers wander the grid, riders request at a fixed rate."""
    rng = random.Random(seed)
    recorder = Recorder(seed=seed, drivers=drivers)
    fleet = [SimDriver.spawn(f"drv-{i:03d}", random.Random(rng.random())) for i in range(drivers)]
    for second in range(int(duration) + 1):
        for driver in fleet:
            lat, lng, heading = driver.step(1.0)
            recorder.position(float(second), driver.driver_id, lat, lng, heading)
    rider_rng = random.Random(rng.random())
    for i in range(int(rate * duration)):
        recorder.ride(i / rate, f"rider-{i:04d}", random_point(rider_rng), random_point(rider_rng))
    return recorder


def read(path: Path) -> tuple[dict[str, Any], list[Event], Summary | None]:
    header: dict[str, Any] = {}
    events: list[Event] = []
    summary: Summary | None = None
    with path.open() as fh:
        for seq, line in enumerate(fh):
            row = json.loads(line)
            kind = row.pop("kind")
            if kind == "header":
                header = row
            elif kind == "summary":
                summary = Summary(**row)
            else:
                events.append(Event(row.pop("t"), seq, kind, row))
    if header.get("version") != FORMAT_VERSION:
        raise ValueError(f"unsupported recording version {header.get('version')!r}")
    return header, sorted(events), summary


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return float(ordered[index])


def fingerprint(assignments: Iterable[tuple[str, str | None, int | None]]) -> str:
    digest = hashlib.sha256()
    for rider_id, driver_id, latency_ms in sorted(assignments):
        digest.update(f"{rider_id}={driver_id}@{latency_ms}\n".encode())
    return digest.hexdigest()[:16]


def replay(
    events: list[Event],
    store: DriverPositionStore,
    session_factory,
    settings: Settings | None = None,
    base: datetime | None = None,
) -> Summary:
    """Run the events through the matcher on a virtual clock and summarize."""
    settings = settings or get_settings()
    base = base or datetime.now(UTC).replace(microsecond=0)
    matcher = Matcher(
        store,
        session_factory,
        initial_radius_m=settings.dispatch_initial_radius_m,
        max_radius_m=settings.dispatch_max_radius_m,
        retry_delay_s=0.0,
        batch_size=settings.dispatch_batch_size,
        offer_timeout_s=settings.dispatch_offer_timeout_s,
    )
    due: list[tuple[float, int, Any]] = []
    rides: dict[Any, str] = {}
    first_request: float | None = None
    last_match: float | None = None

    def complete_due(t: float) -> None:
        while due and due[0][0] <= t:
            _, _, trip_id = heapq.heappop(due)
            with session_factory() as s, s.begin():
                trip = s.get(Trip, trip_id)
                if trip.status in trips.ACTIVE:
                    trips.transition(s, trip, TripStatus.COMPLETED, now=base + timedelta(seconds=t))
                    driver_id = trip.driver_id
                else:
                    driver_id = None
            if driver_id:
                store.set_status(driver_id, DriverStatus.AVAILABLE)

    def accept_and_schedule(t: float) -> None:
        nonlocal last_match
        now = base + timedelta(seconds=t)
        with session_factory() as s, s.begin():
            open_offers = s.scalars(
                select(Trip).where(Trip.status == TripStatus.MATCHED, Trip.accepted_at.is_(None))
            ).all()
            for trip in open_offers:
                trips.accept_offer(s, trip, trip.driver_id, now=now)
                heapq.heappush(due, (t + RIDE_DURATION_S, len(due), trip.id))
                last_match = t

    for event in events:
        complete_due(event.t)
        now = base + timedelta(seconds=event.t)
        if event.kind == "position":
            store.put_position(
                event.data["driver_id"],
                event.data["lat"],
                event.data["lng"],
                event.data.get("heading", 0.0),
                ttl_seconds=POSITION_TTL_S,
                now=now,
            )
        elif event.kind == "ride":
            first_request = event.t if first_request is None else first_request
            request = RideRequest(
                rider_id=event.data["rider_id"],
                pickup=Coordinate(lat=event.data["pickup"][0], lng=event.data["pickup"][1]),
                dropoff=Coordinate(lat=event.data["dropoff"][0], lng=event.data["dropoff"][1]),
            )
            with session_factory() as s, s.begin():
                rides[trips.create_trip(s, request, now=now).id] = request.rider_id
            matcher.run_once(now=now)
            accept_and_schedule(event.t)

    with session_factory() as s:
        rows = s.execute(
            select(Trip.id, Trip.driver_id, Trip.match_latency_ms).where(Trip.id.in_(rides))
        ).all()
    assignments = [(rides[trip_id], driver_id, latency) for trip_id, driver_id, latency in rows]
    latencies = [float(latency) for _, driver_id, latency in assignments if driver_id]
    matched = len(latencies)
    window = (last_match - first_request) if matched and last_match is not None else 0.0
    return Summary(
        rides=len(assignments),
        matched=matched,
        unmatched=len(assignments) - matched,
        matches_per_minute=round(matched / (window / 60), 1) if window > 0 else float(matched),
        p50_latency_ms=percentile(latencies, 50),
        p95_latency_ms=percentile(latencies, 95),
        fingerprint=fingerprint(assignments),
    )


def compare(expected: Summary, actual: Summary) -> list[str]:
    """Human-readable differences that matter for a regression check."""
    diffs = []
    if actual.matched != expected.matched:
        diffs.append(f"matched {actual.matched} (recorded {expected.matched})")
    if actual.rides != expected.rides:
        diffs.append(f"rides {actual.rides} (recorded {expected.rides})")
    if expected.fingerprint and actual.fingerprint != expected.fingerprint:
        diffs.append(f"assignments {actual.fingerprint} (recorded {expected.fingerprint})")
    return diffs


def _stores(in_memory: bool) -> Iterator[tuple[DriverPositionStore, Any]]:
    settings = get_settings()
    if in_memory:
        from moto import mock_aws

        with mock_aws():
            local = settings.model_copy(
                update={
                    "dynamodb_endpoint": None,
                    "aws_access_key_id": "testing",
                    "aws_secret_access_key": "testing",
                }
            )
            ensure_table(local)
            yield DriverPositionStore(local), make_session_factory(make_engine(local))
        return
    ensure_table(settings)
    yield DriverPositionStore(settings), make_session_factory(make_engine(settings))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="record and replay ride streams")
    sub = parser.add_subparsers(dest="command", required=True)
    synth = sub.add_parser("synth", help="write a deterministic synthetic stream")
    synth.add_argument("--seed", type=int, default=7)
    synth.add_argument("--drivers", type=int, default=60)
    synth.add_argument("--rate", type=float, default=3.0)
    synth.add_argument("--duration", type=float, default=30.0)
    synth.add_argument("--out", type=Path, required=True)
    run = sub.add_parser("run", help="replay a stream through the matcher")
    run.add_argument("path", type=Path)
    run.add_argument("--write-summary", action="store_true", help="store this run's summary")
    run.add_argument(
        "--in-memory",
        action="store_true",
        help="use an in-process DynamoDB instead of the endpoint",
    )
    args = parser.parse_args(argv)

    if args.command == "synth":
        synthesize(args.seed, args.drivers, args.rate, args.duration).write(args.out)
        print(f"wrote {args.out}")
        return 0

    header, events, recorded = read(args.path)
    for store, session_factory in _stores(args.in_memory):
        summary = replay(events, store, session_factory)
    print(
        f"replayed {summary.rides} rides over {len(events)} events: "
        f"matched {summary.matched}, unmatched {summary.unmatched}, "
        f"{summary.matches_per_minute:.0f}/min, p50 {summary.p50_latency_ms:.0f} ms, "
        f"p95 {summary.p95_latency_ms:.0f} ms, fingerprint {summary.fingerprint}"
    )
    if args.write_summary:
        recorder = Recorder(seed=header.get("seed"), drivers=header.get("drivers", 0))
        recorder.events = events
        recorder.write(args.path, summary)
        print(f"summary written to {args.path}")
        return 0
    if recorded is None:
        print("no recorded summary to compare against (use --write-summary)")
        return 0
    diffs = compare(recorded, summary)
    if diffs:
        print("REGRESSION: " + "; ".join(diffs))
        return 1
    print(f"matches recording: {recorded.matched} matched, fingerprint {recorded.fingerprint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
