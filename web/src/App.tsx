import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchDispatchStats,
  fetchNearby,
  fetchTrip,
  requestRide,
  tripAction,
  type DispatchStats,
  type NearbyDriver,
  type Trip,
} from './api'
import { CITY_CENTER, type LatLng } from './geo'
import CityMap from './components/CityMap'
import FleetStats from './components/FleetStats'
import TripPanel from './components/TripPanel'

const MAP_RADIUS_M = 4500
const RIDER_ID = `web-${Math.random().toString(36).slice(2, 8)}`

function useInterval(fn: () => void, ms: number) {
  const ref = useRef(fn)
  useEffect(() => {
    ref.current = fn
  }, [fn])
  useEffect(() => {
    ref.current()
    const id = setInterval(() => ref.current(), ms)
    return () => clearInterval(id)
  }, [ms])
}

export default function App() {
  const [drivers, setDrivers] = useState<NearbyDriver[]>([])
  const [online, setOnline] = useState(false)
  const [stats, setStats] = useState<DispatchStats | null>(null)
  const [pickup, setPickup] = useState<LatLng | null>(null)
  const [dropoff, setDropoff] = useState<LatLng | null>(null)
  const [trip, setTrip] = useState<Trip | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useInterval(
    useCallback(() => {
      fetchNearby(CITY_CENTER, MAP_RADIUS_M)
        .then((list) => {
          setDrivers(list)
          setOnline(true)
        })
        .catch(() => setOnline(false))
    }, []),
    1000,
  )

  useInterval(
    useCallback(() => {
      fetchDispatchStats()
        .then(setStats)
        .catch(() => setStats(null))
    }, []),
    2000,
  )

  const tripId = trip?.id
  const terminal = trip?.status === 'completed' || trip?.status === 'cancelled'
  useInterval(
    useCallback(() => {
      if (!tripId || terminal) return
      fetchTrip(tripId).then(setTrip).catch(() => undefined)
    }, [tripId, terminal]),
    1000,
  )

  const onPick = (point: LatLng) => {
    if (trip && !terminal) return
    if (trip) {
      setTrip(null)
      setPickup(point)
      setDropoff(null)
      return
    }
    if (!pickup) setPickup(point)
    else if (!dropoff) setDropoff(point)
    else {
      setPickup(point)
      setDropoff(null)
    }
  }

  const onRequest = async () => {
    if (!pickup || !dropoff) return
    setBusy(true)
    setError(null)
    try {
      setTrip(await requestRide(RIDER_ID, pickup, dropoff))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const onAction = async (action: 'start' | 'complete' | 'cancel') => {
    if (!trip) return
    setBusy(true)
    setError(null)
    try {
      setTrip(await tripAction(trip.id, action))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const onReset = () => {
    setTrip(null)
    setPickup(null)
    setDropoff(null)
    setError(null)
  }

  const hint = !pickup
    ? 'Click the map to set a pickup point'
    : !dropoff
      ? 'Click again to set the dropoff'
      : trip
        ? trip.status === 'requested'
          ? 'Looking for the nearest available driver'
          : trip.status === 'matched'
            ? `${trip.driver_id} is heading to the pickup`
            : trip.status === 'en_route'
              ? 'Trip in progress'
              : 'Trip finished'
        : 'Ready to request'

  return (
    <div className="layout">
      <div className="map-wrap">
        <CityMap drivers={drivers} pickup={pickup} dropoff={dropoff} trip={trip} onPick={onPick} />
        <div className="map-hint">{hint}</div>
        <div className="legend">
          <span style={{ '--dot': 'var(--available)' } as React.CSSProperties}>available</span>
          <span style={{ '--dot': 'var(--busy)' } as React.CSSProperties}>busy</span>
          <span style={{ '--dot': 'var(--matched)' } as React.CSSProperties}>your driver</span>
        </div>
      </div>
      <aside className="sidebar">
        <div className="brand">
          <h1>RideLoop</h1>
          <p>Rider map over the driver location, ride request and dispatch services.</p>
        </div>
        <TripPanel
          pickup={pickup}
          dropoff={dropoff}
          trip={trip}
          busy={busy}
          error={error}
          onRequest={onRequest}
          onAction={onAction}
          onReset={onReset}
        />
        <FleetStats drivers={drivers} stats={stats} online={online} />
      </aside>
    </div>
  )
}
