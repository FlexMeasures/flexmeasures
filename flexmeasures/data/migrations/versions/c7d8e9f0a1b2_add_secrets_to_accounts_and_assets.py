"""Add encrypted secrets JSON fields to accounts and assets

Revision ID: c7d8e9f0a1b2
Revises: b2c3d4e5f6a7
Create Date: 2026-06-11

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "c7d8e9f0a1b2"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("secrets", JSONB(), nullable=False, server_default="{}")
        )

    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("secrets", JSONB(), nullable=False, server_default="{}")
        )


def downgrade():
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.drop_column("secrets")

    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.drop_column("secrets")
