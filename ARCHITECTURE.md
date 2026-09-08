# Architecture

RideLoop is three small HTTP services and two stores. Driver positions are hot,
short-lived and keyed by location, so they live in DynamoDB. Trips are
relational, audited and queried by status and time, so they live in PostgreSQL.

```
 driver clients            rider clients / web map
   |  POST position           |  POST /rides, GET /rides/{id}
   v                          v
+-----------------+     +-----------------+       +-----------------+
| driver_location |     |  ride_request   |       |    dispatch     |
| FastAPI :8001   |     | FastAPI :8002   |       | FastAPI :8003   |
+--------+--------+     +--------+--------+       +---+---------+---+
         |                       |                    |         |
         v                       v                    v         v
   +-----------+          +--------------+     +-----------+ +--------------+
   | DynamoDB  |          | PostgreSQL   |     | DynamoDB  | | PostgreSQL   |
   | positions |          | trips/events |     | nearby +  | | claim + mark |
   | by cell   |          |              |     | claim     | | matched      |
   +-----------+          +--------------+     +-----------+ +--------------+
```

## Driver positions: geohash partitioning

`driver_positions` is a single DynamoDB table:

| key / attribute | type | purpose |
| --- | --- | --- |
| `cell` (partition key) | S | geohash of the position at precision 5 (about 4.9 km x 4.9 km) |
| `driver_id` (sort key) | S | one item per driver per cell |
| `geohash` | S | precision-6 geohash (about 1.2 km x 0.6 km), used to filter inside a cell |
| `lat`, `lng`, `heading` | N | last reported position |
| `status` | S | `available`, `busy` or `offline` |
| `trip_id` | S | set while busy |
| `updated_at` | S | ISO 8601 timestamp of the last ping |
| `ttl` | N | epoch seconds; the table's TTL attribute |
| GSI `by_driver` | | hash key `driver_id`, so a driver can be found without knowing its cell |

Why a geohash prefix as the partition key: a geohash prefix is a bounding box,
and every point inside that box shares the prefix. Putting the prefix in the
partition key turns "who is near this point" into a handful of key lookups
instead of a table scan, and keeps each partition bounded to one city block of
drivers. Precision 5 was chosen because the matcher's search radius caps at
4 km, and a 3 x 3 block of precision-5 cells is guaranteed to cover a 4.9 km
radius from any point in the center cell. Nearby queries read the center cell
and its 8 neighbors so a search box straddling a cell edge is not cut off.

For small radii (500 m to 2 km) reading whole 4.9 km partitions returns far more
rows than needed, so the store enumerates the precision-6 subcells that
intersect the search box, groups them by their precision-5 parent, and adds
`geohash IN (...)` to the query filter. That keeps the key schema simple while
cutting the returned rows roughly tenfold at the first search ring. Turning the
sort key into `geohash#driver_id` would make that filter a key condition; it is
a straightforward follow-up if read units become the bottleneck.

Each position write is an upsert on `(cell, driver_id)`. When a driver crosses
into another cell the old item is deleted and the new one written in a single
`TransactWriteItems` call; the delete is conditioned on the status that was
read, so a concurrent claim by the dispatcher cancels the transaction and the
write is retried with fresh data. The driver therefore never appears twice and
never loses a `busy` flag while moving.

## TTL expiry

Every ping sets `ttl = now + POSITION_TTL_SECONDS` (60 s by default, 20 s in the
demo compose file). A driver that stops reporting is dropped by DynamoDB's TTL
process without any cleanup job. DynamoDB deletes expired items lazily (it can
lag by minutes or more), so the read side treats `ttl` as authoritative:
nearby queries filter `ttl > now` and the dispatcher's claim condition includes
`ttl > now`. A stale driver is invisible the second its TTL passes, regardless
of when the background deletion happens. `make demo` shows this: one driver is
silenced and the summary reports it visible after 3 s and gone after the TTL.

## Trips: PostgreSQL schema

```
trips
  id                uuid primary key
  rider_id          varchar(64)
  pickup_lat/lng    double precision
  dropoff_lat/lng   double precision
  status            trip_status enum (requested, matched, en_route, completed, cancelled)
  driver_id         varchar(64) null
  requested_at      timestamptz
  matched_at        timestamptz null
  completed_at      timestamptz null
  match_latency_ms  integer null
  dispatch_attempts integer
  next_attempt_at   timestamptz
  indexes: (status), (requested_at), (status, next_attempt_at)

drivers
  id, name, status, created_at            registry; status mirrors the dispatch state

ride_events
  id, trip_id -> trips (cascade), event, at   append-only audit trail
```

Migrations are Alembic scripts (`migrations/versions`), applied by the
ride_request container at startup and by `make migrate` locally.

## Dispatch: matching and concurrency

The `trips` table doubles as the dispatch queue. Inserting a trip in
`requested` state is the publish; the dispatcher's sweep is the consume:

```sql
SELECT ... FROM trips
WHERE status = 'requested' AND next_attempt_at <= now()
ORDER BY requested_at LIMIT :batch
FOR UPDATE SKIP LOCKED
```

`FOR UPDATE SKIP LOCKED` lets several dispatcher processes sweep at once
without handing the same trip to two of them; the row lock is held for the
duration of the sweep's transaction and released with the status update.

For each claimed trip the matcher:

1. queries available drivers around the pickup at 500 m, ranked by haversine
   distance;
2. tries to claim the nearest with a conditional update
   (`status = available AND ttl > now`), moving on to the next candidate if the
   claim fails;
3. doubles the radius (1 km, 2 km, 4 km) when a ring has no claimable driver;
4. on success writes `matched`, `driver_id`, `matched_at`,
   `match_latency_ms = matched_at - requested_at` and a `matched` event in the
   same PostgreSQL transaction that holds the row lock;
5. otherwise leaves the trip `requested`, bumps `dispatch_attempts`, sets
   `next_attempt_at` one second out and records a `no_driver` event.

Two safety properties follow. A driver can never be assigned to two trips
because the DynamoDB conditional update is atomic, and a trip can never be
matched twice because the row is locked while it is being matched. If the
process dies between the DynamoDB claim and the PostgreSQL commit, the trip
stays `requested` and is retried; the driver is stuck `busy` until it goes
offline or its next trip completes, which is the one liability of using two
stores without a distributed transaction. A reconciliation sweep that releases
busy drivers whose `trip_id` has no matching trip would close that gap.

Trip completion (`POST /rides/{id}/complete`, or the driver's ping at the
dropoff) flips the driver back to `available` in DynamoDB and mirrors the
status into `drivers`.

## Offers, declines and rematch

A match is not final until the driver says so. `mark_matched` records
`offered_at`; the trip stays `matched` with `accepted_at` null until the
driver calls `accept`. Three things can end an open offer:

- `accept`: `accepted_at` is set and from then on the driver's pings move the
  trip along.
- `decline`: in one PostgreSQL transaction the trip goes back to `requested`
  with `driver_id` cleared, the driver appended to `declined_by` and
  `next_attempt_at = now`; after the commit the DynamoDB claim is released
  with a conditional update (`status = busy AND trip_id = this trip`), so a
  driver that has meanwhile been claimed for another trip is left alone.
- timeout: every dispatcher sweep first runs `expire_offers`, a
  `FOR UPDATE SKIP LOCKED` select over `matched` trips with a null
  `accepted_at` and `offered_at` older than `DISPATCH_OFFER_TIMEOUT_S`, and
  treats each as a decline with the event `offer_timeout`.

The next sweep picks the re-queued trip up like any other; the matcher seeds
its "already tried" set with `declined_by`, so the decliner is skipped even
when it is still the nearest available driver. `dispatch_attempts` and the
event trail (`matched`, `declined`, `matched`) show the rematch. The
ordering of the decline (commit, then release the claim) means a crash in
between leaves the driver busy until its next completion or a timeout, the
same liability the two-store match already has; the reverse order could
leave a trip pointing at a driver another trip has since claimed, which is
worse.

Acceptance is tracked on the `drivers` row: `offers` increments on every
match, `accepts` on accept, `declines` on decline or timeout.
`GET /drivers/{id}/acceptance` reports the rate.

## Trip lifecycle from position reports

```
requested --match--> matched --ping--> en_route --ping <=40m of pickup--> arrived
                                                                            |
        completed <--ping <=40m of dropoff-- in_trip <--ping >=120m from pickup--+
```

After the driver accepts, the trip is moved along by its pings, not by
client calls; a ping before acceptance only refreshes the ETA. The driver_location service, having stored a ping from a
`busy` driver, loads the trip named in the item's `trip_id`, checks the
trip's `driver_id` matches (a stale claim is ignored) and runs
`trips.advance_from_position` in one PostgreSQL transaction. Distances are
L1 (north-south plus east-west), the shape of a drive on a grid. The
thresholds are deliberately asymmetric: arrival triggers inside 40 m, but the
car has to get 120 m away before the rider counts as aboard, so a driver
circling a block for parking does not flip the trip to `in_trip` and back.

If PostgreSQL is unavailable the ping is still stored and the error is logged;
the driver's position must never be lost because the trip database blinked.
The rider-side endpoints (`start`, `complete`, `cancel`) remain as manual
overrides and for clients without a driver app.

## Pickup ETA

`GET /rides/{id}` reads the driver's item from DynamoDB on every call, so the
position and ETA are as fresh as the last ping. The ETA is

    L1 distance to pickup / max(speed, 3 m/s) + 15 s

`speed_mps` is tracked in the driver item: each ping computes the haversine
distance from the previous stored position divided by the elapsed time,
clamps it at 50 m/s (a jump, not a drive) and blends it with the previous
value at 50/50. The floor keeps a parked driver's ETA finite; the 15 s
covers pull-over and door time. `tests/test_lifecycle.py` drives a simulated
car across the grid and requires the ETA taken early in the drive to land
within 15% of the measured time.

## Surge pricing

Surge is computed per precision-5 cell, the same partition the driver index
uses, so demand and supply are counted over the same patch of ground.

    demand(cell, now) = sum over requests r in cell of 0.5 ^ ((now - r.requested_at) / half_life)
    supply(cell, now) = available drivers in cell with ttl > now
    multiplier        = 1                                   if demand <= supply
                        min(1 + step * (demand/supply - 1), cap)   otherwise

Demand comes from PostgreSQL: `trips` carries `pickup_cell`, indexed with
`requested_at`, and the query only reads the last five half-lives (older
requests contribute under 4% each). Supply comes from DynamoDB: one partition
query for a quote, a filtered scan for the heatmap. There are no running
counters to keep in step with the stores, so a restart or a second replica
cannot drift; the trade-off is a query per quote, which at a few hundred
requests a minute is cheap. The decay is exponential rather than a fixed
window so the multiplier eases off smoothly instead of dropping the moment a
burst falls out of a window.

The multiplier a rider was quoted is stored on the trip
(`surge_multiplier`), so the price is fixed at request time even though the
cell's multiplier keeps moving.

## Observability

Metrics live in `rideloop_common/metrics.py` and are incremented where the
event happens: the matcher counts matches, observes the latency it just
wrote to the trip, and counts trips it could not place; the DynamoDB store
counts a claim conflict whenever the conditional `try_mark_busy` fails and a
TTL expiry whenever a read drops an expired row; the ride_request service
counts offer outcomes. `services/common.py` adds a middleware that counts and
times every request by route template, and `GET /metrics` renders the
registry. The driver_location and ride_request containers run two uvicorn
workers, so the Dockerfiles set `PROMETHEUS_MULTIPROC_DIR` and the render
step aggregates across processes.

Expired rows used to be filtered by a server-side `FilterExpression`,
which made them invisible and therefore uncountable. The read path now asks
for the partition (still filtered by subcell) and checks `ttl` itself; the
first read to see an expired row stamps it with `expired_ttl = ttl` under
`ConditionExpression: ttl = :seen AND expired_ttl <> :seen`, so a row
refreshed by a ping that landed in between is not touched and a row already
stamped for this expiry is not counted twice. The row is deliberately not
deleted: DynamoDB's own sweep removes it, and until then a driver that
resumes pinging finds its item, status and trip intact instead of being
recreated as available while a trip in PostgreSQL still names it. The stamp
costs one write per expiry, once, and makes the counter a true count of
expiries rather than of reads that happened to see one.

`rideloop_matches_per_minute` is a gauge fed by the sweep loop's own
trailing-minute deque rather than a PromQL `rate()`, so it reads correctly
on a single scrape and matches the number the demo prints.

## Replay

`sim/replay.py` turns a ride stream into a regression test. The file is
JSON lines: a header, then `position` and `ride` events with a relative
`t`, then a `summary`. `replay()` walks the events on a virtual clock rooted
at the wall time the run starts: positions are written with `now = base + t`
and a long TTL so drift between virtual and real time cannot expire them,
each ride is inserted and immediately followed by `Matcher.run_once(now)`,
open offers are accepted on the spot and a completion is scheduled
`RIDE_DURATION_S` later so drivers cycle back into the pool. The matcher is
deterministic (nearest first, ties by driver id through the stable sort), so
the same file yields the same assignments; the summary carries a sha256
fingerprint of `(rider, driver, latency)` triples and `run` exits 1 when a
later replay disagrees with it.

`sim.demo --record` writes the live stream of a demo run together with the
live match count. Replaying a live recording is sequential where the live
run was concurrent, so its numbers are a reference rather than a guarantee;
the synthesized streams (`make replay`) are the ones that reproduce exactly.

## Throughput

`tests/test_throughput.py` runs the matcher in-process against moto and a real
PostgreSQL with 300 drivers and 500 trips and asserts at least 500 matches per
minute. `make demo` measures the same thing end to end through the HTTP
services with DynamoDB Local; the numbers printed there are the ones quoted in
the README.
