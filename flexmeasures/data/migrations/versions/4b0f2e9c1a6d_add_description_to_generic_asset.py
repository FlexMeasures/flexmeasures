"""add description to generic asset

Revision ID: 4b0f2e9c1a6d
Revises: 55d8936a55f9
Create Date: 2026-07-02 17:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4b0f2e9c1a6d"
down_revision = "55d8936a55f9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.drop_column("description")
