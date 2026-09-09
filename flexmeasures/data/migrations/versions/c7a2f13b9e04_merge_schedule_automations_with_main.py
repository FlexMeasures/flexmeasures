"""merge the schedule automation migrations with main

Two migrations branched off the same revision: the one naming the automation types after the task,
and the one dropping the tables that earlier cleanups missed.
They touch different tables, so this merge only rejoins them and has nothing of its own to do.

Revision ID: c7a2f13b9e04
Revises: a71d6f2c9b04, 8f4a1d0c2e77
Create Date: 2026-09-08 10:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = "c7a2f13b9e04"
down_revision = ("a71d6f2c9b04", "8f4a1d0c2e77")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
