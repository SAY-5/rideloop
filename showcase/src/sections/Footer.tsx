export function Footer() {
  return (
    <footer className="footer">
      <div className="wrap footer-inner">
        <div>
          <span className="brand">
            <span className="brand-mark" aria-hidden="true" />
            RideLoop
          </span>
          <p className="footer-note">
            This page illustrates the dispatch path of three Python microservices, a DynamoDB
            driver index partitioned by geohash with TTL expiry, and a PostgreSQL trip schema. The
            geohash, index and matcher share test vectors with the repository. The simulation uses
            synthetic traffic, a virtual clock and modeled latency (sweep wait, partition reads,
            conditional claim, commit). It does not execute the backend's offer, decline or full trip
            lifecycle and does not measure service latency or capacity.
          </p>
        </div>
        <ul className="footer-links">
          <li>
            <a href="https://github.com/SAY-5/rideloop" rel="noreferrer">
              github.com/SAY-5/rideloop
            </a>
          </li>
          <li>
            <a href="https://github.com/SAY-5/rideloop/blob/main/ARCHITECTURE.md" rel="noreferrer">
              ARCHITECTURE.md
            </a>
          </li>
          <li>
            <a href="https://github.com/SAY-5/rideloop/tree/main/showcase" rel="noreferrer">
              showcase source
            </a>
          </li>
        </ul>
      </div>
    </footer>
  );
}
