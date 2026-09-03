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
            This page is a browser port of the real services: three Python microservices, a DynamoDB
            driver index partitioned by geohash with TTL expiry, and a PostgreSQL trip schema. The
            geohash, index, matcher and simulators here are line-for-line ports checked against the
            repository's test vectors; the latency figures in this tab are modeled from where the real
            latency comes from (sweep wait, partition reads, conditional claim, commit), and the headline
            numbers are from the measured run. Traffic is synthetic.
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
