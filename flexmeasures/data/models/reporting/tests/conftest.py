import pytest
from datetime import datetime, timedelta

from pytz import utc

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief


@pytest.fixture(scope="module")
def setup_dummy_data(db, app):
    """
    Create 2 Sensors, 1 Asset and 1 AssetType
    """

    dummy_asset_type = GenericAssetType(name="DummyGenericAssetType")
    report_asset_type = GenericAssetType(name="ReportAssetType")

    db.session.add_all([dummy_asset_type, report_asset_type])

    dummy_asset = GenericAsset(
        name="DummyGenericAsset", generic_asset_type=dummy_asset_type
    )

    pandas_report = GenericAsset(
        name="PandasReport", generic_asset_type=report_asset_type
    )

    db.session.add_all([dummy_asset, pandas_report])

    sensor1 = Sensor("sensor 1", generic_asset=dummy_asset, event_resolution="1h")
    db.session.add(sensor1)
    sensor2 = Sensor("sensor 2", generic_asset=dummy_asset, event_resolution="1h")
    db.session.add(sensor2)
    report_sensor = Sensor(
        "report sensor", generic_asset=pandas_report, event_resolution="1h"
    )
    db.session.add(report_sensor)

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
                print(si)
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

    db.session.add_all(beliefs)
    db.session.commit()

    yield sensor1, sensor2, report_sensor

    db.session.delete(sensor1)
    db.session.delete(sensor2)

    for b in beliefs:
        db.session.delete(b)

    db.session.delete(dummy_asset)
    db.session.delete(dummy_asset_type)

    db.session.commit()
