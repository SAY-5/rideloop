import { useEffect } from "react";
import { Cells } from "./sections/Cells";
import { Footer } from "./sections/Footer";
import { Hero } from "./sections/Hero";
import { LoadRun } from "./sections/LoadRun";
import { Matching } from "./sections/Matching";
import { TopBar } from "./sections/TopBar";
import { formatReport, runSelfCheck } from "./sim/selfcheck";
import { WorldProvider } from "./sim/WorldProvider";
import "./styles/app.css";

function useStartupSelfCheck() {
  useEffect(() => {
    const run = () => {
      const report = runSelfCheck();
      const style = report.ok ? "color:#c8f135" : "color:#ff6b7a";
      console.info("%cRideLoop showcase self-check", style);
      console.info(formatReport(report));
    };
    const idle = (window as Window & { requestIdleCallback?: (cb: () => void) => number }).requestIdleCallback;
    if (idle) idle(run);
    else setTimeout(run, 800);
  }, []);
}

export default function App() {
  useStartupSelfCheck();
  return (
    <WorldProvider>
      <TopBar />
      <main>
        <Hero />
        <Cells />
        <Matching />
        <LoadRun />
      </main>
      <Footer />
    </WorldProvider>
  );
}
