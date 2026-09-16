"""add the sensor_data_source summary table

Records which data sources have recorded beliefs for which sensors.

The same information is already implicit in ``timed_belief``,
but getting it from there costs a scan of the largest table in the database,
to produce a relation bounded by sensors times sources,
which in practice is a few thousand rows.
It also has to be read in ``source_id`` order for ``DataSource.sensors``,
which no index serves once the primary key leads with ``sensor_id``.

The table is kept current by a statement-level trigger on ``timed_belief``, rather than by application code.
A trigger cannot be bypassed:
bulk inserts, ``COPY``, plugins and raw SQL all maintain the summary,
whereas a hook in the save path only covers the callers that happen to use it.
Doing it per statement rather than per row means one small upsert per insert statement,
however many rows that statement carries.

The table is a superset:
pairs are added when beliefs are inserted and are not removed when beliefs are deleted,
because deciding whether a pair went stale needs exactly the scan this avoids.
``Sensor.search_data_sources`` still reads ``timed_belief`` whenever time filters are given,
so time-bounded questions remain exact.

The backfill reads every belief row once.
It takes a plain ACCESS SHARE lock, so reads and writes continue,
but on a large database expect it to take a few minutes.

The function and trigger definitions come from
``flexmeasures.data.models.time_series``, the same ones ``create_all()`` installs,
rather than being written out again here.
There is only one such trigger, not a history of versions to preserve,
so nothing is lost by installing the current definition instead of a frozen one.
That said, sharing the text does not make a future change to it reach an existing
database on its own: like any other schema change,
a changed trigger needs a new migration that installs it,
because ``flexmeasures db upgrade`` only ever runs a migration once.

Revision ID: f1c8a3d75e29
Revises: b7e5a2c40f18
Create Date: 2026-08-03

"""

import logging

from alembic import op
import sqlalchemy as sa

from flexmeasures.data.models.time_series import (
    RECORD_SENSOR_DATA_SOURCES_FUNCTION,
    RECORD_SENSOR_DATA_SOURCES_TRIGGER,
)

# revision identifiers, used by Alembic.
revision = "f1c8a3d75e29"
down_revision = "b7e5a2c40f18"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


BACKFILL = """
INSERT INTO sensor_data_source (sensor_id, source_id)
SELECT DISTINCT sensor_id, source_id FROM timed_belief
ON CONFLICT DO NOTHING
"""


def upgrade():
    connection = op.get_bind()

    # Guarded, because the steps below commit as they go:
    # a run that fails during the backfill leaves the table and trigger in place,
    # and the retry has to get past this point.
    if not sa.inspect(connection).has_table("sensor_data_source"):
        op.create_table(
            "sensor_data_source",
            sa.Column("sensor_id", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["sensor_id"],
                ["sensor.id"],
                name=op.f("sensor_data_source_sensor_id_sensor_fkey"),
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["source_id"],
                ["data_source.id"],
                name=op.f("sensor_data_source_source_id_data_source_fkey"),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint(
                "sensor_id", "source_id", name=op.f("sensor_data_source_pkey")
            ),
        )

    # Install the trigger *before* the backfill, and commit it, so that it is live for
    # other sessions while the backfill runs.
    # The other order loses data:
    # the backfill reads a snapshot taken when its statement began,
    # so beliefs inserted while it runs are not in it,
    # and a trigger created afterwards in the same transaction was not visible to those
    # inserting sessions either, so nothing would ever record them.
    # With this order the two overlap instead of leaving a gap,
    # and ON CONFLICT DO NOTHING absorbs the overlap.
    with op.get_context().autocommit_block():
        op.execute(sa.text(RECORD_SENSOR_DATA_SOURCES_FUNCTION))
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS timed_belief_record_sensor_data_sources"
                " ON timed_belief"
            )
        )
        op.execute(sa.text(RECORD_SENSOR_DATA_SOURCES_TRIGGER))

    # Backfill the beliefs that predate the trigger.
    # DISTINCT over the whole table is the one expensive step here,
    # and it is also the last time we ever have to ask this question that way.
    n_rows = connection.execute(
        sa.text("SELECT reltuples::bigint FROM pg_class WHERE relname = 'timed_belief'")
    ).scalar_one_or_none()
    if n_rows is not None and n_rows > 1_000_000:
        message = (
            f"Summarising which sources recorded for which sensors"
            f" (~{n_rows:,} belief rows to scan once): this may take a few minutes."
        )
        # Also print: FlexMeasures' logging setup does not surface the alembic logger.
        print(message, flush=True)
        logger.info(message)

    op.execute(sa.text(BACKFILL))


def downgrade():
    op.execute(
        "DROP TRIGGER IF EXISTS timed_belief_record_sensor_data_sources ON timed_belief"
    )
    op.execute("DROP FUNCTION IF EXISTS record_sensor_data_sources()")
    op.drop_table("sensor_data_source")
