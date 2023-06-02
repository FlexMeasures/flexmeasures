from datetime import datetime
from pytz import utc
import timely_beliefs as tb

from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.models.time_series import Sensor


def test_reporter_empty(setup_dummy_data):
    """check that calling compute with missing data returns an empty report"""

    class DummyReporter(Reporter):
        def __init__(self, sensor: Sensor, input_sensor: Sensor) -> None:
            reporter_config_raw = dict(
                beliefs_search_configs=[
                    dict(sensor=input_sensor.id, alias="input_sensor")
                ]
            )
            super().__init__(sensor, reporter_config_raw)

        def _compute(self, *args, **kwargs) -> tb.BeliefsDataFrame:
            return self.data["input_sensor"]

    s1, s2, reporter_sensor = setup_dummy_data

    reporter = DummyReporter(reporter_sensor, s1)

    # compute report on available data
    report = reporter.compute(
        datetime(2023, 4, 10, tzinfo=utc), datetime(2023, 4, 10, 10, tzinfo=utc)
    )

    assert not report.empty

    # compute report on dates with no data available
    report = reporter.compute(
        datetime(2021, 4, 10, tzinfo=utc), datetime(2021, 4, 10, 10, tzinfo=utc)
    )

    assert report.empty
