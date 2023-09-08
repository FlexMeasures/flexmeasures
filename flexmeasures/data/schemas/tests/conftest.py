import pytest
from datetime import timedelta

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType


@pytest.fixture(scope="module")
def setup_dummy_sensors(db, app):

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
