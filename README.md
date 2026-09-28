# RideLoop

Ride request and dispatch platform: three Python microservices, a DynamoDB
driver index partitioned by geohash with TTL expiry, a PostgreSQL trip schema,
and a React rider map. The local demo submits synthetic traffic at 10 rides
per second; the browser showcase models the dispatch path on a virtual clock.

| service | port | stores | job |
| --- | --- | --- | --- |
| `driver_location` | 8001 | DynamoDB, PostgreSQL | ingest driver pings, answer "who is near this point", move a busy driver's trip along |
| `ride_request` | 8002 | PostgreSQL, DynamoDB | create trips, expose their lifecycle with the driver's position and pickup ETA, release drivers on completion |
| `dispatch` | 8003 | PostgreSQL, DynamoDB | match requested trips to the nearest available driver, report throughput and the surge heatmap |
| `web` | 5173 | | rider map: drivers, pickup pin, request, matched driver approaching |

```
        drivers (sim/drivers.py)                       riders (sim/riders.py, web/)
            |  POST /drivers/{id}/position                 |  POST /rides
            v                                              v
   +------------------+                          +------------------+
   | driver_location  |                          |   ride_request   |
   +--------+---------+                          +--------+---------+
            | put / query by geohash cell                 | insert trip (status=requested)
            v                                              v
   +------------------+   nearby + conditional   +------------------+
   |    DynamoDB      | <----------------------- |     dispatch     |
   | driver_positions |   claim (busy)           |  matcher loop    |
   |  pk=cell(gh5)    |                          +--------+---------+
   |  sk=driver_id    |                                   | FOR UPDATE SKIP LOCKED,
   |  ttl attribute   |                                   | set matched + latency
   +------------------+                                   v
                                                 +------------------+
                                                 |    PostgreSQL    |
                                                 | trips, drivers,  |
                                                 | ride_events      |
                                                 +------------------+
```

## Run the demo

Requires Docker, `uv` and Python 3.12. `make demo` builds the images, starts
PostgreSQL, DynamoDB Local and the three services, seeds 300 simulated drivers
that post a position every second (spread over three worker processes so the
load generator cannot starve itself), submits rides at 10 per second for 60
seconds, has drivers accept the offers (and decline one in ten, to exercise
the rematch), rides each one to completion, and prints a summary. Every
figure is read back from the running system (trip timestamps from
PostgreSQL, fleet visibility from DynamoDB, the dispatch service's own stats
endpoint).

### Historical v5 transcript — unverified

The following summary was recorded in documentation at
[`905549c`](https://github.com/SAY-5/rideloop/blob/905549cfaa0daa1b58f920e84c61b1cfa725cbb8/README.md).
No raw run log, UTC run timestamp or machine metadata was retained in the
repository. It is not a current verified benchmark. The earlier showcase's
601/min and 59/101 ms came from a different, pre-offer/decline transcript;
neither is a valid direct comparison with the browser model. See
[measurement provenance](docs/measurement-provenance.md) for both sources and
the evidence required for new claims. Documentation commit time is not run time.

```
$ make demo
...
================ RideLoop demo summary ================
drivers seeded            300 (14305 position posts, 3 errors)
rides submitted           600 (10/s for 60s)
rides matched             600 (100.0%)
rides completed           600
rides left requested      0
matches per minute        586 (600 matches over 61.4s, first request to last match)
match latency p50 / p95   62 ms / 1101 ms (mean 181 ms)
offers                    600 accepted, 51 declined by drivers (decline rate 10%); 51 declines and 0 timeouts re-queued, 48 of the matched rides went through a rematch
dispatch service stats    matched_total=600 last_minute=484 p50=63.0 p95=1243.0499999999968 sweeps=1165
ttl expiry                driver drv-000 stopped at 15:16:15; visible after 3s: yes; visible after ttl (13s): no -> expired as expected
=======================================================
```

The demo compose file sets `POSITION_TTL_SECONDS=20` so the expiry is visible
within the run; the service default is 60 s. The transcript reports a higher
p95 after offer declines and rematching were introduced. Without the raw
latency samples and environment metadata, that observation is not a measured
causal attribution or a capacity claim. While the stack is up,
`curl localhost:8003/metrics` exposes the live service's Prometheus counters.

If 5432 or 8000 are taken on your machine:

```
POSTGRES_HOST_PORT=5435 DYNAMODB_HOST_PORT=8100 make demo
```

To watch it on the map, leave the stack up (`docker compose up -d --wait`),
run `make web`, open http://localhost:5173, then run
`uv run python -m sim.drivers --count 300 --duration 600` for a fleet to look
at. Click the map to drop a pickup and a dropoff, request a ride, and the
matched driver turns green and heads for the pin while the trip moves through
requested, matched, en route and completed.

## Development

```
make setup      # uv sync, pnpm install
make test-db    # throwaway PostgreSQL on localhost:5434 for the integration tests
make test       # pytest: unit + integration (moto for DynamoDB, real PostgreSQL)
make lint       # ruff check, ruff format --check, eslint
make migrate    # alembic upgrade head against DATABASE_URL
make tables     # create the DynamoDB table with TTL against DYNAMODB_ENDPOINT
```

Tests cover geohash vectors and neighbors, haversine, input validation, the
TTL attribute and read-side expiry filter, cell changes carrying dispatch
status, the matcher's nearest-first choice and expanding-radius fallback,
conditional claims under concurrent matchers, the trip lifecycle with its event
trail, the position-driven en_route / arrived / in_trip / completed
progression, the pickup ETA against a simulated grid drive (within 15%),
migrations up and down including the enum rebuild, the surge multiplier
climbing over a burst of requests in one cell and cooling off with the
half-life, the heatmap ordering, offers that must be accepted before pings
move the trip, declines and timeouts releasing the claim and rematching
without the decliner, the Prometheus counters after a sweep, a claim race and
an expiry, a replayed stream reproducing its own matches and fingerprint, and
an in-process run of 500 trips that must sustain at least 500 matches per
minute. CI (`.github/workflows/ci.yml`) runs
the same steps with a `postgres:16` service container, a separate job for
the `web/` rider app, and an independent `showcase/` job for its locked build,
simulation selfcheck and rendered provenance regression tests.

## Configuration

| variable | default | used by |
| --- | --- | --- |
| `DYNAMODB_ENDPOINT` | `http://localhost:8000` | all; unset it to use AWS |
| `DRIVER_POSITIONS_TABLE` | `driver_positions` | all |
| `POSITION_TTL_SECONDS` | `60` | driver_location |
| `CELL_PRECISION` | `5` | all |
| `DATABASE_URL` | `postgresql+psycopg://rideloop:rideloop@localhost:5432/rideloop` | ride_request, dispatch |
| `DISPATCH_INITIAL_RADIUS_M` / `DISPATCH_MAX_RADIUS_M` | `500` / `4000` | dispatch |
| `DISPATCH_RETRY_DELAY_S` | `1.0` | dispatch |
| `DISPATCH_OFFER_TIMEOUT_S` | `15.0` | dispatch |
| `DISPATCH_POLL_INTERVAL_S` | `0.1` | dispatch |
| `SURGE_HALF_LIFE_S` / `SURGE_STEP` / `SURGE_MAX_MULTIPLIER` | `60` / `0.5` / `3.0` | ride_request, dispatch |
| `DRIVER_LOCATION_URL` / `RIDE_REQUEST_URL` / `DISPATCH_URL` | `http://localhost:800{1,2,3}` | simulators |

## API

### driver_location (8001)

| method | path | notes |
| --- | --- | --- |
| `POST` | `/drivers/{id}/position` | body `{lat, lng, heading}`; upserts the cell item, refreshes `ttl`, keeps dispatch status, updates the smoothed `speed_mps`; a busy driver's ping also advances its trip (see lifecycle below) |
| `GET` | `/drivers/nearby?lat&lng&radius_m&status&limit` | drivers within `radius_m` (max 10 km), nearest first, expired excluded |
| `GET` | `/drivers/{id}` | current position and status |
| `PUT` | `/drivers/{id}/status?status=` | `available`, `busy` or `offline` |
| `DELETE` | `/drivers/{id}` | remove the driver |

### ride_request (8002)

| method | path | notes |
| --- | --- | --- |
| `POST` | `/rides` | body `{rider_id, pickup: {lat, lng}, dropoff: {lat, lng}}`; returns the trip with status `requested`, its `pickup_cell` and the `surge_multiplier` it was priced at |
| `GET` | `/rides/surge?lat&lng` | the cell a pickup at this point falls in with its current `demand`, `supply` and `multiplier` |
| `GET` | `/rides/{id}` | trip with its `events`, plus `driver_position` (lat, lng, heading, speed_mps, distance_to_pickup_m, updated_at) and `pickup_eta_s` while a driver is assigned |
| `GET` | `/rides?status&limit` | recent trips (no driver position lookup) |
| `POST` | `/rides/{id}/accept?driver_id=` | the offered driver takes the trip; sets `accepted_at`, after which its pings move the trip along |
| `POST` | `/rides/{id}/decline?driver_id=` | the offered driver passes: the claim is released, the trip goes back to `requested` with the driver in `declined_by`, and the next sweep rematches it to someone else |
| `GET` | `/drivers/{id}/acceptance` | `offers`, `accepts`, `declines` (timeouts included) and `acceptance_rate` for a driver |
| `POST` | `/rides/{id}/start` | `matched` to `en_route` (rider-side shortcut; pings do this on their own) |
| `POST` | `/rides/{id}/complete` | any active state to `completed`; frees the driver |
| `POST` | `/rides/{id}/cancel` | `requested`/`matched`/`en_route`/`arrived` to `cancelled`; frees the driver |

Trip lifecycle: `requested` -> `matched` -> `en_route` -> `arrived` ->
`in_trip` -> `completed`, with `cancelled` reachable from every state before
the rider is aboard. A match is an offer: the trip carries `offered_at` and
the driver has `DISPATCH_OFFER_TIMEOUT_S` (15 s) to accept or decline. A
decline, or silence past the timeout, releases the DynamoDB claim with a
conditional update, appends the driver to `declined_by`, and puts the trip
back in the queue where the next sweep matches it to the nearest driver not
in that list. The transitions after acceptance are driven by the assigned
driver's position reports: the first ping after acceptance sets
`en_route`, a ping within 40 m (route distance) of the pickup sets `arrived`,
pulling 120 m away from the pickup again sets `in_trip`, and a ping within
40 m of the dropoff sets `completed` and releases the driver. Every hop is
timestamped (`matched_at`, `arrived_at`, `started_at`, `completed_at`) and
recorded in `events`.

The pickup ETA is `route_distance / speed + 15 s`, where route distance is the
north-south plus east-west (L1) distance, which is what a car on a street grid
actually drives, and speed is an exponentially smoothed estimate from the
driver's last pings, floored at 3 m/s so a parked driver still gets a finite
ETA.

### dispatch (8003)

| method | path | notes |
| --- | --- | --- |
| `GET` | `/dispatch/stats` | `matched_total`, `pending`, `matches_last_minute`, `matches_per_minute`, `p50_match_latency_ms`, `p95_match_latency_ms`, `offers_declined`, `offers_timed_out`, `sweeps`, `uptime_s` |
| `GET` | `/dispatch/heatmap` | every cell with recent demand or available drivers: `cell`, `lat`, `lng`, `demand`, `supply`, `multiplier`, hottest first |

Surge pricing works per precision-5 cell. Demand is the sum of recent ride
requests whose pickup is in the cell, each weighted by `0.5 ^ (age /
SURGE_HALF_LIFE_S)`, so a burst pushes the number up and it halves every
minute on its own. Supply is the count of available, unexpired drivers in the
cell. The multiplier is 1.0 while demand does not exceed supply and otherwise
`1 + SURGE_STEP * (demand / supply - 1)`, capped at `SURGE_MAX_MULTIPLIER`.
Nothing is counted incrementally: both numbers are read from the stores at
request time.

All three expose `GET /healthz`, Prometheus `GET /metrics` and interactive
docs at `/docs`.

## Metrics

Every service serves `GET /metrics` in the Prometheus text format
(`prometheus-client`; the containers run two uvicorn workers and aggregate
through `PROMETHEUS_MULTIPROC_DIR`). HTTP requests are counted and timed per
service, method and route (`rideloop_http_requests_total`,
`rideloop_http_request_seconds`). The dispatcher's counters:

| metric | meaning |
| --- | --- |
| `rideloop_matches_total` | trips matched to a driver |
| `rideloop_match_latency_seconds` | histogram of request-to-match latency |
| `rideloop_matches_per_minute` | matches in the trailing 60 s, from the sweep loop |
| `rideloop_unmatched_total` | sweeps that found no claimable driver for a trip (the trip is retried) |
| `rideloop_claim_conflicts_total` | conditional claims that lost to a concurrent matcher or an expired driver |
| `rideloop_ttl_expiries_total` | expired driver rows the read path dropped, counted once per expiry |
| `rideloop_offers_total{outcome}` | `accepted`, `declined`, `timed_out` |
| `rideloop_dispatch_sweeps_total`, `rideloop_positions_total`, `rideloop_rides_total` | work counters |

TTL expiry is observable because the nearby query filters `ttl` on the
client and, on first sight of an expired row, stamps it with the ttl that
lapsed (a conditional update that fails if the row was refreshed or already
stamped), so each expiry is counted exactly once even though DynamoDB's own
sweep may lag by minutes. The row itself is left for that sweep: a driver
that resumes pinging keeps its dispatch status and trip.

## Replay

`sim/replay.py` records a ride stream (driver position reports and ride
requests with relative timestamps, JSON lines) and replays it through the
matcher on a virtual clock, so the same file produces the same matches, the
same rider-to-driver assignments and the same latencies every run. The
summary line carries a fingerprint of the assignments; a second run compares
against it and exits 1 on any drift, which turns a matcher change into a
one-command regression check.

```
make replay                                   # synthesize, replay, replay again and compare
uv run python -m sim.replay synth --seed 7 --drivers 60 --rate 3 --duration 30 --out s.jsonl
uv run python -m sim.replay run s.jsonl --in-memory --write-summary
uv run python -m sim.replay run s.jsonl --in-memory       # exit 1 if matches differ
uv run python -m sim.demo --record live.jsonl             # record a real demo run
```

`--in-memory` uses an in-process DynamoDB (moto) so the check needs only
PostgreSQL; without it the replay runs against `DYNAMODB_ENDPOINT`.

## Schema

DynamoDB `driver_positions`: partition key `cell` (geohash precision 5), sort
key `driver_id`, attributes `geohash` (precision 6), `lat`, `lng`, `heading`,
`speed_mps`, `status`, `trip_id`, `updated_at`, `ttl` (TTL attribute), GSI
`by_driver`.

PostgreSQL (Alembic revisions `0001` to `0004`):

```
trips        id uuid pk, rider_id, pickup_lat, pickup_lng, dropoff_lat, dropoff_lng,
             status trip_status, driver_id, requested_at, matched_at, offered_at,
             accepted_at, arrived_at, started_at, completed_at, match_latency_ms,
             pickup_eta_s, dispatch_attempts, next_attempt_at, pickup_cell,
             surge_multiplier, declined_by varchar[]
             index (status), (requested_at), (status, next_attempt_at),
             (pickup_cell, requested_at), (status, offered_at)
drivers      id pk, name, status, created_at, offers, accepts, declines
ride_events  id pk, trip_id -> trips.id on delete cascade, event, at
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the reasoning behind the
partitioning, TTL handling and the matcher's concurrency model.

## Layout

```
rideloop_common/   geohash, haversine, pydantic models, settings, DynamoDB store, SQLAlchemy schema, trip repository, eta, surge, metrics
services/          driver_location, ride_request, dispatch (FastAPI apps, one Dockerfile each)
migrations/        Alembic environment and revisions
sim/               city grid, driver fleet, rider load, demo orchestrator, ride stream replay
scripts/           create_tables.py
tests/             pytest suite
web/               Vite + React + TypeScript rider map
showcase/          browser-only dispatch model, not a live backend benchmark
docs/              measurement provenance and historical source references
```

## Releases

The project grew in five tagged releases, each with its own migration, tests
and GitHub release notes.

- **v5.0.0** Observability and replay. Prometheus `GET /metrics` on every
  service: matches, match latency histogram, matches per minute, unmatched
  sweeps, claim conflicts, TTL expiries (the read path now deletes expired
  rows on sight and counts them), offer outcomes and HTTP request counters.
  `sim/replay.py` records a ride stream and replays it deterministically
  through the matcher, with a fingerprinted summary for regression
  comparison (`make replay`); `sim.demo --record` captures a live run.
- **v4.0.0** Driver accept and decline. A match is an offer with a timeout;
  `POST /rides/{id}/accept` and `/decline` answer it, an unanswered offer
  times out in the dispatcher's sweep. Declines and timeouts release the claim
  with a conditional update, re-queue the trip with the driver excluded, and
  count against the driver's acceptance rate (`GET /drivers/{id}/acceptance`).
  Simulated drivers decline 10% of offers in the demo to exercise the rematch.
- **v3.0.0** Surge pricing. Trips record their `pickup_cell` and the
  `surge_multiplier` they were priced at (Alembic `0003`). Demand per cell is
  a half-life-decayed count of recent requests, supply is the available
  drivers in the cell, and the multiplier rises with the ratio and decays on
  its own. `GET /rides/surge` quotes a point, `GET /dispatch/heatmap` lists
  every active cell.
- **v2.0.0** Trip lifecycle and ETA. New `arrived` and `in_trip` states
  (Alembic `0002`, with a downgrade that rebuilds the enum). The
  driver_location service advances a busy driver's trip from its pings and
  releases the driver at the dropoff. `GET /rides/{id}` returns the driver's
  live position and a pickup ETA from grid route distance and the smoothed
  observed speed. The simulated drivers now drive to the pickup, wait, and
  carry on to the dropoff.
- **v1.0.0** Geohash-partitioned DynamoDB driver index with TTL expiry,
  PostgreSQL trips through Alembic, nearest-driver matcher with atomic claims
  and expanding radius, 500 matches per minute floor, React rider map.

## License

MIT
