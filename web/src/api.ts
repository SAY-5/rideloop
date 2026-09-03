import type { LatLng } from './geo'

export type DriverStatus = 'available' | 'busy' | 'offline'
export type TripStatus = 'requested' | 'matched' | 'en_route' | 'completed' | 'cancelled'

export interface NearbyDriver {
  driver_id: string
  cell: string
  lat: number
  lng: number
  heading: number
  status: DriverStatus
  trip_id: string | null
  updated_at: string
  distance_m: number
}

export interface TripEvent {
  event: string
  at: string
}

export interface Trip {
  id: string
  rider_id: string
  pickup_lat: number
  pickup_lng: number
  dropoff_lat: number
  dropoff_lng: number
  status: TripStatus
  driver_id: string | null
  requested_at: string
  matched_at: string | null
  completed_at: string | null
  match_latency_ms: number | null
  events: TripEvent[]
}

export interface DispatchStats {
  matched_total: number
  pending: number
  matches_last_minute: number
  matches_per_minute: number
  p50_match_latency_ms: number | null
  p95_match_latency_ms: number | null
  sweeps: number
  uptime_s: number
}

const LOCATION = '/api/location'
const RIDES = '/api/rides'
const DISPATCH = '/api/dispatch'

async function json<T>(input: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(input, init)
  if (!resp.ok) {
    const body = await resp.text()
    throw new Error(`${resp.status} ${resp.statusText}: ${body}`)
  }
  return (await resp.json()) as T
}

export function fetchNearby(center: LatLng, radiusM: number): Promise<NearbyDriver[]> {
  const params = new URLSearchParams({
    lat: String(center.lat),
    lng: String(center.lng),
    radius_m: String(radiusM),
    limit: '1000',
  })
  return json(`${LOCATION}/drivers/nearby?${params}`)
}

export function requestRide(riderId: string, pickup: LatLng, dropoff: LatLng): Promise<Trip> {
  return json(`${RIDES}/rides`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ rider_id: riderId, pickup, dropoff }),
  })
}

export function fetchTrip(id: string): Promise<Trip> {
  return json(`${RIDES}/rides/${id}`)
}

export function tripAction(id: string, action: 'start' | 'complete' | 'cancel'): Promise<Trip> {
  return json(`${RIDES}/rides/${id}/${action}`, { method: 'POST' })
}

export function fetchDispatchStats(): Promise<DispatchStats> {
  return json(`${DISPATCH}/dispatch/stats`)
}
