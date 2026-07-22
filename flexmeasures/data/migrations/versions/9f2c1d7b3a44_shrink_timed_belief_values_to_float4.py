"""shrink timed_belief value columns from float8 to float4

Change ``cumulative_probability`` and ``event_value`` on ``timed_belief`` from
double precision (float8, 8 bytes) to single precision (float4/REAL, 4 bytes).
These are the two per-row numeric value columns on what is typically the
largest table, so halving their width shrinks the table on disk by roughly
15-20%.

Single precision keeps ~7 significant decimal digits, which is plenty for
sensor readings and for a cumulative probability in [0, 1]. Values already
stored are rounded to the nearest float4 by the implicit cast.

Note: ``ALTER COLUMN ... TYPE`` rewrites the whole table (and rebuilds the
primary key, since ``cumulative_probability`` is part of it), so on a large
``timed_belief`` this is a heavy, table-locking operation — run it during a
maintenance window.

Revision ID: 9f2c1d7b3a44
Revises: 4b0f2e9c1a6d
Create Date: 2026-07-20

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9f2c1d7b3a44"
down_revision = "4b0f2e9c1a6d"
branch_labels = None
depends_on = None

# Single precision (float4/REAL) is a Float with precision <= 24; double
# precision (float8) is a bare Float. See the matching ORM columns on
# flexmeasures.data.models.time_series.TimedBelief.
FLOAT4 = sa.Float(precision=24)
FLOAT8 = sa.Float()


def upgrade():
    for column in ("cumulative_probability", "event_value"):
        op.alter_column(
            "timed_belief",
            column,
            type_=FLOAT4,
            existing_type=FLOAT8,
            existing_nullable=False,
        )


def downgrade():
    for column in ("cumulative_probability", "event_value"):
        op.alter_column(
            "timed_belief",
            column,
            type_=FLOAT8,
            existing_type=FLOAT4,
            existing_nullable=False,
        )
