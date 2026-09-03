# Contributing

## Setup

```
make setup            # uv sync + pnpm install
make test-db          # throwaway PostgreSQL on localhost:5434
make test             # pytest (moto for DynamoDB, real PostgreSQL)
make lint             # ruff check, ruff format --check, eslint
```

Python 3.12, `uv` for dependencies, `pnpm` for `web/`.

## Ground rules

- Keep the three services independent: shared code goes in `rideloop_common`.
- Schema changes go through Alembic (`migrations/versions`), never `create_all`.
- Every change to the store or matcher needs a test against moto and PostgreSQL;
  SQLite is not a stand-in for the schema tests.
- Conventional commit subjects (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
- CI must be green (`.github/workflows/ci.yml`) before merging.
