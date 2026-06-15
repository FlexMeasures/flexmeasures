"""Add materialized view for belief optimization

Revision ID: c98798csds8c
Revises: b8f3cda5e023
Create Date: 2025-08-08 04:55:33.722545

"""

from alembic import op

# revision identifiers
revision = "c98798csds8c"
down_revision = "b8f3cda5e023"
branch_labels = None
depends_on = None


def upgrade():
    # Create the materialized view with proper alias
    op.execute(
        """
        CREATE MATERIALIZED VIEW most_recent_beliefs_mview AS
        SELECT *
        FROM (
            SELECT
                timed_belief.sensor_id,
                timed_belief.event_start,
                timed_belief.source_id,
                MIN(timed_belief.belief_horizon) AS most_recent_belief_horizon
            FROM timed_belief
            INNER JOIN data_source
                ON data_source.id = timed_belief.source_id
            GROUP BY
                timed_belief.sensor_id,
                timed_belief.event_start,
                timed_belief.source_id
        ) AS belief_mins
        GROUP BY
            sensor_id,
            event_start,
            source_id,
            most_recent_belief_horizon;
    """
    )

    # Create indexes
    op.execute(
        """
        CREATE INDEX idx_most_recent_beliefs_mview_sensor_event
        ON most_recent_beliefs_mview(sensor_id, event_start);
    """
    )

    op.execute(
        """
        CREATE INDEX idx_most_recent_beliefs_mview_event_start
        ON most_recent_beliefs_mview(event_start);
    """
    )

    # Create a unique index to allow concurrent refreshes
    op.execute(
        """
        CREATE UNIQUE INDEX idx_most_recent_beliefs_mview_unique
        ON most_recent_beliefs_mview(sensor_id, event_start, source_id);
    """
    )


def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS most_recent_beliefs_mview CASCADE;")
