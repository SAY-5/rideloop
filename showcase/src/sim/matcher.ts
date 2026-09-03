/**
 * The dispatch matcher: pairs a requested trip with the nearest available driver.
 * Port of services/dispatch/matcher.py with a step-by-step trace so the UI can
 * replay the search ring by ring and claim by claim.
 */

import type { NearbyDriver, PositionIndex, QueryPlanEntry } from "./index";

const AVAILABLE = new Set<"available">(["available"]);

/** 500, 1000, 2000, 4000: double until the cap, always ending at the cap. */
export function expandingRadii(initialM: number, maxM: number): number[] {
  const radii: number[] = [];
  let radius = initialM;
  while (radius < maxM) {
    radii.push(radius);
    radius *= 2;
  }
  radii.push(maxM);
  return radii;
}

export const DEFAULT_RADII = expandingRadii(500, 4000);

export interface CandidateTrace {
  driverId: string;
  cell: string;
  distanceM: number;
  /** claimed: conditional update succeeded; lost: condition failed; skipped: already tried in a smaller ring */
  result: "claimed" | "lost" | "skipped";
}

export interface RingTrace {
  radiusM: number;
  plan: QueryPlanEntry[];
  rowsRead: number;
  candidates: CandidateTrace[];
}

export interface MatchOutcome {
  tripId: string;
  driver: NearbyDriver | null;
  radiusM: number | null;
  candidatesSeen: number;
  rings: RingTrace[];
  partitionReads: number;
  claimAttempts: number;
}

export type MatchStep =
  | { kind: "query"; radiusM: number; candidates: NearbyDriver[]; plan: QueryPlanEntry[] }
  | { kind: "claim"; radiusM: number; driver: NearbyDriver; ok: boolean }
  | { kind: "widen"; fromM: number; toM: number };

/**
 * Widen the search ring until a driver is claimed or the cap is reached.
 * Yields after every query and every claim so two searches can be interleaved
 * to show contention for one driver: the loser simply moves to the next candidate.
 */
export function* matchSteps(
  index: PositionIndex,
  lat: number,
  lng: number,
  tripId: string,
  now: number,
  radii: readonly number[] = DEFAULT_RADII,
): Generator<MatchStep, MatchOutcome, void> {
  let seen = 0;
  let partitionReads = 0;
  let claimAttempts = 0;
  const tried = new Set<string>();
  const rings: RingTrace[] = [];
  for (let r = 0; r < radii.length; r++) {
    const radius = radii[r];
    if (r > 0) yield { kind: "widen", fromM: radii[r - 1], toM: radius };
    const { drivers, plan, rowsRead } = index.nearby(lat, lng, radius, AVAILABLE, now);
    partitionReads += plan.length;
    const ring: RingTrace = { radiusM: radius, plan, rowsRead, candidates: [] };
    rings.push(ring);
    yield { kind: "query", radiusM: radius, candidates: drivers, plan };
    for (const candidate of drivers) {
      if (tried.has(candidate.driverId)) {
        ring.candidates.push({ ...pick(candidate), result: "skipped" });
        continue;
      }
      tried.add(candidate.driverId);
      seen += 1;
      claimAttempts += 1;
      const ok = index.tryMarkBusy(candidate.cell, candidate.driverId, tripId, now);
      ring.candidates.push({ ...pick(candidate), result: ok ? "claimed" : "lost" });
      yield { kind: "claim", radiusM: radius, driver: candidate, ok };
      if (ok) {
        return {
          tripId,
          driver: candidate,
          radiusM: radius,
          candidatesSeen: seen,
          rings,
          partitionReads,
          claimAttempts,
        };
      }
    }
  }
  return { tripId, driver: null, radiusM: null, candidatesSeen: seen, rings, partitionReads, claimAttempts };
}

function pick(c: NearbyDriver): Omit<CandidateTrace, "result"> {
  return { driverId: c.driverId, cell: c.cell, distanceM: c.distanceM };
}

/** Run the search to completion in one go. */
export function findDriver(
  index: PositionIndex,
  lat: number,
  lng: number,
  tripId: string,
  now: number,
  radii: readonly number[] = DEFAULT_RADII,
): MatchOutcome {
  const gen = matchSteps(index, lat, lng, tripId, now, radii);
  for (;;) {
    const next = gen.next();
    if (next.done) return next.value;
  }
}
