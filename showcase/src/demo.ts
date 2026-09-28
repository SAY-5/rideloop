/** Inputs to the browser model, not measurements of the Python services. */
export const SIMULATION_CONFIG = {
  drivers: 300,
  ratePerSecond: 10,
  durationS: 60,
  ttlSeconds: 20,
  visibleAfterS: 3,
  silencedDriver: "drv-000",
} as const;

/** These revisions identify documentation, not the revisions executed by a run. */
export const HISTORICAL_DEMOS = [
  {
    status: "historical-unverified",
    label: "Early demo transcript",
    sourceRevision: "1945cbd8fee7cc428ac63a65931e120592c37ac3",
  },
  {
    status: "historical-unverified",
    label: "v5 demo transcript",
    sourceRevision: "905549cfaa0daa1b58f920e84c61b1cfa725cbb8",
  },
] as const;
