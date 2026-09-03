import type { DispatchStats, NearbyDriver } from '../api'

interface Props {
  drivers: NearbyDriver[]
  stats: DispatchStats | null
  online: boolean
}

function ms(v: number | null | undefined): string {
  return v == null ? '-' : `${Math.round(v)} ms`
}

export default function FleetStats({ drivers, stats, online }: Props) {
  const available = drivers.filter((d) => d.status === 'available').length
  const busy = drivers.filter((d) => d.status === 'busy').length
  return (
    <>
      <div className="card">
        <h2>Fleet</h2>
        <div className="grid2">
          <div className="stat">
            <span className="big">{drivers.length}</span>
            <span className="label">drivers on map</span>
          </div>
          <div className="stat">
            <span className="big">{available}</span>
            <span className="label">available</span>
          </div>
          <div className="stat">
            <span className="big">{busy}</span>
            <span className="label">busy</span>
          </div>
          <div className="stat">
            <span className="big">{online ? 'live' : 'offline'}</span>
            <span className="label">location service</span>
          </div>
        </div>
      </div>
      <div className="card">
        <h2>Dispatch</h2>
        <div className="grid2">
          <div className="stat">
            <span className="big">{stats ? Math.round(stats.matches_per_minute) : '-'}</span>
            <span className="label">matches / minute</span>
          </div>
          <div className="stat">
            <span className="big">{stats?.pending ?? '-'}</span>
            <span className="label">waiting for a driver</span>
          </div>
        </div>
        <div style={{ marginTop: 8 }}>
          <div className="row">
            <span className="label">Matched total</span>
            <span className="value">{stats?.matched_total ?? '-'}</span>
          </div>
          <div className="row">
            <span className="label">Match latency p50</span>
            <span className="value">{ms(stats?.p50_match_latency_ms)}</span>
          </div>
          <div className="row">
            <span className="label">Match latency p95</span>
            <span className="value">{ms(stats?.p95_match_latency_ms)}</span>
          </div>
          <div className="row">
            <span className="label">Sweeps</span>
            <span className="value">{stats?.sweeps ?? '-'}</span>
          </div>
        </div>
      </div>
    </>
  )
}
