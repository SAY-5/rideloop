/** Great-circle helpers. Port of rideloop_common/geo.py. */

export const EARTH_RADIUS_M = 6_371_008.8;

const RAD = Math.PI / 180;

/** Distance in meters between two WGS84 points along the sphere. */
export function haversineM(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const phi1 = lat1 * RAD;
  const phi2 = lat2 * RAD;
  const dphi = (lat2 - lat1) * RAD;
  const dlambda = (lng2 - lng1) * RAD;
  const a =
    Math.sin(dphi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlambda / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
}

/** Move a point by the given meters north and east (small-distance approximation). */
export function offsetM(lat: number, lng: number, northM: number, eastM: number): [number, number] {
  const dlat = northM / EARTH_RADIUS_M;
  const dlng = eastM / (EARTH_RADIUS_M * Math.cos(lat * RAD));
  return [lat + dlat / RAD, lng + dlng / RAD];
}
