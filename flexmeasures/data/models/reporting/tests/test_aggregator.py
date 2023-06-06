import pytest

from flexmeasures.data.models.reporting.aggregatator import AggregatorReporter

from datetime import datetime
from pytz import utc


@pytest.mark.parametrize(
    "aggregation_method, expected_value", [("SUM", 2), ("MEAN", 1)]
)
def test_aggregator(setup_dummy_data, aggregation_method, expected_value):
    """ """
    s1, s2, reporter_sensor = setup_dummy_data

    reporter_config_raw = dict(
        beliefs_search_configs=[
            dict(sensor=s1.id, source=1),
            dict(sensor=s2.id, source=2),
        ],  # TODO: make source compulsory
        method=aggregation_method,
    )

    agg_reporter = AggregatorReporter(
        reporter_sensor, reporter_config_raw=reporter_config_raw
    )

    result = agg_reporter.compute(
        start=datetime(2023, 5, 10, tzinfo=utc),
        end=datetime(2023, 5, 11, tzinfo=utc),
    )

    # check that we got a result for 24 hours
    assert len(result) == 24

    # check that the value is equal to expected_value
    assert (result == expected_value).all().event_value
