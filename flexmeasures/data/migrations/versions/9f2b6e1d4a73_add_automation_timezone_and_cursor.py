"""add automation timezone and cursor

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

    # Both columns are required, but existing rows have no value for them yet.
    # So add them as nullable, backfill every row, and only then enforce NOT NULL.
    op.add_column(
        "automation", sa.Column("timezone", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "automation",
        sa.Column("cursor", sa.DateTime(timezone=True), nullable=True),
    )
    automation = sa.table(
        "automation",
        sa.column("timezone", sa.String(length=64)),
        sa.column("cursor", sa.DateTime(timezone=True)),
    )
    # Existing automations predate the timezone column, and were run against the server timezone, so adopt that.
    # Their cursor starts one minute before the upgrade, mirroring `get_initial_cursor` for newly created automations:
    # a run scheduled in the very minute of the upgrade is still queued, while runs scheduled before that are not replayed.
    op.execute(
        automation.update().values(
            timezone=timezone,
            cursor=sa.func.date_trunc("minute", sa.func.current_timestamp())
            - sa.text("interval '1 minute'"),
        )
    )
    op.alter_column("automation", "timezone", nullable=False)
    op.alter_column("automation", "cursor", nullable=False)
    # PostgreSQL does not index a foreign key by itself, and automations are looked up by asset
    # (on an asset's automations page, and when finding the automations that feed a sensor).
    op.create_index(
        op.f("ix_automation_asset_id"), "automation", ["asset_id"], unique=False
    )


def downgrade():
    op.drop_index(op.f("ix_automation_asset_id"), table_name="automation")
    op.drop_column("automation", "cursor")
    op.drop_column("automation", "timezone")
