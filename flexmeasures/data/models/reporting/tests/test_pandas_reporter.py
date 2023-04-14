import pytest

from datetime import datetime, timedelta

from pytz import utc

from flexmeasures.data.models.reporting.pandas_reporter import PandasReporter
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief


@pytest.fixture
def setup_dummy_data(db, app):

    """
    Create Sensors 2, 1 Asset and 1 AssetType
    """
    dummy_asset_type = GenericAssetType(name="DummyGenericAssetType")
    db.session.add(dummy_asset_type)

    dummy_asset = GenericAsset(
        name="DummyGenericAsset", generic_asset_type=dummy_asset_type
    )
    db.session.add(dummy_asset)

    sensor1 = Sensor("sensor 1", generic_asset=dummy_asset)
    db.session.add(sensor1)
    sensor2 = Sensor("sensor 2", generic_asset=dummy_asset)
    db.session.add(sensor2)
    report_sensor = Sensor("report sensor", generic_asset=dummy_asset)
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


def test_reporter(setup_dummy_data):
    s1, s2, reporter_sensor = setup_dummy_data

    reporter_config_raw = dict(
        start=str(datetime(2023, 4, 10, tzinfo=utc)),
        end=str(datetime(2023, 4, 10, 10, tzinfo=utc)),
        tb_query_config=[dict(sensor=s1.id), dict(sensor=s2.id)],
        transformations=[
            dict(
                df_input="sensor_1",
                df_output="sensor_1_source_1",
                method="xs",
                args=["@source_1"],
                kwargs=dict(level=2),
            ),
            dict(
                df_input="sensor_2",
                df_output="sensor_2_source_1",
                method="xs",
                args=["@source_1"],
                kwargs=dict(level=2),
            ),
            dict(
                df_output="df_merge",
                df_input="sensor_1_source_1",
                method="merge",
                args=["@sensor_2_source_1"],
                kwargs=dict(on="event_start", suffixes=("_sensor1", "_sensor2")),
            ),
            dict(method="resample", args=["2h"]),
            dict(method="mean"),
            dict(method="sum", kwargs=dict(axis=1)),
        ],
        final_df_output="df_merge",
    )

    reporter = PandasReporter(reporter_config_raw=reporter_config_raw)

    report1 = reporter.compute()

    assert len(report1) == 5
    assert str(report1.index[0]) == "2023-04-10 00:00:00+00:00"

    report2 = reporter.compute(start=str(datetime(2023, 4, 10, 3, tzinfo=utc)))
    assert len(report2) == 4
    assert str(report2.index[0]) == "2023-04-10 02:00:00+00:00"
