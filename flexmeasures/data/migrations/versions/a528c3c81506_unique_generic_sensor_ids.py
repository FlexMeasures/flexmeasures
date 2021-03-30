"""unique generic sensor ids

Revision ID: a528c3c81506
Revises: 22ce09690d23
Create Date: 2021-03-19 23:21:22.992700

This should be regarded as a non-reversible migration for production servers!
Downgraded ids for markets and weather sensors are not guaranteed to be the same as before upgrading,
because their ids have been shifted by the max_id of assets, and by the max_id of assets and markets, respectively.
If new assets and markets have been created between upgrading and downgrading,
the downgraded ids are not the same as before upgrading.
Mitigating circumstances are that neither market ids nor weather sensor ids had been presented to users before,
so the shift in ids shouldn't burden users.
Asset ids (and their derived entity addresses) remain the same with this revision.
This migration prepares the use of market ids and weather sensors ids in their entity addresses.


Upgrade:

- (schema for new sensors)
  - Creates new table for generic sensors, using timely_beliefs.SensorDBMixin
- (data, with temporary schema change)
  - Updates non-user-exposed ids of markets and weather sensors to ensure unique ids across assets, markets and weather sensors
  - Creates new generic sensors for all assets, markets and weather sensors, specifically setting their id to correspond to the ids of the old sensors
- (schema for old sensors)
  - Makes the id of old sensors a foreign key of the new generic sensor table


Downgrade:

- (schema for old sensors)
  - Lets old sensors store their own id again
- (data, with temporary schema change)
  - Drops new generic sensors corresponding to old sensors
  - Reverts ids of markets and weather sensors to their old ids (migration fails if old sensors have no old id backed up)
- (schema for new sensors)
  - Drop table for generic sensors


The logic for shifting ids of markets and weather stations, by example:


                asset ids           market ids              weather station ids

                                    (+max_asset_id = +6)    (+ max_asset_id + max_market_id = +6 + 8 = +14)

  (upgrade)     a 1,2,6 -> 1,2,6    m 3,4,8 -> 9,10,14      w 1,6,7 -> 15,20,21


                                    (-max_asset_id = -6)    (-max_market_id = -14)

(downgrade)     a 1,2,6 <- 1,2,6    m 3,4,8 <- 9,10,14      w 1,6,7 <- 15,20,21 (- max_market_id)

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import orm

from flexmeasures.data.models.time_series import Sensor

# revision identifiers, used by Alembic.
revision = "a528c3c81506"
down_revision = "22ce09690d23"
branch_labels = None
depends_on = None


def upgrade():
    upgrade_schema_new_sensors()
    upgrade_data()
    upgrade_schema_old_sensors()


def upgrade_schema_new_sensors():
    """Schema migration to create a new sensor table."""
    op.create_table(
        "sensor",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=80), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("event_resolution", sa.Interval(), nullable=False),
        sa.Column("knowledge_horizon_fnc", sa.String(length=80), nullable=False),
        sa.Column("knowledge_horizon_par", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("sensor_pkey")),
    )


def upgrade_data():
    """Data migration to update the ids of old sensors."""

    # To support data upgrade, cascade upon updating ids
    recreate_sensor_fks(recreate_with_cascade_on_update=True)

    # Declare ORM table views
    t_assets = sa.Table(
        "asset",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
        sa.Column("name", sa.String(80)),
    )
    t_markets = sa.Table(
        "market",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
        sa.Column("name", sa.String(80)),
    )
    t_weather_sensors = sa.Table(
        "weather_sensor",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
        sa.Column("name", sa.String(80)),
    )

    # Use SQLAlchemy's connection and transaction to go through the data
    connection = op.get_bind()

    # Get the max id used by assets and markets
    max_asset_id = get_max_id(connection, "asset")
    max_market_id = get_max_id(connection, "market")
    max_weather_sensor_id = get_max_id(connection, "weather_sensor")

    # Select all existing ids that need migrating, while keeping names intact
    asset_results = connection.execute(
        sa.select(
            [
                t_assets.c.id,
                t_assets.c.name,
            ]
        )
    ).fetchall()
    market_results = connection.execute(
        sa.select(
            [
                t_markets.c.id,
                t_markets.c.name,
            ]
        )
    ).fetchall()
    weather_sensor_results = connection.execute(
        sa.select(
            [
                t_weather_sensors.c.id,
                t_weather_sensors.c.name,
            ]
        )
    ).fetchall()

    # Prepare to build a list of new sensors
    new_sensors = []

    # Iterate over all assets
    for id_, name in asset_results:
        # Determine the new id
        new_id = id_  # assets keep their original ids
        # Create new Sensors with matching ids
        new_sensor = Sensor(name=name)
        new_sensor.id = new_id
        new_sensors.append(new_sensor)

    # Iterate over all markets
    for id_, name in market_results:
        # Determine the new id
        new_id = id_ + max_asset_id
        # Update the id
        connection.execute(
            t_markets.update().where(t_markets.c.name == name).values(id=new_id)
        )
        # Create new Sensors with matching ids
        new_sensor = Sensor(name=name)
        new_sensor.id = new_id
        new_sensors.append(new_sensor)

    # Iterate over all weather sensors
    for id_, name in weather_sensor_results:
        # Determine the new id
        new_id = id_ + max_asset_id + max_market_id
        # Update the id
        connection.execute(
            t_weather_sensors.update()
            .where(t_weather_sensors.c.name == name)
            .values(id=new_id)
        )
        # Create new Sensors with matching ids
        new_sensor = Sensor(name=name)
        new_sensor.id = new_id
        new_sensors.append(new_sensor)

    # Add the new sensors
    session = orm.Session(bind=connection)
    session.add_all(new_sensors)
    session.commit()

    # After supporting data upgrade, stop cascading upon updating ids
    recreate_sensor_fks(recreate_with_cascade_on_update=False)

    # Finally, help out the autoincrement of the Sensor table
    t_sensors = sa.Table(
        "sensor",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
    )
    sequence_name = "%s_id_seq" % t_sensors.name
    # Set next id for table seq to just after max id of all old sensors combined
    connection.execute(
        "SELECT setval('%s', %s, true);"
        % (sequence_name, max_asset_id + max_market_id + max_weather_sensor_id + 1)
    )


def upgrade_schema_old_sensors():
    """Schema migration to let old sensor tables get their id from the new sensor table."""
    op.create_foreign_key(
        "asset_id_sensor_fkey",
        "asset",
        "sensor",
        ["id"],
        ["id"],
    )
    op.create_foreign_key(
        "market_id_sensor_fkey",
        "market",
        "sensor",
        ["id"],
        ["id"],
    )
    op.create_foreign_key(
        "weather_sensor_id_sensor_fkey",
        "weather_sensor",
        "sensor",
        ["id"],
        ["id"],
    )


def downgrade():
    downgrade_schema_old_sensors()
    downgrade_data()
    downgrade_schema_new_sensors()


def downgrade_schema_old_sensors():
    """Schema migration to decouple the id of old sensor tables from the new sensor table."""
    op.drop_constraint("asset_id_sensor_fkey", "asset", type_="foreignkey")
    op.drop_constraint("market_id_sensor_fkey", "market", type_="foreignkey")
    op.drop_constraint(
        "weather_sensor_id_sensor_fkey", "weather_sensor", type_="foreignkey"
    )


def downgrade_data():
    """Data migration to retrieve the ids of old sensors.

    Note that downgraded ids are not guaranteed to be the same as during upgrade."""

    # To support data downgrade, cascade upon updating ids
    recreate_sensor_fks(recreate_with_cascade_on_update=True)

    # Declare ORM table views
    t_markets = sa.Table(
        "market",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
        sa.Column("name", sa.String(80)),
    )

    # Use Alchemy's connection and transaction to go through the data
    connection = op.get_bind()

    # Get the max id used by assets and markets
    max_asset_id = get_max_id(
        connection, "asset"
    )  # may be different than during upgrade!
    max_market_id = get_max_id(
        connection, "market"
    )  # may be different than during upgrade!

    # Select all existing ids that need migrating
    market_results = connection.execute(
        sa.select(
            [
                t_markets.c.id,
                t_markets.c.name,
            ]
        )
    ).fetchall()
    # Iterate over all selected data tuples
    for id_, name in market_results:
        # Determine the new id
        new_id = id_ - max_asset_id
        # Update the id
        connection.execute(
            t_markets.update().where(t_markets.c.name == name).values(id=new_id)
        )

    # Repeat steps for weather sensors
    t_weather_sensors = sa.Table(
        "weather_sensor",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
        sa.Column("name", sa.String(80)),
    )
    weather_sensor_results = connection.execute(
        sa.select(
            [
                t_weather_sensors.c.id,
                t_weather_sensors.c.name,
            ]
        )
    ).fetchall()
    for id_, name in weather_sensor_results:
        # Determine the new id
        new_id = id_ - max_market_id
        # Update the id
        connection.execute(
            t_weather_sensors.update()
            .where(t_weather_sensors.c.name == name)
            .values(id=new_id)
        )

    # After supporting data downgrade, stop cascading upon updating ids
    recreate_sensor_fks(recreate_with_cascade_on_update=False)


def downgrade_schema_new_sensors():
    """Schema migration to drop the new sensor table."""
    op.drop_table("sensor")


def recreate_sensor_fks(recreate_with_cascade_on_update: bool):
    """Schema migration to make foreign id keys cascade on update."""
    op.drop_constraint("asset_market_id_market_fkey", "asset", type_="foreignkey")
    op.create_foreign_key(
        "asset_market_id_market_fkey",
        "asset",
        "market",
        ["market_id"],
        ["id"],
        onupdate="CASCADE" if recreate_with_cascade_on_update else None,
    )
    op.drop_constraint("price_market_id_market_fkey", "price", type_="foreignkey")
    op.create_foreign_key(
        "price_market_id_market_fkey",
        "price",
        "market",
        ["market_id"],
        ["id"],
        onupdate="CASCADE" if recreate_with_cascade_on_update else None,
    )
    op.drop_constraint(
        "weather_sensor_id_weather_sensor_fkey", "weather", type_="foreignkey"
    )
    op.create_foreign_key(
        "weather_sensor_id_weather_sensor_fkey",
        "weather",
        "weather_sensor",
        ["sensor_id"],
        ["id"],
        onupdate="CASCADE" if recreate_with_cascade_on_update else None,
    )


def get_max_id(connection, generic_sensor_type: str) -> int:
    """
    Get the max id of a given generic sensor type.
    :param generic_sensor_type: "asset", "market", or "weather_sensor"
    """
    t_generic_sensor = sa.Table(
        generic_sensor_type,
        sa.MetaData(),
        sa.Column("id", sa.Integer),
    )
    max_id = connection.execute(
        sa.select(
            [
                sa.sql.expression.func.max(
                    t_generic_sensor.c.id,
                )
            ]
        )
    ).scalar()  # None if there are none
    max_id = 0 if max_id is None else max_id
    return max_id
