"""merge the automation timezone and schedule generator migrations

Two migrations branched off the same revision: one adding an automation's timezone and scheduling cursor,
the other allowing a schedule automation to exist without a data generator.
They touch different columns, so this merge only rejoins them and has nothing of its own to do.

Revision ID: c63896a97a8e
Revises: 5a9c0e3b7d21, 9f2b6e1d4a73
Create Date: 2026-08-11 01:06:28.121631

"""

# revision identifiers, used by Alembic.
revision = "c63896a97a8e"
down_revision = ("5a9c0e3b7d21", "9f2b6e1d4a73")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
