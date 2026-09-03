import { useMemo, useState } from "react";
import { CityMap, type MapHighlight } from "../components/CityMap";
import { Reveal } from "../components/Reveal";
import { REAL } from "../real";
import { haversineM } from "../sim/geo";
import * as geohash from "../sim/geohash";
import { useWorld } from "../sim/WorldProvider";

type Overlay = "off" | "partitions" | "subcells";

const DEFAULT_CELL = geohash.encode(37.7749, -122.4194, 6); // 9q8yyk, the city center

function cellSizeKm(key: string): [number, number] {
  const [latLo, latHi, lngLo, lngHi] = geohash.decodeBbox(key);
  const midLat = (latLo + latHi) / 2;
  const width = haversineM(midLat, lngLo, midLat, lngHi) / 1000;
  const height = haversineM(latLo, lngLo, latHi, lngLo) / 1000;
  return [width, height];
}

export function Cells() {
  const { world } = useWorld();
  const [overlay, setOverlay] = useState<Overlay>("subcells");
  const [selected, setSelected] = useState<string>(DEFAULT_CELL);
  const [silencedAt, setSilencedAt] = useState<number | null>(null);

  const parent = selected.slice(0, 5);
  const subcell = selected.length === 6 ? selected : null;
  const block = useMemo(() => geohash.cellWithNeighbors(parent), [parent]);
  const [center] = useMemo(() => [geohash.decode(subcell ?? parent)], [subcell, parent]);
  const [partWkm, partHkm] = useMemo(() => cellSizeKm(parent), [parent]);
  const [subWkm, subHkm] = useMemo(() => cellSizeKm(subcell ?? `${parent}s`), [subcell, parent]);

  const planSmall = world.index.queryPlan(center[0], center[1], 500);
  const planLarge = world.index.queryPlan(center[0], center[1], 4000);
  const inPartition = world.index.partitionSize(parent);
  let inSubcell = 0;
  if (subcell) {
    for (const item of world.index.queryCell(parent, world.now, [subcell])) if (item) inSubcell += 1;
  }

  // ttl demo
  const driverId = REAL.silencedDriver;
  const item = world.index.getDriver(driverId);
  const silenced = world.silenced.has(driverId);
  const remaining = item ? item.ttl - world.now : 0;
  const visible = item ? item.ttl > world.now : false;
  const sinceSilence = silencedAt === null ? null : world.now - silencedAt;

  const silence = () => {
    world.silence(driverId);
    setSilencedAt(world.now);
  };
  const resume = () => {
    world.resume(driverId);
    setSilencedAt(null);
  };

  const highlights: MapHighlight[] = [{ driverId, tone: silenced ? "coral" : "ice", hollow: true }];

  const cellsLayer =
    overlay === "subcells"
      ? { precision: 6 as const, selected: subcell, onSelect: setSelected }
      : overlay === "partitions"
        ? { precision: 5 as const, selected: parent, onSelect: setSelected }
        : null;

  return (
    <section className="section" id="cells" aria-labelledby="cells-title">
      <div className="wrap">
        <Reveal className="section-intro">
          <div>
            <span className="eyebrow">01 / geohash cells</span>
            <h2 className="title" id="cells-title">
              One partition per city block of drivers.
            </h2>
          </div>
          <p className="lede">
            The partition key is the position's geohash at precision 5, a box about 4.9 km tall. Every
            driver inside shares the key, so "who is near this point" becomes a handful of key lookups:
            the rider's cell and its eight neighbors. A precision-6 <code>geohash</code> attribute
            narrows small searches inside a partition. Each ping refreshes a <code>ttl</code>; reads
            treat it as authoritative, so a silent driver disappears the second it passes.
          </p>
        </Reveal>

        <div className="demo-grid">
          <Reveal className="demo-map glass" delay={0.1}>
            <span className="demo-map-hint">
              {overlay === "off" ? "overlay off" : overlay === "partitions" ? "click a partition" : "click a subcell"}
            </span>
            <CityMap
              label="City map with the geohash grid overlay; select a cell to inspect its partition"
              cells={cellsLayer}
              partitionOutline={overlay === "subcells"}
              partitionBlock={overlay === "off" ? [] : block}
              highlights={highlights}
            />
          </Reveal>

          <Reveal className="panel glass" delay={0.2}>
            <div className="controls" role="group" aria-label="Grid overlay">
              <span className="panel-title">overlay</span>
              <div className="btn-group">
                {(["off", "partitions", "subcells"] as Overlay[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    className="btn"
                    aria-pressed={overlay === mode}
                    onClick={() => setOverlay(mode)}
                  >
                    {mode === "partitions" ? "precision 5" : mode === "subcells" ? "precision 6" : "off"}
                  </button>
                ))}
              </div>
            </div>

            <dl className="kv">
              <dt>partition key</dt>
              <dd className="is-lime">
                cell = "{parent}" <span className="tag">{partWkm.toFixed(1)} x {partHkm.toFixed(1)} km</span>
              </dd>
              <dt>geohash attr</dt>
              <dd>
                {subcell ? (
                  <>
                    "{subcell}" <span className="tag">{subWkm.toFixed(2)} x {subHkm.toFixed(2)} km</span>
                  </>
                ) : (
                  <span style={{ color: "var(--ink-3)" }}>select a precision-6 subcell</span>
                )}
              </dd>
              <dt>items in partition</dt>
              <dd>{inPartition} drivers</dd>
              {subcell && (
                <>
                  <dt>items in subcell</dt>
                  <dd>{inSubcell} drivers</dd>
                </>
              )}
            </dl>

            <div>
              <span className="panel-title">3 x 3 neighbor block, cell_with_neighbors("{parent}")</span>
              <div className="neighbor-grid" style={{ marginTop: 10 }} aria-label="Neighbor cells">
                {[block[8], block[1], block[2], block[7], block[0], block[3], block[6], block[5], block[4]].map(
                  (key, i) => (
                    <span key={key} className={`cellkey${i === 4 ? " is-center" : ""}`}>
                      {key}
                      <small>{["nw", "n", "ne", "w", "center", "e", "sw", "s", "se"][i]}</small>
                    </span>
                  ),
                )}
              </div>
            </div>

            <pre className="code-block" aria-label="Query plan for the selected cell">
              <span className="c">{"// nearby(center of " + (subcell ?? parent) + ")"}</span>
              {"\n"}
              <span className="k">radius 500 m</span>
              {"   -> " + planSmall.length + " partition" + (planSmall.length === 1 ? "" : "s") + ", "}
              <span className="v">{"geohash IN (" + planSmall.reduce((n, p) => n + (p.subcells?.length ?? 0), 0) + " subcells)"}</span>
              {"\n"}
              <span className="k">radius 4000 m</span>
              {"  -> " + planLarge.length + " partitions, "}
              <span className="v">{planLarge[0]?.subcells ? "subcell filter" : "whole 3 x 3 block"}</span>
              {"\n"}
              <span className="k">filter</span>
              {"         ttl > now"}
            </pre>

            <div className="ttl-card" aria-live="polite">
              <div className="controls" style={{ justifyContent: "space-between" }}>
                <span className="panel-title">ttl expiry, {driverId}</span>
                {silenced ? (
                  <button type="button" className="btn" onClick={resume}>
                    Resume pings
                  </button>
                ) : (
                  <button type="button" className="btn btn-primary" onClick={silence}>
                    Silence {driverId}
                  </button>
                )}
              </div>
              <div className={`ttl-bar${silenced ? "" : " is-live"}`} aria-hidden="true">
                <span style={{ width: `${Math.max(0, Math.min(100, (remaining / world.ttlSeconds) * 100))}%` }} />
              </div>
              <dl className="kv">
                <dt>last ping</dt>
                <dd>{item ? `t+${item.updatedAt.toFixed(1)} s` : "none"}</dd>
                <dt>ttl</dt>
                <dd>
                  {item ? `t+${item.ttl.toFixed(1)} s` : "none"}
                  {silenced && (
                    <span className={remaining > 0 ? "tag is-coral" : "tag"} style={{ marginLeft: 8 }}>
                      {remaining > 0 ? `${remaining.toFixed(1)} s left` : "expired"}
                    </span>
                  )}
                </dd>
                <dt>visible to reads</dt>
                <dd className={visible ? "is-lime" : "is-coral"}>{visible ? "yes" : "no, ttl passed"}</dd>
              </dl>
              {silenced && sinceSilence !== null && (
                <div className="ttl-timeline">
                  <span className="tag is-coral">silenced at t+{silencedAt?.toFixed(1)} s</span>
                  {sinceSilence >= REAL.visibleAfterS && (
                    <span className="tag is-lime">after {REAL.visibleAfterS} s: visible</span>
                  )}
                  {!visible && <span className="tag is-coral">after ttl ({world.ttlSeconds} s): gone</span>}
                </div>
              )}
              {!silenced && (
                <p style={{ color: "var(--ink-3)", fontSize: 13 }}>
                  The demo silences one driver and reads it back: visible after {REAL.visibleAfterS} s, gone after the
                  {" "}{REAL.ttlSeconds} s ttl. No cleanup job, the read filters <code>ttl &gt; now</code>.
                </p>
              )}
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
