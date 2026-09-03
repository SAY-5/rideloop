import type { MouseEvent } from 'react'
import type { NearbyDriver, Trip } from '../api'
import { BLOCK_M, CITY_HALF_M, toLatLng, toLocal, type LatLng } from '../geo'

interface Props {
  drivers: NearbyDriver[]
  pickup: LatLng | null
  dropoff: LatLng | null
  trip: Trip | null
  onPick: (point: LatLng) => void
}

const SIZE = CITY_HALF_M * 2

function project(p: LatLng): { x: number; y: number } {
  const { north, east } = toLocal(p)
  return { x: east, y: -north }
}

export default function CityMap({ drivers, pickup, dropoff, trip, onPick }: Props) {
  const roads: number[] = []
  for (let v = -CITY_HALF_M; v <= CITY_HALF_M; v += BLOCK_M) roads.push(v)

  const handleClick = (e: MouseEvent<SVGSVGElement>) => {
    const svg = e.currentTarget
    const rect = svg.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * SIZE - CITY_HALF_M
    const y = ((e.clientY - rect.top) / rect.height) * SIZE - CITY_HALF_M
    onPick(toLatLng({ north: -y, east: x }))
  }

  const matchedDriver = trip?.driver_id
    ? drivers.find((d) => d.driver_id === trip.driver_id) ?? null
    : null
  const pickupXY = pickup ? project(pickup) : null
  const dropoffXY = dropoff ? project(dropoff) : null
  const matchedXY = matchedDriver ? project(matchedDriver) : null
  const active = trip && (trip.status === 'matched' || trip.status === 'en_route')

  return (
    <svg
      className="map"
      viewBox={`${-CITY_HALF_M} ${-CITY_HALF_M} ${SIZE} ${SIZE}`}
      onClick={handleClick}
      role="img"
      aria-label="city map with drivers"
    >
      <rect x={-CITY_HALF_M} y={-CITY_HALF_M} width={SIZE} height={SIZE} fill="#f9fafb" />
      {roads.map((v) => {
        const major = v % 1000 === 0
        const stroke = major ? 'var(--road-major)' : 'var(--road)'
        const width = major ? 14 : 7
        return (
          <g key={v}>
            <line x1={v} y1={-CITY_HALF_M} x2={v} y2={CITY_HALF_M} stroke={stroke} strokeWidth={width} />
            <line x1={-CITY_HALF_M} y1={v} x2={CITY_HALF_M} y2={v} stroke={stroke} strokeWidth={width} />
          </g>
        )
      })}

      {drivers.map((d) => {
        const { x, y } = project(d)
        const mine = matchedDriver?.driver_id === d.driver_id
        const fill = mine ? 'var(--matched)' : d.status === 'busy' ? 'var(--busy)' : 'var(--available)'
        return (
          <g key={d.driver_id} transform={`translate(${x} ${y}) rotate(${d.heading})`}>
            <circle r={mine ? 42 : 30} fill={fill} opacity={d.status === 'offline' ? 0.3 : 0.9} />
            <line x1={0} y1={0} x2={0} y2={mine ? -70 : -50} stroke={fill} strokeWidth={10} strokeLinecap="round" />
          </g>
        )
      })}

      {active && matchedXY && pickupXY && (
        <line
          x1={matchedXY.x}
          y1={matchedXY.y}
          x2={pickupXY.x}
          y2={pickupXY.y}
          stroke="var(--matched)"
          strokeWidth={10}
          strokeDasharray="40 30"
          opacity={0.8}
        />
      )}

      {pickupXY && dropoffXY && (
        <line
          x1={pickupXY.x}
          y1={pickupXY.y}
          x2={dropoffXY.x}
          y2={dropoffXY.y}
          stroke="var(--accent)"
          strokeWidth={6}
          strokeDasharray="20 20"
          opacity={0.5}
        />
      )}

      {dropoffXY && (
        <g transform={`translate(${dropoffXY.x} ${dropoffXY.y})`}>
          <rect x={-40} y={-40} width={80} height={80} fill="#fff" stroke="var(--accent)" strokeWidth={12} />
        </g>
      )}

      {pickupXY && (
        <g transform={`translate(${pickupXY.x} ${pickupXY.y})`}>
          {trip?.status === 'requested' && <circle className="pulse" r={60} fill="none" stroke="var(--accent)" strokeWidth={8} />}
          <circle r={55} fill="var(--accent)" />
          <circle r={22} fill="#fff" />
        </g>
      )}
    </svg>
  )
}
