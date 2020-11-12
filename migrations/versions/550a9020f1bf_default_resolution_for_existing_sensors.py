"""default-resolution-for-existing-sensors

Revision ID: 550a9020f1bf
Revises: a5b970eadb3b
Create Date: 2020-11-05 17:48:49.670289

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "550a9020f1bf"
down_revision = "a5b970eadb3b"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE asset SET event_resolution = interval '00:15:00' where event_resolution = interval '00:00:00';"
    )
    op.execute(
        "UPDATE weather_sensor SET event_resolution = interval '00:15:00' where event_resolution = interval '00:00:00';"
    )
    op.execute(
        "UPDATE market SET event_resolution = interval '00:15:00' where event_resolution = interval '00:00:00';"
    )


def downgrade():
    op.execute(
        "UPDATE asset SET event_resolution = interval '00:00:00' where event_resolution = interval '00:15:00';"
    )
    op.execute(
        "UPDATE weather_sensor SET event_resolution = interval '00:00:00' where event_resolution = interval '00:15:00';"
    )
    op.execute(
        "UPDATE market SET event_resolution = interval '00:00:00' where event_resolution = interval '00:15:00';"
    )
