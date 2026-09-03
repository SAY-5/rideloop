"""Bits every FastAPI service shares."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def add_common_routes(app: FastAPI, name: str) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"service": name, "status": "ok"}
