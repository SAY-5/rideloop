"""Prometheus metrics shared by the services.

Every service exposes ``GET /metrics``. The dispatcher's counters are the
interesting ones: matches, match latency, trips that found no driver, claim
conflicts (a driver claimed by someone else between the query and the
conditional update) and TTL expiries the read path observed and cleaned up.
When ``PROMETHEUS_MULTIPROC_DIR`` is set (the containers run two uvicorn
workers) the counters are aggregated across worker processes.
"""

from __future__ import annotations

import os

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

MATCHES = Counter("rideloop_matches_total", "Trips matched to a driver")
MATCH_LATENCY = Histogram(
    "rideloop_match_latency_seconds",
    "Seconds from ride request to match",
    buckets=LATENCY_BUCKETS,
)
UNMATCHED = Counter("rideloop_unmatched_total", "Sweeps that found no claimable driver for a trip")
CLAIM_CONFLICTS = Counter(
    "rideloop_claim_conflicts_total",
    "Conditional driver claims that failed because the driver was no longer available",
)
TTL_EXPIRIES = Counter(
    "rideloop_ttl_expiries_total", "Expired driver positions dropped and deleted on read"
)
OFFERS = Counter("rideloop_offers_total", "Offer outcomes", ["outcome"])
MATCHES_PER_MINUTE = Gauge(
    "rideloop_matches_per_minute",
    "Matches in the trailing sixty seconds, from the dispatcher's own sweeps",
    multiprocess_mode="max",
)
SWEEPS = Counter("rideloop_dispatch_sweeps_total", "Dispatcher sweeps")
POSITIONS = Counter("rideloop_positions_total", "Driver position reports stored")
RIDES = Counter("rideloop_rides_total", "Ride requests created")
HTTP_REQUESTS = Counter(
    "rideloop_http_requests_total", "HTTP requests", ["service", "method", "path", "status"]
)
HTTP_LATENCY = Histogram(
    "rideloop_http_request_seconds",
    "HTTP request latency",
    ["service", "method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)


def registry() -> CollectorRegistry:
    """The registry to scrape: aggregated across workers when configured, else the default."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        reg = CollectorRegistry()
        multiprocess.MultiProcessCollector(reg)
        return reg
    return REGISTRY


def render() -> bytes:
    return generate_latest(registry())
