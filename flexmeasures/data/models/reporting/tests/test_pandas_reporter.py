from datetime import datetime

from pytz import utc

from flexmeasures.data.models.reporting.pandas_reporter import PandasReporter


def test_reporter(app, setup_dummy_data):
    s1, s2, reporter_sensor = setup_dummy_data

    reporter_config = dict(
        input_variables=["sensor_1", "sensor_2"],
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

    reporter = PandasReporter(reporter_sensor, reporter_config=reporter_config)

    start = datetime(2023, 4, 10, tzinfo=utc)
    end = datetime(2023, 4, 10, 10, tzinfo=utc)
    input_sensors = dict(sensor_1=dict(sensor=s1), sensor_2=dict(sensor=s2))

    report1 = reporter.compute(start=start, end=end, input_sensors=input_sensors)

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
    report2 = reporter.compute(
        start=datetime(2023, 4, 10, 3, tzinfo=utc), end=end, input_sensors=input_sensors
    )
    assert len(report2) == 4
    assert str(report2.event_starts[0]) == "2023-04-10 02:00:00+00:00"


def test_reporter_repeated(setup_dummy_data):
    """check that calling compute doesn't change the result"""

    s1, s2, reporter_sensor = setup_dummy_data

    reporter_config = dict(
        input_variables=["sensor_1", "sensor_2"],
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

    report_config = dict(
        start="2023-04-10T00:00:00 00:00",
        end="2023-04-10T10:00:00 00:00",
        input_sensors=dict(
            sensor_1=dict(sensor=s1.id),
            sensor_2=dict(sensor=s2.id),
        ),
    )

    reporter = PandasReporter(reporter_sensor, reporter_config=reporter_config)

    report1 = reporter.compute(report_config=report_config)
    report2 = reporter.compute(report_config=report_config)

    assert all(report2.values == report1.values)


def test_reporter_empty(setup_dummy_data):
    """check that calling compute with missing data returns an empty report"""
    s1, s2, reporter_sensor = setup_dummy_data

    reporter_config = dict(
        input_variables=["sensor_1"],
        transformations=[],
        final_df_output="sensor_1",
    )

    reporter = PandasReporter(reporter_sensor, reporter_config=reporter_config)

    # compute report on available data
    report = reporter.compute(
        start=datetime(2023, 4, 10, tzinfo=utc),
        end=datetime(2023, 4, 10, 10, tzinfo=utc),
        input_sensors=dict(sensor_1=dict(sensor=s1)),
    )

    assert not report.empty

    # compute report on dates with no data available
    report = reporter.compute(
        start=datetime(2021, 4, 10, tzinfo=utc),
        end=datetime(2021, 4, 10, 10, tzinfo=utc),
        input_sensors=dict(sensor_1=dict(sensor=s1)),
    )

    assert report.empty
