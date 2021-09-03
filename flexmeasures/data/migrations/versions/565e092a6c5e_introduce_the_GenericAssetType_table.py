"""introduce the GenericAssetType table

Revision ID: 565e092a6c5e
Revises: 04f0e2d2924a
Create Date: 2021-07-20 16:16:50.872449

"""
import json

from alembic import context, op
from sqlalchemy import orm
import sqlalchemy as sa

from flexmeasures.data.models.generic_assets import GenericAssetType

# revision identifiers, used by Alembic.
revision = "565e092a6c5e"
down_revision = "04f0e2d2924a"
branch_labels = None
depends_on = None


def upgrade():
    """Add GenericAssetType table

    A GenericAssetType is created for each AssetType, MarketType and WeatherSensorType.
    Optionally, additional GenericAssetTypes can be created using:

    flexmeasures db upgrade +1 -x '{"name": "waste power plant"}' -x '{"name": "EVSE", "description": "Electric Vehicle Supply Equipment"}'

    The +1 makes sure we only upgrade by 1 revision, as these arguments are only meant to be used by this upgrade function.
    """

    upgrade_schema()
    upgrade_data()


def downgrade():
    op.drop_table("generic_asset_type")


def upgrade_data():
    """Data migration adding 1 generic asset type for each user defined generic asset type,
    plus 1 generic asset type for each AssetType, MarketType and WeatherSensorType.
    """

    # Get user defined generic asset types
    generic_asset_types = context.get_x_argument()

    # Declare ORM table views
    t_asset_types = sa.Table(
        "asset_type",
        sa.MetaData(),
        sa.Column("name", sa.String(80)),
        sa.Column("display_name", sa.String(80)),
    )
    t_market_types = sa.Table(
        "market_type",
        sa.MetaData(),
        sa.Column("name", sa.String(80)),
        sa.Column("display_name", sa.String(80)),
    )
    t_weather_sensor_types = sa.Table(
        "weather_sensor_type",
        sa.MetaData(),
        sa.Column("name", sa.String(80)),
        sa.Column("display_name", sa.String(80)),
    )

    # Use SQLAlchemy's connection and transaction to go through the data
    connection = op.get_bind()
    session = orm.Session(bind=connection)

    # Select all existing ids that need migrating, while keeping names intact
    asset_type_results = connection.execute(
        sa.select(
            [
                t_asset_types.c.name,
                t_asset_types.c.display_name,
            ]
        )
    ).fetchall()
    market_type_results = connection.execute(
        sa.select(
            [
                t_market_types.c.name,
                t_market_types.c.display_name,
            ]
        )
    ).fetchall()
    weather_sensor_type_results = connection.execute(
        sa.select(
            [
                t_weather_sensor_types.c.name,
                t_weather_sensor_types.c.display_name,
            ]
        )
    ).fetchall()

    # Prepare to build a list of new generic assets
    new_generic_asset_types = []

    # Construct generic asset type for each user defined generic asset type
    asset_type_results_dict = {k: v for k, v in asset_type_results}
    market_type_results_dict = {k: v for k, v in market_type_results}
    weather_sensor_type_results_dict = {k: v for k, v in weather_sensor_type_results}
    for i, generic_asset_type in enumerate(generic_asset_types):
        generic_asset_type_dict = json.loads(generic_asset_type)
        print(
            f"Constructing one generic asset type according to: {generic_asset_type_dict}"
        )
        if generic_asset_type_dict["name"] in asset_type_results_dict.keys():
            raise ValueError(
                f"User defined generic asset type named '{generic_asset_type_dict['name']}' already exists as asset type."
            )
        if generic_asset_type_dict["name"] in market_type_results_dict.keys():
            raise ValueError(
                f"User defined generic asset type named '{generic_asset_type_dict['name']}' already exists as market type."
            )
        if generic_asset_type_dict["name"] in weather_sensor_type_results_dict.keys():
            raise ValueError(
                f"User defined generic asset type named '{generic_asset_type_dict['name']}' already exists as weather sensor type."
            )
        new_generic_asset_type = GenericAssetType(
            name=generic_asset_type_dict["name"],
            description=generic_asset_type_dict.get("description", None),
        )
        new_generic_asset_types.append(new_generic_asset_type)

    # Construct generic asset types for each AssetType
    if asset_type_results_dict:
        print(
            f"Constructing generic asset types for each of the following asset types: {asset_type_results_dict}"
        )
    for name, display_name in asset_type_results_dict.items():
        # Create new GenericAssets with matching names
        new_generic_asset_type = GenericAssetType(name=name, description=display_name)
        new_generic_asset_types.append(new_generic_asset_type)

    # Construct generic asset types for each MarketType
    if market_type_results_dict:
        print(
            f"Constructing generic asset types for each of the following market types: {market_type_results_dict}"
        )
    for name, display_name in market_type_results_dict.items():
        # Create new GenericAssets with matching names
        new_generic_asset_type = GenericAssetType(name=name, description=display_name)
        new_generic_asset_types.append(new_generic_asset_type)

    # Construct generic asset types for each WeatherSensorType
    if weather_sensor_type_results_dict:
        print(
            f"Constructing generic asset types for each of the following weather sensor types: {weather_sensor_type_results_dict}"
        )
    for name, display_name in weather_sensor_type_results_dict.items():
        # Create new GenericAssets with matching names
        new_generic_asset_type = GenericAssetType(name=name, description=display_name)
        new_generic_asset_types.append(new_generic_asset_type)

    # Add the new generic asset types
    session.add_all(new_generic_asset_types)
    session.commit()


def upgrade_schema():
    op.create_table(
        "generic_asset_type",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=True),
        sa.Column("description", sa.String(length=80), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("generic_asset_type_pkey")),
    )
