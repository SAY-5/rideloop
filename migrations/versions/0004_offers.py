"""driver offers: acceptance, declines and rematch bookkeeping

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("offered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("trips", sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "trips",
        sa.Column(
            "declined_by",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_index("ix_trips_status_offered_at", "trips", ["status", "offered_at"])
    # trips matched before this release were never offered; treat them as accepted
    op.execute(
        "UPDATE trips SET offered_at = matched_at, accepted_at = matched_at "
        "WHERE matched_at IS NOT NULL"
    )
    for column in ("offers", "accepts", "declines"):
        op.add_column("drivers", sa.Column(column, sa.Integer, nullable=False, server_default="0"))


def downgrade() -> None:
    for column in ("declines", "accepts", "offers"):
        op.drop_column("drivers", column)
    op.drop_index("ix_trips_status_offered_at", table_name="trips")
    op.drop_column("trips", "declined_by")
    op.drop_column("trips", "accepted_at")
    op.drop_column("trips", "offered_at")
