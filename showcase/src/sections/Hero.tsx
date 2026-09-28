import { motion, useReducedMotion } from "framer-motion";
import { CityMap } from "../components/CityMap";
import { CountUp } from "../components/CountUp";
import { useWorld } from "../sim/WorldProvider";
import { SIMULATION_CONFIG } from "../demo";


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
            A city of drivers. One ride, <em>matched.</em>
          </motion.h1>
          <motion.p className="lede" {...rise(0.28)}>
            Driver positions land in a geohash-partitioned index with a TTL. A dispatcher sweeps
            requested trips, ranks the drivers around each pickup nearest first, and claims one with
            a conditional write that cannot hand a driver to two riders. Explore a TypeScript model
            of that dispatch path against {SIMULATION_CONFIG.drivers} synthetic drivers.
          </motion.p>
          <motion.div className="hero-actions" {...rise(0.4)}>
            <a className="btn btn-primary" href="#load">
              Run the 60 second load
            </a>
            <a className="btn" href="#cells">
              See how it works
            </a>
          </motion.div>
          <motion.dl className="hero-stats" aria-label="Simulation configuration" {...rise(0.52)}>
            <div className="stat">
              <dt className="stat-label">simulated drivers</dt>
              <dd className="stat-value is-lime">
                <CountUp to={SIMULATION_CONFIG.drivers} duration={1.8} delay={0.6} />
              </dd>
            </div>
            <div className="stat">
              <dt className="stat-label">scheduled rides</dt>
              <dd className="stat-value">
                <CountUp to={Math.floor(SIMULATION_CONFIG.ratePerSecond * SIMULATION_CONFIG.durationS)} duration={1.8} delay={0.7} />
              </dd>
            </div>
            <div className="stat">
              <dt className="stat-label">requests / second</dt>
              <dd className="stat-value">
                <CountUp to={SIMULATION_CONFIG.ratePerSecond} duration={1.6} delay={0.8} />
              </dd>
            </div>
            <div className="stat">
              <dt className="stat-label">load duration</dt>
              <dd className="stat-value">
                <CountUp to={SIMULATION_CONFIG.durationS} duration={1.6} delay={0.9} />
                <span className="stat-unit">s</span>
              </dd>
            </div>
          </motion.dl>
          <motion.p className="hero-note" {...rise(0.65)}>
            These are workload settings, not benchmark results. The browser uses a virtual clock
            and modeled latency; it does not call the Python services, DynamoDB Local or PostgreSQL.
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
