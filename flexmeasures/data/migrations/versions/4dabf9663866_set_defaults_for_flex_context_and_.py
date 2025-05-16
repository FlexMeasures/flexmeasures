"""Set defaults for flex_context and sensors_to_show

Revision ID: 4dabf9663866
Revises: cb8df44ebda5
Create Date: 2025-05-16 15:53:22.814840

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4dabf9663866"
down_revision = "cb8df44ebda5"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "generic_asset",
        "flex_context",
        existing_type=sa.JSON(),
        nullable=False,
        server_default=sa.text("'{}'::json"),
    )
    op.alter_column(
        "generic_asset",
        "sensors_to_show",
        existing_type=sa.JSON(),
        nullable=False,
        server_default=sa.text("'[]'::json"),
    ),


def downgrade():
    op.alter_column(
        "generic_asset", "flex_context", existing_type=sa.JSON(), nullable=False
    ),
    op.alter_column(
        "generic_asset", "sensors_to_show", existing_type=sa.JSON(), nullable=False
    )
