"""Migrate sensor relationships for Power/Price/Weather

Revision ID: 830e72a8b218
Revises: 6cf5b241b85f
Create Date: 2021-12-02 14:58:06.581092

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "830e72a8b218"
down_revision = "6cf5b241b85f"
branch_labels = None
depends_on = None


def upgrade():

    # Migrate Power/Asset relationship to Power/Sensor relationship
    op.drop_constraint("power_asset_id_asset_fkey", "power", type_="foreignkey")
    op.drop_index("power_asset_id_idx", table_name="power")
    op.alter_column("power", "asset_id", new_column_name="sensor_id")
    op.create_index(op.f("power_sensor_id_idx"), "power", ["sensor_id"], unique=False)
    op.create_foreign_key(
        op.f("power_sensor_id_sensor_fkey"),
        "power",
        "sensor",
        ["sensor_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Migrate Price/Market relationship to Price/Sensor relationship
    op.drop_constraint("price_market_id_market_fkey", "price", type_="foreignkey")
    op.drop_index("price_market_id_idx", table_name="price")
    op.alter_column("price", "market_id", new_column_name="sensor_id")
    op.create_index(op.f("price_sensor_id_idx"), "price", ["sensor_id"], unique=False)
    op.create_foreign_key(
        op.f("price_sensor_id_sensor_fkey"), "price", "sensor", ["sensor_id"], ["id"]
    )

    # Migrate Weather/WeatherSensor relationship to Weather/Sensor relationship
    op.drop_constraint(
        "weather_sensor_id_weather_sensor_fkey", "weather", type_="foreignkey"
    )
    op.create_foreign_key(
        op.f("weather_sensor_id_sensor_fkey"),
        "weather",
        "sensor",
        ["sensor_id"],
        ["id"],
    )


def downgrade():
    # Migrate Weather/Sensor relationship to Weather/WeatherSensor relationship
    op.drop_constraint(
        op.f("weather_sensor_id_sensor_fkey"), "weather", type_="foreignkey"
    )
    op.create_foreign_key(
        "weather_sensor_id_weather_sensor_fkey",
        "weather",
        "weather_sensor",
        ["sensor_id"],
        ["id"],
    )

    # Migrate Price/Sensor relationship to Price/Market relationship
    op.drop_constraint(op.f("price_sensor_id_sensor_fkey"), "price", type_="foreignkey")
    op.drop_index(op.f("price_sensor_id_idx"), table_name="price")
    op.alter_column("price", "sensor_id", new_column_name="market_id")
    op.create_index("price_market_id_idx", "price", ["market_id"], unique=False)
    op.create_foreign_key(
        "price_market_id_market_fkey", "price", "market", ["market_id"], ["id"]
    )

    # Migrate Power/Sensor relationship to Power/Asset relationship
    op.drop_constraint(op.f("power_sensor_id_sensor_fkey"), "power", type_="foreignkey")
    op.drop_index(op.f("power_sensor_id_idx"), table_name="power")
    op.alter_column("power", "sensor_id", new_column_name="asset_id")
    op.create_index("power_asset_id_idx", "power", ["asset_id"], unique=False)
    op.create_foreign_key(
        "power_asset_id_asset_fkey",
        "power",
        "asset",
        ["asset_id"],
        ["id"],
        ondelete="CASCADE",
    )
