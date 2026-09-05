"""Bits every FastAPI service shares: CORS, /healthz, /metrics and request metrics."""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST

from rideloop_common import metrics


def add_common_routes(app: FastAPI, name: str) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def count_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        if path not in ("/metrics", "/healthz"):
            metrics.HTTP_REQUESTS.labels(name, request.method, path, response.status_code).inc()
            metrics.HTTP_LATENCY.labels(name, request.method, path).observe(
                time.perf_counter() - started
            )
        return response

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"service": name, "status": "ok"}

    @app.get("/metrics", tags=["ops"])
    def prometheus_metrics() -> Response:
        return Response(metrics.render(), media_type=CONTENT_TYPE_LATEST)
