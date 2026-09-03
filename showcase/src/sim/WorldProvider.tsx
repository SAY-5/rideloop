import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { World } from "./world";

type FrameListener = (world: World) => void;

interface WorldContextValue {
  world: World;
  /** bumps at about 15 Hz so panels re-read the simulation */
  frame: number;
  speed: number;
  setSpeed: (speed: number) => void;
  paused: boolean;
  setPaused: (paused: boolean) => void;
  /** subscribe to every animation frame, for canvas drawing */
  onFrame: (listener: FrameListener) => () => void;
}

const WorldContext = createContext<WorldContextValue | null>(null);

const MAX_SUBSTEP_S = 0.05;
const MAX_FRAME_S = 0.12;

export function WorldProvider({ children }: { children: ReactNode }) {
  const world = useMemo(() => {
    const w = new World({ seed: 42, driverCount: 300, ttlSeconds: 20 });
    w.tick(1);
    return w;
  }, []);
  const [frame, setFrame] = useState(0);
  const [speed, setSpeed] = useState(1);
  const [paused, setPaused] = useState(false);
  const speedRef = useRef(speed);
  const pausedRef = useRef(paused);
  const listeners = useRef(new Set<FrameListener>());
  speedRef.current = speed;
  pausedRef.current = paused;

  const onFrame = useCallback((listener: FrameListener) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);

  useEffect(() => {
    let raf = 0;
    let last: number | null = null;
    let counter = 0;
    const loop = (t: number) => {
      raf = requestAnimationFrame(loop);
      if (last === null) last = t;
      const realDt = Math.min(MAX_FRAME_S, (t - last) / 1000);
      last = t;
      if (!pausedRef.current) {
        let remaining = realDt * speedRef.current;
        while (remaining > 0) {
          const step = Math.min(MAX_SUBSTEP_S, remaining);
          world.tick(step);
          remaining -= step;
        }
      }
      for (const listener of listeners.current) listener(world);
      counter += 1;
      if (counter % 4 === 0) setFrame((f) => f + 1);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [world]);

  const value = useMemo(
    () => ({ world, frame, speed, setSpeed, paused, setPaused, onFrame }),
    [world, frame, speed, paused, onFrame],
  );
  return <WorldContext.Provider value={value}>{children}</WorldContext.Provider>;
}

export function useWorld(): WorldContextValue {
  const ctx = useContext(WorldContext);
  if (!ctx) throw new Error("useWorld must be used inside WorldProvider");
  return ctx;
}
