import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from moto import mock_aws
from sqlalchemy import text

from rideloop_common.config import Settings, get_settings
from rideloop_common.db import make_engine, make_session_factory
from rideloop_common.dynamo import DriverPositionStore, ensure_table

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://rideloop:rideloop@localhost:5432/rideloop"
)
os.environ["DATABASE_URL"] = DATABASE_URL
get_settings.cache_clear()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def alembic_config() -> Config:
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "migrations"))
    return cfg


@pytest.fixture(scope="session")
def migrated_engine():
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = make_engine(Settings(database_url=DATABASE_URL))
    yield engine
    engine.dispose()


@pytest.fixture
def engine(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE ride_events, trips, drivers RESTART IDENTITY CASCADE"))
    return migrated_engine


@pytest.fixture
def session_factory(engine):
    return make_session_factory(engine)


@pytest.fixture
def session(session_factory) -> Iterator:
    with session_factory() as s:
        yield s


@pytest.fixture
def dynamo_settings() -> Iterator[Settings]:
    with mock_aws():
        settings = Settings(
            dynamodb_endpoint=None,
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
            database_url=DATABASE_URL,
        )
        ensure_table(settings)
        yield settings


@pytest.fixture
def store(dynamo_settings) -> DriverPositionStore:
    return DriverPositionStore(dynamo_settings)
