import { useCallback, useEffect, useRef, useState } from "react";
import { CityMap, type MapHighlight, type MapPin, type MapRing, type Tone } from "../components/CityMap";
import { Reveal } from "../components/Reveal";
import { offsetM } from "../sim/geo";
import { matchSteps, type MatchOutcome, type MatchStep } from "../sim/matcher";
import { useWorld } from "../sim/WorldProvider";
import type { Trip } from "../sim/world";

interface TraceLine {
  id: number;
  who: "A" | "B";
  kind: MatchStep["kind"] | "done" | "none";
  text: string;
  tone: Tone | "muted";
}

interface Run {
  who: "A" | "B";
  trip: Trip;
  radiusM: number;
  spent: number[];
  candidates: string[];
  won: string | null;
  lost: string[];
  outcome: MatchOutcome | null;
  latency: ReturnType<import("../sim/world").World["estimateLatency"]> | null;
}

const TONE_OF: Record<"A" | "B", Tone> = { A: "lime", B: "ice" };
const STEP_DELAY: Record<MatchStep["kind"], number> = { query: 700, claim: 650, widen: 550 };

export function Matching() {
  const { world } = useWorld();
  const [runs, setRuns] = useState<Run[]>([]);
  const [trace, setTrace] = useState<TraceLine[]>([]);
  const [busy, setBusy] = useState(false);
  const lineId = useRef(0);
  const timer = useRef<number | null>(null);

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  const log = useCallback((who: "A" | "B", kind: TraceLine["kind"], text: string, tone: TraceLine["tone"]) => {
    setTrace((t) => [...t.slice(-11), { id: lineId.current++, who, kind, text, tone }]);
  }, []);

  const start = useCallback(
    (pickups: { who: "A" | "B"; at: [number, number] }[]) => {
      if (timer.current) window.clearTimeout(timer.current);
      setBusy(true);
      setTrace([]);
      const now = world.now;
      const jobs = pickups.map(({ who, at }) => {
        const dropoff = offsetM(at[0], at[1], 900, -600);
        const trip = world.requestRide(at, dropoff, { manual: true, riderId: `rider-${who}` });
        const gen = matchSteps(world.index, at[0], at[1], trip.id, now, world.radii);
        const run: Run = { who, trip, radiusM: 0, spent: [], candidates: [], won: null, lost: [], outcome: null, latency: null };
        return { who, gen, run, done: false };
      });
      setRuns(jobs.map((j) => j.run));
      for (const j of jobs) log(j.who, "query", `${j.run.trip.id} requested at the pin`, "muted");

      const tick = () => {
        let delay = 0;
        for (const job of jobs) {
          if (job.done) continue;
          const next = job.gen.next();
          if (next.done) {
            job.done = true;
            const outcome = next.value;
            const latency = world.estimateLatency(outcome);
            job.run = { ...job.run, outcome, latency };
            world.applyOutcome(job.run.trip, outcome, Math.round(latency.totalMs));
            if (outcome.driver) {
              log(
                job.who,
                "done",
                `matched ${outcome.driver.driverId} at ${Math.round(outcome.driver.distanceM)} m, ring ${outcome.radiusM} m, ${outcome.candidatesSeen} candidate${outcome.candidatesSeen === 1 ? "" : "s"}, ${Math.round(latency.totalMs)} ms`,
                TONE_OF[job.who],
              );
            } else {
              log(job.who, "none", `no claimable driver within 4 km, trip stays requested and retries in 1 s`, "coral");
            }
            continue;
          }
          const step = next.value;
          delay = Math.max(delay, STEP_DELAY[step.kind]);
          if (step.kind === "query") {
            job.run = { ...job.run, radiusM: step.radiusM, candidates: step.candidates.map((c) => c.driverId) };
            log(
              job.who,
              "query",
              `nearby r=${step.radiusM} m: ${step.plan.length} partition${step.plan.length === 1 ? "" : "s"} read, ${step.candidates.length} available driver${step.candidates.length === 1 ? "" : "s"}${step.candidates[0] ? `, nearest ${step.candidates[0].driverId} at ${Math.round(step.candidates[0].distanceM)} m` : ""}`,
              "muted",
            );
          } else if (step.kind === "widen") {
            job.run = { ...job.run, spent: [...job.run.spent, step.fromM] };
            log(job.who, "widen", `no claim at ${step.fromM} m, widen to ${step.toM} m`, "muted");
          } else {
            if (step.ok) {
              job.run = { ...job.run, won: step.driver.driverId };
              log(job.who, "claim", `claim ${step.driver.driverId}: status=available AND ttl>now held, now busy`, TONE_OF[job.who]);
            } else {
              job.run = { ...job.run, lost: [...job.run.lost, step.driver.driverId] };
              log(job.who, "claim", `claim ${step.driver.driverId}: ConditionalCheckFailed, already busy, next candidate`, "coral");
            }
          }
        }
        setRuns(jobs.map((j) => j.run));
        if (jobs.every((j) => j.done)) {
          setBusy(false);
          return;
        }
        timer.current = window.setTimeout(tick, delay || 400);
      };
      timer.current = window.setTimeout(tick, 350);
    },
    [world, log],
  );

  const dropPin = (lat: number, lng: number) => {
    if (busy) return;
    start([{ who: "A", at: [lat, lng] }]);
  };

  const randomPin = () => {
    if (busy) return;
    const driver = world.drivers[world.rng.int(world.drivers.length)];
    const [lat, lng] = driver.latlng();
    start([{ who: "A", at: offsetM(lat, lng, world.rng.uniform(-300, 300), world.rng.uniform(-300, 300)) }]);
  };

  const contend = () => {
    if (busy) return;
    // two riders a few meters apart share the same nearest driver
    const available = world.drivers.filter((d) => world.index.getDriver(d.driverId)?.status === "available");
    const driver = available[world.rng.int(available.length)] ?? world.drivers[0];
    const [lat, lng] = driver.latlng();
    start([
      { who: "A", at: offsetM(lat, lng, 60, 40) },
      { who: "B", at: offsetM(lat, lng, -50, 70) },
    ]);
  };

  const pins: MapPin[] = runs.map((r) => ({
    id: r.trip.id,
    lat: r.trip.pickupLat,
    lng: r.trip.pickupLng,
    tone: TONE_OF[r.who],
    label: runs.length > 1 ? `rider ${r.who}` : "pickup",
  }));
  const rings: MapRing[] = runs.flatMap((r) => [
    ...r.spent.map((m) => ({ id: `${r.trip.id}-${m}`, lat: r.trip.pickupLat, lng: r.trip.pickupLng, radiusM: m, tone: TONE_OF[r.who], spent: true })),
    ...(r.radiusM ? [{ id: `${r.trip.id}-${r.radiusM}`, lat: r.trip.pickupLat, lng: r.trip.pickupLng, radiusM: r.radiusM, tone: TONE_OF[r.who] }] : []),
  ]);
  const highlights: MapHighlight[] = runs.flatMap((r) => [
    ...r.candidates.filter((id) => id !== r.won && !r.lost.includes(id)).map((driverId) => ({ driverId, tone: TONE_OF[r.who], hollow: true })),
    ...r.lost.map((driverId) => ({ driverId, tone: "coral" as Tone, hollow: true })),
    ...(r.won ? [{ driverId: r.won, tone: TONE_OF[r.who] }] : []),
  ]);

  return (
    <section className="section" id="matching" aria-labelledby="matching-title">
      <div className="wrap">
        <Reveal className="section-intro">
          <div>
            <span className="eyebrow">02 / nearest driver, one claim</span>
            <h2 className="title" id="matching-title">
              Widen the ring, claim the nearest, never twice.
            </h2>
          </div>
          <p className="lede">
            The matcher queries available drivers at 500 m, ranked by haversine distance, and tries to
            claim the nearest with a conditional update: <code>status = available AND ttl &gt; now</code>.
            If the claim fails it moves to the next candidate; if a ring is empty it doubles to 1, 2 and
            4 km. Two dispatchers racing for one driver cannot both win, so the loser just takes the
            next nearest.
          </p>
        </Reveal>

        <div className="demo-grid">
          <Reveal className="demo-map glass" delay={0.1}>
            <span className="demo-map-hint">{busy ? "matching" : "click the map to drop a pickup"}</span>
            <CityMap
              label="City map; click to drop a pickup pin and watch the matcher search"
              onClick={dropPin}
              pins={pins}
              rings={rings}
              highlights={highlights}
            />
          </Reveal>

          <Reveal className="panel glass" delay={0.2}>
            <div className="controls">
              <button type="button" className="btn btn-primary" onClick={randomPin} disabled={busy}>
                Drop a pickup
              </button>
              <button type="button" className="btn" onClick={contend} disabled={busy}>
                Two riders, one driver
              </button>
            </div>

            {runs.length > 0 && (
              <div className="run-cards">
                {runs.map((r) => (
                  <div key={r.trip.id} className={`run-card is-${TONE_OF[r.who]}`}>
                    <div className="run-card-head">
                      <span className="tag" style={{ color: `var(--${TONE_OF[r.who]})` }}>rider {r.who}</span>
                      <span className="mono run-card-trip">{r.trip.id}</span>
                    </div>
                    {r.outcome ? (
                      r.outcome.driver ? (
                        <dl className="kv">
                          <dt>driver</dt>
                          <dd className={r.who === "A" ? "is-lime" : ""}>{r.outcome.driver.driverId} at {Math.round(r.outcome.driver.distanceM)} m</dd>
                          <dt>ring</dt>
                          <dd>{r.outcome.radiusM} m, {r.outcome.candidatesSeen} tried</dd>
                          <dt>latency</dt>
                          <dd>
                            {Math.round(r.latency?.totalMs ?? 0)} ms
                            <span className="run-card-breakdown">
                              wait {Math.round(r.latency?.waitMs ?? 0)} + reads {Math.round(r.latency?.readsMs ?? 0)} + claims{" "}
                              {Math.round(r.latency?.claimsMs ?? 0)} + commit {Math.round(r.latency?.commitMs ?? 0)}
                            </span>
                          </dd>
                        </dl>
                      ) : (
                        <p className="mono" style={{ color: "var(--coral)", fontSize: 13 }}>no driver within 4 km</p>
                      )
                    ) : (
                      <p className="mono" style={{ color: "var(--ink-3)", fontSize: 13 }}>
                        searching at {r.radiusM || 500} m
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}

            <ol className="trace" aria-live="polite" aria-label="Matcher trace">
              {trace.length === 0 && (
                <li className="trace-empty">
                  Drop a pickup to watch the search ring by ring. "Two riders, one driver" runs two matchers at once
                  against the same nearest driver: exactly one claim succeeds.
                </li>
              )}
              {trace.map((line) => (
                <li key={line.id} className={`trace-line is-${line.tone}`}>
                  <span className="trace-who" style={{ color: `var(--${TONE_OF[line.who]})` }}>{line.who}</span>
                  <span className="trace-kind">{line.kind}</span>
                  <span className="trace-text">{line.text}</span>
                </li>
              ))}
            </ol>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
