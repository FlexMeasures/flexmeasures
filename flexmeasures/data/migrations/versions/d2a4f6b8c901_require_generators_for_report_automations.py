"""Require generators for forecast and report automations.

Revision ID: d2a4f6b8c901
Revises: c63896a97a8e
Create Date: 2026-08-12 02:20:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "d2a4f6b8c901"
down_revision = "c63896a97a8e"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("forecast_generator", "automation", type_="check")
    op.create_check_constraint(
        "automation_generator",
        "automation",
        "type NOT IN ('forecasts', 'reports') OR generator_id IS NOT NULL",
    )


def downgrade():
    op.drop_constraint("automation_generator", "automation", type_="check")
    op.create_check_constraint(
        "forecast_generator",
        "automation",
        "type != 'forecasts' OR generator_id IS NOT NULL",
    )
