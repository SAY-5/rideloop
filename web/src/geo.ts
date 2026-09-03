// Mirrors sim/city.py: a flat local frame in meters around the city center.
export const CITY_CENTER = { lat: 37.7749, lng: -122.4194 }
export const CITY_HALF_M = 3000
export const BLOCK_M = 250
const EARTH_RADIUS_M = 6_371_008.8

const toRad = (deg: number) => (deg * Math.PI) / 180
const toDeg = (rad: number) => (rad * 180) / Math.PI

export interface LatLng {
  lat: number
  lng: number
}

export interface Local {
  north: number
  east: number
}

export function toLocal(p: LatLng): Local {
  const north = toRad(p.lat - CITY_CENTER.lat) * EARTH_RADIUS_M
  const east = toRad(p.lng - CITY_CENTER.lng) * EARTH_RADIUS_M * Math.cos(toRad(CITY_CENTER.lat))
  return { north, east }
}

export function toLatLng(p: Local): LatLng {
  const lat = CITY_CENTER.lat + toDeg(p.north / EARTH_RADIUS_M)
  const lng = CITY_CENTER.lng + toDeg(p.east / (EARTH_RADIUS_M * Math.cos(toRad(CITY_CENTER.lat))))
  return { lat, lng }
}

export function haversineM(a: LatLng, b: LatLng): number {
  const dLat = toRad(b.lat - a.lat)
  const dLng = toRad(b.lng - a.lng)
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h))
}
