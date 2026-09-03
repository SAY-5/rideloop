/**
 * Geohash encode, decode and neighbors. Port of rideloop_common/geohash.py.
 *
 * A geohash interleaves longitude and latitude bits and packs them five at a
 * time into a base32 alphabet. A prefix is a bounding box that contains the
 * full hash, which is what makes it a good partition key.
 */

export const BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz";
const DECODE = new Map<string, number>();
for (let i = 0; i < BASE32.length; i++) DECODE.set(BASE32[i], i);

export const DEFAULT_PRECISION = 6;

export type Direction = "n" | "s" | "e" | "w";

// Index 0 is used when the hash length is even, index 1 when it is odd.
const NEIGHBORS: Record<Direction, [string, string]> = {
  n: ["p0r21436x8zb9dcf5h7kjnmqesgutwvy", "bc01fg45238967deuvhjyznpkmstqrwx"],
  s: ["14365h7k9dcfesgujnmqp0r2twvyx8zb", "238967debc01fg45kmstqrwxuvhjyznp"],
  e: ["bc01fg45238967deuvhjyznpkmstqrwx", "p0r21436x8zb9dcf5h7kjnmqesgutwvy"],
  w: ["238967debc01fg45kmstqrwxuvhjyznp", "14365h7k9dcfesgujnmqp0r2twvyx8zb"],
};
const BORDERS: Record<Direction, [string, string]> = {
  n: ["prxz", "bcfguvyz"],
  s: ["028b", "0145hjnp"],
  e: ["bcfguvyz", "prxz"],
  w: ["0145hjnp", "028b"],
};

function checkCoords(lat: number, lng: number): void {
  if (!(lat >= -90 && lat <= 90)) throw new RangeError(`latitude out of range: ${lat}`);
  if (!(lng >= -180 && lng <= 180)) throw new RangeError(`longitude out of range: ${lng}`);
}

/** Encode a coordinate pair into a geohash of the given character length. */
export function encode(lat: number, lng: number, precision: number = DEFAULT_PRECISION): string {
  checkCoords(lat, lng);
  if (precision < 1 || precision > 12) throw new RangeError("precision must be between 1 and 12");
  let latLo = -90;
  let latHi = 90;
  let lngLo = -180;
  let lngHi = 180;
  let out = "";
  let bits = 0;
  let value = 0;
  let even = true;
  while (out.length < precision) {
    if (even) {
      const mid = (lngLo + lngHi) / 2;
      if (lng >= mid) {
        value = (value << 1) | 1;
        lngLo = mid;
      } else {
        value <<= 1;
        lngHi = mid;
      }
    } else {
      const mid = (latLo + latHi) / 2;
      if (lat >= mid) {
        value = (value << 1) | 1;
        latLo = mid;
      } else {
        value <<= 1;
        latHi = mid;
      }
    }
    even = !even;
    bits += 1;
    if (bits === 5) {
      out += BASE32[value];
      bits = 0;
      value = 0;
    }
  }
  return out;
}

export type Bbox = readonly [latMin: number, latMax: number, lngMin: number, lngMax: number];

/** Bounding box (latMin, latMax, lngMin, lngMax) of a cell. */
export function decodeBbox(geohash: string): Bbox {
  if (!geohash) throw new RangeError("geohash must not be empty");
  let latLo = -90;
  let latHi = 90;
  let lngLo = -180;
  let lngHi = 180;
  let even = true;
  for (const ch of geohash) {
    const value = DECODE.get(ch);
    if (value === undefined) throw new RangeError(`invalid geohash character: ${ch}`);
    for (const shift of [4, 3, 2, 1, 0]) {
      const bit = (value >> shift) & 1;
      if (even) {
        const mid = (lngLo + lngHi) / 2;
        if (bit) lngLo = mid;
        else lngHi = mid;
      } else {
        const mid = (latLo + latHi) / 2;
        if (bit) latLo = mid;
        else latHi = mid;
      }
      even = !even;
    }
  }
  return [latLo, latHi, lngLo, lngHi];
}

/** Center (lat, lng) of a cell. */
export function decode(geohash: string): [number, number] {
  const [latLo, latHi, lngLo, lngHi] = decodeBbox(geohash);
  return [(latLo + latHi) / 2, (lngLo + lngHi) / 2];
}

/** The neighboring cell in direction n, s, e or w. */
export function adjacent(geohash: string, direction: Direction): string {
  if (!geohash) throw new RangeError("geohash must not be empty");
  geohash = geohash.toLowerCase();
  const last = geohash[geohash.length - 1];
  let parent = geohash.slice(0, -1);
  const kind = geohash.length % 2;
  if (BORDERS[direction][kind].includes(last) && parent) {
    parent = adjacent(parent, direction);
  }
  const idx = NEIGHBORS[direction][kind].indexOf(last);
  if (idx < 0) throw new RangeError(`invalid geohash character: ${last}`);
  return parent + BASE32[idx];
}

/** The 8 surrounding cells, starting north and going clockwise. */
export function neighbors(geohash: string): string[] {
  const n = adjacent(geohash, "n");
  const s = adjacent(geohash, "s");
  return [
    n,
    adjacent(n, "e"),
    adjacent(geohash, "e"),
    adjacent(s, "e"),
    s,
    adjacent(s, "w"),
    adjacent(geohash, "w"),
    adjacent(n, "w"),
  ];
}

/** The cell itself followed by its 8 neighbors: the 3x3 block used for lookups. */
export function cellWithNeighbors(geohash: string): string[] {
  return [geohash, ...neighbors(geohash)];
}
