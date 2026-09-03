import { animate, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

interface CountUpProps {
  to: number;
  decimals?: number;
  duration?: number;
  delay?: number;
  /** re-run the animation whenever this changes */
  trigger?: unknown;
}

/** Animates a number from zero on mount; renders the final value directly under reduced motion. */
export function CountUp({ to, decimals = 0, duration = 1.6, delay = 0, trigger }: CountUpProps) {
  const reduceMotion = useReducedMotion();
  const [value, setValue] = useState(reduceMotion ? to : 0);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (reduceMotion) {
      setValue(to);
      return;
    }
    const controls = animate(0, to, {
      duration,
      delay,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setValue(v),
    });
    return () => controls.stop();
  }, [to, duration, delay, reduceMotion, trigger]);

  return (
    <span ref={ref} className="mono">
      {value.toFixed(decimals)}
    </span>
  );
}
