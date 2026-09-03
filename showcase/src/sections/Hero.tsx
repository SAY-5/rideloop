import { motion, useReducedMotion } from "framer-motion";
import { CityMap } from "../components/CityMap";
import { CountUp } from "../components/CountUp";
import { useWorld } from "../sim/WorldProvider";
import { REAL } from "../real";


export function Hero() {
  const { world } = useWorld();
  const reduceMotion = useReducedMotion();
  const counts = world.counts();
  const online = world.drivers.filter((d) => world.index.isVisible(d.driverId, world.now)).length;

  const rise = (delay: number) => ({
    initial: reduceMotion ? false : { opacity: 0, y: 22 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.8, delay, ease: [0.22, 1, 0.36, 1] as const },
  });

  return (
    <header className="hero" id="top">
      <div className="wrap hero-grid">
        <div className="hero-copy">
          <motion.span className="eyebrow" {...rise(0.05)}>
            RideLoop dispatch, in the browser
          </motion.span>
          <motion.h1 className="hero-title" {...rise(0.15)}>
            Five hundred rides a&nbsp;minute, <em>matched.</em>
          </motion.h1>
          <motion.p className="lede" {...rise(0.28)}>
            Driver positions land in a geohash-partitioned index with a TTL. A dispatcher sweeps
            requested trips, ranks the drivers around each pickup nearest first, and claims one with
            a conditional write that cannot hand a driver to two riders. This page runs a faithful
            TypeScript port of that path against 300 synthetic drivers.
          </motion.p>
          <motion.div className="hero-actions" {...rise(0.4)}>
            <a className="btn btn-primary" href="#load">
              Run the 60 second load
            </a>
            <a className="btn" href="#cells">
              See how it works
            </a>
          </motion.div>
          <motion.dl className="hero-stats" {...rise(0.52)}>
            <div className="stat">
              <dt className="stat-label">matches per minute</dt>
              <dd className="stat-value is-lime">
                <CountUp to={REAL.perMinute} duration={1.8} delay={0.6} />
              </dd>
            </div>
            <div className="stat">
              <dt className="stat-label">rides matched</dt>
              <dd className="stat-value">
                <CountUp to={REAL.matched} duration={1.8} delay={0.7} />
                <span className="stat-unit">/ {REAL.submitted}</span>
              </dd>
            </div>
            <div className="stat">
              <dt className="stat-label">match latency p50</dt>
              <dd className="stat-value">
                <CountUp to={REAL.p50} duration={1.6} delay={0.8} />
                <span className="stat-unit">ms</span>
              </dd>
            </div>
            <div className="stat">
              <dt className="stat-label">p95</dt>
              <dd className="stat-value">
                <CountUp to={REAL.p95} duration={1.6} delay={0.9} />
                <span className="stat-unit">ms</span>
              </dd>
            </div>
          </motion.dl>
          <motion.p className="hero-note" {...rise(0.65)}>
            Headline figures are from <code>make demo</code> on a laptop: three Python services,
            DynamoDB Local and PostgreSQL, 300 drivers, 600 rides in 60 s, every number read back
            from the running system.
          </motion.p>
        </div>
        <motion.div
          className="hero-map glass"
          initial={reduceMotion ? false : { opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 1.1, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
        >
          <CityMap label="City map with 300 simulated drivers moving along a road grid" />
          <div className="hero-map-strip mono" aria-live="off">
            <span>
              <b>{online}</b> drivers visible
            </span>
            <span>
              <b className="is-lime">{counts.busy}</b> busy
            </span>
            <span>
              <b>{world.index.partitions().length}</b> partitions
            </span>
            <span>
              t+<b>{world.now.toFixed(1)}</b>s
            </span>
          </div>
        </motion.div>
      </div>
      <div className="hero-glow" aria-hidden="true" />
    </header>
  );
}
