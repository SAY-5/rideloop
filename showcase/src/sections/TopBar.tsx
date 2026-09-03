import { useWorld } from "../sim/WorldProvider";

export function TopBar() {
  const { world, speed } = useWorld();
  return (
    <div className="topbar">
      <div className="wrap topbar-inner">
        <a className="brand" href="#top" aria-label="RideLoop dispatch, back to top">
          <span className="brand-mark" aria-hidden="true" />
          RideLoop
        </a>
        <nav className="topbar-nav" aria-label="Sections">
          <a href="#cells">Cells</a>
          <a href="#matching">Matching</a>
          <a href="#load">Load run</a>
          <a href="https://github.com/SAY-5/rideloop" rel="noreferrer">
            Source
          </a>
        </nav>
        <span className="topbar-clock" aria-live="off">
          <span className="dot" aria-hidden="true" />
          sim {world.now.toFixed(0)}s
          {speed !== 1 && <span>x{speed}</span>}
        </span>
      </div>
    </div>
  );
}
