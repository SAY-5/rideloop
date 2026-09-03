import { useState } from "react";
import { CityMap } from "../components/CityMap";
import { Reveal } from "../components/Reveal";
import { REAL } from "../real";
import { useWorld } from "../sim/WorldProvider";

const SPEEDS = [1, 2, 4, 8];
const BUCKETS = 10;
const BUCKET_MS = 20;

function fmt(v: number | null, digits = 0): string {
  return v === null ? "..." : v.toFixed(digits);
}

export function LoadRun() {
  const { world, speed, setSpeed } = useWorld();
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [total, setTotal] = useState(0);

  const counts = world.counts();
  const submitting = world.scheduledRemaining > 0;
  const running = startedAt !== null && (submitting || counts.pending > 0 || counts.submitted < total);
  const done = startedAt !== null && !running && counts.submitted >= total && total > 0;
  const elapsed = startedAt === null ? 0 : Math.min(REAL.durationS, world.now - startedAt);
  const rateSoFar = done ? world.rate.perMinute() : world.rate.perMinuteSoFar(world.now);
  const p50 = world.latency.p50();
  const p95 = world.latency.p95();
  const spanS = world.rate.perMinute() && world.rate.firstRequestAt !== null ? (world.rate.total / (world.rate.perMinute() as number)) * 60 : null;

  const start = () => {
    setTotal(world.scheduleLoad(REAL.ratePerSecond, REAL.durationS));
    setStartedAt(world.now);
  };

  // latency histogram
  const hist = new Array<number>(BUCKETS).fill(0);
  for (const id of world.tripOrder) {
    const trip = world.trips.get(id)!;
    if (trip.source !== "load" || trip.requestedAt < world.loadStartedAt || trip.matchLatencyMs === null) continue;
    hist[Math.min(BUCKETS - 1, Math.floor(trip.matchLatencyMs / BUCKET_MS))] += 1;
  }
  const histMax = Math.max(1, ...hist);
  const recent = world.log.filter((e) => e.kind === "match" || e.kind === "no_driver").slice(-6).reverse();

  return (
    <section className="section" id="load" aria-labelledby="load-title">
      <div className="wrap">
        <Reveal className="section-intro">
          <div>
            <span className="eyebrow">03 / the load run</span>
            <h2 className="title" id="load-title">
              Sixty seconds, ten rides a second.
            </h2>
          </div>
          <p className="lede">
            <code>make demo</code> seeds 300 drivers, submits rides at 10 per second for 60 seconds and
            rides each to completion. The same schedule runs here against the in-browser port: riders
            arrive on the clock, the dispatcher sweeps every 100 ms, drivers are released 7 s after a match.
            The submission rate is the ceiling, not the matcher.
          </p>
        </Reveal>

        <div className="demo-grid is-reversed">
          <Reveal className="panel glass" delay={0.1}>
            <div className="controls" style={{ justifyContent: "space-between" }}>
              <button type="button" className="btn btn-primary" onClick={start} disabled={running}>
                {running ? "Running" : done ? "Run again" : "Start the 60 s run"}
              </button>
              <div className="btn-group" role="group" aria-label="Simulation speed">
                {SPEEDS.map((s) => (
                  <button key={s} type="button" className="btn" aria-pressed={speed === s} onClick={() => setSpeed(s)}>
                    {s}x
                  </button>
                ))}
              </div>
            </div>

            <div className="progress" aria-hidden="true">
              <span style={{ width: `${(elapsed / REAL.durationS) * 100}%` }} />
            </div>
            <p className="mono progress-label" aria-live="polite">
              {startedAt === null
                ? "idle"
                : submitting
                  ? `submitting, ${elapsed.toFixed(1)} s of ${REAL.durationS} s`
                  : running
                    ? `draining ${counts.pending} pending`
                    : "complete"}
            </p>

            <dl className="load-stats">
              <div className="stat">
                <dt className="stat-label">submitted</dt>
                <dd className="stat-value">
                  {counts.submitted}
                  <span className="stat-unit">/ {total || REAL.submitted}</span>
                </dd>
              </div>
              <div className="stat">
                <dt className="stat-label">matched</dt>
                <dd className="stat-value">
                  {counts.matched}
                  <span className="stat-unit">{counts.submitted ? `${((counts.matched / counts.submitted) * 100).toFixed(0)}%` : ""}</span>
                </dd>
              </div>
              <div className="stat">
                <dt className="stat-label">matches / minute</dt>
                <dd className="stat-value is-lime">{fmt(rateSoFar)}</dd>
              </div>
              <div className="stat">
                <dt className="stat-label">p50 / p95</dt>
                <dd className="stat-value">
                  {fmt(p50)}
                  <span className="stat-unit">/ {fmt(p95)} ms</span>
                </dd>
              </div>
              <div className="stat">
                <dt className="stat-label">busy drivers</dt>
                <dd className="stat-value">{counts.busy}</dd>
              </div>
              <div className="stat">
                <dt className="stat-label">sweeps</dt>
                <dd className="stat-value">{world.sweeps}</dd>
              </div>
            </dl>

            <div className="hist" role="img" aria-label="Histogram of match latency in 20 millisecond buckets">
              {hist.map((n, i) => (
                <div key={i} className="hist-col">
                  <span className="hist-bar" style={{ height: `${(n / histMax) * 100}%` }} />
                  <span className="hist-label">{i === BUCKETS - 1 ? `${i * BUCKET_MS}+` : i * BUCKET_MS}</span>
                </div>
              ))}
            </div>

            <table className="compare" aria-label="Browser run compared with the measured demo">
              <thead>
                <tr>
                  <th scope="col"></th>
                  <th scope="col">this run</th>
                  <th scope="col">make demo</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">rides matched</th>
                  <td>{counts.matched} / {counts.submitted}</td>
                  <td>{REAL.matched} / {REAL.submitted}</td>
                </tr>
                <tr>
                  <th scope="row">matches per minute</th>
                  <td className="is-lime">{fmt(rateSoFar)}{done && spanS ? ` (over ${spanS.toFixed(1)} s)` : ""}</td>
                  <td className="is-lime">{REAL.perMinute} (over {REAL.spanS} s)</td>
                </tr>
                <tr>
                  <th scope="row">latency p50 / p95</th>
                  <td>{fmt(p50)} / {fmt(p95)} ms</td>
                  <td>{REAL.p50} / {REAL.p95} ms</td>
                </tr>
                <tr>
                  <th scope="row">drivers seeded</th>
                  <td>{world.drivers.length}, pinging every {world.pingIntervalS} s</td>
                  <td>{REAL.drivers}, {REAL.positionPosts.toLocaleString()} posts</td>
                </tr>
              </tbody>
            </table>

            <ul className="event-feed" aria-label="Recent dispatch events">
              {recent.length === 0 && <li className="trace-empty">match events will stream here</li>}
              {recent.map((e, i) => (
                <li key={`${e.at}-${i}`} className={`event-line${e.kind === "no_driver" ? " is-coral" : ""}`}>
                  <span className="event-at">t+{e.at.toFixed(2)}</span>
                  <span>{e.text}</span>
                </li>
              ))}
            </ul>
          </Reveal>

          <Reveal className="demo-map glass" delay={0.2}>
            <span className="demo-map-hint">{running ? `${counts.busy} drivers en route` : "fleet"}</span>
            <CityMap label="City map showing the fleet during the load run; busy drivers glow and head for their pickups" />
          </Reveal>
        </div>
      </div>
    </section>
  );
}
