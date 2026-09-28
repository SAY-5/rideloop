import os
import time
import uuid
from collections.abc import Iterator
from ipaddress import ip_address
from urllib.parse import urlsplit

import boto3
import pytest
from alembic import command
from alembic.config import Config
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from moto import mock_aws
from sqlalchemy import text

from rideloop_common.config import Settings, get_settings
from rideloop_common.db import make_engine, make_session_factory
from rideloop_common.dynamo import DriverPositionStore, _create_table, ensure_table

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


def local_dynamo_settings(endpoint: str | None) -> Settings:
    message = (
        "Set TEST_DYNAMODB_ENDPOINT to a literal loopback HTTP address with an explicit port, "
        "for example http://127.0.0.1:8000 (DynamoDB Local 2.5.2 is required; no Moto fallback)"
    )
    try:
        url = urlsplit(endpoint or "")
        valid = (
            url.scheme == "http"
            and ip_address(url.hostname or "").is_loopback
            and url.port is not None
            and 1 <= url.port <= 65535
            and url.username is None
            and url.password is None
            and url.path in ("", "/")
            and not url.query
            and not url.fragment
        )
    except ValueError as error:
        raise ValueError(message) from error
    if not valid:
        raise ValueError(message)
    return Settings(
        dynamodb_endpoint=endpoint,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        aws_region="us-east-1",
        driver_positions_table=f"rideloop-test-{uuid.uuid4().hex}",
        database_url=DATABASE_URL,
    )


@pytest.fixture
def local_store() -> Iterator[DriverPositionStore]:
    """Real DynamoDB Local, isolated to one UUID table; absent service is a failure."""
    try:
        settings = local_dynamo_settings(os.environ.get("TEST_DYNAMODB_ENDPOINT"))
    except ValueError as error:
        pytest.fail(str(error), pytrace=False)
    session = boto3.session.Session()
    client_options = {
        "endpoint_url": settings.dynamodb_endpoint,
        "region_name": settings.aws_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
        "config": BotoConfig(
            connect_timeout=1,
            read_timeout=1,
            retries={"max_attempts": 0},
            max_pool_connections=32,
            proxies={},
        ),
    }
    resource = session.resource("dynamodb", **client_options)
    client = resource.meta.client
    created = False
    instance = None
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                client.list_tables(Limit=1)
                break
            except (BotoCoreError, ClientError) as error:
                if time.monotonic() >= deadline:
                    pytest.fail(
                        f"DynamoDB Local unavailable at TEST_DYNAMODB_ENDPOINT="
                        f"{settings.dynamodb_endpoint}: {error}",
                        pytrace=False,
                    )
                time.sleep(0.1)
        _create_table(client, settings.driver_positions_table)
        created = True
        client.get_waiter("table_exists").wait(
            TableName=settings.driver_positions_table,
            WaiterConfig={"Delay": 1, "MaxAttempts": 10},
        )
        instance = DriverPositionStore(settings, resource=resource)
        # Transactions need a separate low-level client, with the same test-only bounds.
        instance.raw_client.close()
        instance.raw_client = session.client("dynamodb", **client_options)
        yield instance
    finally:
        if instance is not None:
            instance._pool.shutdown(wait=True, cancel_futures=True)
            instance.raw_client.close()
        try:
            if created:
                client.delete_table(TableName=settings.driver_positions_table)
        finally:
            client.close()
