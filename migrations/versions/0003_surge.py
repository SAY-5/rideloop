"""pickup cell and surge multiplier on trips

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("pickup_cell", sa.String(12), nullable=True))
    op.add_column(
        "trips",
        sa.Column("surge_multiplier", sa.Float, nullable=False, server_default="1.0"),
    )
    op.create_index("ix_trips_pickup_cell_requested_at", "trips", ["pickup_cell", "requested_at"])


def downgrade() -> None:
    op.drop_index("ix_trips_pickup_cell_requested_at", table_name="trips")
    op.drop_column("trips", "surge_multiplier")
    op.drop_column("trips", "pickup_cell")
