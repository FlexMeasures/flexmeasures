"""introduce the GenericAsset table

Revision ID: b6d49ed7cceb
Revises: 565e092a6c5e
Create Date: 2021-07-20 20:15:28.019102

"""
import json

from alembic import context, op
from sqlalchemy import orm, insert, update
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b6d49ed7cceb"
down_revision = "565e092a6c5e"
branch_labels = None
depends_on = None

# Declare ORM table views we are using
t_sensors = sa.Table(
    "sensor",
    sa.MetaData(),
    sa.Column("id", sa.Integer),
    sa.Column("name", sa.String(80)),
    sa.Column("generic_asset_id", sa.Integer),
)
t_generic_assets = sa.Table(
    "generic_asset",
    sa.MetaData(),
    sa.Column("id", sa.Integer),
    sa.Column("name", sa.String(80)),
    sa.Column("generic_asset_type_id", sa.Integer),
    sa.Column("owner_id", sa.Integer),
)
t_generic_asset_types = sa.Table(
    "generic_asset_type",
    sa.MetaData(),
    sa.Column("id"),
    sa.Column("name"),
)
t_assets = sa.Table(
    "asset",
    sa.MetaData(),
    sa.Column("id"),
    sa.Column(
        "asset_type_name",
    ),
)
t_markets = sa.Table(
    "market",
    sa.MetaData(),
    sa.Column("id"),
    sa.Column(
        "market_type_name",
    ),
)
t_weather_sensors = sa.Table(
    "weather_sensor",
    sa.MetaData(),
    sa.Column("id"),
    sa.Column(
        "weather_sensor_type_name",
    ),
)


def upgrade():
    """Add GenericAsset table and link with Sensor table

    For Sensors with corresponding Assets, Markets or WeatherSensors, a GenericAsset is created with matching name.
    For Sensors without, a GenericAsset is created with matching name.
    Optionally, sensors that do not correspond to an existing Asset, Market or WeatherSensor can be grouped using

    flexmeasures db upgrade +1 -x '{"asset_type_name": "waste power plant", "sensor_ids": [2, 4], "asset_name": "Afval Energie Centrale", "owner_id": 2}' -x '{"asset_type_name": "EVSE", "sensor_ids": [7, 8], "asset_name": "Laadstation Rijksmuseum - charger 2", "owner_id": 2}'

    The +1 makes sure we only upgrade by 1 revision, as these arguments are only meant to be used by this upgrade function.
    """

    upgrade_schema()
    upgrade_data()
    op.alter_column("generic_asset", "generic_asset_type_id", nullable=False)
    op.alter_column("sensor", "generic_asset_id", nullable=False)


def downgrade():
    op.drop_constraint(
        op.f("sensor_generic_asset_id_generic_asset_fkey"), "sensor", type_="foreignkey"
    )
    op.drop_column("sensor", "generic_asset_id")
    op.drop_table("generic_asset")


def upgrade_data():
    """Data migration adding 1 generic asset for each user defined group of sensors,
    plus 1 generic asset for each remaining sensor (i.e. those not part of a user defined group).
    """

    # Get user defined sensor groups
    sensor_groups = context.get_x_argument()

    # Use SQLAlchemy's connection and transaction to go through the data
    connection = op.get_bind()
    session = orm.Session(bind=connection)

    # Select all existing ids that need migrating, while keeping names intact
    sensor_results = connection.execute(
        sa.select(
            *[
                t_sensors.c.id,
                t_sensors.c.name,
            ]
        )
    ).fetchall()
    sensor_ids = [sensor_result[0] for sensor_result in sensor_results]

    # Construct generic asset for each user defined sensor group
    sensor_results_dict = {k: v for k, v in sensor_results}
    for i, sensor_group in enumerate(sensor_groups):
        sensor_group_dict = json.loads(sensor_group)
        print(f"Constructing one generic asset according to: {sensor_group_dict}")
        if not set(sensor_group_dict["sensor_ids"]).issubset(
            set(sensor_results_dict.keys())
        ):
            raise ValueError(
                f"At least some of these sensor ids {sensor_group_dict['sensor_ids']} do not exist."
            )
        generic_asset_type_results = connection.execute(
            sa.select(*[t_generic_asset_types.c.id]).where(
                t_generic_asset_types.c.name == sensor_group_dict["asset_type_name"]
            )
        ).one_or_none()
        if generic_asset_type_results is None:
            raise ValueError(
                f"Asset type name '{sensor_group_dict['asset_type_name']}' does not exist."
            )
        generic_asset_type_id = generic_asset_type_results[0]
        group_sensor_ids = [
            sensor_id
            for sensor_id in sensor_ids
            if sensor_id in sensor_group_dict["sensor_ids"]
        ]
        connection.execute(
            insert(t_generic_assets).values(
                name=sensor_group_dict["asset_name"],
                generic_asset_type_id=generic_asset_type_id,
                owner_id=sensor_group_dict["owner_id"],
            )
        )
        latest_ga_id = get_latest_generic_asset_id(connection)
        print(
            f"Created new generic asset with ID {latest_ga_id}. Now tying {len(group_sensor_ids)} sensors to it ..."
        )
        for sensor_id in group_sensor_ids:
            connection.execute(
                update(t_sensors)
                .where(t_sensors.c.id == sensor_id)
                .values(generic_asset_id=latest_ga_id)
            )
        for id_ in sensor_group_dict["sensor_ids"]:
            sensor_results_dict.pop(id_)

    # Construct generic assets for all remaining sensors
    if sensor_results_dict:
        print(
            f"Constructing generic assets for each of the following sensors: {sensor_results_dict}"
        )
    for id_, name in sensor_results_dict.items():
        _sensor_ids = [sensor_id for sensor_id in sensor_ids if sensor_id == id_]

        asset_results = connection.execute(
            sa.select(
                *[
                    t_assets.c.asset_type_name,
                ]
            ).where(t_assets.c.id == id_)
        ).one_or_none()
        if asset_results is not None:
            asset_type_name = asset_results[0]
        else:
            market_results = connection.execute(
                sa.select(
                    *[
                        t_markets.c.market_type_name,
                    ]
                ).where(t_markets.c.id == id_)
            ).one_or_none()
            if market_results is not None:
                asset_type_name = market_results[0]
            else:
                weather_sensor_results = connection.execute(
                    sa.select(
                        *[
                            t_weather_sensors.c.weather_sensor_type_name,
                        ]
                    ).where(t_weather_sensors.c.id == id_)
                ).one_or_none()
                if weather_sensor_results is not None:
                    asset_type_name = weather_sensor_results[0]
                else:
                    raise ValueError(
                        f"Cannot find an Asset, Market or WeatherSensor with id {id_}"
                    )

        generic_asset_type_results = connection.execute(
            sa.select(
                *[
                    t_generic_asset_types.c.id,
                ]
            ).where(t_generic_asset_types.c.name == asset_type_name)
        ).one_or_none()

        # Create new GenericAssets with matching names
        connection.execute(
            insert(t_generic_assets).values(
                name=name,
                generic_asset_type_id=generic_asset_type_results[0],
            )
        )
        latest_ga_id = get_latest_generic_asset_id(connection)
        print(
            f"Created new generic asset with ID {latest_ga_id}. Now tying {len(_sensor_ids)} sensors to it ..."
        )
        for sensor_id in _sensor_ids:
            connection.execute(
                update(t_sensors)
                .where(t_sensors.c.id == sensor_id)
                .values(generic_asset_id=latest_ga_id)
            )

    session.commit()


def upgrade_schema():
    op.create_table(
        "generic_asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column(
            "generic_asset_type_id", sa.Integer(), nullable=True
        ),  # we set nullable=False after data migration
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["generic_asset_type_id"],
            ["generic_asset_type.id"],
            name=op.f("generic_asset_generic_asset_type_id_generic_asset_type_fkey"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["fm_user.id"],
            name=op.f("generic_asset_owner_id_fm_user_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("generic_asset_pkey")),
    )
    op.add_column(
        "sensor", sa.Column("generic_asset_id", sa.Integer(), nullable=True)
    )  # we set nullable=False after data migration
    op.create_foreign_key(
        op.f("sensor_generic_asset_id_generic_asset_fkey"),
        "sensor",
        "generic_asset",
        ["generic_asset_id"],
        ["id"],
    )


def get_latest_generic_asset_id(connection) -> int:
    """
    Getting the latest (highest) GenericAsset ID.
    This is a useful method as somehow there was no inserted_primary_key available
    through the engine result (see
    https://docs.sqlalchemy.org/en/14/core/connections.html#sqlalchemy.engine.LegacyCursorResult.inserted_primary_key)
    """
    return connection.execute(
        sa.select(*[t_generic_assets.c.id]).order_by(t_generic_assets.c.id)
    ).fetchall()[-1][0]
