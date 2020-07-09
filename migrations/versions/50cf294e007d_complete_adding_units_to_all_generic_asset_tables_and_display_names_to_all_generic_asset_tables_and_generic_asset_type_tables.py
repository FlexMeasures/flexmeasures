"""complete_adding_units_to_all_generic_asset_tables_and_display_names_to_all_generic_asset_tables_and_generic_asset_type_tables

Revision ID: 50cf294e007d
Revises: db1f67336324
Create Date: 2018-10-12 11:12:03.525000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "50cf294e007d"
down_revision = "db1f67336324"
branch_labels = None
depends_on = None


def upgrade():

    # All markets, assets and weather sensors should specify a unit for their physical/economic quantities.
    op.alter_column("market", "price_unit", new_column_name="unit")
    op.add_column(
        "asset",
        sa.Column("unit", sa.String(length=80), nullable=False, server_default=""),
    )
    op.execute(
        """
        update asset set unit = 'MW';
        """
    )
    op.add_column(
        "weather_sensor",
        sa.Column("unit", sa.String(length=80), nullable=False, server_default=""),
    )
    op.execute(
        """
        update weather_sensor set unit = '°C' where weather_sensor_type_name = 'temperature';
        update weather_sensor set unit = 'm/s' where weather_sensor_type_name = 'wind_speed';
        update weather_sensor set unit = 'kW/m²' where weather_sensor_type_name = 'radiation';
        """
    )

    # All generic assets and generic asset types should specify a display name.
    op.add_column(
        "market_type",
        sa.Column(
            "display_name", sa.String(length=80), nullable=False, server_default=""
        ),
    )
    op.execute(
        """
        update market_type set display_name = 'day-ahead market' where name = 'day_ahead';
        update market set display_name = 'EPEX SPOT' where display_name = 'EPEX SPOT day-ahead market';
        update market set display_name = 'KPX' where display_name = 'KPX day-ahead market';
        """
    )
    op.add_column(
        "asset_type",
        sa.Column(
            "display_name", sa.String(length=80), nullable=False, server_default=""
        ),
    )
    op.execute(
        """
        update asset_type set display_name = 'solar panel' where name = 'solar';
        update asset_type set display_name = 'wind turbine' where name = 'wind';
        update asset_type set display_name = 'charging station' where name = 'charging_station';
        update asset_type set display_name = 'stationary battery' where name = 'battery';
        update asset_type set display_name = 'building' where name = 'building';
        """
    )
    op.add_column(
        "weather_sensor_type",
        sa.Column(
            "display_name", sa.String(length=80), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "weather_sensor",
        sa.Column(
            "display_name", sa.String(length=80), nullable=True, server_default=""
        ),
    )
    op.execute(
        """
        update weather_sensor_type set display_name = 'ambient temperature' where name = 'temperature';
        update weather_sensor_type set display_name = 'wind speed' where name = 'wind_speed';
        update weather_sensor_type set display_name = 'solar irradiation' where name = 'radiation';
        """
    )
    op.create_unique_constraint(
        "market_type_display_name_key", "market_type", ["display_name"]
    )
    op.create_unique_constraint(
        "asset_type_display_name_key", "asset_type", ["display_name"]
    )
    op.create_unique_constraint(
        "weather_sensor_type_display_name_key", "weather_sensor_type", ["display_name"]
    )


def downgrade():
    op.drop_constraint(
        "weather_sensor_type_display_name_key", "weather_sensor_type", type_="unique"
    )
    op.drop_constraint("asset_type_display_name_key", "asset_type", type_="unique")
    op.drop_constraint("market_type_display_name_key", "market_type", type_="unique")

    op.drop_column("weather_sensor", "display_name")
    op.drop_column("weather_sensor_type", "display_name")
    op.drop_column("asset_type", "display_name")
    op.drop_column("market_type", "display_name")

    op.drop_column("weather_sensor", "unit")
    op.drop_column("asset", "unit")
    op.alter_column("market", "unit", new_column_name="price_unit")
