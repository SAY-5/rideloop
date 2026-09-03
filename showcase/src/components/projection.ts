/** Map projection: the city's local metric frame (north, east) to pixels on a square map. */

import { CITY_HALF_M, latLngToLocal, toLatLng } from "../sim/city";
import * as geohash from "../sim/geohash";

/** Extra meters drawn beyond the city edge so cells crossing the border are visible. */
export const MAP_MARGIN_M = 400;
export const MAP_EXTENT_M = CITY_HALF_M + MAP_MARGIN_M;

export function localToPx(northM: number, eastM: number, size: number): [number, number] {
  const scale = size / (2 * MAP_EXTENT_M);
  return [(eastM + MAP_EXTENT_M) * scale, (MAP_EXTENT_M - northM) * scale];
}

export function pxToLocal(x: number, y: number, size: number): [number, number] {
  const scale = (2 * MAP_EXTENT_M) / size;
  return [MAP_EXTENT_M - y * scale, x * scale - MAP_EXTENT_M];
}

export function latLngToPx(lat: number, lng: number, size: number): [number, number] {
  const [n, e] = latLngToLocal(lat, lng);
  return localToPx(n, e, size);
}

export function pxToLatLng(x: number, y: number, size: number): [number, number] {
  const [n, e] = pxToLocal(x, y, size);
  return toLatLng(n, e);
}

export function metersToPx(m: number, size: number): number {
  return (m * size) / (2 * MAP_EXTENT_M);
}

export interface CellRect {
  key: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /** center in lat/lng */
  center: [number, number];
}

/** Pixel rectangle of a geohash cell in the local frame (cells are near-rectangular at city scale). */
export function cellRect(key: string, size: number): CellRect {
  const [latLo, latHi, lngLo, lngHi] = geohash.decodeBbox(key);
  const [nLo, eLo] = latLngToLocal(latLo, lngLo);
  const [nHi, eHi] = latLngToLocal(latHi, lngHi);
  const [x0, y1] = localToPx(nLo, eLo, size);
  const [x1, y0] = localToPx(nHi, eHi, size);
  return { key, x: x0, y: y0, w: x1 - x0, h: y1 - y0, center: [(latLo + latHi) / 2, (lngLo + lngHi) / 2] };
}

const cellCache = new Map<number, string[]>();

/** Every geohash cell of the given precision that intersects the drawn map area. */
export function visibleCells(precision: number): string[] {
  const cached = cellCache.get(precision);
  if (cached) return cached;
  const seen = new Set<string>();
  const out: string[] = [];
  // sample more densely than the smallest cell edge at this precision
  const step = precision >= 6 ? 250 : 1000;
  for (let n = -MAP_EXTENT_M; n <= MAP_EXTENT_M; n += step) {
    for (let e = -MAP_EXTENT_M; e <= MAP_EXTENT_M; e += step) {
      const [lat, lng] = toLatLng(n, e);
      const key = geohash.encode(lat, lng, precision);
      if (!seen.has(key)) {
        seen.add(key);
        out.push(key);
      }
    }
  }
  cellCache.set(precision, out);
  return out;
}
