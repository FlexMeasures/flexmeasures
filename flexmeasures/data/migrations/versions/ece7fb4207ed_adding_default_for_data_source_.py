"""Adding default for data_source attributes

Revision ID: ece7fb4207ed
Revises: 4dabf9663866
Create Date: 2025-05-16 16:55:33.722545

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ece7fb4207ed"
down_revision = "4dabf9663866"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "data_source",
        "attributes",
        existing_type=sa.JSON(),
        nullable=False,
        server_default=sa.text("'{}'::json"),
    )


def downgrade():
    op.alter_column(
        "data_source", "attributes", existing_type=sa.JSON(), nullable=False
    )
