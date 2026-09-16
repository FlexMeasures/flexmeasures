"""Retain the user authorizing unattended automation runs.

Revision ID: b63a02d5e184
Revises: c7a2f13b9e04
"""

from alembic import op
import sqlalchemy as sa

revision = "b63a02d5e184"
down_revision = "c7a2f13b9e04"
branch_labels = None
depends_on = None


def upgrade():
    # Legacy automations retain trusted execution. No FK: a deleted creator must
    # remain identifiable so a run fails closed rather than gaining CLI trust.
    with op.batch_alter_table("automation") as batch_op:
        batch_op.add_column(sa.Column("execution_user_id", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("automation") as batch_op:
        batch_op.drop_column("execution_user_id")
