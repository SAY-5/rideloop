"""arrived and in_trip statuses, progress timestamps, pickup eta

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

OLD_LABELS = ("requested", "matched", "en_route", "completed", "cancelled")


def upgrade() -> None:
    # PostgreSQL 12+ accepts ADD VALUE inside a transaction as long as the new
    # label is not used in the same transaction, which this migration does not.
    op.execute("ALTER TYPE trip_status ADD VALUE IF NOT EXISTS 'arrived' AFTER 'en_route'")
    op.execute("ALTER TYPE trip_status ADD VALUE IF NOT EXISTS 'in_trip' AFTER 'arrived'")
    op.add_column("trips", sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("trips", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("trips", sa.Column("pickup_eta_s", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("trips", "pickup_eta_s")
    op.drop_column("trips", "started_at")
    op.drop_column("trips", "arrived_at")
    # Enum labels cannot be dropped in place: fold the new states back into
    # en_route, rebuild the type without them and swap it in.
    op.execute("UPDATE trips SET status = 'en_route' WHERE status IN ('arrived', 'in_trip')")
    old = postgresql.ENUM(*OLD_LABELS, name="trip_status_old")
    old.create(op.get_bind(), checkfirst=True)
    op.execute("ALTER TABLE trips ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE trips ALTER COLUMN status TYPE trip_status_old "
        "USING status::text::trip_status_old"
    )
    op.execute("ALTER TABLE trips ALTER COLUMN status SET DEFAULT 'requested'")
    op.execute("DROP TYPE trip_status")
    op.execute("ALTER TYPE trip_status_old RENAME TO trip_status")
