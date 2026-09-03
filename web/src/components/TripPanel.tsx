import type { Trip, TripStatus } from '../api'
import type { LatLng } from '../geo'

interface Props {
  pickup: LatLng | null
  dropoff: LatLng | null
  trip: Trip | null
  busy: boolean
  error: string | null
  onRequest: () => void
  onAction: (action: 'start' | 'complete' | 'cancel') => void
  onReset: () => void
}

const STEPS: { status: TripStatus; label: string }[] = [
  { status: 'requested', label: 'Requested' },
  { status: 'matched', label: 'Driver matched' },
  { status: 'en_route', label: 'En route' },
  { status: 'completed', label: 'Completed' },
]

const ORDER: Record<TripStatus, number> = {
  requested: 0,
  matched: 1,
  en_route: 2,
  completed: 3,
  cancelled: 4,
}

function fmt(p: LatLng | null): string {
  return p ? `${p.lat.toFixed(4)}, ${p.lng.toFixed(4)}` : 'click the map'
}

function timeOf(trip: Trip, event: string): string {
  const found = trip.events.find((e) => e.event === event)
  if (!found) return ''
  return new Date(found.at).toLocaleTimeString([], { hour12: false })
}

export default function TripPanel({ pickup, dropoff, trip, busy, error, onRequest, onAction, onReset }: Props) {
  const rank = trip ? ORDER[trip.status] : -1
  const cancelled = trip?.status === 'cancelled'

  return (
    <div className="card">
      <h2>Ride</h2>
      <div className="row">
        <span className="label">Pickup</span>
        <span className="value">{fmt(pickup)}</span>
      </div>
      <div className="row">
        <span className="label">Dropoff</span>
        <span className="value">{pickup ? fmt(dropoff) : ''}</span>
      </div>

      {!trip && (
        <div className="actions">
          <button className="primary" disabled={!pickup || !dropoff || busy} onClick={onRequest}>
            Request ride
          </button>
          {(pickup || dropoff) && <button onClick={onReset}>Clear</button>}
        </div>
      )}

      {trip && (
        <>
          <ul className="timeline" style={{ marginTop: 10 }}>
            {STEPS.map((step, i) => {
              const cls = cancelled
                ? i === 0
                  ? 'done'
                  : ''
                : i < rank
                  ? 'done'
                  : i === rank
                    ? 'current'
                    : ''
              return (
                <li key={step.status} className={cls}>
                  {step.label}
                  <small>{timeOf(trip, step.status)}</small>
                </li>
              )
            })}
            {cancelled && (
              <li className="current">
                Cancelled
                <small>{timeOf(trip, 'cancelled')}</small>
              </li>
            )}
          </ul>
          <div style={{ marginTop: 10 }}>
            <div className="row">
              <span className="label">Trip</span>
              <span className="value">{trip.id.slice(0, 8)}</span>
            </div>
            <div className="row">
              <span className="label">Driver</span>
              <span className="value">{trip.driver_id ?? (trip.status === 'requested' ? 'searching' : '')}</span>
            </div>
            <div className="row">
              <span className="label">Match latency</span>
              <span className="value">{trip.match_latency_ms != null ? `${trip.match_latency_ms} ms` : ''}</span>
            </div>
          </div>
          <div className="actions">
            {trip.status === 'matched' && (
              <button className="primary" disabled={busy} onClick={() => onAction('start')}>
                Start trip
              </button>
            )}
            {(trip.status === 'matched' || trip.status === 'en_route') && (
              <button disabled={busy} onClick={() => onAction('complete')}>
                Complete
              </button>
            )}
            {(trip.status === 'requested' || trip.status === 'matched' || trip.status === 'en_route') && (
              <button className="danger" disabled={busy} onClick={() => onAction('cancel')}>
                Cancel
              </button>
            )}
            {(trip.status === 'completed' || trip.status === 'cancelled') && (
              <button className="primary" onClick={onReset}>
                New ride
              </button>
            )}
          </div>
        </>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  )
}
