"""Create persistent per-guild radio stations.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "radio_stations",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("name_key", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.PrimaryKeyConstraint("guild_id", "name_key"),
    )


def downgrade() -> None:
    op.drop_table("radio_stations")
