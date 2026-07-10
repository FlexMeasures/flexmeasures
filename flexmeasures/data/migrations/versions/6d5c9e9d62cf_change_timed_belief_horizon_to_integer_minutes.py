"""change timed belief horizon to integer minutes

Also delete duplicate beliefs that would have become duplicate primary keys after the change
(we keep the most recent beliefs). Those are beliefs with sub-minute differences in belieff horizons.
That last part is not reversible.

Revision ID: 6d5c9e9d62cf
Revises: 55d8936a55f9
Create Date: 2026-07-10 02:05:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "6d5c9e9d62cf"
down_revision = "55d8936a55f9"
branch_labels = None
depends_on = None


def upgrade():
    deleted_duplicate_beliefs = (
        op.get_bind()
        .execute(
            sa.text(
                """
            WITH ranked_beliefs AS (
                SELECT
                    ctid,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            source_id,
                            event_start,
                            FLOOR(EXTRACT(EPOCH FROM belief_horizon) / 60)::INTEGER,
                            cumulative_probability,
                            sensor_id
                        ORDER BY belief_horizon ASC
                    ) AS rank_in_future_primary_key
                FROM timed_belief
            ),
            deleted_rows AS (
                DELETE FROM timed_belief
                WHERE ctid IN (
                    SELECT ctid
                    FROM ranked_beliefs
                    WHERE rank_in_future_primary_key > 1
                )
                RETURNING 1
            )
            SELECT COUNT(*) FROM deleted_rows
            """
            )
        )
        .scalar_one()
    )
    print(
        "Deleted "
        f"{deleted_duplicate_beliefs} timed_belief rows that would have become "
        "duplicate primary keys after converting belief_horizon to integer minutes."
    )
    op.alter_column(
        "timed_belief",
        "belief_horizon",
        existing_type=postgresql.INTERVAL(),
        type_=sa.Integer(),
        postgresql_using="FLOOR(EXTRACT(EPOCH FROM belief_horizon) / 60)::INTEGER",
    )


def downgrade():
    op.alter_column(
        "timed_belief",
        "belief_horizon",
        existing_type=sa.Integer(),
        type_=postgresql.INTERVAL(),
        postgresql_using="belief_horizon * interval '1 minute'",
    )
