import pytest

from flexmeasures.data.models.reporting.aggregator import AggregatorReporter
from flexmeasures.data.models.data_sources import DataSource
from datetime import datetime
from pytz import utc, timezone

import pandas as pd
from marshmallow import ValidationError


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
    In case of encountering more than one source per event, the first source defined in the sources
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

    # Naming the sources the other way round hands the overlapping event to the other source,
    # which is what "the first source defined in the sources array" means.
    reversed_result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, sources=[ds2, ds1])],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]
    assert (reversed_result[:12] == 1).all().event_value
    assert (reversed_result[12:] == -1).all().event_value

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
    # as there are events with different data sources in the report time period.
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

    # The exception to the above is when a new version of the same source recorded a value,
    # in which case the latest version takes precedence. This happened in the last hour of the day.
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24, 18, 0)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3)],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert (result[:5] == -1).all().event_value  # beliefs from the older version
    assert (result[5:] == 3).all().event_value  # belief from the latest version

    # If we exclude source type "A" (source 1 is of that type) we should get the same result.
    same_result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24, 18, 0)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, exclude_source_types=["A"])],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert (same_result == result).all().event_value

    # If we exclude source type "B" (both versions of source 2 are of that type) we should get an empty result
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24, 18, 0)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, exclude_source_types=["B"])],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert result.empty

    # If we set use_latest_version_per_event=False, we should get both versions of source 2,
    # and one_deterministic_belief_per_event=True kicks in to give back the most recent version
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24, 18, 0)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, use_latest_version_per_event=False)],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert len(result) == 6
    assert (result[:5] == -1).all().event_value  # beliefs from the older version
    assert (result[5:] == 3).all().event_value  # belief from the latest version


def test_an_input_cleans_the_readings_it_asks_for(setup_dummy_data, db):
    """An input entry may bound the readings it reads, the way a forecaster's regressors and a scheduler's references can.

    Sensor 1 records 1 and sensor 2 records -1, so their sum is 0.
    Holding the second at or above zero makes the same report add 1 and 0.
    """
    s1, s2, _, _, report_sensor, _ = setup_dummy_data
    source_1 = db.session.get(DataSource, 1)
    source_2 = db.session.get(DataSource, 2)

    def summed(second_input: dict):
        return AggregatorReporter(method="sum").compute(
            input=[dict(sensor=s1, source=source_1), second_input],
            output=[dict(sensor=report_sensor)],
            start=datetime(2023, 5, 10, tzinfo=utc),
            end=datetime(2023, 5, 11, tzinfo=utc),
        )[0]["data"]

    unbounded = summed(dict(sensor=s2, source=source_2))
    # Sensor 2 records no unit, so a bare number says what its own readings are bounded by.
    bounded = summed(dict(sensor=s2, source=source_2, lower=0))

    assert (unbounded == 0).all().event_value
    assert (bounded == 1).all().event_value


def test_an_input_snaps_the_readings_it_asks_for(setup_dummy_data, db):
    """Snapping runs before clipping here too, so a reading inside an interval is replaced by its target."""
    s1, _, _, _, report_sensor, _ = setup_dummy_data
    source_1 = db.session.get(DataSource, 1)

    result = AggregatorReporter(method="sum").compute(
        input=[
            dict(
                sensor=s1,
                source=source_1,
                snap={"1.5 kW": ["0.5 kW", "1.5 kW"]},
            )
        ],
        output=[dict(sensor=report_sensor)],
        start=datetime(2023, 5, 10, tzinfo=utc),
        end=datetime(2023, 5, 11, tzinfo=utc),
    )[0]["data"]

    # Sensor 1 records 1 kW, which the interval [0.5, 1.5) covers, so it reads as its target.
    assert (result == 1.5).all().event_value


def test_a_bound_an_input_sensor_cannot_take_is_refused(setup_dummy_data, db):
    """A bound is checked against the sensor it applies to while the report is being set up, not once its data is read."""
    _, s2, _, _, report_sensor, _ = setup_dummy_data
    source_2 = db.session.get(DataSource, 2)

    with pytest.raises(ValidationError) as refusal:
        AggregatorReporter(method="sum").compute(
            # Sensor 2 records no unit, so a bound in kW cannot be read in it.
            input=[dict(sensor=s2, source=source_2, lower="0 kW")],
            output=[dict(sensor=report_sensor)],
            start=datetime(2023, 5, 10, tzinfo=utc),
            end=datetime(2023, 5, 11, tzinfo=utc),
        )

    assert "lower" in str(refusal.value)
    assert "sensor 2" in str(refusal.value)
