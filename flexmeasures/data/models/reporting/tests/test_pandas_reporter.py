from datetime import datetime

from pytz import utc

from flexmeasures.data.models.reporting.pandas_reporter import PandasReporter


def test_reporter(app, setup_dummy_data):
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

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

    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

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
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

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


def test_pandas_reporter_unit_conversion(app, setup_dummy_data):
    """
    Check that the unit conversion feature can handle the following cases:
        - kW -> kW
        - kW -> MW
        - kW -> MWh
        - kW -> W -> kW
    """
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

    reporter_config = dict(
        required_input=[
            {"name": "sensor_4"},
            {"name": "sensor_4_kw"},
            {"name": "sensor_4_mw", "unit": "MW"},
            {"name": "sensor_4_mwh", "unit": "MWh"},
        ],
        required_output=[
            {"name": "sensor_4_kw"},
            {"name": "sensor_4_mw"},
            {"name": "sensor_4_mwh"},
            # Assume that the internal operations that produce sensor_4_output_w have "W"
            {"name": "sensor_4_output_w", "unit": "W"},
        ],
        transformations=[
            {"df_input": "sensor_4", "method": "copy", "df_output": "sensor_4_output_w"}
        ],
    )

    reporter = PandasReporter(config=reporter_config)

    start = datetime(2023, 1, 1, tzinfo=utc)
    end = datetime(2023, 1, 2, tzinfo=utc)
    input = [
        dict(name="sensor_4", sensor=s4),
        dict(name="sensor_4_kw", sensor=s4),
        dict(name="sensor_4_mw", sensor=s4),
        dict(name="sensor_4_mwh", sensor=s4),
    ]
    output = [
        dict(name="sensor_4_kw", sensor=s4),
        dict(name="sensor_4_mw", sensor=s4),
        dict(name="sensor_4_mwh", sensor=s4),
        dict(name="sensor_4_output_w", sensor=s4),
    ]

    report = reporter.compute(start=start, end=end, input=input, output=output)
    result_kw = report[0]["data"]
    result_mw = report[1]["data"]
    result_mwh = report[2]["data"]
    result_output_w = report[3]["data"]

    # MW = kW / 1000
    assert (result_mw.event_value.values == result_kw.event_value.values / 1000).all()

    # MWh = MW * 0.25 (resolution = 15 min)
    assert (result_mwh.event_value.values == result_mw.event_value.values * 0.25).all()

    # Input is in kW; the operations transform the data to produce values in W and it transforms the values to the output sensor unit (kW).
    # In summary, Input = 1 kW -(copy the values)-> 1 W -> 0.001 kW
    assert (
        result_output_w.event_value.values == result_kw.event_value.values * 0.001
    ).all()
