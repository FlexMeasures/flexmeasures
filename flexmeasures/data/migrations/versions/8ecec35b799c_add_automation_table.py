"""add automation table

Revision ID: 8ecec35b799c
Revises: 55d8936a55f9
Create Date: 2026-07-11 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "8ecec35b799c"
down_revision = "55d8936a55f9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "automation",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("cronstr", sa.String(length=80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("generator_id", sa.Integer(), nullable=True),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["generic_asset.id"],
            name=op.f("automation_asset_id_generic_asset_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generator_id"],
            ["data_source.id"],
            name=op.f("automation_generator_id_data_source_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("automation_pkey")),
    )


def downgrade():
    op.drop_table("automation")
