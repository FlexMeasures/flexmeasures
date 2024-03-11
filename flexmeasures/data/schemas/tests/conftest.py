import pytest
from datetime import timedelta

from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType


@pytest.fixture(scope="module")
def dummy_asset(db, app):
    dummy_asset_type = GenericAssetType(name="DummyGenericAssetType")
    db.session.add(dummy_asset_type)

    _dummy_asset = GenericAsset(
        name="DummyGenericAsset", generic_asset_type=dummy_asset_type
    )
    db.session.add(_dummy_asset)

    return _dummy_asset


@pytest.fixture(scope="module")
def setup_dummy_sensors(db, app, dummy_asset):
    sensor1 = Sensor(
        "sensor 1",
        generic_asset=dummy_asset,
        event_resolution=timedelta(hours=1),
        unit="MWh",
    )
    db.session.add(sensor1)

    sensor2 = Sensor(
        "sensor 2",
        generic_asset=dummy_asset,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
    )
    db.session.add(sensor2)

    sensor3 = Sensor(
        "sensor 3",
        generic_asset=dummy_asset,
        event_resolution=timedelta(hours=1),
        unit="EUR",
    )
    db.session.add(sensor3)

    sensor4 = Sensor(
        "sensor 4",
        generic_asset=dummy_asset,
        event_resolution=timedelta(hours=1),
        unit="MW",
    )
    db.session.add(sensor4)

    db.session.commit()

    yield sensor1, sensor2


@pytest.fixture(scope="module")
def setup_efficiency_sensors(db, app, dummy_asset):
    sensor = Sensor(
        "efficiency",
        generic_asset=dummy_asset,
        event_resolution=timedelta(hours=1),
        unit="%",
    )
    db.session.add(sensor)
    db.session.commit()

    return sensor


@pytest.fixture(scope="module")
def setup_site_capacity_sensor(db, app, dummy_asset, setup_sources):
    sensor = Sensor(
        "site-power-capacity",
        generic_asset=dummy_asset,
        event_resolution="P1Y",
        unit="MVA",
    )
    db.session.add(sensor)
    capacity = TimedBelief(
        sensor=sensor,
        source=setup_sources["Seita"],
        event_value=0.8,
        belief_horizon="P45D",
        event_start="2024-02-26T00:00+02",
    )
    db.session.add(capacity)

    db.session.commit()

    return {sensor.name: sensor}
