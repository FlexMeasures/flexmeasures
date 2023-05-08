import pytest

from datetime import datetime, timedelta
from pytz import utc

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief


@pytest.fixture(scope="module")
@pytest.mark.skip_github
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

    """
        Create 1 DataSources
    """
    source = DataSource("source1")

    """
        Create TimedBeliefs
    """
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

    yield sensor1, sensor2, report_sensor

    db.session.delete(sensor1)
    db.session.delete(sensor2)

    for b in beliefs:
        db.session.delete(b)

    db.session.delete(dummy_asset)
    db.session.delete(dummy_asset_type)

    db.session.commit()


@pytest.fixture(scope="module")
@pytest.mark.skip_github
def reporter_config_raw(app, db, setup_dummy_data):
    sensor1, sensor2, report_sensor = setup_dummy_data

    reporter_config_raw = dict(
        tb_query_config=[dict(sensor=sensor1.id), dict(sensor=sensor2.id)],
        transformations=[
            dict(
                df_input="sensor_1",
                df_output="df_agg",
                method="add",
                args=["@sensor_2"],
            ),
            dict(method="resample_events", args=["2h"]),
        ],
        final_df_output="df_agg",
    )

    return reporter_config_raw
