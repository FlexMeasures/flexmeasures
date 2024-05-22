import pytest
from datetime import datetime, timedelta

from pytz import utc
import pandas as pd

from flexmeasures.data.models.planning.utils import initialize_index
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief


@pytest.fixture(scope="module")
def generic_report(db, app):
    report_asset_type = GenericAssetType(name="ReportAssetType")

    db.session.add(report_asset_type)

    generic_report = GenericAsset(
        name="GenericReport", generic_asset_type=report_asset_type
    )

    db.session.add(generic_report)

    return generic_report


@pytest.fixture(scope="module")
def profit_report(db, app, generic_report, add_market_prices, setup_sources):

    device_type = GenericAssetType(name="Device")

    db.session.add(device_type)

    electricity_device = GenericAsset(
        name="Electricity Consuming Device", generic_asset_type=device_type
    )

    db.session.add(electricity_device)

    power_sensor = Sensor(
        "power",
        generic_asset=electricity_device,
        event_resolution=timedelta(minutes=15),
        unit="MW",
        timezone="Europe/Amsterdam",
    )

    energy_sensor = Sensor(
        "energy",
        generic_asset=electricity_device,
        event_resolution=timedelta(minutes=15),
        unit="MWh",
        timezone="Europe/Amsterdam",
    )

    profit_sensor_hourly = Sensor(
        "profit hourly",
        generic_asset=generic_report,
        event_resolution=timedelta(hours=1),
        unit="EUR",
        timezone="Europe/Amsterdam",
    )

    profit_sensor_daily = Sensor(
        "profit daily",
        generic_asset=generic_report,
        event_resolution=timedelta(hours=24),
        unit="EUR",
        timezone="Europe/Amsterdam",
    )

    db.session.add_all(
        [profit_sensor_hourly, profit_sensor_daily, energy_sensor, power_sensor]
    )

    time_slots = initialize_index(
        start=pd.Timestamp("2015-01-03").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2015-01-04").tz_localize("Europe/Amsterdam"),
        resolution="15min",
    )

    def save_values(sensor, values):
        beliefs = [
            TimedBelief(
                event_start=dt,
                belief_horizon=timedelta(hours=0),
                event_value=val,
                source=setup_sources["Seita"],
                sensor=sensor,
            )
            for dt, val in zip(time_slots, values)
        ]
        db.session.add_all(beliefs)

    # periodic pattern of producing 100kW for 4h and consuming 100kW for 4h:
    # i.e. [0.1 0.1 0.1 0.1 ... -0.1 -0.1 -0.1 -0.1]
    save_values(power_sensor, ([0.1] * 16 + [-0.1] * 16) * 3)

    # creating the same pattern as above but with energy
    # a flat consumption / production rate of 100kW is equivalent to consume / produce 25kWh
    # every 15min block for 1h
    save_values(energy_sensor, ([0.025] * 16 + [-0.025] * 16) * 3)

    db.session.commit()

    yield profit_sensor_hourly, profit_sensor_daily, power_sensor, energy_sensor


@pytest.fixture(scope="module")
def setup_dummy_data(db, app, generic_report):
    """
    Create 2 Sensors, 1 Asset and 1 AssetType
    """

    dummy_asset_type = GenericAssetType(name="DummyGenericAssetType")

    db.session.add(dummy_asset_type)

    dummy_asset = GenericAsset(
        name="DummyGenericAsset", generic_asset_type=dummy_asset_type
    )

    db.session.add(dummy_asset)

    sensor1 = Sensor(
        "sensor 1",
        generic_asset=dummy_asset,
        event_resolution=timedelta(hours=1),
        unit="kW",
    )
    db.session.add(sensor1)
    sensor2 = Sensor(
        "sensor 2", generic_asset=dummy_asset, event_resolution=timedelta(hours=1)
    )
    db.session.add(sensor2)
    sensor3 = Sensor(
        "sensor 3",
        generic_asset=dummy_asset,
        event_resolution=timedelta(hours=1),
        timezone="Europe/Amsterdam",
    )
    db.session.add(sensor3)
    sensor4 = Sensor(
        "sensor 4",
        generic_asset=dummy_asset,
        event_resolution=timedelta(minutes=15),
        timezone="Europe/Amsterdam",
        unit="kW",
    )
    db.session.add(sensor4)

    report_sensor = Sensor(
        "report sensor",
        generic_asset=generic_report,
        event_resolution=timedelta(hours=1),
    )
    db.session.add(report_sensor)
    daily_report_sensor = Sensor(
        "daily report sensor",
        generic_asset=generic_report,
        event_resolution=timedelta(days=1),
        timezone="Europe/Amsterdam",
    )

    db.session.add(daily_report_sensor)

    """
        Create 2 DataSources
    """
    source1 = DataSource("source1")
    source2 = DataSource("source2")

    """
        Create TimedBeliefs
    """
    beliefs = []
    for sensor in [sensor1, sensor2]:
        for si, source in enumerate([source1, source2]):
            for t in range(10):
                beliefs.append(
                    TimedBelief(
                        event_start=datetime(2023, 4, 10, tzinfo=utc)
                        + timedelta(hours=t + si),
                        belief_horizon=timedelta(hours=24),
                        event_value=t,
                        sensor=sensor,
                        source=source,
                    )
                )

    # add simple data for testing the AggregatorReporter:
    # 24 hourly events with value 1 for sensor1 and value -1 for sensor2
    for sensor, source, value in zip([sensor1, sensor2], [source1, source2], [1, -1]):
        for t in range(24):
            beliefs.append(
                TimedBelief(
                    event_start=datetime(2023, 5, 10, tzinfo=utc) + timedelta(hours=t),
                    belief_horizon=timedelta(hours=24),
                    event_value=value,
                    sensor=sensor,
                    source=source,
                )
            )

    # add simple data for testing DST transition
    for t in range(24 * 4):  # create data for 4 days
        # UTC+1 -> UTC+2
        beliefs.append(
            TimedBelief(
                event_start=datetime(2023, 3, 24, tzinfo=utc) + timedelta(hours=t),
                belief_horizon=timedelta(hours=24),
                event_value=t,
                sensor=sensor3,
                source=source1,
            )
        )

        # UTC+2 -> UTC+1
        beliefs.append(
            TimedBelief(
                event_start=datetime(2023, 10, 27, tzinfo=utc) + timedelta(hours=t),
                belief_horizon=timedelta(hours=24),
                event_value=t,
                sensor=sensor3,
                source=source1,
            )
        )

    # Add data source transition, from DataSource 1 to DataSource 2
    # At 12:00, there is one event from both of the sources
    for t in range(12):  # create data for 4 days
        # 00:00 -> 12:00
        beliefs.append(
            TimedBelief(
                event_start=datetime(2023, 4, 24, tzinfo=utc) + timedelta(hours=t),
                belief_horizon=timedelta(hours=24),
                event_value=1,
                sensor=sensor3,
                source=source1,
            )
        )
        # 12:00 -> 24:00
        beliefs.append(
            TimedBelief(
                event_start=datetime(2023, 4, 24, tzinfo=utc) + timedelta(hours=t + 12),
                belief_horizon=timedelta(hours=24),
                event_value=-1,
                sensor=sensor3,
                source=source2,
            )
        )

    # add a belief belonging to Source 2 in the second half of the day ()
    beliefs.append(
        TimedBelief(
            event_start=datetime(2023, 4, 24, tzinfo=utc) + timedelta(hours=12),
            belief_horizon=timedelta(hours=24),
            event_value=1,
            sensor=sensor3,
            source=source1,
        )
    )

    # add data for sensor 4
    for t in range(24 * 3):
        beliefs.append(
            TimedBelief(
                event_start=datetime(2023, 1, 1, tzinfo=utc) + timedelta(hours=t),
                belief_horizon=timedelta(hours=24),
                event_value=1,
                sensor=sensor4,
                source=source1,
            )
        )

    db.session.add_all(beliefs)
    db.session.commit()

    yield sensor1, sensor2, sensor3, sensor4, report_sensor, daily_report_sensor
