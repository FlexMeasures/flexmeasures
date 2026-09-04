"""Drop obsolete tables missed by the earlier cleanup.

Revision ID: 8f4a1d0c2e77
Revises: 84f268f5153c
Create Date: 2026-09-04 11:05:00.000000

The upgrade of revision ad98460751d9 dropped seven obsolete tables, but its downgrade recreates nine.
The two extra ones, asset_type and weather_sensor_type, were therefore never dropped by any upgrade,
and any database that was downgraded past ad98460751d9 and then upgraded again kept them for good.
This revision drops all nine, so that the outcome no longer depends on the database's migration history.

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError
import click

from flexmeasures.data.config import db

# revision identifiers, used by Alembic.
revision = "8f4a1d0c2e77"
down_revision = "84f268f5153c"
branch_labels = None
depends_on = None


def upgrade():
    # Children before parents, so that no foreign key blocks a drop.
    tables = [
        "power",
        "price",
        "weather",
        "asset",
        "weather_sensor",
        "market",
        "asset_type",
        "weather_sensor_type",
        "market_type",
    ]

    # Check for existing data.
    # The LIMIT is what keeps this a constant-time emptiness check: without it, a table holding more than one row makes scalar_one_or_none raise MultipleResultsFound,
    # which is exactly the case this check exists to detect.
    tables_with_data = []
    inspect = sa.inspect(db.engine)
    for table in tables:
        try:
            if inspect.has_table(table):
                result = db.session.execute(
                    sa.text(f"SELECT 1 FROM {table} LIMIT 1;")
                ).scalar_one_or_none()
                if result:
                    tables_with_data.append(table)
        except ProgrammingError:
            # Leaving the failed transaction unrolled back would break every later query in this migration,
            # and dropping a table whose contents we failed to check is not something to do quietly.
            db.session.rollback()
            raise
    db.session.close()  # https://stackoverflow.com/a/26346280/13775459

    if tables_with_data:
        click.confirm(
            f"The following tables still have data and will be dropped by this upgrade: {tables_with_data}. Use `flexmeasures db-ops dump` to create a backup. Are you sure you want to upgrade the database?: ",
            abort=True,
        )

    # Drop the tables that are still around.
    for table in tables:
        if inspect.has_table(table):
            op.drop_table(table)


def downgrade():
    # Deliberately a no-op. Downgrading to 84f268f5153c should leave these tables absent,
    # which is exactly the state that the upgrade of ad98460751d9 already produces.
    # Downgrading further, past ad98460751d9, recreates all nine tables there;
    # recreating them here as well would make that downgrade fail on tables that already exist.
    pass
