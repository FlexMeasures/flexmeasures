import pytest

from flexmeasures.data.models.reporting.aggregator import AggregatorReporter
from flexmeasures.data.models.data_sources import DataSource
from datetime import datetime
from pytz import utc, timezone

import pandas as pd


@pytest.mark.parametrize(
    "aggregation_method, expected_value",
    [
        ("sum", 0),
        ("mean", 0),
        ("var", 2),
        ("std", 2**0.5),
        ("max", 1),
        ("min", -1),
        ("prod", -1),
        ("median", 0),
    ],
)
def test_aggregator(setup_dummy_data, aggregation_method, expected_value, db):
    """
    This test computes the aggregation of two sensors containing 24 entries
    with value 1 and -1, respectively, for sensors 1 and 2.

    Test cases:
        1) sum: 0 = 1 + (-1)
        2) mean: 0 = ((1) + (-1))/2
        3) var: 2 = (1)^2 + (-1)^2
        4) std: sqrt(2) = sqrt((1)^2 + (-1)^2)
        5) max: 1 = max(1, -1)
        6) min: -1 = min(1, -1)
        7) prod: -1 = (1) * (-1)
        8) median: even number of elements, mean of the most central elements, 0 = ((1) + (-1))/2
    """
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

    agg_reporter = AggregatorReporter(method=aggregation_method)

    source_1 = db.session.get(DataSource, 1)
    source_2 = db.session.get(DataSource, 2)

    result = agg_reporter.compute(
        input=[dict(sensor=s1, source=source_1), dict(sensor=s2, source=source_2)],
        output=[dict(sensor=report_sensor)],
        start=datetime(2023, 5, 10, tzinfo=utc),
        end=datetime(2023, 5, 11, tzinfo=utc),
    )[0]["data"]

    # check that we got a result for 24 hours
    assert len(result) == 24

    # check that the value is equal to expected_value
    assert (result == expected_value).all().event_value


@pytest.mark.parametrize(
    "weight_1, weight_2, expected_result",
    [(1, 1, 0), (1, -1, 2), (2, 0, 2), (0, 2, -2)],
)
def test_aggregator_reporter_weights(
    setup_dummy_data, weight_1, weight_2, expected_result, db
):
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

    reporter_config = dict(method="sum", weights={"s1": weight_1, "sensor_2": weight_2})

    source_1 = db.session.get(DataSource, 1)
    source_2 = db.session.get(DataSource, 2)

    agg_reporter = AggregatorReporter(config=reporter_config)

    result = agg_reporter.compute(
        input=[
            dict(name="s1", sensor=s1, source=source_1),
            dict(sensor=s2, source=source_2),
        ],
        output=[dict(sensor=report_sensor)],
        start=datetime(2023, 5, 10, tzinfo=utc),
        end=datetime(2023, 5, 11, tzinfo=utc),
    )[0]["data"]

    # check that we got a result for 24 hours
    assert len(result) == 24

    # check that the value is equal to expected_value
    assert (result == expected_result).all().event_value


def test_dst_transition(setup_dummy_data, db):
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

    agg_reporter = AggregatorReporter()

    tz = timezone("Europe/Amsterdam")

    # transition from winter (CET) to summer (CEST)
    result = agg_reporter.compute(
        input=[dict(sensor=s3, source=db.session.get(DataSource, 1))],
        output=[dict(sensor=report_sensor)],
        start=tz.localize(datetime(2023, 3, 26)),
        end=tz.localize(datetime(2023, 3, 27)),
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert len(result) == 23

    # transition from summer (CEST) to winter (CET)
    result = agg_reporter.compute(
        input=[dict(sensor=s3, source=db.session.get(DataSource, 1))],
        output=[dict(sensor=report_sensor)],
        start=tz.localize(datetime(2023, 10, 29)),
        end=tz.localize(datetime(2023, 10, 30)),
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert len(result) == 25


def test_resampling(setup_dummy_data, db):
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

    agg_reporter = AggregatorReporter()

    tz = timezone("Europe/Amsterdam")

    # transition from winter (CET) to summer (CEST)
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 3, 27)),
        end=tz.localize(datetime(2023, 3, 28)),
        input=[dict(sensor=s3, source=db.session.get(DataSource, 1))],
        output=[dict(sensor=daily_report_sensor, source=db.session.get(DataSource, 1))],
        belief_time=tz.localize(datetime(2023, 12, 1)),
        resolution=pd.Timedelta("1D"),
    )[0]["data"]

    assert result.event_starts[0] == pd.Timestamp(
        year=2023, month=3, day=27, tz="Europe/Amsterdam"
    )

    # transition from summer (CEST) to winter (CET)
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 10, 29)),
        end=tz.localize(datetime(2023, 10, 30)),
        input=[dict(sensor=s3, source=db.session.get(DataSource, 1))],
        output=[dict(sensor=daily_report_sensor, source=db.session.get(DataSource, 1))],
        belief_time=tz.localize(datetime(2023, 12, 1)),
        resolution=pd.Timedelta("1D"),
    )[0]["data"]

    assert result.event_starts[0] == pd.Timestamp(
        year=2023, month=10, day=29, tz="Europe/Amsterdam"
    )


def test_source_transition(setup_dummy_data, db):
    """The first 13 hours of the time window "belong" to Source 1 and are filled with 1.0.
    From 12:00 to 24:00, there are events belonging to Source 2 with value -1.

    We expect the reporter to use only the values defined in the `sources` array in the `input` field.
    In case of encountering more that one source per event, the first source defined in the sources
    array is prioritized.

    """
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

    agg_reporter = AggregatorReporter()

    tz = timezone("UTC")

    ds1 = db.session.get(DataSource, 1)
    ds2 = db.session.get(DataSource, 2)

    # considering DataSource 1 and 2
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, sources=[ds1, ds2])],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert len(result) == 24
    assert (
        (result[:13] == 1).all().event_value
    )  # the data from the first source is used
    assert (result[13:] == -1).all().event_value

    # only considering DataSource 1
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, sources=[ds1])],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert len(result) == 13
    assert (result == 1).all().event_value

    # only considering DataSource 2
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, sources=[ds2])],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert len(result) == 12
    assert (result == -1).all().event_value

    # if no source is passed, the reporter should raise a ValueError
    # as there are events with different time sources in the report time period.
    # This is important, for instance, for sensors containing power and scheduled values
    # where we could get beliefs from both sources.
    with pytest.raises(ValueError):
        result = agg_reporter.compute(
            start=tz.localize(datetime(2023, 4, 24)),
            end=tz.localize(datetime(2023, 4, 25)),
            input=[dict(sensor=s3)],
            output=[dict(sensor=report_sensor)],
            belief_time=tz.localize(datetime(2023, 12, 1)),
        )[0]["data"]
