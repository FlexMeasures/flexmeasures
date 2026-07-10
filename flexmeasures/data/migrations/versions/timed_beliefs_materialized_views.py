"""Add materialized view caching the most recent belief per event per source

The SQL below is frozen output of the DDL generators in timely_beliefs.beliefs.materialized_views
(generated against timely-beliefs' TimedBeliefDBMixin for FlexMeasures' timed_belief table),
so that this migration stays immutable while timely-beliefs owns the canonical view definition.

Revision ID: c98798csds8c
Revises: 55d8936a55f9
Create Date: 2025-08-08 04:55:33.722545

"""

import logging

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "c98798csds8c"
down_revision = "55d8936a55f9"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# Measured creation rate for the view plus its indexes (see FlexMeasures PR #1671):
# roughly 1 minute per 15 million rows in the timed_belief table.
ROWS_PER_MINUTE = 15_000_000


def upgrade():
    # Set a duration expectation, based on the table's estimated row count
    # (pg_class.reltuples, so we don't pay for an exact COUNT on a large table).
    n_rows = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT reltuples::bigint FROM pg_class WHERE relname = 'timed_belief'"
            )
        )
        .scalar_one_or_none()
    )
    if n_rows is not None and n_rows > 0:
        minutes = max(1, round(n_rows / ROWS_PER_MINUTE))
        message = (
            f"Creating a materialized view over the timed_belief table"
            f" (~{n_rows:,} rows): expect this to take up to ~{minutes} minute(s)."
        )
        # Also print: FlexMeasures' logging setup does not surface the alembic
        # logger, and the whole point of this message is to be seen.
        print(message, flush=True)
        logger.info(message)

    op.execute(
        """
        CREATE MATERIALIZED VIEW most_recent_beliefs_mview AS
        SELECT
            sensor_id,
            event_start,
            source_id,
            MIN(belief_horizon) AS most_recent_belief_horizon
        FROM timed_belief
        GROUP BY
            sensor_id,
            event_start,
            source_id;
    """
    )

    op.execute(
        """
        CREATE INDEX idx_most_recent_beliefs_mview_sensor_event
            ON most_recent_beliefs_mview (sensor_id, event_start);
    """
    )

    op.execute(
        """
        CREATE INDEX idx_most_recent_beliefs_mview_event_start
            ON most_recent_beliefs_mview (event_start);
    """
    )

    # A unique index is required to allow concurrent refreshes
    op.execute(
        """
        CREATE UNIQUE INDEX idx_most_recent_beliefs_mview_unique
            ON most_recent_beliefs_mview (sensor_id, event_start, source_id);
    """
    )

    # Autovacuum may not have analyzed the freshly created view yet, leaving the
    # planner without statistics and prone to picking bad query plans until it does.
    op.execute("ANALYZE most_recent_beliefs_mview;")


def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS most_recent_beliefs_mview;")
