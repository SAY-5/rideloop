# RideLoop showcase

Interactive model of the dispatch path, running entirely in the browser.
`src/sim/` implements the geohash module, the cell-partitioned
position index with TTL, the expanding-radius matcher with conditional claims,
and the grid-city simulators. `npm run selfcheck` runs the same vectors as the
Python tests plus a 600 ride synthetic load; the app runs it once at startup and
prints the report to the console.

```
npm ci --ignore-scripts
npm run dev        # http://localhost:5173
npm run build      # tsc -b && vite build -> dist/
npm run selfcheck  # port self-check under tsx
npm test           # rendered provenance regression checks
```

Deploy with the Vercel project root set to `showcase/`; `vercel.json` here
carries the framework and rewrite settings.

CI builds this directory and runs both checks in a separate `showcase` job;
the backend and `web/` rider app keep their own jobs. The locked install does
not execute package lifecycle scripts; Vite/tsx use the platform-specific
esbuild binary from the lockfile.

The headline numbers are **simulation settings**, not measured backend
results. Match latency inside this tab is modeled from the dispatcher's
100 ms poll wait, partition reads, conditional claim attempts and commit.
Rates use a virtual clock. The model releases a driver seven seconds after a
match; it does not execute v5 offers, declines, rematching or the full trip
lifecycle.

The old showcase values (601/min, p50/p95 59/101 ms) came from an early README,
while the root README reports a later v5 transcript (586/min, 62/1101 ms).
Neither has retained raw output, a run timestamp or machine metadata. They
are **historical, unverified** transcripts, not comparable current benchmarks.
See [measurement provenance](../docs/measurement-provenance.md) for immutable
sources and requirements for a future measured result.
