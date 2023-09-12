import pytest

from datetime import datetime, timedelta
from pytz import utc

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief


@pytest.fixture(scope="function")
@pytest.mark.skip_github
def setup_dummy_asset(fresh_db, app):
    """
    Create an Asset to add sensors to and return the id.
    """

    db = fresh_db

    dummy_asset_type = GenericAssetType(name="DummyGenericAssetType")

    db.session.add(dummy_asset_type)

    dummy_asset = GenericAsset(
        name="DummyGenericAsset", generic_asset_type=dummy_asset_type
    )
    db.session.add(dummy_asset)
    db.session.commit()

    return dummy_asset.id


@pytest.fixture(scope="function")
@pytest.mark.skip_github
def setup_dummy_data(fresh_db, app, setup_dummy_asset):
    """
    Create an asset with two sensors (1 and 2), and add the same set of 200 beliefs with an hourly resolution to each of them.
    Return the two sensors and a result sensor (which has no data).
    """

    db = fresh_db

    report_asset_type = GenericAssetType(name="ReportAssetType")

    db.session.add(report_asset_type)

    pandas_report = GenericAsset(
        name="PandasReport", generic_asset_type=report_asset_type
    )

    db.session.add(pandas_report)

    dummy_asset = GenericAsset.query.get(setup_dummy_asset)

    sensor1 = Sensor(
        "sensor 1", generic_asset=dummy_asset, event_resolution=timedelta(hours=1)
    )

    db.session.add(sensor1)
    sensor2 = Sensor(
        "sensor 2", generic_asset=dummy_asset, event_resolution=timedelta(hours=1)
    )
    db.session.add(sensor2)
    report_sensor = Sensor(
        "report sensor",
        generic_asset=pandas_report,
        event_resolution=timedelta(hours=2),
    )
    db.session.add(report_sensor)

    report_sensor_2 = Sensor(
        "report sensor 2",
        generic_asset=pandas_report,
        event_resolution=timedelta(hours=2),
    )
    db.session.add(report_sensor_2)

    # Create 1 DataSources
    source = DataSource("source1")

    # Create TimedBeliefs
    beliefs = []
    for sensor in [sensor1, sensor2]:
        for t in range(200):
            beliefs.append(
                TimedBelief(
                    event_start=datetime(2023, 4, 10, tzinfo=utc) + timedelta(hours=t),
                    belief_time=datetime(2023, 4, 9, tzinfo=utc),
                    event_value=t,
                    sensor=sensor,
                    source=source,
                )
            )

    db.session.add_all(beliefs)
    db.session.commit()

    yield sensor1.id, sensor2.id, report_sensor.id, report_sensor_2.id


@pytest.mark.skip_github
@pytest.fixture(scope="function")
def process_power_sensor(
    fresh_db,
    app,
):
    """
    Create an asset of type "process", power sensor to hold the result of
    the scheduler and price data consisting of 8 expensive hours, 8 cheap hours, and again 8 expensive hours-

    """

    db = fresh_db

    process_asset_type = GenericAssetType(name="process")

    db.session.add(process_asset_type)

    process_asset = GenericAsset(
        name="Test Process Asset", generic_asset_type=process_asset_type
    )

    db.session.add(process_asset)

    power_sensor = Sensor(
        "power",
        generic_asset=process_asset,
        event_resolution=timedelta(hours=1),
        unit="MW",
    )

    db.session.add(power_sensor)

    db.session.commit()

    yield power_sensor.id
