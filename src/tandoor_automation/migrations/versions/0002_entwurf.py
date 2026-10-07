"""Entwürfe des Wochenplans, bis sie in Tandoor stehen.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07 11:00:19.577476
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Schema nach vorn."""
    op.create_table(
        "draft",
        sa.Column("week", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("proposal", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("bundle", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("reasoning", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("hints", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("problems", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("released_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.Column("changed_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("week"),
    )


def downgrade() -> None:
    """Schema zurück."""
    op.drop_table("draft")
