import pytest
from datetime import datetime, timedelta

from pytz import utc

import pandas as pd

from flexmeasures.data.models.reporting.pandas_reporter import PandasReporter
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief


@pytest.fixture(scope="module")
def setup_dummy_data(db, app):

    """
    Create Sensors 2, 1 Asset and 1 AssetType
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

    reporter = PandasReporter(reporter_sensor, reporter_config_raw=reporter_config_raw)

    start = datetime(2023, 4, 10, tzinfo=utc)
    end = datetime(2023, 4, 10, 10, tzinfo=utc)
    report1 = reporter.compute(start, end)

    assert len(report1) == 5
    assert str(report1.index[0]) == "2023-04-10 00:00:00+00:00"
    assert (
        report1.sensor == reporter_sensor
    )  # check that the output sensor is effectively assigned.

    # check that calling compute with different parameters changes the result
    report3 = reporter.compute(start=datetime(2023, 4, 10, 3, tzinfo=utc), end=end)
    assert len(report3) == 4
    assert str(report3.index[0]) == "2023-04-10 02:00:00+00:00"


def test_reporter_repeated(setup_dummy_data):
    """check that calling compute doesn't change the result"""

    s1, s2, reporter_sensor = setup_dummy_data

    reporter_config_raw = dict(
        tb_query_config=[
            dict(
                sensor=s1.id,
                event_starts_after="2023-04-10T00:00:00 00:00",
                event_ends_before="2023-04-10T10:00:00 00:00",
            ),
            dict(
                sensor=s2.id,
                event_starts_after="2023-04-10T00:00:00 00:00",
                event_ends_before="2023-04-10T10:00:00 00:00",
            ),
        ],
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

    reporter = PandasReporter(reporter_sensor, reporter_config_raw=reporter_config_raw)
    start = datetime(2023, 4, 10, tzinfo=utc)
    end = datetime(2023, 4, 10, 10, tzinfo=utc)

    report1 = reporter.compute(start=start, end=end)
    report2 = reporter.compute(start=start, end=end)

    pd.testing.assert_series_equal(report1, report2)
