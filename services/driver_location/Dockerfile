FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 \
    PROMETHEUS_MULTIPROC_DIR=/tmp/rideloop-metrics
RUN mkdir -p /tmp/rideloop-metrics
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY rideloop_common ./rideloop_common
COPY services ./services
COPY sim ./sim
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "services.driver_location.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
