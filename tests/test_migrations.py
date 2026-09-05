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
        "arrived_at",
        "started_at",
        "pickup_eta_s",
        "pickup_cell",
        "surge_multiplier",
        "offered_at",
        "accepted_at",
        "declined_by",
    }
    driver_cols = {c["name"] for c in insp.get_columns("drivers")}
    assert {"offers", "accepts", "declines"} <= driver_cols
    indexes = {i["name"] for i in insp.get_indexes("trips")}
    assert {
        "ix_trips_status",
        "ix_trips_requested_at",
        "ix_trips_pickup_cell_requested_at",
    } <= indexes
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
    assert labels == [
        "requested",
        "matched",
        "en_route",
        "arrived",
        "in_trip",
        "completed",
        "cancelled",
    ]


def enum_labels(engine) -> list[str]:
    with engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'trip_status' ORDER BY enumsortorder"
                )
            )
            .scalars()
            .all()
        )


def test_downgrade_to_0001_rebuilds_the_enum_without_progress_states(migrated_engine):
    cfg = alembic_config()
    with migrated_engine.begin() as conn:
        conn.execute(text("DELETE FROM trips"))
        conn.execute(
            text(
                "INSERT INTO trips (id, rider_id, pickup_lat, pickup_lng, dropoff_lat, "
                "dropoff_lng, status) VALUES (gen_random_uuid(), 'r', 0, 0, 0, 0, 'in_trip')"
            )
        )
    command.downgrade(cfg, "0003")
    cols = {c["name"] for c in inspect(migrated_engine).get_columns("trips")}
    assert "declined_by" not in cols and "offered_at" not in cols
    assert "offers" not in {c["name"] for c in inspect(migrated_engine).get_columns("drivers")}
    command.downgrade(cfg, "0002")
    cols = {c["name"] for c in inspect(migrated_engine).get_columns("trips")}
    assert "surge_multiplier" not in cols and "pickup_cell" not in cols
    command.downgrade(cfg, "0001")
    assert enum_labels(migrated_engine) == [
        "requested",
        "matched",
        "en_route",
        "completed",
        "cancelled",
    ]
    cols = {c["name"] for c in inspect(migrated_engine).get_columns("trips")}
    assert "arrived_at" not in cols and "pickup_eta_s" not in cols
    with migrated_engine.connect() as conn:
        assert conn.execute(text("SELECT status::text FROM trips")).scalar() == "en_route"
    command.upgrade(cfg, "head")
    assert "in_trip" in enum_labels(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.execute(text("DELETE FROM trips"))


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
