"""Allow schedule automations without a generator.

Revision ID: 5a9c0e3b7d21
Revises: 4d5e6f708192
Create Date: 2026-08-05 12:15:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "5a9c0e3b7d21"
down_revision = "4d5e6f708192"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("automation", "generator_id", nullable=True)
    op.create_check_constraint(
        "forecast_generator",
        "automation",
        "type != 'forecasts' OR generator_id IS NOT NULL",
    )


def downgrade():
    op.drop_constraint("forecast_generator", "automation", type_="check")
    op.alter_column("automation", "generator_id", nullable=False)
