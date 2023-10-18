from datetime import datetime

from pytz import utc

from flexmeasures.data.models.reporting.pandas_reporter import PandasReporter


def test_reporter(app, setup_dummy_data):
    s1, s2, s3, report_sensor, daily_report_sensor = setup_dummy_data

    reporter_config = dict(
        required_input=[{"name": "sensor_1"}, {"name": "sensor_2"}],
        required_output=[{"name": "df_merge"}],
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
    )

    reporter = PandasReporter(config=reporter_config)

    start = datetime(2023, 4, 10, tzinfo=utc)
    end = datetime(2023, 4, 10, 10, tzinfo=utc)
    input = [dict(name="sensor_1", sensor=s1), dict(name="sensor_2", sensor=s2)]
    output = [dict(name="df_merge", sensor=report_sensor)]

    report1 = reporter.compute(start=start, end=end, input=input, output=output)
    result = report1[0]["data"]

    assert len(result) == 5
    assert str(result.event_starts[0]) == "2023-04-10 00:00:00+00:00"
    assert (
        result.sensor == report_sensor
    )  # check that the output sensor is effectively assigned.

    data_source_name = app.config.get("FLEXMEASURES_DEFAULT_DATASOURCE")
    data_source_type = "reporter"

    assert all(
        (source.name == data_source_name) and (source.type == data_source_type)
        for source in result.sources
    )  # check data source is assigned

    # check that calling compute with different parameters changes the result
    report2 = reporter.compute(
        start=datetime(2023, 4, 10, 3, tzinfo=utc), end=end, input=input, output=output
    )
    result2 = report2[0]["data"]

    assert len(result2) == 4
    assert str(result2.event_starts[0]) == "2023-04-10 02:00:00+00:00"


def test_reporter_repeated(setup_dummy_data):
    """check that calling compute doesn't change the result"""

    s1, s2, s3, report_sensor, daily_report_sensor = setup_dummy_data

    reporter_config = dict(
        required_input=[{"name": "sensor_1"}, {"name": "sensor_2"}],
        required_output=[{"name": "df_merge"}],
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
    )

    parameters = dict(
        start="2023-04-10T00:00:00 00:00",
        end="2023-04-10T10:00:00 00:00",
        input=[
            dict(name="sensor_1", sensor=s1.id),
            dict(name="sensor_2", sensor=s2.id),
        ],
        output=[dict(name="df_merge", sensor=report_sensor.id)],
    )

    reporter = PandasReporter(config=reporter_config)

    report1 = reporter.compute(parameters=parameters)
    report2 = reporter.compute(parameters=parameters)

    assert all(report2[0]["data"].values == report1[0]["data"].values)


def test_reporter_empty(setup_dummy_data):
    """check that calling compute with missing data returns an empty report"""
    s1, s2, s3, report_sensor, daily_report_sensor = setup_dummy_data

    config = dict(
        required_input=[{"name": "sensor_1"}],
        required_output=[{"name": "sensor_1"}],
        transformations=[],
    )

    reporter = PandasReporter(config=config)

    # compute report on available data
    report = reporter.compute(
        start=datetime(2023, 4, 10, tzinfo=utc),
        end=datetime(2023, 4, 10, 10, tzinfo=utc),
        input=[dict(name="sensor_1", sensor=s1)],
        output=[dict(name="sensor_1", sensor=report_sensor)],
    )

    assert not report[0]["data"].empty

    # compute report on dates with no data available
    report = reporter.compute(
        sensor=report_sensor,
        start=datetime(2021, 4, 10, tzinfo=utc),
        end=datetime(2021, 4, 10, 10, tzinfo=utc),
        input=[dict(name="sensor_1", sensor=s1)],
        output=[dict(name="sensor_1", sensor=report_sensor)],
    )

    assert report[0]["data"].empty
