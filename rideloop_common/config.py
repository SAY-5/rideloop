"""Environment-driven configuration shared by every service."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # DynamoDB
    dynamodb_endpoint: str | None = "http://localhost:8000"
    aws_region: str = "us-east-1"
    aws_access_key_id: str = "local"
    aws_secret_access_key: str = "local"
    driver_positions_table: str = "driver_positions"
    position_ttl_seconds: int = 60
    cell_precision: int = 5
    dynamodb_auto_create: bool = True

    # PostgreSQL
    database_url: str = "postgresql+psycopg://rideloop:rideloop@localhost:5432/rideloop"

    # Service addresses (used by the simulators and the web dev proxy)
    driver_location_url: str = "http://localhost:8001"
    ride_request_url: str = "http://localhost:8002"
    dispatch_url: str = "http://localhost:8003"

    # Dispatch matcher
    dispatch_poll_interval_s: float = 0.1
    dispatch_batch_size: int = 50
    dispatch_initial_radius_m: float = 500.0
    dispatch_max_radius_m: float = 4000.0
    dispatch_retry_delay_s: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
