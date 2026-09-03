/** Seeded PRNG (mulberry32). Every source of randomness in the showcase goes through this. */
export class Rng {
  private state: number;

  constructor(seed: number) {
    this.state = seed >>> 0;
  }

  /** Uniform float in [0, 1). */
  next(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  uniform(lo: number, hi: number): number {
    return lo + (hi - lo) * this.next();
  }

  int(n: number): number {
    return Math.floor(this.next() * n);
  }

  choice<T>(items: readonly T[]): T {
    return items[this.int(items.length)];
  }

  /** A child generator seeded from this one, mirroring random.Random(rng.random()). */
  fork(): Rng {
    return new Rng(Math.floor(this.next() * 4294967296));
  }
}
