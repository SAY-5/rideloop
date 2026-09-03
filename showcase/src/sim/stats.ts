/** Latency percentiles and match-rate windows, the numbers the demo summary prints. */

export class LatencyStats {
  private readonly samples: number[] = [];
  private sorted: number[] | null = null;
  private sum = 0;

  push(ms: number): void {
    this.samples.push(ms);
    this.sum += ms;
    this.sorted = null;
  }

  get count(): number {
    return this.samples.length;
  }

  mean(): number | null {
    return this.samples.length ? this.sum / this.samples.length : null;
  }

  /** Nearest-rank percentile, p in [0, 100]. */
  percentile(p: number): number | null {
    if (!this.samples.length) return null;
    if (!this.sorted) this.sorted = [...this.samples].sort((a, b) => a - b);
    const rank = Math.max(1, Math.ceil((p / 100) * this.sorted.length));
    return this.sorted[rank - 1];
  }

  p50(): number | null {
    return this.percentile(50);
  }

  p95(): number | null {
    return this.percentile(95);
  }

  reset(): void {
    this.samples.length = 0;
    this.sum = 0;
    this.sorted = null;
  }
}

/** Timestamps of matches; answers "how many in the last minute" and the demo's overall rate. */
export class MatchRate {
  private readonly times: number[] = [];
  firstRequestAt: number | null = null;

  noteRequest(at: number): void {
    if (this.firstRequestAt === null || at < this.firstRequestAt) this.firstRequestAt = at;
  }

  noteMatch(at: number): void {
    this.times.push(at);
  }

  get total(): number {
    return this.times.length;
  }

  lastMinute(now: number): number {
    let n = 0;
    for (let i = this.times.length - 1; i >= 0 && this.times[i] > now - 60; i--) n += 1;
    return n;
  }

  /** matches / (last match - first request) * 60, the formula the demo summary uses. */
  perMinute(): number | null {
    if (this.firstRequestAt === null || this.times.length < 2) return null;
    const span = this.times[this.times.length - 1] - this.firstRequestAt;
    return span > 0 ? (this.times.length / span) * 60 : null;
  }

  /** Rate so far, measured against the current time while a run is in progress. */
  perMinuteSoFar(now: number): number | null {
    if (this.firstRequestAt === null || !this.times.length) return null;
    const span = now - this.firstRequestAt;
    return span > 0.5 ? (this.times.length / span) * 60 : null;
  }

  reset(): void {
    this.times.length = 0;
    this.firstRequestAt = null;
  }
}
