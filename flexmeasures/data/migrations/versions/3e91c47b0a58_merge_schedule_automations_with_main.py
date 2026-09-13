"""merge the schedule automation migrations with main

Two migrations branched off the same revision: the one adding an automation's timezone and cursor,
and those reordering the timed belief primary key and adding the sensor data source association.
They touch different tables, so this merge only rejoins them and has nothing of its own to do.

Revision ID: 3e91c47b0a58
Revises: 9f2b6e1d4a73, 84f268f5153c
Create Date: 2026-09-02 10:30:00.000000

"""

# revision identifiers, used by Alembic.
revision = "3e91c47b0a58"
down_revision = ("9f2b6e1d4a73", "84f268f5153c")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
