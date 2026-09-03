/**
 * Self-check for the TypeScript port. Runs the same vectors as the Python test
 * suite (tests/test_geohash.py, test_geo.py, test_matcher.py) and a synthetic
 * load of 600 rides that must match every ride without ever handing one driver
 * to two trips at once. Run with `npm run selfcheck`; the app also runs it once
 * at startup and prints the report to the console.
 */

import { haversineM, offsetM } from "./geo";
import * as geohash from "./geohash";
import { PositionIndex } from "./index";
import { expandingRadii, findDriver, matchSteps } from "./matcher";
import { World } from "./world";

export interface CheckResult {
  name: string;
  ok: boolean;
  detail: string;
}

export interface SelfCheckReport {
  ok: boolean;
  results: CheckResult[];
  load: { submitted: number; matched: number; perMinute: number | null; p50: number | null; p95: number | null; doubleAssigned: number } | null;
}

const CENTER: [number, number] = [37.7749, -122.4194];

export function runSelfCheck(): SelfCheckReport {
  const results: CheckResult[] = [];
  const check = (name: string, fn: () => string | true) => {
    try {
      const out = fn();
      results.push({ name, ok: true, detail: out === true ? "ok" : out });
    } catch (err) {
      results.push({ name, ok: false, detail: err instanceof Error ? err.message : String(err) });
    }
  };
  const expect = (cond: boolean, msg: string) => {
    if (!cond) throw new Error(msg);
  };
  const approx = (a: number, b: number, tol: number) => Math.abs(a - b) <= tol;

  check("geohash encode vectors", () => {
    const vectors: [number, number, number, string][] = [
      [42.605, -5.603, 5, "ezs42"],
      [57.64911, 10.40744, 11, "u4pruydqqvj"],
      [37.7749, -122.4194, 6, "9q8yyk"],
      [37.7749, -122.4194, 8, "9q8yyk8y"],
      [0, 0, 1, "s"],
      [-33.8688, 151.2093, 7, "r3gx2f7"],
      [90, 180, 4, "zzzz"],
      [-90, -180, 4, "0000"],
    ];
    for (const [lat, lng, p, want] of vectors) {
      const got = geohash.encode(lat, lng, p);
      expect(got === want, `encode(${lat}, ${lng}, ${p}) = ${got}, want ${want}`);
    }
    return `${vectors.length} vectors`;
  });

  check("geohash decode center", () => {
    const [lat, lng] = geohash.decode("u4pruydqqvj");
    expect(approx(lat, 57.64911, 1e-5) && approx(lng, 10.40744, 1e-5), `decode gave ${lat}, ${lng}`);
    const [lo, hi, lngLo, lngHi] = geohash.decodeBbox(geohash.encode(37.7749, -122.4194, 5));
    expect(approx(hi - lo, 0.0439453125, 1e-9) && approx(lngHi - lngLo, 0.0439453125, 1e-9), "bbox size");
    return true;
  });

  check("geohash neighbors reference vector", () => {
    const got = geohash.neighbors("ezs42");
    const want = ["ezs48", "ezs49", "ezs43", "ezs41", "ezs40", "ezefp", "ezefr", "ezefx"];
    expect(got.join(",") === want.join(","), `neighbors(ezs42) = ${got.join(",")}`);
    expect(geohash.adjacent("9q8yy", "n") === "9q8zn", "adjacent n");
    expect(geohash.adjacent("9q8yy", "s") === "9q8yw", "adjacent s");
    expect(geohash.adjacent("9q8yy", "e") === "9q8yz", "adjacent e");
    expect(geohash.adjacent("9q8yy", "w") === "9q8yv", "adjacent w");
    expect(geohash.adjacent("ezs40", "s") === "ezs1b", "crosses parent boundary");
    const block = geohash.cellWithNeighbors("u4pru");
    expect(block.length === 9 && new Set(block).size === 9 && block[0] === "u4pru", "3x3 block");
    return true;
  });

  check("haversine and offset", () => {
    expect(haversineM(37.7749, -122.4194, 37.7749, -122.4194) === 0, "zero distance");
    const parisLondon = haversineM(48.8566, 2.3522, 51.5074, -0.1278);
    expect(Math.abs(parisLondon - 343_500) / 343_500 < 0.005, `paris-london ${parisLondon}`);
    const north = offsetM(37.7749, -122.4194, 1000, 0);
    expect(Math.abs(haversineM(37.7749, -122.4194, ...north) - 1000) < 1, "offset north 1 km");
    return true;
  });

  check("expanding radii", () => {
    expect(expandingRadii(500, 4000).join() === "500,1000,2000,4000", "500..4000");
    expect(expandingRadii(300, 1000).join() === "300,600,1000", "300..1000");
    expect(expandingRadii(1000, 1000).join() === "1000", "1000");
    return true;
  });

  check("matcher picks the nearest available driver", () => {
    const index = new PositionIndex(5, 60);
    const [lat, lng] = CENTER;
    index.putPosition("far", ...offsetM(lat, lng, 400, 0), 0, 0);
    index.putPosition("nearest", ...offsetM(lat, lng, 120, 90), 0, 0);
    index.putPosition("mid", ...offsetM(lat, lng, -250, 0), 0, 0);
    const outcome = findDriver(index, lat, lng, "trip-1", 1);
    expect(outcome.driver?.driverId === "nearest", `picked ${outcome.driver?.driverId}`);
    expect(outcome.radiusM === 500 && outcome.candidatesSeen === 1, "first ring, one candidate");
    expect(index.getDriver("nearest")?.status === "busy" && index.getDriver("nearest")?.tripId === "trip-1", "claimed");
    expect(index.getDriver("far")?.status === "available", "others untouched");
    return true;
  });

  check("matcher skips busy and expired drivers", () => {
    const index = new PositionIndex(5, 60);
    const [lat, lng] = CENTER;
    const busy = index.putPosition("busy", ...offsetM(lat, lng, 50, 0), 0, 0);
    expect(index.tryMarkBusy(busy.cell, "busy", "other-trip", 1), "claim busy");
    index.putPosition("stale", ...offsetM(lat, lng, 60, 0), 0, 0, 5);
    index.putPosition("free", ...offsetM(lat, lng, 300, 0), 0, 0);
    const outcome = findDriver(index, lat, lng, "trip-2", 10);
    expect(outcome.driver?.driverId === "free", `picked ${outcome.driver?.driverId}`);
    expect(!index.isVisible("stale", 10) && index.isVisible("stale", 4), "ttl visibility");
    return true;
  });

  check("matcher expands the radius and gives up past the cap", () => {
    const index = new PositionIndex(5, 60);
    const [lat, lng] = CENTER;
    index.putPosition("distant", ...offsetM(lat, lng, 0, 2500), 0, 0);
    const found = findDriver(index, lat, lng, "trip-3", 1);
    expect(found.driver?.driverId === "distant" && found.radiusM === 4000, "found at 4 km");
    const index2 = new PositionIndex(5, 60);
    index2.putPosition("too-far", ...offsetM(lat, lng, 4500, 0), 0, 0);
    const none = findDriver(index2, lat, lng, "trip-4", 1);
    expect(none.driver === null && none.radiusM === null, "no driver");
    expect(index2.getDriver("too-far")?.status === "available", "not claimed");
    return true;
  });

  check("two matchers contend, exactly one wins the driver", () => {
    const index = new PositionIndex(5, 60);
    const [lat, lng] = CENTER;
    index.putPosition("nearest", ...offsetM(lat, lng, 100, 0), 0, 0);
    index.putPosition("second", ...offsetM(lat, lng, 200, 0), 0, 0);
    const a = matchSteps(index, lat, lng, "trip-a", 1);
    const b = matchSteps(index, lat, lng, "trip-b", 1);
    a.next(); // a queries
    b.next(); // b queries, sees the same list
    const aClaim = a.next(); // a claims nearest
    const bClaim = b.next(); // b tries nearest, loses
    expect(aClaim.value && !aClaim.done && aClaim.value.kind === "claim" && aClaim.value.ok, "a wins");
    expect(bClaim.value && !bClaim.done && bClaim.value.kind === "claim" && !bClaim.value.ok, "b loses");
    let bDone = b.next();
    while (!bDone.done) bDone = b.next();
    expect(bDone.value.driver?.driverId === "second" && bDone.value.candidatesSeen === 2, "b falls through");
    let aDone = a.next();
    while (!aDone.done) aDone = a.next();
    expect(aDone.value.driver?.driverId === "nearest", "a keeps nearest");
    return true;
  });

  let load: SelfCheckReport["load"] = null;
  check("synthetic load: 600 rides, no double-assigned driver", () => {
    const world = new World({ seed: 42, driverCount: 300, ttlSeconds: 20 });
    world.tick(1); // let the fleet warm up
    world.scheduleLoad(10, 60);
    let doubleAssigned = 0;
    const activeByDriver = new Map<string, string>();
    for (let i = 0; i < 90 * 20; i++) {
      world.tick(0.05);
      activeByDriver.clear();
      for (const id of world.tripOrder) {
        const trip = world.trips.get(id)!;
        if ((trip.status === "matched" || trip.status === "en_route") && trip.driverId) {
          if (activeByDriver.has(trip.driverId)) doubleAssigned += 1;
          activeByDriver.set(trip.driverId, id);
        }
      }
    }
    const counts = world.counts();
    load = {
      submitted: counts.submitted,
      matched: counts.matched,
      perMinute: world.rate.perMinute(),
      p50: world.latency.p50(),
      p95: world.latency.p95(),
      doubleAssigned,
    };
    expect(counts.submitted === 600, `submitted ${counts.submitted}`);
    expect(counts.matched >= 500, `matched ${counts.matched}`);
    expect(doubleAssigned === 0, `double assigned ${doubleAssigned}`);
    expect((load.perMinute ?? 0) >= 500, `per minute ${load.perMinute}`);
    return `${counts.matched}/${counts.submitted} matched, ${Math.round(load.perMinute ?? 0)}/min, p50 ${load.p50} ms, p95 ${load.p95} ms`;
  });

  return { ok: results.every((r) => r.ok), results, load };
}

export function formatReport(report: SelfCheckReport): string {
  const lines = report.results.map((r) => `${r.ok ? "PASS" : "FAIL"}  ${r.name}: ${r.detail}`);
  lines.push(report.ok ? "self-check passed" : "self-check FAILED");
  return lines.join("\n");
}

// `npm run selfcheck` entry point (tsx); the browser imports runSelfCheck instead.
const isNodeMain =
  typeof process !== "undefined" &&
  Array.isArray(process.argv) &&
  /selfcheck\.ts$/.test(process.argv[1] ?? "");
if (isNodeMain) {
  const report = runSelfCheck();
  console.log(formatReport(report));
  process.exit(report.ok ? 0 : 1);
}
