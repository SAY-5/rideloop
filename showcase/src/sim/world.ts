/**
 * The whole demo in one object: a fleet of simulated drivers pinging the
 * position index once a second, riders submitting trips, and the dispatcher
 * sweeping pending trips on its poll interval. Time is a simulation clock in
 * seconds; nothing here reads the wall clock.
 *
 * Match latency is modeled the way it arises in the real services: a trip
 * waits for the next sweep (the dispatcher polls every 100 ms when idle), then
 * pays for each partition read, each conditional claim and the PostgreSQL commit.
 */

import { CITY_HALF_M, latLngToLocal, randomPoint, SimDriver, toLatLng } from "./city";
import { PositionIndex } from "./index";
import { DEFAULT_RADII, findDriver, type MatchOutcome } from "./matcher";
import { Rng } from "./prng";
import { LatencyStats, MatchRate } from "./stats";

export type TripStatus = "requested" | "matched" | "en_route" | "completed" | "cancelled";

export interface Trip {
  id: string;
  riderId: string;
  pickupLat: number;
  pickupLng: number;
  dropoffLat: number;
  dropoffLng: number;
  status: TripStatus;
  driverId: string | null;
  requestedAt: number;
  matchedAt: number | null;
  startAt: number | null;
  completedAt: number | null;
  matchLatencyMs: number | null;
  dispatchAttempts: number;
  nextAttemptAt: number;
  radiusM: number | null;
  candidatesSeen: number;
  /** manual trips are matched by the UI step by step, not by the sweep loop */
  manual: boolean;
  events: { event: string; at: number }[];
}

export interface WorldEvent {
  at: number;
  kind: "request" | "match" | "no_driver" | "start" | "complete" | "silence" | "expire";
  text: string;
  tripId?: string;
  driverId?: string;
}

export interface WorldOptions {
  seed?: number;
  driverCount?: number;
  ttlSeconds?: number;
  pollIntervalS?: number;
  pingIntervalS?: number;
  retryDelayS?: number;
  batchSize?: number;
}

/** Cost model in milliseconds, tuned against the demo summary in the README. */
const COST = {
  rowLock: 1.4, // SELECT ... FOR UPDATE SKIP LOCKED
  partitionRead: 0.9, // one DynamoDB Query per partition in the plan
  claim: 1.5, // one conditional UpdateItem
  commit: 2.0, // UPDATE trips + INSERT ride_events, commit
  jitter: 2.0, // network and scheduler noise
  submitJitter: 0.03, // seconds: HTTP round trip on POST /rides
  pollJitter: 0.004, // seconds: asyncio wakeup slack on the poll sleep
};

export const PICKUP_TO_START_S = 3;
export const START_TO_COMPLETE_S = 4;

export class World {
  readonly rng: Rng;
  readonly drivers: SimDriver[];
  readonly index: PositionIndex;
  readonly trips = new Map<string, Trip>();
  readonly tripOrder: string[] = [];
  readonly latency = new LatencyStats();
  readonly rate = new MatchRate();
  readonly log: WorldEvent[] = [];
  readonly silenced = new Set<string>();
  readonly ttlSeconds: number;
  readonly pollIntervalS: number;
  readonly pingIntervalS: number;
  readonly retryDelayS: number;
  readonly batchSize: number;
  readonly radii = DEFAULT_RADII;

  now = 0;
  posts = 0;
  sweeps = 0;
  private nextSweepAt = 0;
  private readonly nextPingAt: number[];
  private readonly scheduled: { at: number; riderId: string }[] = [];
  private tripSeq = 0;
  private riderSeq = 0;
  private readonly riderRng: Rng;
  private readonly noiseRng: Rng;

  constructor(opts: WorldOptions = {}) {
    const seed = opts.seed ?? 42;
    this.rng = new Rng(seed);
    this.riderRng = new Rng(7 + seed);
    this.noiseRng = new Rng(99 + seed);
    this.ttlSeconds = opts.ttlSeconds ?? 20;
    this.pollIntervalS = opts.pollIntervalS ?? 0.1;
    this.pingIntervalS = opts.pingIntervalS ?? 1;
    this.retryDelayS = opts.retryDelayS ?? 1;
    this.batchSize = opts.batchSize ?? 50;
    this.index = new PositionIndex(5, this.ttlSeconds);
    const count = opts.driverCount ?? 300;
    this.drivers = [];
    this.nextPingAt = [];
    for (let i = 0; i < count; i++) {
      const id = `drv-${String(i).padStart(3, "0")}`;
      const driver = SimDriver.spawn(id, this.rng.fork());
      this.drivers.push(driver);
      // spread the fleet over the interval so posts are not bunched
      this.nextPingAt.push(((i % 50) / 50) * this.pingIntervalS);
    }
    // every driver has pinged once before anything else happens
    for (let i = 0; i < this.drivers.length; i++) this.ping(i, 0);
  }

  // -- riders -----------------------------------------------------------------

  /** Queue `rate * durationS` submissions starting now, like sim/riders.py. */
  scheduleLoad(rate: number, durationS: number): number {
    const total = Math.floor(rate * durationS);
    const gap = 1 / rate;
    for (let i = 0; i < total; i++) {
      this.scheduled.push({
        at: this.now + i * gap + this.noiseRng.uniform(0, COST.submitJitter),
        riderId: `rider-${String(this.riderSeq++).padStart(4, "0")}`,
      });
    }
    this.scheduled.sort((a, b) => a.at - b.at);
    return total;
  }

  get scheduledRemaining(): number {
    return this.scheduled.length;
  }

  cancelScheduled(): void {
    this.scheduled.length = 0;
  }

  requestRide(
    pickup: [number, number],
    dropoff: [number, number],
    options: { manual?: boolean; riderId?: string } = {},
  ): Trip {
    const id = `trip-${String(++this.tripSeq).padStart(4, "0")}`;
    const trip: Trip = {
      id,
      riderId: options.riderId ?? `rider-${String(this.riderSeq++).padStart(4, "0")}`,
      pickupLat: pickup[0],
      pickupLng: pickup[1],
      dropoffLat: dropoff[0],
      dropoffLng: dropoff[1],
      status: "requested",
      driverId: null,
      requestedAt: this.now,
      matchedAt: null,
      startAt: null,
      completedAt: null,
      matchLatencyMs: null,
      dispatchAttempts: 0,
      nextAttemptAt: this.now,
      radiusM: null,
      candidatesSeen: 0,
      manual: options.manual ?? false,
      events: [{ event: "requested", at: this.now }],
    };
    this.trips.set(id, trip);
    this.tripOrder.push(id);
    if (!trip.manual) this.rate.noteRequest(this.now);
    this.push({ at: this.now, kind: "request", tripId: id, text: `${id} requested` });
    return trip;
  }

  /** Register the outcome of a UI-driven (manual) search on a trip. */
  applyOutcome(trip: Trip, outcome: MatchOutcome, latencyMs: number): void {
    if (outcome.driver) {
      this.markMatched(trip, outcome, this.now, latencyMs);
    } else {
      this.defer(trip, this.now);
    }
  }

  // -- drivers ----------------------------------------------------------------

  silence(driverId: string): void {
    if (this.silenced.has(driverId)) return;
    this.silenced.add(driverId);
    this.push({ at: this.now, kind: "silence", driverId, text: `${driverId} stopped pinging` });
  }

  resume(driverId: string): void {
    this.silenced.delete(driverId);
  }

  driverPickup(driverId: string): [number, number] | null {
    const item = this.index.getDriver(driverId);
    if (!item?.tripId) return null;
    const trip = this.trips.get(item.tripId);
    return trip ? [trip.pickupLat, trip.pickupLng] : null;
  }

  private ping(i: number, at: number): void {
    const driver = this.drivers[i];
    const [lat, lng] = driver.latlng();
    const item = this.index.putPosition(driver.driverId, lat, lng, driver.heading, at);
    this.posts += 1;
    // follow assignment: head for the pickup while busy, wander when released
    const tripId = item.status === "busy" ? item.tripId : null;
    if (tripId === driver.tripId) return;
    driver.tripId = tripId;
    if (tripId === null) {
      driver.clearTarget();
      return;
    }
    const trip = this.trips.get(tripId);
    if (trip) driver.setTarget(...latLngToLocal(trip.pickupLat, trip.pickupLng));
    else driver.clearTarget();
  }

  // -- dispatcher -------------------------------------------------------------

  private pendingBatch(at: number): Trip[] {
    const out: Trip[] = [];
    for (const id of this.tripOrder) {
      const trip = this.trips.get(id)!;
      if (trip.status === "requested" && !trip.manual && trip.nextAttemptAt <= at) {
        out.push(trip);
        if (out.length >= this.batchSize) break;
      }
    }
    return out;
  }

  private sweep(at: number): number {
    let cursor = at + (COST.rowLock + this.noiseRng.uniform(0, COST.jitter)) / 1000;
    let matched = 0;
    for (const trip of this.pendingBatch(at)) {
      const outcome = findDriver(this.index, trip.pickupLat, trip.pickupLng, trip.id, cursor, this.radii);
      const costMs =
        COST.partitionRead * outcome.partitionReads +
        COST.claim * outcome.claimAttempts +
        COST.commit +
        this.noiseRng.uniform(0, COST.jitter);
      cursor += costMs / 1000;
      if (outcome.driver) {
        this.markMatched(trip, outcome, cursor, Math.round((cursor - trip.requestedAt) * 1000));
        matched += 1;
      } else {
        this.defer(trip, cursor);
      }
    }
    this.sweeps += 1;
    this.nextSweepAt =
      matched > 0 ? cursor : cursor + this.pollIntervalS + this.noiseRng.uniform(0, COST.pollJitter);
    return matched;
  }

  private markMatched(trip: Trip, outcome: MatchOutcome, at: number, latencyMs: number): void {
    const driver = outcome.driver!;
    trip.status = "matched";
    trip.driverId = driver.driverId;
    trip.matchedAt = at;
    trip.matchLatencyMs = latencyMs;
    trip.radiusM = outcome.radiusM;
    trip.candidatesSeen = outcome.candidatesSeen;
    trip.dispatchAttempts += 1;
    trip.startAt = at + PICKUP_TO_START_S;
    trip.events.push({ event: "matched", at });
    if (!trip.manual) {
      this.latency.push(latencyMs);
      this.rate.noteMatch(at);
    }
    this.push({
      at,
      kind: "match",
      tripId: trip.id,
      driverId: driver.driverId,
      text: `${trip.id} matched ${driver.driverId} at ${Math.round(driver.distanceM)} m in ${latencyMs} ms`,
    });
  }

  private defer(trip: Trip, at: number): void {
    trip.dispatchAttempts += 1;
    trip.nextAttemptAt = at + this.retryDelayS;
    trip.events.push({ event: "no_driver", at });
    this.push({ at, kind: "no_driver", tripId: trip.id, text: `${trip.id} no driver within 4 km, retry in 1 s` });
  }

  // -- trip lifecycle ---------------------------------------------------------

  private nextLifecycleAt(): number {
    let t = Infinity;
    for (const id of this.tripOrder) {
      const trip = this.trips.get(id)!;
      if (trip.status === "matched" && trip.startAt !== null) t = Math.min(t, trip.startAt);
      else if (trip.status === "en_route" && trip.completedAt !== null) t = Math.min(t, trip.completedAt);
    }
    return t;
  }

  private advanceLifecycle(at: number): void {
    for (const id of this.tripOrder) {
      const trip = this.trips.get(id)!;
      if (trip.status === "matched" && trip.startAt !== null && trip.startAt <= at) {
        trip.status = "en_route";
        trip.completedAt = trip.startAt + START_TO_COMPLETE_S;
        trip.events.push({ event: "started", at: trip.startAt });
        this.push({ at: trip.startAt, kind: "start", tripId: id, driverId: trip.driverId ?? undefined, text: `${id} en route` });
      }
      if (trip.status === "en_route" && trip.completedAt !== null && trip.completedAt <= at) {
        trip.status = "completed";
        trip.events.push({ event: "completed", at: trip.completedAt });
        if (trip.driverId) this.index.setStatus(trip.driverId, "available");
        this.push({ at: trip.completedAt, kind: "complete", tripId: id, driverId: trip.driverId ?? undefined, text: `${id} completed, ${trip.driverId} released` });
      }
    }
  }

  // -- clock ------------------------------------------------------------------

  /** Advance the simulation by dtS seconds. */
  tick(dtS: number): void {
    const target = this.now + dtS;
    for (let guard = 0; guard < 10_000; guard++) {
      const nextSubmit = this.scheduled.length ? this.scheduled[0].at : Infinity;
      const nextLife = this.nextLifecycleAt();
      const t = Math.min(nextSubmit, this.nextSweepAt, nextLife);
      if (t > target) break;
      this.now = Math.max(this.now, t);
      if (t === nextSubmit) {
        const job = this.scheduled.shift()!;
        this.requestRide(randomPoint(this.riderRng), randomPoint(this.riderRng), { riderId: job.riderId });
      } else if (t === nextLife) {
        this.advanceLifecycle(t);
      } else {
        this.sweep(t);
      }
    }
    this.now = target;
    for (let i = 0; i < this.drivers.length; i++) {
      this.drivers[i].step(dtS);
      if (this.nextPingAt[i] <= target) {
        this.nextPingAt[i] += this.pingIntervalS;
        if (this.nextPingAt[i] <= target) this.nextPingAt[i] = target + this.pingIntervalS;
        if (!this.silenced.has(this.drivers[i].driverId)) this.ping(i, target);
      }
    }
  }

  // -- summary ----------------------------------------------------------------

  counts(): { submitted: number; matched: number; completed: number; pending: number; busy: number } {
    let submitted = 0;
    let matched = 0;
    let completed = 0;
    let pending = 0;
    for (const id of this.tripOrder) {
      const trip = this.trips.get(id)!;
      if (trip.manual) continue;
      submitted += 1;
      if (trip.status === "requested") pending += 1;
      else if (trip.status === "completed") {
        matched += 1;
        completed += 1;
      } else matched += 1;
    }
    let busy = 0;
    for (const d of this.drivers) if (this.index.getDriver(d.driverId)?.status === "busy") busy += 1;
    return { submitted, matched, completed, pending, busy };
  }

  private push(event: WorldEvent): void {
    this.log.push(event);
    if (this.log.length > 400) this.log.splice(0, this.log.length - 400);
  }
}

export { CITY_HALF_M, toLatLng };
