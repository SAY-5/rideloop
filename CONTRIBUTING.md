# Contributing

## Setup

```
make setup            # uv sync + pnpm install
make test             # full suite after configuring isolated test services below
make lint             # ruff check, ruff format --check, eslint
```

Python 3.12, `uv` for dependencies, `pnpm` for `web/`.

Follow the [isolated service setup](README.md#development) for PostgreSQL 16
and DynamoDB Local 2.5.2, then pass `TEST_DATABASE_URL` and
`TEST_DYNAMODB_ENDPOINT` to `make test`. The fast tests use moto; the
`integration`-marked acceptance tests exercise real DynamoDB conditional writes
and PostgreSQL locks. They are required for the full suite, not optional evidence
of concurrency safety. The PostgreSQL fixture recreates the schema and truncates
tables: use only a disposable database.

The legacy `make test-db` helper starts PostgreSQL only, publishes a fixed host
port and replaces the container named `rideloop-test-pg`. Prefer the uniquely
named, loopback-bound containers documented in the README.

## Ground rules

- Keep the three services independent: shared code goes in `rideloop_common`.
- Schema changes go through Alembic (`migrations/versions`), never `create_all`.
- Every change to the store or matcher needs focused moto/PostgreSQL coverage;
  conditional-write and concurrent-matcher changes also need the real
  DynamoDB Local acceptance tests. SQLite is not a stand-in for PostgreSQL.
- Conventional commit subjects (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
- CI must be green (`.github/workflows/ci.yml`) before merging.
