# RideLoop

Ride request and dispatch platform: three Python microservices, a DynamoDB
driver index partitioned by geohash with TTL expiry, a PostgreSQL trip schema,
and a React rider map. Synthetic traffic drives it at about 600 rides a minute
on a laptop.

| service | port | stores | job |
| --- | --- | --- | --- |
| `driver_location` | 8001 | DynamoDB | ingest driver pings, answer "who is near this point" |
| `ride_request` | 8002 | PostgreSQL, DynamoDB | create trips, expose their lifecycle, release drivers on completion |
| `dispatch` | 8003 | PostgreSQL, DynamoDB | match requested trips to the nearest available driver, report throughput |
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
that post a position every second, submits rides at 10 per second for 60
seconds, rides each one to completion, and prints a summary. Every figure is
read back from the running system (trip timestamps from PostgreSQL, fleet
visibility from DynamoDB, the dispatch service's own stats endpoint).

```
$ make demo
...
================ RideLoop demo summary ================
drivers seeded            300 (8092 position posts, 1 errors)
rides submitted           600 (10/s for 60s)
rides matched             600 (100.0%)
rides completed           600
rides left requested      0
matches per minute        601 (600 matches over 59.9s, first request to last match)
match latency p50 / p95   59 ms / 101 ms (mean 57 ms)
dispatch service stats    matched_total=1200 last_minute=520 p50=59.0 p95=101.0 sweeps=3491
ttl expiry                driver drv-000 stopped at 22:01:27; visible after 3s: yes; visible after ttl (19s): no -> expired as expected
=======================================================
```

The demo compose file sets `POSITION_TTL_SECONDS=20` so the expiry is visible
within the run; the service default is 60 s. The submission rate is the
ceiling here, not the matcher: median match latency is around 60 ms end to end.

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
trail, migrations up and down, and an in-process run of 500 trips that must
sustain at least 500 matches per minute. CI (`.github/workflows/ci.yml`) runs
the same steps with a `postgres:16` service container and a separate job for
the web app.

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
| `DISPATCH_POLL_INTERVAL_S` | `0.1` | dispatch |
| `DRIVER_LOCATION_URL` / `RIDE_REQUEST_URL` / `DISPATCH_URL` | `http://localhost:800{1,2,3}` | simulators |

## API

### driver_location (8001)

| method | path | notes |
| --- | --- | --- |
| `POST` | `/drivers/{id}/position` | body `{lat, lng, heading}`; upserts the cell item, refreshes `ttl`, keeps dispatch status |
| `GET` | `/drivers/nearby?lat&lng&radius_m&status&limit` | drivers within `radius_m` (max 10 km), nearest first, expired excluded |
| `GET` | `/drivers/{id}` | current position and status |
| `PUT` | `/drivers/{id}/status?status=` | `available`, `busy` or `offline` |
| `DELETE` | `/drivers/{id}` | remove the driver |

### ride_request (8002)

| method | path | notes |
| --- | --- | --- |
| `POST` | `/rides` | body `{rider_id, pickup: {lat, lng}, dropoff: {lat, lng}}`; returns the trip with status `requested` |
| `GET` | `/rides/{id}` | trip with its `events` |
| `GET` | `/rides?status&limit` | recent trips |
| `POST` | `/rides/{id}/start` | `matched` to `en_route` |
| `POST` | `/rides/{id}/complete` | `matched`/`en_route` to `completed`; frees the driver |
| `POST` | `/rides/{id}/cancel` | `requested`/`matched`/`en_route` to `cancelled`; frees the driver |

### dispatch (8003)

| method | path | notes |
| --- | --- | --- |
| `GET` | `/dispatch/stats` | `matched_total`, `pending`, `matches_last_minute`, `matches_per_minute`, `p50_match_latency_ms`, `p95_match_latency_ms`, `sweeps`, `uptime_s` |

All three expose `GET /healthz` and interactive docs at `/docs`.

## Schema

DynamoDB `driver_positions`: partition key `cell` (geohash precision 5), sort
key `driver_id`, attributes `geohash` (precision 6), `lat`, `lng`, `heading`,
`status`, `trip_id`, `updated_at`, `ttl` (TTL attribute), GSI `by_driver`.

PostgreSQL (Alembic revision `0001`):

```
trips        id uuid pk, rider_id, pickup_lat, pickup_lng, dropoff_lat, dropoff_lng,
             status trip_status, driver_id, requested_at, matched_at, completed_at,
             match_latency_ms, dispatch_attempts, next_attempt_at
             index (status), (requested_at), (status, next_attempt_at)
drivers      id pk, name, status, created_at
ride_events  id pk, trip_id -> trips.id on delete cascade, event, at
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the reasoning behind the
partitioning, TTL handling and the matcher's concurrency model.

## Layout

```
rideloop_common/   geohash, haversine, pydantic models, settings, DynamoDB store, SQLAlchemy schema, trip repository
services/          driver_location, ride_request, dispatch (FastAPI apps, one Dockerfile each)
migrations/        Alembic environment and revisions
sim/               city grid, driver fleet, rider load, demo orchestrator
scripts/           create_tables.py
tests/             pytest suite
web/               Vite + React + TypeScript rider map
```

## License

MIT
