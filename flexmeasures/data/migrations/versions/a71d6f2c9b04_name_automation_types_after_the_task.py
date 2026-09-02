"""Name automation types after the task, not its results.

The rest of the codebase calls these tasks "forecasting" and "scheduling" (queue names, job types),
so the automation types follow suit: 'forecasts' becomes 'forecasting' and 'schedules' becomes 'scheduling'.
The check constraint requiring a data generator for forecast automations is recreated with the new value.

Revision ID: a71d6f2c9b04
Revises: 3e91c47b0a58
Create Date: 2026-09-02 11:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a71d6f2c9b04"
down_revision = "3e91c47b0a58"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("forecast_generator", "automation", type_="check")
    op.execute("UPDATE automation SET type = 'forecasting' WHERE type = 'forecasts'")
    op.execute("UPDATE automation SET type = 'scheduling' WHERE type = 'schedules'")
    op.create_check_constraint(
        "forecast_generator",
        "automation",
        "type != 'forecasting' OR generator_id IS NOT NULL",
    )


def downgrade():
    op.drop_constraint("forecast_generator", "automation", type_="check")
    op.execute("UPDATE automation SET type = 'forecasts' WHERE type = 'forecasting'")
    op.execute("UPDATE automation SET type = 'schedules' WHERE type = 'scheduling'")
    op.create_check_constraint(
        "forecast_generator",
        "automation",
        "type != 'forecasts' OR generator_id IS NOT NULL",
    )
