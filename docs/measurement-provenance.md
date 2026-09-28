# Measurement provenance

## What the showcase measures

The showcase is a browser simulation, not a client of the Python services.
Its rate uses a virtual clock, and its latency is modeled from sweep waits,
partition reads, conditional claims and commits. Its load schedule is 300
drivers and 600 requests at 10 per simulated second for 60 seconds. These
are inputs, not a measured throughput claim. It releases drivers after seven
seconds rather than reproducing the backend's offer/decline/rematch and full
trip lifecycle.

`npm run selfcheck` checks shared geohash/matcher vectors, concurrent claims
and a synthetic load. Passing that check does not establish backend latency,
backend capacity or full behavioral parity with the v5 services.

## Historical transcripts: unverified

The repository contains two different documented runs:

| Documentation source | Values printed in that source | Context |
| --- | --- | --- |
| [Early README, `1945cbd`](https://github.com/SAY-5/rideloop/blob/1945cbd8fee7cc428ac63a65931e120592c37ac3/README.md) | 601 matches/min; p50 59 ms; p95 101 ms | Predates the offer/decline lifecycle. These values were copied into the showcase by [`06c7d3e`](https://github.com/SAY-5/rideloop/commit/06c7d3e29055efd0005dc5c9a42c8fafb3d7eea2). |
| [v5 README, `905549c`](https://github.com/SAY-5/rideloop/blob/905549cfaa0daa1b58f920e84c61b1cfa725cbb8/README.md) | 586 matches/min; p50 62 ms; p95 1101 ms | Describes offers with a 10% simulated decline rate, rematching and a multiprocess position generator. |

These links identify **documentation revisions**, not verified execution
revisions. Commit timestamps are not run timestamps. Inspection of the
tracked repository and its history on 2026-09-28 found no retained raw run
logs, machine metadata or complete run manifest for either transcript.
The README summaries are historical records of what was reported, not
independently verified benchmarks. The numerical difference is not evidence
of a performance regression: the behavior and workload changed, and the
environments cannot be compared.

The showcase therefore does not use either transcript as current headline
performance or a direct comparison with the browser model. The original
transcripts remain accessible in Git history; no raw evidence has been
reconstructed from their constants, and this change makes no new performance
claim.

## Requirements for a new measured result

A future full-stack run must retain all of the following before its numbers
are promoted to measured headlines:

- Exact execution commit and any dirty diff, command, workload and seed.
- UTC run start/end times, OS/architecture, CPU and available memory, runtime
  and container versions, and service configuration without secrets.
- Original stdout/stderr and machine-readable summaries from the running
  services, including errors, retries, declines, pending work and durations.
- Immutable artifact locations and checksums, with a description of what
  each latency and rate denominator includes.
- An independent reproduction or review of the retained evidence.

`make demo` exercises real local services with synthetic traffic; it is not
production traffic or a capacity benchmark merely because it runs in Docker.
Do not compare it directly to the browser's virtual-clock results.
