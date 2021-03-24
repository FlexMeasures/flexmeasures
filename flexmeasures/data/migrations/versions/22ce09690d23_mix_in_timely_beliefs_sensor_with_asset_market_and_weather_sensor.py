"""mix in timely beliefs sensor with asset, market and weather sensor; introduce knowledge horizons

Revision ID: 22ce09690d23
Revises: 564e8df4e3a9
Create Date: 2021-01-31 14:31:16.370110

"""
from alembic import op
import json
import sqlalchemy as sa
from timely_beliefs.sensors.func_store import knowledge_horizons


# revision identifiers, used by Alembic.
revision = "22ce09690d23"
down_revision = "564e8df4e3a9"
branch_labels = None
depends_on = None

# set default parameters for the two default knowledge horizon functions
ex_ante_default_par = {knowledge_horizons.ex_ante.__code__.co_varnames[0]: "PT0H"}
ex_post_default_par = {knowledge_horizons.ex_post.__code__.co_varnames[1]: "PT0H"}


def upgrade():

    # Mix in timely_beliefs.Sensor with flexmeasures.Asset
    op.add_column(
        "asset",
        sa.Column(
            "knowledge_horizon_fnc",
            sa.String(length=80),
            nullable=True,
            default=knowledge_horizons.ex_post.__name__,
        ),
    )
    op.execute(
        f"update asset set knowledge_horizon_fnc = '{knowledge_horizons.ex_post.__name__}';"
    )  # default assumption that power measurements are known right after the fact
    op.alter_column("asset", "knowledge_horizon_fnc", nullable=False)

    op.add_column(
        "asset",
        sa.Column(
            "knowledge_horizon_par",
            sa.JSON(),
            nullable=True,
            default={knowledge_horizons.ex_post.__code__.co_varnames[1]: "PT0H"},
        ),
    )
    op.execute(
        f"""update asset set knowledge_horizon_par = '{json.dumps(ex_post_default_par)}';"""
    )
    op.alter_column("asset", "knowledge_horizon_par", nullable=False)

    op.add_column("asset", sa.Column("timezone", sa.String(length=80), nullable=True))
    op.execute("update asset set timezone = 'Asia/Seoul';")
    op.alter_column("asset", "timezone", nullable=False)

    # Mix in timely_beliefs.Sensor with flexmeasures.Market
    op.add_column(
        "market",
        sa.Column(
            "knowledge_horizon_fnc",
            sa.String(length=80),
            nullable=True,
            default=knowledge_horizons.ex_ante.__name__,
        ),
    )
    op.execute(
        f"update market set knowledge_horizon_fnc = '{knowledge_horizons.ex_ante.__name__}';"
    )  # default assumption that prices are known before a transaction
    op.execute(
        f"update market set knowledge_horizon_fnc = '{knowledge_horizons.at_date.__name__}' where name in ('kepco_cs_fast', 'kepco_cs_slow', 'kepco_cs_smart');"
    )
    op.alter_column("market", "knowledge_horizon_fnc", nullable=False)

    op.add_column(
        "market",
        sa.Column(
            "knowledge_horizon_par",
            sa.JSON(),
            nullable=True,
            default=ex_ante_default_par,
        ),
    )
    op.execute(
        f"""update market set knowledge_horizon_par = '{json.dumps(ex_ante_default_par)}';"""
    )
    op.execute(
        """update market set knowledge_horizon_par = '{"knowledge_time": "2014-12-31 00:00:00+00:00"}' where name in ('kepco_cs_fast', 'kepco_cs_slow', 'kepco_cs_smart');"""
    )  # tariff publication date (unofficial)
    op.alter_column("market", "knowledge_horizon_par", nullable=False)
    op.execute(
        "update price set horizon = interval '0 hours' from market where market_id = market.id and market.name in ('kepco_cs_fast', 'kepco_cs_slow', 'kepco_cs_smart');"
    )  # 0 hours after fixed knowledge time (i.e. at publication date)

    op.add_column("market", sa.Column("timezone", sa.String(length=80), nullable=True))
    op.execute("update market set timezone = 'UTC';")
    op.execute("update market set timezone = 'Europe/Paris' where name='epex_da';")
    op.execute("update market set timezone = 'Asia/Seoul' where unit='KRW/kWh';")
    op.alter_column("market", "timezone", nullable=False)

    # Mix in timely_beliefs.Sensor with flexmeasures.WeatherSensor
    op.add_column(
        "weather_sensor",
        sa.Column(
            "knowledge_horizon_fnc",
            sa.String(length=80),
            nullable=True,
            default=knowledge_horizons.ex_post.__name__,
        ),
    )
    op.execute(
        f"update weather_sensor set knowledge_horizon_fnc = '{knowledge_horizons.ex_post.__name__}';"
    )  # default assumption that weather measurements are known right after the fact
    op.alter_column("weather_sensor", "knowledge_horizon_fnc", nullable=False)

    op.add_column(
        "weather_sensor",
        sa.Column(
            "knowledge_horizon_par",
            sa.JSON(),
            nullable=True,
            default={knowledge_horizons.ex_post.__code__.co_varnames[1]: "PT0H"},
        ),
    )
    op.execute(
        f"""update weather_sensor set knowledge_horizon_par = '{json.dumps(ex_post_default_par)}';"""
    )
    op.alter_column("weather_sensor", "knowledge_horizon_par", nullable=False)

    op.add_column(
        "weather_sensor", sa.Column("timezone", sa.String(length=80), nullable=True)
    )
    op.execute("update weather_sensor set timezone = 'Asia/Seoul';")
    op.alter_column("weather_sensor", "timezone", nullable=False)

    # todo: execute after adding relevant tests and updating our strategy to create forecasting jobs when new information arrives
    # op.execute(
    #     f"update market set knowledge_horizon_fnc = '{knowledge_horizons.x_days_ago_at_y_oclock.__name__}' where name in ('epex_da', 'kpx_da');"
    # )
    # op.execute(
    #     """update market set knowledge_horizon_par = '{"x": 1, "y": 12, "z": "Europe/Paris"}' where name='epex_da';"""
    # )  # gate closure at 12:00 on the preceding day, with expected price publication at 12.42 and 12.55 (from EPEX Spot Day-Ahead Multi-Regional Coupling, https://www.epexspot.com/en/downloads#rules-fees-processes )
    # op.execute(
    #     """update market set knowledge_horizon_par = '{"x": 1, "y": 10, "z": "Asia/Seoul"}' where name='kpx_da';"""
    # )  # gate closure at 10.00 on the preceding day, with expected price publication at 15.00 (from KPX Power Market Operation, https://www.slideshare.net/sjchung0/power-market-operation )
    # todo: add statement to update the horizon for prices on these markets, in accordance with their new knowledge horizon function


def downgrade():
    # Drop mixed in columns
    op.drop_column("asset", "timezone")
    op.drop_column("asset", "knowledge_horizon_par")
    op.drop_column("asset", "knowledge_horizon_fnc")
    op.drop_column("market", "timezone")
    op.drop_column("market", "knowledge_horizon_par")
    op.drop_column("market", "knowledge_horizon_fnc")
    op.drop_column("weather_sensor", "timezone")
    op.drop_column("weather_sensor", "knowledge_horizon_par")
    op.drop_column("weather_sensor", "knowledge_horizon_fnc")
    op.execute(
        "update price set horizon = ((datetime + market.event_resolution) - '2014-12-31 00:00:00+00:00') from market where market_id = market.id and name in ('kepco_cs_fast', 'kepco_cs_slow', 'kepco_cs_smart');"
    )  # rolling horizon before end of event (i.e. at publication date)
