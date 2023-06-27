import pytest

from flexmeasures.data.models.reporting import Reporter

from datetime import datetime
from pytz import UTC


def test_get_reporter_from_source(
    db, app, aggregator_reporter_data_source, add_nearby_weather_sensors
):
    reporter = aggregator_reporter_data_source.data_generator

    assert isinstance(reporter, Reporter)
    assert reporter.__class__.__name__ == "TestReporter"

    print(aggregator_reporter_data_source.data_generator)

    res = reporter.compute(
        start=datetime(2023, 1, 1, tzinfo=UTC), end=datetime(2023, 1, 2, tzinfo=UTC)
    )

    assert res.lineage.sources[0] == reporter.data_source

    with pytest.raises(AttributeError):
        reporter.compute(start=datetime(2023, 1, 1, tzinfo=UTC), end="not a date")


def test_creation_of_new_data_source(
    db, app, aggregator_reporter_data_source, add_nearby_weather_sensors
):
    sensor1 = add_nearby_weather_sensors.get("temperature")
    sensor2 = add_nearby_weather_sensors.get("farther_temperature")

    TestReporter = app.data_generators["TestReporter"]

    ds1 = TestReporter(config={"sensor": sensor1.id})

    db.session.add(ds1.data_source)
    db.session.commit()

    ds2 = TestReporter(sensor=sensor1)

    assert ds1.data_source == ds2.data_source
    assert ds1.data_source.attributes.get("config") == ds2.data_source.attributes.get(
        "config"
    )

    ds3 = TestReporter(config={"sensor": sensor2.id})

    assert ds3.data_source != ds2.data_source
    assert ds3.data_source.attributes.get("config") != ds2.data_source.attributes.get(
        "config"
    )
