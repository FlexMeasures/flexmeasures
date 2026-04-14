"""add attributes field to account model

Revision ID: a3b1c2d4e5f6
Revises: 3f4a6f9d2b11
Create Date: 2026-04-07

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "a3b1c2d4e5f6"
down_revision = "3f4a6f9d2b11"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "attributes",
                JSONB(),
                nullable=False,
                server_default="{}",
            )
        )


def downgrade():
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.drop_column("attributes")
