import { motion, useReducedMotion } from "framer-motion";
import { useEffect, useMemo, useRef, type KeyboardEvent, type MouseEvent } from "react";
import { CITY_HALF_M, BLOCK_M } from "../sim/city";
import { useWorld } from "../sim/WorldProvider";
import type { World } from "../sim/world";
import { cellRect, latLngToPx, localToPx, metersToPx, pxToLatLng, visibleCells } from "./projection";

export type Tone = "lime" | "coral" | "ice";

export interface MapPin {
  id: string;
  lat: number;
  lng: number;
  tone: Tone;
  label?: string;
}

export interface MapRing {
  id: string;
  lat: number;
  lng: number;
  radiusM: number;
  tone: Tone;
  /** faded ring for a radius that has already been searched */
  spent?: boolean;
}

export interface MapHighlight {
  driverId: string;
  tone: Tone;
  /** ring only, no fill */
  hollow?: boolean;
}

export interface CellLayer {
  precision: 5 | 6;
  selected?: string | null;
  /** cells read by a query: drawn filled */
  block?: string[];
  onSelect?: (key: string) => void;
}

interface CityMapProps {
  cells?: CellLayer | null;
  pins?: MapPin[];
  rings?: MapRing[];
  highlights?: MapHighlight[];
  onClick?: (lat: number, lng: number) => void;
  showLinks?: boolean;
  label: string;
  className?: string;
  dim?: boolean;
}

/** SVG coordinates are computed at this size; CSS scales the whole map. */
const V = 1000;

const TONE: Record<Tone, string> = {
  lime: "#c8f135",
  coral: "#ff6b7a",
  ice: "#7fd7ff",
};

export function CityMap({
  cells,
  pins = [],
  rings = [],
  highlights = [],
  onClick,
  showLinks = true,
  label,
  className,
  dim = false,
}: CityMapProps) {
  const { onFrame } = useWorld();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const highlightRef = useRef(highlights);
  highlightRef.current = highlights;
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let width = 0;
    let dpr = 1;
    const resize = () => {
      dpr = Math.min(2, window.devicePixelRatio || 1);
      width = canvas.clientWidth;
      canvas.width = Math.max(1, Math.round(width * dpr));
      canvas.height = canvas.width;
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    const unsubscribe = onFrame((w) => {
      if (width === 0) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      drawDrivers(ctx, w, width, highlightRef.current, showLinks);
    });
    return () => {
      unsubscribe();
      ro.disconnect();
    };
  }, [onFrame, showLinks]);

  const roads = useMemo(() => buildRoads(), []);
  const cellRects = useMemo(
    () => (cells ? visibleCells(cells.precision).map((key) => cellRect(key, V)) : []),
    [cells?.precision, cells],
  );
  const blockSet = useMemo(() => new Set(cells?.block ?? []), [cells?.block]);

  const handleClick = (event: MouseEvent<SVGSVGElement>) => {
    if (!onClick) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * V;
    const y = ((event.clientY - rect.top) / rect.height) * V;
    const [lat, lng] = pxToLatLng(x, y, V);
    onClick(lat, lng);
  };

  const [cityX0, cityY0] = localToPx(CITY_HALF_M, -CITY_HALF_M, V);
  const [cityX1, cityY1] = localToPx(-CITY_HALF_M, CITY_HALF_M, V);

  return (
    <div className={`citymap${dim ? " is-dim" : ""}${className ? ` ${className}` : ""}`}>
      <svg className="citymap-roads" viewBox={`0 0 ${V} ${V}`} aria-hidden="true">
        <defs>
          <radialGradient id="citymap-vignette" cx="50%" cy="45%" r="70%">
            <stop offset="0%" stopColor="#101a36" />
            <stop offset="70%" stopColor="#0a1124" />
            <stop offset="100%" stopColor="#060a18" />
          </radialGradient>
        </defs>
        <rect width={V} height={V} fill="url(#citymap-vignette)" />
        <rect
          x={cityX0}
          y={cityY0}
          width={cityX1 - cityX0}
          height={cityY1 - cityY0}
          fill="rgba(255,255,255,0.015)"
          stroke="rgba(159,174,214,0.32)"
          strokeWidth={1.2}
        />
        {roads.map((r) => (
          <line
            key={r.key}
            x1={r.x1}
            y1={r.y1}
            x2={r.x2}
            y2={r.y2}
            stroke={r.major ? "var(--road-major)" : "var(--road)"}
            strokeWidth={r.major ? 1.4 : 0.7}
          />
        ))}
      </svg>
      <canvas ref={canvasRef} className="citymap-canvas" aria-hidden="true" />
      <svg
        className={`citymap-overlay${onClick ? " is-clickable" : ""}`}
        viewBox={`0 0 ${V} ${V}`}
        role={cells?.onSelect ? "group" : "img"}
        aria-label={label}
        onClick={handleClick}
      >
        {cells &&
          cellRects.map((c) => {
            const selected = cells.selected === c.key;
            const inBlock = blockSet.has(c.key);
            const interactive = !!cells.onSelect;
            const onKey = (event: KeyboardEvent<SVGRectElement>) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                cells.onSelect?.(c.key);
              }
            };
            return (
              <g key={c.key} className="citymap-cell">
                <rect
                  x={c.x}
                  y={c.y}
                  width={c.w}
                  height={c.h}
                  className={`citymap-cell-rect${selected ? " is-selected" : ""}${inBlock ? " is-block" : ""}${cells.precision === 5 ? " is-partition" : ""}`}
                  role={interactive ? "button" : undefined}
                  tabIndex={interactive ? 0 : undefined}
                  aria-label={interactive ? `geohash cell ${c.key}` : undefined}
                  aria-pressed={interactive ? selected : undefined}
                  onClick={(event) => {
                    if (!interactive) return;
                    event.stopPropagation();
                    cells.onSelect?.(c.key);
                  }}
                  onKeyDown={interactive ? onKey : undefined}
                />
                {(cells.precision === 5 || selected || inBlock) && (
                  <text
                    x={c.x + 10}
                    y={c.y + (cells.precision === 5 ? 26 : 18)}
                    className={`citymap-cell-key${selected ? " is-selected" : ""}`}
                  >
                    {c.key}
                  </text>
                )}
              </g>
            );
          })}
        {rings.map((ring) => {
          const [cx, cy] = latLngToPx(ring.lat, ring.lng, V);
          const r = metersToPx(ring.radiusM, V);
          return (
            <motion.circle
              key={ring.id}
              cx={cx}
              cy={cy}
              initial={reduceMotion ? { r } : { r: Math.max(0, r * 0.5), opacity: 0 }}
              animate={{ r, opacity: ring.spent ? 0.35 : 1 }}
              transition={{ duration: reduceMotion ? 0 : 0.55, ease: [0.22, 1, 0.36, 1] }}
              fill={ring.spent ? "none" : `${TONE[ring.tone]}10`}
              stroke={TONE[ring.tone]}
              strokeWidth={ring.spent ? 1 : 1.6}
              strokeDasharray={ring.spent ? "4 6" : undefined}
              pointerEvents="none"
            />
          );
        })}
        {pins.map((pin) => {
          const [x, y] = latLngToPx(pin.lat, pin.lng, V);
          return (
            <g key={pin.id} className="citymap-pin" transform={`translate(${x} ${y})`} pointerEvents="none">
              <circle r={16} fill="none" stroke={TONE[pin.tone]} strokeWidth={1.2} className="citymap-pin-pulse" />
              <circle r={5.5} fill={TONE[pin.tone]} />
              <circle r={2} fill="#060a18" />
              {pin.label && (
                <text x={12} y={-10} className="citymap-pin-label" fill={TONE[pin.tone]}>
                  {pin.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

interface Road {
  key: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  major: boolean;
}

function buildRoads(): Road[] {
  const roads: Road[] = [];
  for (let m = -CITY_HALF_M; m <= CITY_HALF_M; m += BLOCK_M) {
    const major = m % 1000 === 0;
    const [x, yTop] = localToPx(CITY_HALF_M, m, V);
    const [, yBottom] = localToPx(-CITY_HALF_M, m, V);
    roads.push({ key: `v${m}`, x1: x, y1: yTop, x2: x, y2: yBottom, major });
    const [xLeft, y] = localToPx(m, -CITY_HALF_M, V);
    const [xRight] = localToPx(m, CITY_HALF_M, V);
    roads.push({ key: `h${m}`, x1: xLeft, y1: y, x2: xRight, y2: y, major });
  }
  return roads;
}

function drawDrivers(
  ctx: CanvasRenderingContext2D,
  world: World,
  size: number,
  highlights: MapHighlight[],
  showLinks: boolean,
) {
  ctx.clearRect(0, 0, size, size);
  const now = world.now;
  const scale = size / V;
  const dotR = Math.max(1.6, 2.4 * scale);

  if (showLinks) {
    ctx.lineWidth = Math.max(0.6, 0.8 * scale);
    ctx.strokeStyle = "rgba(200, 241, 53, 0.22)";
    ctx.beginPath();
    for (const driver of world.drivers) {
      const item = world.index.getDriver(driver.driverId);
      if (!item || item.status !== "busy" || !item.tripId) continue;
      const trip = world.trips.get(item.tripId);
      if (!trip || trip.status === "en_route") continue;
      const [x, y] = localToPx(driver.northM, driver.eastM, size);
      const [px, py] = latLngToPx(trip.pickupLat, trip.pickupLng, size);
      ctx.moveTo(x, y);
      ctx.lineTo(px, py);
    }
    ctx.stroke();
  }

  // available drivers: quiet, cool dots with a heading tick
  ctx.fillStyle = "rgba(186, 204, 255, 0.72)";
  ctx.strokeStyle = "rgba(186, 204, 255, 0.5)";
  ctx.lineWidth = Math.max(0.8, 1 * scale);
  for (const driver of world.drivers) {
    const item = world.index.getDriver(driver.driverId);
    const silenced = world.silenced.has(driver.driverId);
    if (silenced || !item || item.status !== "available") continue;
    const [x, y] = localToPx(driver.northM, driver.eastM, size);
    const rad = (driver.heading * Math.PI) / 180;
    ctx.beginPath();
    ctx.arc(x, y, dotR, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + Math.sin(rad) * dotR * 3, y - Math.cos(rad) * dotR * 3);
    ctx.stroke();
  }

  // busy drivers: lime with a soft halo
  for (const driver of world.drivers) {
    const item = world.index.getDriver(driver.driverId);
    if (world.silenced.has(driver.driverId) || !item || item.status !== "busy") continue;
    const [x, y] = localToPx(driver.northM, driver.eastM, size);
    ctx.fillStyle = "rgba(200, 241, 53, 0.18)";
    ctx.beginPath();
    ctx.arc(x, y, dotR * 3.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#c8f135";
    ctx.beginPath();
    ctx.arc(x, y, dotR * 1.25, 0, Math.PI * 2);
    ctx.fill();
  }

  // silenced drivers: drawn where the index last saw them, fading toward their ttl
  for (const driverId of world.silenced) {
    const item = world.index.getDriver(driverId);
    if (!item) continue;
    const [x, y] = latLngToPx(item.lat, item.lng, size);
    const remaining = item.ttl - now;
    const alive = remaining > 0;
    const alpha = alive ? 0.35 + 0.65 * Math.min(1, remaining / world.ttlSeconds) : 0.3;
    ctx.strokeStyle = `rgba(255, 107, 122, ${alpha})`;
    ctx.lineWidth = Math.max(1, 1.4 * scale);
    ctx.beginPath();
    ctx.arc(x, y, dotR * 3, 0, Math.PI * 2);
    ctx.stroke();
    if (alive) {
      ctx.fillStyle = `rgba(255, 107, 122, ${alpha})`;
      ctx.beginPath();
      ctx.arc(x, y, dotR * 1.3, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.beginPath();
      ctx.moveTo(x - dotR * 1.6, y - dotR * 1.6);
      ctx.lineTo(x + dotR * 1.6, y + dotR * 1.6);
      ctx.moveTo(x + dotR * 1.6, y - dotR * 1.6);
      ctx.lineTo(x - dotR * 1.6, y + dotR * 1.6);
      ctx.stroke();
    }
  }

  // highlighted drivers (candidates, winners, losers)
  for (const h of highlights) {
    const driver = world.drivers.find((d) => d.driverId === h.driverId);
    if (!driver) continue;
    const [x, y] = localToPx(driver.northM, driver.eastM, size);
    ctx.strokeStyle = TONE[h.tone];
    ctx.lineWidth = Math.max(1.2, 1.8 * scale);
    ctx.beginPath();
    ctx.arc(x, y, dotR * 3.6, 0, Math.PI * 2);
    ctx.stroke();
    if (!h.hollow) {
      ctx.fillStyle = TONE[h.tone];
      ctx.beginPath();
      ctx.arc(x, y, dotR * 1.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}
