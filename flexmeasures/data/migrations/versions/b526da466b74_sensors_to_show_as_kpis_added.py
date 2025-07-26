"""Add sensors_to_show_as_kpis column to generic_asset

Revision ID: b526da466b74
Revises: 0f64e22d6b9e
Create Date: 2025-07-14 22:34:53.522875

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b526da466b74"
down_revision = "0f64e22d6b9e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "generic_asset",
        sa.Column(
            "sensors_to_show_as_kpis",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade():
    op.drop_column("generic_asset", "sensors_to_show_as_kpis")
