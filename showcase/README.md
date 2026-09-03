# RideLoop showcase

Interactive web demo of the dispatch path, running entirely in the browser.
`src/sim/` is a TypeScript port of the geohash module, the cell-partitioned
position index with TTL, the expanding-radius matcher with conditional claims,
and the grid-city simulators. `npm run selfcheck` runs the same vectors as the
Python tests plus a 600 ride synthetic load; the app runs it once at startup and
prints the report to the console.

```
npm install
npm run dev        # http://localhost:5173
npm run build      # tsc -b && vite build -> dist/
npm run selfcheck  # port self-check under tsx
```

Deploy with the Vercel project root set to `showcase/`; `vercel.json` here
carries the framework and rewrite settings.

The headline numbers on the page come from `make demo` in the repository root
(300 drivers, 600 rides in 60 s, 601 matches per minute, p50 59 ms). Match
latency inside this tab is modeled from the same sources as the real one:
the dispatcher's 100 ms poll wait, one read per partition in the query plan,
one conditional update per claim attempt, and the commit.
