from alembic import command
from sqlalchemy import inspect, text

from tests.conftest import alembic_config


def test_upgrade_creates_schema(migrated_engine):
    insp = inspect(migrated_engine)
    assert {"trips", "drivers", "ride_events", "alembic_version"} <= set(insp.get_table_names())

    trip_cols = {c["name"] for c in insp.get_columns("trips")}
    assert trip_cols >= {
        "id",
        "rider_id",
        "pickup_lat",
        "pickup_lng",
        "dropoff_lat",
        "dropoff_lng",
        "status",
        "driver_id",
        "requested_at",
        "matched_at",
        "completed_at",
        "match_latency_ms",
    }
    indexes = {i["name"] for i in insp.get_indexes("trips")}
    assert {"ix_trips_status", "ix_trips_requested_at"} <= indexes
    fks = insp.get_foreign_keys("ride_events")
    assert fks[0]["referred_table"] == "trips"
    assert fks[0]["options"].get("ondelete") == "CASCADE"

    with migrated_engine.connect() as conn:
        labels = (
            conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'trip_status' ORDER BY enumsortorder"
                )
            )
            .scalars()
            .all()
        )
    assert labels == ["requested", "matched", "en_route", "completed", "cancelled"]


def test_downgrade_and_upgrade_are_clean(migrated_engine):
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    insp = inspect(migrated_engine)
    assert "trips" not in insp.get_table_names()
    with migrated_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM pg_type WHERE typname = 'trip_status'")
            ).scalar()
            == 0
        )
    command.upgrade(cfg, "head")
    assert "trips" in inspect(migrated_engine).get_table_names()
