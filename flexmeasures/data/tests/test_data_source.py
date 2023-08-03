import pytest

from flexmeasures.data.models.reporting import Reporter

from datetime import datetime
from pytz import UTC


def test_get_reporter_from_source(
    db, app, aggregator_reporter_data_source, add_nearby_weather_sensors
):

    reporter = aggregator_reporter_data_source.data_generator

    reporter_sensor = add_nearby_weather_sensors.get("farther_temperature")

    assert isinstance(reporter, Reporter)
    assert reporter.__class__.__name__ == "TestReporter"

    res = reporter.compute(
        sensor=reporter_sensor,
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )

    assert res.lineage.sources[0] == reporter.data_source

    with pytest.raises(AttributeError):
        reporter.compute(
            sensor=reporter_sensor,
            start=datetime(2023, 1, 1, tzinfo=UTC),
            end="not a date",
        )


def test_data_source(db, app, aggregator_reporter_data_source):
    TestTeporter = app.data_generators["reporter"].get("TestReporter")

    ds1 = TestTeporter(config={"a": "1"})

    db.session.add(ds1.data_source)
    db.session.commit()

    ds2 = TestTeporter(config={"a": "1"})

    assert ds1.data_source == ds2.data_source
    assert ds1.data_source.attributes.get("data_generator").get(
        "config"
    ) == ds2.data_source.attributes.get("data_generator").get("config")

    ds3 = TestTeporter(config={"a": "2"})

    assert ds3.data_source != ds2.data_source
    assert ds3.data_source.attributes.get("data_generator").get(
        "config"
    ) != ds2.data_source.attributes.get("data_generator").get("config")

    ds4 = ds3.data_source.data_generator

    assert ds4._config == ds3._config


def test_data_generator_save_config(
    db, app, aggregator_reporter_data_source, add_nearby_weather_sensors
):
    TestTeporter = app.data_generators["reporter"].get("TestReporter")

    reporter_sensor = add_nearby_weather_sensors.get("farther_temperature")

    reporter = TestTeporter(config={"a": "1"})

    res = reporter.compute(
        sensor=reporter_sensor,
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )

    assert res.lineage.sources[0].attributes.get("data_generator").get("config") == {
        "a": "1"
    }

    reporter = TestTeporter(config={"a": "1"}, save_config=False)

    res = reporter.compute(
        sensor=reporter_sensor,
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )

    assert len(res.lineage.sources[0].attributes) == 0
