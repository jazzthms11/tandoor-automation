"""Die Tabellen, die bis M2 als TSV-Dateien im Repo lagen, dazu der Stand der Bons.

Revision ID: 0001
Revises:
Create Date: 2026-10-06 15:15:08.314977
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Schema nach vorn."""
    op.create_table(
        "bookedreceipt",
        sa.Column("receipt_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("booked_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("receipt_id"),
    )
    op.create_table(
        "categoryclass",
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("section", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("changed_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("stock_class", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("location", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("category"),
    )
    op.create_table(
        "foodexception",
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("section", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("changed_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=False),
        sa.Column("stock_class", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("location", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("food_id"),
    )
    op.create_table(
        "foodinterval",
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("section", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("changed_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("food_id"),
    )
    op.create_table(
        "rating",
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("section", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("changed_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("recipe_id"),
    )
    op.create_table(
        "receiptmapping",
        sa.Column("store", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("receipt_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=True),
        sa.Column("discarded", sa.Boolean(), nullable=False),
        sa.Column("changed_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("store", "receipt_name"),
    )


def downgrade() -> None:
    """Schema zurück."""
    op.drop_table("receiptmapping")
    op.drop_table("rating")
    op.drop_table("foodinterval")
    op.drop_table("foodexception")
    op.drop_table("categoryclass")
    op.drop_table("bookedreceipt")
