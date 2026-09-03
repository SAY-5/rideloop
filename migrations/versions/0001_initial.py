"""initial trips, drivers and ride_events

Revision ID: 0001
Revises:
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TRIP_STATUS = postgresql.ENUM(
    "requested", "matched", "en_route", "completed", "cancelled", name="trip_status"
)


def upgrade() -> None:
    TRIP_STATUS.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "drivers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="available"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "trips",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rider_id", sa.String(64), nullable=False),
        sa.Column("pickup_lat", sa.Float, nullable=False),
        sa.Column("pickup_lng", sa.Float, nullable=False),
        sa.Column("dropoff_lat", sa.Float, nullable=False),
        sa.Column("dropoff_lng", sa.Float, nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="trip_status", create_type=False),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("driver_id", sa.String(64), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_latency_ms", sa.Integer, nullable=True),
        sa.Column("dispatch_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_trips_status", "trips", ["status"])
    op.create_index("ix_trips_requested_at", "trips", ["requested_at"])
    op.create_index("ix_trips_status_next_attempt", "trips", ["status", "next_attempt_at"])

    op.create_table(
        "ride_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "trip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_ride_events_trip_id", "ride_events", ["trip_id"])


def downgrade() -> None:
    op.drop_index("ix_ride_events_trip_id", table_name="ride_events")
    op.drop_table("ride_events")
    op.drop_index("ix_trips_status_next_attempt", table_name="trips")
    op.drop_index("ix_trips_requested_at", table_name="trips")
    op.drop_index("ix_trips_status", table_name="trips")
    op.drop_table("trips")
    op.drop_table("drivers")
    TRIP_STATUS.drop(op.get_bind(), checkfirst=True)
