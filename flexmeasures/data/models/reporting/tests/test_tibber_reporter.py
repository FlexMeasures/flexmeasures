import pytest

from flexmeasures.data.models.reporting.pandas_reporter import PandasReporter
from flexmeasures.data.models.time_series import Sensor, DataSource, TimedBelief
from flexmeasures.data.models.generic_assets import GenericAssetType, GenericAsset

import pandas as pd
from datetime import datetime, timedelta
from pytz import utc

index = pd.date_range(
    datetime(2023, 4, 13), datetime(2023, 4, 13, 23), freq="H", tz=utc
)

entsoe_prices = [
    97.23,
    85.09,
    79.49,
    72.86,
    71.12,
    82.50,
    102.06,
    115.04,
    122.15,
    105.39,
    83.40,
    34.90,
    -4.50,
    -50.00,
    -50.07,
    -50.00,
    -0.90,
    08.10,
    128.10,
    151.00,
    155.20,
    152.00,
    134.04,
    120.10,
]  # EUR / MWh

tibber_app_price = [
    29.2,
    27.7,
    27.0,
    26.2,
    26.0,
    27.4,
    29.8,
    31.3,
    32.2,
    30.2,
    27.5,
    21.7,
    16.9,
    11.4,
    11.4,
    11.4,
    17.3,
    30.5,
    32.9,
    35.7,
    36.2,
    35.8,
    33.6,
    32.0,
]  # EUR/MWh


class TibberReporter(PandasReporter):
    def __init__(self, start: datetime, end: datetime) -> None:
        """This class calculates the price of energy of a tariff indexed to the Day Ahead prices.
        Energy Price = (1 + VAT) x ( EB + Tiber + DA Prices)
        """

        # search the sensors
        EB = Sensor.query.filter(Sensor.name == "EB").one_or_none()
        BWV = Sensor.query.filter(Sensor.name == "BWV").one_or_none()
        tibber_tariff = Sensor.query.filter(
            Sensor.name == "Tibber Tariff"
        ).one_or_none()

        da_prices = Sensor.query.filter(Sensor.name == "DA prices").one_or_none()

        tb_query_config_extra = dict(
            resolution=3600,  # 1h = 3600s
            event_starts_after=str(start),
            event_ends_before=str(end),
        )

        # creating the PandasReporter reporter config
        reporter_config_raw = dict(
            start=str(start),
            end=str(end),
            tb_query_config=[
                dict(sensor=EB.id, **tb_query_config_extra),
                dict(sensor=BWV.id, **tb_query_config_extra),
                dict(sensor=tibber_tariff.id, **tb_query_config_extra),
                dict(sensor=da_prices.id, **tb_query_config_extra),
            ],
            transformations=[
                dict(
                    df_input="sensor_1",
                    df_output="BWV",
                    method="droplevel",
                    args=[[1, 2, 3]],
                ),
                dict(method="add", args=[1]),  # this is to get 1 + BWV
                dict(
                    df_input="sensor_2",
                    df_output="EB",
                    method="droplevel",
                    args=[[1, 2, 3]],
                ),
                dict(
                    df_input="sensor_3",
                    df_output="tibber_tariff",
                    method="droplevel",
                    args=[[1, 2, 3]],
                ),
                dict(
                    df_input="sensor_4",
                    df_output="da_prices",
                    method="droplevel",
                    args=[[1, 2, 3]],
                ),
                dict(
                    method="multiply",
                    args=[1 / 1000],
                ),
                dict(
                    df_output="energy_price",
                    df_input="EB",
                    method="add",
                    args=["@tibber_tariff"],
                ),
                dict(method="add", args=["@da_prices"]),
                dict(method="multiply", args=["@BWV"]),
            ],
            final_df_output="energy_price",
        )

        super().__init__(reporter_config_raw)


def beliefs_from_timeseries(index, values, sensor, source):
    beliefs = []
    for dt, value in zip(index, values):
        beliefs.append(
            TimedBelief(
                event_start=dt,
                belief_horizon=timedelta(hours=24),
                event_value=value,
                sensor=sensor,
                source=source,
            )
        )

    return beliefs


@pytest.fixture()
def tibber_test_data(fresh_db, app):
    db = fresh_db

    tax = GenericAssetType(name="Tax")
    price = GenericAssetType(name="Price")

    db.session.add_all([tax, price])

    # Belastingdienst

    electricity_price = GenericAsset(name="Electricity Price", generic_asset_type=price)

    VAT = GenericAsset(name="VAT", generic_asset_type=tax)

    electricity_tax = GenericAsset(name="Energy Tax", generic_asset_type=tax)

    db.session.add_all([electricity_price, VAT, electricity_tax])

    # Taxes
    BWV = Sensor("BWV", generic_asset=VAT, event_resolution=timedelta(days=365))
    EB = Sensor(
        "EB", generic_asset=electricity_tax, event_resolution=timedelta(days=365)
    )

    # Tibber Tariff
    tibber_tariff = Sensor(
        "Tibber Tariff",
        generic_asset=electricity_price,
        event_resolution=timedelta(days=365),
    )

    db.session.add_all([BWV, EB, tibber_tariff])

    """
        Saving TimeBeliefs to the DB
    """

    # Adding EB, BWV and Tibber Tarriff beliefs to the DB
    for sensor, source_name, value in [
        (BWV, "Belastingdienst", 0.21),
        (EB, "Belastingdienst", 0.12599),
        (tibber_tariff, "Tibber", 0.018),
    ]:
        belief = TimedBelief(
            sensor=sensor,
            source=DataSource(source_name),
            event_value=value,
            event_start=datetime(2023, 1, 1, tzinfo=utc),
            belief_time=datetime(2023, 1, 1, tzinfo=utc),
        )

        db.session.add(belief)

    # DA Prices
    entsoe = DataSource("ENTSOE")
    da_prices = Sensor(
        "DA prices",
        generic_asset=electricity_price,
        event_resolution=timedelta(hours=1),
    )
    db.session.add(da_prices)
    da_prices_beliefs = beliefs_from_timeseries(index, entsoe_prices, da_prices, entsoe)
    db.session.add_all(da_prices_beliefs)

    return


def test_tibber_reporter(tibber_test_data):
    """
    This test checks if the calculation of the energy prices gets close enough to the ones
    displayed in Tibber's App.
    """

    tibber_reporter = TibberReporter(
        datetime(2023, 4, 13, tzinfo=utc), datetime(2023, 4, 14, tzinfo=utc)
    )

    result = tibber_reporter.compute()

    # checking that we've get a result for 24 hours
    assert len(result) == 24

    tibber_app_price_df = (
        pd.DataFrame(tibber_app_price, index=index, columns=["event_value"]) / 100
    )

    # checking that (EPEX+EB + Tibber Tariff)*(1+BWV) = Tibber App Price
    assert (
        abs(result - tibber_app_price_df).mean().iloc[0] < 0.01
    )  # difference of less than 1 cent / kWh
