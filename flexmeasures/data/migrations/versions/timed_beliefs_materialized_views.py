"""Add materialized view caching the most recent belief per event per source

The SQL below is frozen output of the DDL generators in timely_beliefs.beliefs.materialized_views
(generated against timely-beliefs' TimedBeliefDBMixin for FlexMeasures' timed_belief table),
so that this migration stays immutable while timely-beliefs owns the canonical view definition.

Revision ID: c98798csds8c
Revises: 55d8936a55f9
Create Date: 2025-08-08 04:55:33.722545

"""

from alembic import op

# revision identifiers
revision = "c98798csds8c"
down_revision = "55d8936a55f9"
branch_labels = None
depends_on = None


def upgrade():
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
