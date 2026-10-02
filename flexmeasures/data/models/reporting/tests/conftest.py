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
        Create 3 DataSources
    """
    source1 = DataSource("source1", type="A")
    source2 = DataSource("source2", type="B")
    source2v02 = DataSource("source2", type="B", version="0.2")

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

    # add a day of extra data for sensor 1, but not for sensor 2
    for sensor, source, value in zip([sensor1], [source1, source2], [1, -1]):
        for t in range(24):
            beliefs.append(
                TimedBelief(
                    event_start=datetime(2023, 5, 11, tzinfo=utc) + timedelta(hours=t),
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
    # add a belief belonging to Source 1 in the second half of the day
    beliefs.append(
        TimedBelief(
            event_start=datetime(2023, 4, 24, tzinfo=utc) + timedelta(hours=12),
            belief_horizon=timedelta(hours=24),
            event_value=1,
            sensor=sensor3,
            source=source1,
        )
    )
    # add a belief belonging to version 0.2 of Source 2 around the end of the day, recorded 25 instead of 24 hours in advance
    beliefs.append(
        TimedBelief(
            event_start=datetime(2023, 4, 24, tzinfo=utc) + timedelta(hours=23),
            belief_horizon=timedelta(hours=25),
            event_value=3,
            sensor=sensor3,
            source=source2v02,
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


@pytest.fixture(scope="module")
def setup_pv_group(db, app):
    """Build the asset tree of a PV group, exactly as the flex-config describes it for scheduling.

    Farm (site)
    └── PV (the group, recording its aggregate production on "PV production", MW, 15 min)
        ├── Roof PV      "power", kW, 15 min
        ├── Carport PV   "power", MW, 1 hour
        └── Weather      "temperature", °C, 1 hour  (in the subtree, but not a member of the group)

    No topology is written for the reporter: the members declare themselves inflexible producers of the group,
    and the group's own entry says where its aggregate belongs.
    """
    site_type = GenericAssetType(name="PvGroupSite")
    solar_type = GenericAssetType(name="PvGroupSolar")
    weather_type = GenericAssetType(name="PvGroupWeather")
    db.session.add_all([site_type, solar_type, weather_type])

    farm = GenericAsset(name="Farm", generic_asset_type=site_type)
    db.session.add(farm)
    db.session.flush()

    pv_group = GenericAsset(name="PV", generic_asset_type=solar_type, parent_asset=farm)
    db.session.add(pv_group)
    db.session.flush()

    roof = GenericAsset(
        name="Roof PV", generic_asset_type=solar_type, parent_asset=pv_group
    )
    carport = GenericAsset(
        name="Carport PV", generic_asset_type=solar_type, parent_asset=pv_group
    )
    weather = GenericAsset(
        name="Weather", generic_asset_type=weather_type, parent_asset=pv_group
    )
    db.session.add_all([roof, carport, weather])
    db.session.flush()

    aggregate_sensor = Sensor(
        "PV production",
        generic_asset=pv_group,
        event_resolution=timedelta(minutes=15),
        unit="MW",
        timezone="UTC",
    )
    roof_power = Sensor(
        "power",
        generic_asset=roof,
        event_resolution=timedelta(minutes=15),
        unit="kW",
        timezone="UTC",
    )
    carport_power = Sensor(
        "power",
        generic_asset=carport,
        event_resolution=timedelta(hours=1),
        unit="MW",
        timezone="UTC",
    )
    temperature = Sensor(
        "temperature",
        generic_asset=weather,
        event_resolution=timedelta(hours=1),
        unit="°C",
        timezone="UTC",
    )
    db.session.add_all([aggregate_sensor, roof_power, carport_power, temperature])
    db.session.flush()

    # the flex-config: members name their group, the group names where its aggregate goes
    roof.flex_model = {
        "inflexible-production": {"sensor": roof_power.id},
        "group": {"asset": pv_group.id},
    }
    carport.flex_model = {
        "inflexible-production": {"sensor": carport_power.id},
        "group": {"asset": pv_group.id},
    }
    weather.flex_model = {}
    pv_group.flex_model = {"production": {"sensor": aggregate_sensor.id}}

    measured = DataSource("pv measurements", type="A")
    forecaster = DataSource("pv forecaster", type="forecaster")
    db.session.add_all([measured, forecaster])
    db.session.flush()

    start = datetime(2026, 6, 1, tzinfo=utc)

    def save(sensor, value, source, horizon=timedelta(0)):
        db.session.add_all(
            [
                TimedBelief(
                    event_start=start + event * sensor.event_resolution,
                    belief_horizon=horizon,
                    event_value=value,
                    sensor=sensor,
                    source=source,
                )
                for event in range(int(timedelta(days=1) / sensor.event_resolution))
            ]
        )

    save(roof_power, 400, measured)  # 400 kW, quarter-hourly
    save(carport_power, 0.15, measured)  # 0.15 MW, hourly
    save(temperature, 18, measured)  # 18 °C, hourly
    # a forecast on the roof sensor, which a realized report must leave out
    save(roof_power, 999, forecaster, horizon=timedelta(hours=12))
    # a schedule already sitting on the aggregate sensor, which must not be read back in
    save(aggregate_sensor, 42, measured)

    db.session.commit()

    yield farm, pv_group, aggregate_sensor, roof_power, carport_power, temperature, roof, carport
