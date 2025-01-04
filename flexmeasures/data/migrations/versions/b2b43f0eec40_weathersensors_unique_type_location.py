"""weather sensor unique type and location

Revision ID: b2b43f0eec40
Revises: 1b64acf01809
Create Date: 2018-09-12 11:14:46.486640

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "b2b43f0eec40"
down_revision = "1b64acf01809"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_unique_constraint(
        "_type_name_location_unique",
        "weather_sensor",
        ["weather_sensor_type_name", "latitude", "longitude"],
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("_type_name_location_unique", "weather_sensor", type_="unique")
    # ### end Alembic commands ###
