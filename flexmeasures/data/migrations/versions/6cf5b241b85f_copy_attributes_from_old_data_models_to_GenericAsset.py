"""Copy attributes from old data models to GenericAsset

Revision ID: 6cf5b241b85f
Revises: 1ae32ffc8c3f
Create Date: 2021-11-11 17:18:15.395915

"""
import json
from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6cf5b241b85f"
down_revision = "1ae32ffc8c3f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "generic_asset",
        sa.Column("attributes", sa.JSON(), nullable=True, default={}),
    )
    op.add_column(
        "sensor",
        sa.Column("attributes", sa.JSON(), nullable=True, default={}),
    )

    """
    - For each OldModel (Market/WeatherSensor/Asset), get the Sensor with the same id as the OldModel,
      and then get the GenericAsset of that Sensor.
    - Add the OldModel's display name to the corresponding GenericAsset's attributes,
      and other attributes we want to copy.
    - Find the OldModelType (MarketType/WeatherSensorType/AssetType) of the OldModel,
      and copy its seasonalities to the GenericAsset's attributes.
    """
    # todo: find places where we look for seasonality and get it from the corresponding GenericAsset instead
    # todo: find places where we look for old_model_type and get it from the corresponding GenericAsset instead

    # Declare ORM table views
    t_generic_asset = sa.Table(
        "generic_asset",
        sa.MetaData(),
        sa.Column("id"),
        sa.Column("attributes"),
    )
    t_sensor = sa.Table(
        "sensor",
        sa.MetaData(),
        sa.Column("id"),
        sa.Column("attributes"),
        sa.Column("generic_asset_id"),
        sa.Column("unit"),
        sa.Column("event_resolution"),
        sa.Column("knowledge_horizon_fnc"),
        sa.Column("knowledge_horizon_par"),
    )
    t_market = sa.Table(
        "market",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
        sa.Column("market_type_name", sa.String(80)),
        sa.Column(
            "display_name", sa.String(80)
        ),  # Copy to both Sensor and to GenericAsset
        sa.Column("unit"),  # Copy to Sensor [done]
        sa.Column("event_resolution"),  # Copy to Sensor [done]
        sa.Column("knowledge_horizon_fnc"),  # Copy to Sensor [done]
        sa.Column("knowledge_horizon_par"),  # Copy to Sensor [done]
    )
    t_market_type = sa.Table(
        "market_type",
        sa.MetaData(),
        sa.Column("name", sa.String(80)),
        sa.Column("daily_seasonality", sa.Boolean),  # Copy to Sensor
        sa.Column("weekly_seasonality", sa.Boolean),  # Copy to Sensor
        sa.Column("yearly_seasonality", sa.Boolean),  # Copy to Sensor
    )
    t_asset = sa.Table(
        "asset",
        sa.MetaData(),
        sa.Column("id"),
        sa.Column("asset_type_name"),
        sa.Column("display_name"),  # Copy to both Sensor and to GenericAsset
        sa.Column("capacity_in_mw"),  # Copy to Sensor
        sa.Column("min_soc_in_mwh"),  # Copy to GenericAsset [1]
        sa.Column("max_soc_in_mwh"),  # Copy to GenericAsset [1]
        sa.Column("soc_in_mwh"),  # Copy to GenericAsset [1]
        sa.Column("soc_datetime"),  # Copy to GenericAsset [1]
        sa.Column("soc_udi_event_id"),  # Copy to GenericAsset [2]
        sa.Column("market_id"),  # Copy to Sensor [3]
        sa.Column("unit"),  # Copy to Sensor [done]
        sa.Column("event_resolution"),  # Copy to Sensor [done]
        sa.Column("knowledge_horizon_fnc"),  # Copy to Sensor [done]
        sa.Column("knowledge_horizon_par"),  # Copy to Sensor [done]
    )
    # [1] will be moved to a separate sensor later
    # [2] deprecated in favour of Redis job id since api v1.3
    # [3] will be deprecated in favour of something like a weighed by relationship (could be multiple)
    t_asset_type = sa.Table(
        "asset_type",
        sa.MetaData(),
        sa.Column("name", sa.String(80)),
        sa.Column("is_consumer"),  # Copy to Sensor
        sa.Column("is_producer"),  # Copy to Sensor
        sa.Column("can_curtail"),  # Copy to GenericAsset [4]
        sa.Column("can_shift"),  # Copy to GenericAsset [4]
        sa.Column("daily_seasonality", sa.Boolean),  # Copy to Sensor
        sa.Column("weekly_seasonality", sa.Boolean),  # Copy to Sensor
        sa.Column("yearly_seasonality", sa.Boolean),  # Copy to Sensor
    )
    # [4] will be deprecated in favour of actuator functionality
    t_weather_sensor = sa.Table(
        "weather_sensor",
        sa.MetaData(),
        sa.Column("id"),
        sa.Column("weather_sensor_type_name"),
        sa.Column("display_name"),  # Copy to both Sensor and to GenericAsset
        sa.Column("unit"),  # Copy to Sensor [done]
        sa.Column("event_resolution"),  # Copy to Sensor [done]
        sa.Column("knowledge_horizon_fnc"),  # Copy to Sensor [done]
        sa.Column("knowledge_horizon_par"),  # Copy to Sensor [done]
    )
    t_weather_sensor_type = sa.Table(
        "weather_sensor_type",
        sa.MetaData(),
        sa.Column("name", sa.String(80)),
    )

    # Use SQLAlchemy's connection and transaction to go through the data
    connection = op.get_bind()

    # Set default attributes
    connection.execute(
        t_sensor.update().values(
            attributes=json.dumps({}),
        )
    )
    connection.execute(
        t_generic_asset.update().values(
            attributes=json.dumps({}),
        )
    )

    copy_attributes(
        connection,
        t_market,
        t_sensor,
        t_target=t_sensor,
        t_old_model_type=t_market_type,
        old_model_attributes=["id", "market_type_name", "display_name"],
        old_model_type_attributes=[
            "daily_seasonality",
            "weekly_seasonality",
            "yearly_seasonality",
        ],
    )
    copy_attributes(
        connection,
        t_market,
        t_sensor,
        t_target=t_generic_asset,
        t_old_model_type=t_market_type,
        old_model_attributes=["id", "market_type_name", "display_name"],
    )
    copy_attributes(
        connection,
        t_weather_sensor,
        t_sensor,
        t_target=t_sensor,
        t_old_model_type=t_weather_sensor_type,
        old_model_attributes=["id", "weather_sensor_type_name", "display_name"],
        extra_attributes={
            "daily_seasonality": True,
            "weekly_seasonality": False,
            "yearly_seasonality": True,
        },  # The WeatherSensor table had these hardcoded (d, w, y) seasonalities
    )
    copy_attributes(
        connection,
        t_weather_sensor,
        t_sensor,
        t_target=t_generic_asset,
        t_old_model_type=t_weather_sensor_type,
        old_model_attributes=["id", "weather_sensor_type_name", "display_name"],
    )
    copy_attributes(
        connection,
        t_asset,
        t_sensor,
        t_target=t_sensor,
        t_old_model_type=t_asset_type,
        old_model_attributes=[
            "id",
            "asset_type_name",
            "display_name",
            "capacity_in_mw",
            "market_id",
        ],
        old_model_type_attributes=[
            "is_consumer",
            "is_producer",
            "daily_seasonality",
            "weekly_seasonality",
            "yearly_seasonality",
        ],
    )
    copy_attributes(
        connection,
        t_asset,
        t_sensor,
        t_target=t_generic_asset,
        t_old_model_type=t_asset_type,
        old_model_attributes=[
            "id",
            "asset_type_name",
            "display_name",
            "min_soc_in_mwh",
            "max_soc_in_mwh",
            "soc_in_mwh",
            "soc_datetime",
            "soc_udi_event_id",
        ],
        old_model_type_attributes=[
            "can_curtail",
            "can_shift",
        ],
    )
    op.alter_column(
        "sensor",
        "attributes",
        nullable=False,
    )
    op.alter_column(
        "generic_asset",
        "attributes",
        nullable=False,
    )
    copy_sensor_columns(connection, t_market, t_sensor)
    copy_sensor_columns(connection, t_weather_sensor, t_sensor)
    copy_sensor_columns(connection, t_asset, t_sensor)


def downgrade():
    op.drop_column("sensor", "attributes")
    op.drop_column("generic_asset", "attributes")


def copy_sensor_columns(connection, t_old_model, t_sensor):
    old_model_attributes = [
        "id",
        "unit",
        "event_resolution",
        "knowledge_horizon_fnc",
        "knowledge_horizon_par",
    ]

    # Get columns from old model
    results = connection.execute(
        sa.select([getattr(t_old_model.c, a) for a in old_model_attributes])
    ).fetchall()

    for sensor_id, *args in results:

        # Obtain columns we want to copy over, from the old model
        old_model_columns_to_copy = {
            k: v if not isinstance(v, dict) else json.dumps(v)
            for k, v in zip(old_model_attributes[-len(args) :], args)
        }

        # Fill in the Sensor's columns
        connection.execute(
            t_sensor.update()
            .where(t_sensor.c.id == sensor_id)
            .values(
                **old_model_columns_to_copy,
            )
        )


def copy_attributes(
    connection,
    t_old_model,
    t_sensor,
    t_target,
    t_old_model_type,
    old_model_attributes,
    old_model_type_attributes=[],
    extra_attributes={},
):
    """

    :param old_model_attributes: first two attributes should be id and old_model_type_name, then any other columns we want to copy over from the old model
    :param old_model_type_attributes: columns we want to copy over from the old model type
    :param extra_attributes: any additional attributes we want to set
    """
    # Get attributes from old model
    results = connection.execute(
        sa.select([getattr(t_old_model.c, a) for a in old_model_attributes])
    ).fetchall()

    for id, type_name, *args in results:

        # Obtain attributes we want to copy over, from the old model
        old_model_attributes_to_copy = {
            k: v if not isinstance(v, datetime) else v.isoformat()
            for k, v in zip(old_model_attributes[-len(args) :], args)
        }

        # Obtain seasonality attributes we want to copy over, from the old model type
        old_model_type_attributes_to_copy = get_old_model_type_attributes(
            connection,
            type_name,
            t_old_model_type,
            old_model_type_attributes=old_model_type_attributes,
        )

        # Find out where to copy over the attributes
        if t_target.name == "generic_asset":
            target_id = get_generic_asset_id(connection, id, t_sensor)
        elif t_target.name == "sensor":
            target_id = id
        else:
            raise ValueError

        # Fill in the target class's attributes
        connection.execute(
            t_target.update()
            .where(t_target.c.id == target_id)
            .values(
                attributes=json.dumps(
                    {
                        **old_model_attributes_to_copy,
                        **old_model_type_attributes_to_copy,
                        **extra_attributes,
                    }
                )
            )
        )


def get_generic_asset_id(connection, old_model_id: int, t_sensors) -> int:
    """Get the Sensor with the same id as the OldModel, and then get the id of the GenericAsset of that Sensor."""
    (generic_asset_id,) = connection.execute(
        sa.select(
            [
                t_sensors.c.generic_asset_id,
            ]
        ).filter(t_sensors.c.id == old_model_id)
    ).one_or_none()
    assert generic_asset_id is not None
    return generic_asset_id


def get_old_model_type_attributes(
    connection, old_model_type_name, t_old_model_types, old_model_type_attributes
) -> dict:
    """Get the attributes from the OldModelType."""
    values = connection.execute(
        sa.select(
            [getattr(t_old_model_types.c, a) for a in old_model_type_attributes]
        ).filter(t_old_model_types.c.name == old_model_type_name)
    ).one_or_none()
    assert values is not None
    return {k: v for k, v in zip(old_model_type_attributes, values)}
