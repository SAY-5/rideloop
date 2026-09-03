.PHONY: setup lint test test-db migrate tables demo demo-down web web-build

UV ?= uv
TEST_PG_PORT ?= 5434
TEST_DATABASE_URL ?= postgresql+psycopg://rideloop:rideloop@localhost:$(TEST_PG_PORT)/rideloop

setup:
	$(UV) sync
	cd web && pnpm install

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	cd web && pnpm lint

## Start a throwaway PostgreSQL for the integration tests (skip if you have one).
test-db:
	docker rm -f rideloop-test-pg >/dev/null 2>&1 || true
	docker run -d --name rideloop-test-pg -e POSTGRES_USER=rideloop -e POSTGRES_PASSWORD=rideloop \
		-e POSTGRES_DB=rideloop -p $(TEST_PG_PORT):5432 postgres:16
	@until docker exec rideloop-test-pg pg_isready -U rideloop >/dev/null 2>&1; do sleep 1; done

test:
	DATABASE_URL=$(TEST_DATABASE_URL) $(UV) run pytest -q

migrate:
	$(UV) run alembic upgrade head

tables:
	$(UV) run python scripts/create_tables.py

## Full stack demo: compose up, seed 300 drivers, 10 rides/s for 60s, print the summary.
demo:
	docker compose up -d --build --wait
	$(UV) run python -m sim.demo --drivers 300 --rate 10 --duration 60
	docker compose down

demo-down:
	docker compose down -v

web:
	cd web && pnpm dev

web-build:
	cd web && pnpm build
