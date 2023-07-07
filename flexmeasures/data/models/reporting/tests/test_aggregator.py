import pytest

from flexmeasures.data.models.reporting.aggregator import AggregatorReporter

from datetime import datetime
from pytz import utc, timezone


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
def test_aggregator(setup_dummy_data, aggregation_method, expected_value):
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
    s1, s2, reporter_sensor = setup_dummy_data

    reporter_config = dict(
        data=[
            dict(sensor=s1.id, source=1),
            dict(sensor=s2.id, source=2),
        ],
        method=aggregation_method,
    )

    agg_reporter = AggregatorReporter(config=reporter_config)

    result = agg_reporter.compute(
        sensor=reporter_sensor,
        start=datetime(2023, 5, 10, tzinfo=utc),
        end=datetime(2023, 5, 11, tzinfo=utc),
    )

    # check that we got a result for 24 hours
    assert len(result) == 24

    # check that the value is equal to expected_value
    assert (result == expected_value).all().event_value


def test_dst_transition(setup_dummy_data):
    s1, _, reporter_sensor = setup_dummy_data

    reporter_config = dict(
        data=[
            dict(sensor=s1.id, source=1),
        ],
    )

    agg_reporter = AggregatorReporter(config=reporter_config)

    tz = timezone("Europe/Amsterdam")

    # transition from winter (CET) to summer (CEST)
    result = agg_reporter.compute(
        sensor=reporter_sensor,
        start=tz.localize(datetime(2023, 3, 26)),
        end=tz.localize(datetime(2023, 3, 27)),
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )

    assert len(result) == 23

    # transition from summer (CEST) to winter (CET)
    result = agg_reporter.compute(
        sensor=reporter_sensor,
        start=tz.localize(datetime(2023, 10, 29)),
        end=tz.localize(datetime(2023, 10, 30)),
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )

    assert len(result) == 25
