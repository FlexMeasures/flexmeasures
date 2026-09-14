"""Name automation types after the task, not its results.

The rest of the codebase calls these tasks "forecasting" and "scheduling" (queue names, job types),
so the automation types follow suit: 'forecasts' becomes 'forecasting' and 'schedules' becomes 'scheduling'.

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
    op.execute("UPDATE automation SET type = 'forecasting' WHERE type = 'forecasts'")
    op.execute("UPDATE automation SET type = 'scheduling' WHERE type = 'schedules'")


def downgrade():
    op.execute("UPDATE automation SET type = 'forecasts' WHERE type = 'forecasting'")
    op.execute("UPDATE automation SET type = 'schedules' WHERE type = 'scheduling'")
