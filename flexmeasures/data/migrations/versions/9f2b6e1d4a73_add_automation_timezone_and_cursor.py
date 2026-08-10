"""add automation timezone and scheduling cursor

Revision ID: 9f2b6e1d4a73
Revises: 4d5e6f708192
Create Date: 2026-08-05 03:00:00.000000

"""

from flask import current_app
from alembic import op
from pytz import all_timezones_set
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9f2b6e1d4a73"
down_revision = "4d5e6f708192"
branch_labels = None
depends_on = None


def upgrade():
    timezone = current_app.config.get("FLEXMEASURES_TIMEZONE", "UTC")
    if timezone not in all_timezones_set:
        raise ValueError(
            f"Cannot migrate automations with invalid FLEXMEASURES_TIMEZONE {timezone!r}."
        )

    op.add_column(
        "automation", sa.Column("timezone", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "automation",
        sa.Column("scheduling_cursor", sa.DateTime(timezone=True), nullable=True),
    )
    automation = sa.table(
        "automation",
        sa.column("timezone", sa.String(length=64)),
        sa.column("scheduling_cursor", sa.DateTime(timezone=True)),
    )
    op.execute(
        automation.update().values(
            timezone=timezone,
            scheduling_cursor=sa.func.date_trunc("minute", sa.func.current_timestamp())
            - sa.text("interval '1 minute'"),
        )
    )
    op.alter_column("automation", "timezone", nullable=False)
    op.alter_column("automation", "scheduling_cursor", nullable=False)


def downgrade():
    op.drop_column("automation", "scheduling_cursor")
    op.drop_column("automation", "timezone")
