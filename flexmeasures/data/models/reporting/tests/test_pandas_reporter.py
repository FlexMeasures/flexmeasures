from datetime import datetime

from pytz import utc

from flexmeasures.data.models.reporting.pandas_reporter import PandasReporter


def test_reporter(app, setup_dummy_data):
    s1, s2, reporter_sensor = setup_dummy_data

    reporter_config_raw = dict(
        beliefs_search_configs=[dict(sensor=s1.id), dict(sensor=s2.id)],
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
    assert str(report1.event_starts[0]) == "2023-04-10 00:00:00+00:00"
    assert (
        report1.sensor == reporter_sensor
    )  # check that the output sensor is effectively assigned.

    data_source_name = app.config.get("FLEXMEASURES_DEFAULT_DATASOURCE")
    data_source_type = "reporter"

    assert all(
        (source.name == data_source_name) and (source.type == data_source_type)
        for source in report1.sources
    )  # check data source is assigned

    # check that calling compute with different parameters changes the result
    report3 = reporter.compute(start=datetime(2023, 4, 10, 3, tzinfo=utc), end=end)
    assert len(report3) == 4
    assert str(report3.event_starts[0]) == "2023-04-10 02:00:00+00:00"


def test_reporter_repeated(setup_dummy_data):
    """check that calling compute doesn't change the result"""

    s1, s2, reporter_sensor = setup_dummy_data

    reporter_config_raw = dict(
        beliefs_search_configs=[
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

    assert all(report2.values == report1.values)
