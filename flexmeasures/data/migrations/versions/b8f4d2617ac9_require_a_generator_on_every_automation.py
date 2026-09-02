"""Require a data generator on every automation.

A schedule automation now points at the data source describing its scheduler and the flex config it computes under,
just as a forecast automation points at the one describing its forecaster and configuration,
so the column no longer has to be nullable and the constraint requiring it only for forecasts can go.

Revision ID: b8f4d2617ac9
Revises: a71d6f2c9b04
Create Date: 2026-09-02 16:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b8f4d2617ac9"
down_revision = "a71d6f2c9b04"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    without_generator = connection.execute(
        sa.text("SELECT id, name FROM automation WHERE generator_id IS NULL")
    ).fetchall()
    if without_generator:
        listing = ", ".join(f"{row.id} ('{row.name}')" for row in without_generator)
        raise RuntimeError(
            "These automations have no data generator, which this revision makes mandatory: "
            f"{listing}."
            " They are schedule automations created before a schedule automation resolved its scheduler's data source."
            " Resolving one takes the scheduler and the asset's flex config, which this migration cannot do,"
            " so recreate them with `flexmeasures add automation` (`flexmeasures delete automation --id <id>` removes one),"
            " and run this migration again."
        )
    op.drop_constraint("forecast_generator", "automation", type_="check")
    op.alter_column("automation", "generator_id", nullable=False)


def downgrade():
    op.alter_column("automation", "generator_id", nullable=True)
    op.create_check_constraint(
        "forecast_generator",
        "automation",
        "type != 'forecasting' OR generator_id IS NOT NULL",
    )
