from __future__ import annotations
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
    108.10,
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
    21.6,  # originally 21.7 due to a rounding error from 216.4569 EUR/MWh (probably via 216.5) to 217 EUR/MWh
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
]  # cents/kWh


pandas_reporter_config = dict(
    required_input=[{"name": v} for v in ["energy_tax", "VAT", "tariff", "da_prices"]],
    required_output=[{"name": "da_prices"}],
    transformations=[
        dict(
            df_input="VAT",
            method="droplevel",
            args=[[1, 2, 3]],
        ),
        dict(method="add", args=[1]),  # this is to get 1 + VAT
        dict(
            df_input="energy_tax",
            method="droplevel",
            args=[[1, 2, 3]],
        ),
        dict(
            df_input="tariff",
            method="droplevel",
            args=[[1, 2, 3]],
        ),
        dict(
            df_input="da_prices",
            method="droplevel",
            args=[[1, 2, 3]],
        ),
        dict(method="add", args=["@tariff"]),  # da_prices = da_prices + tibber_tariff
        dict(method="add", args=["@energy_tax"]),  # da_prices = da_prices + energy_tax
        dict(method="multiply", args=["@VAT"]),  # da_prices = da_price * VAT, VAT
        dict(method="round"),
    ],
)


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
    report = GenericAssetType(name="Report")

    db.session.add_all([tax, price])

    # Taxes

    electricity_price = GenericAsset(name="Electricity Price", generic_asset_type=price)

    VAT_asset = GenericAsset(name="VAT", generic_asset_type=tax)

    electricity_tax = GenericAsset(name="Energy Tax", generic_asset_type=tax)

    tibber_report = GenericAsset(name="TibberReport", generic_asset_type=report)

    db.session.add_all([electricity_price, VAT_asset, electricity_tax, tibber_report])

    # Taxes
    VAT = Sensor(
        "VAT",
        generic_asset=VAT_asset,
        event_resolution=timedelta(days=365),
        unit="",
    )
    EnergyTax = Sensor(
        "EnergyTax",
        generic_asset=electricity_tax,
        event_resolution=timedelta(days=365),
        unit="EUR/MWh",
    )

    # Tibber Tariff
    tibber_tariff = Sensor(
        "Tibber Tariff",
        generic_asset=electricity_price,
        event_resolution=timedelta(days=365),
        unit="EUR/MWh",
    )

    db.session.add_all([VAT, EnergyTax, tibber_tariff])

    """
        Saving TimeBeliefs to the DB
    """

    # Add EnergyTax, VAT and Tibber Tariff beliefs to the DB
    for sensor, source_name, value in [
        (VAT, "Tax Authority", 0.21),
        (EnergyTax, "Tax Authority", 125.99),  # EUR / MWh
        (tibber_tariff, "Tibber", 18.0),  # EUR /MWh
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

    tibber_report_sensor = Sensor(
        "TibberReportSensor",
        generic_asset=tibber_report,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
    )
    db.session.add(tibber_report_sensor)

    db.session.commit()

    return tibber_report_sensor, EnergyTax, VAT, tibber_tariff, da_prices


def test_tibber_reporter(tibber_test_data):
    """
    This test checks if the calculation of the energy prices gets close enough to the ones
    displayed in Tibber's App.
    """

    tibber_report_sensor, EnergyTax, VAT, tibber_tariff, da_prices = tibber_test_data

    tibber_reporter = PandasReporter(config=pandas_reporter_config)

    result = tibber_reporter.compute(
        input=[
            {"name": "energy_tax", "sensor": EnergyTax},
            {"name": "VAT", "sensor": VAT},
            {"name": "tariff", "sensor": tibber_tariff},
            {"name": "da_prices", "sensor": da_prices},
        ],
        output=[dict(sensor=tibber_report_sensor, name="da_prices")],
        start=datetime(2023, 4, 13, tzinfo=utc),
        end=datetime(2023, 4, 14, tzinfo=utc),
    )[0]["data"]

    # check that we got a result for 24 hours
    assert len(result) == 24

    tibber_app_price_df = (
        pd.DataFrame(tibber_app_price, index=index, columns=["event_value"])
        * 10  # convert cents/kWh to EUR/MWh
    )

    result = result.droplevel(["source", "belief_time", "cumulative_probability"])

    error = abs(result - tibber_app_price_df)

    # check that (EPEX + EnergyTax + Tibber Tariff)*(1 + VAT) = Tibber App Price
    assert error.sum(min_count=1).event_value == 0
