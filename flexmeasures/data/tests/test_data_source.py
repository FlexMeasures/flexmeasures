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


def test_data_source(db, app, test_reporter):
    # get TestReporter class from the data_generators registry
    TestReporter = app.data_generators["reporter"].get("TestReporter")

    reporter1 = TestReporter(config={"a": "1"})

    db.session.add(reporter1.data_source)

    reporter2 = TestReporter(config={"a": "1"})

    # reporter1 and reporter2 have the same data_source because they share the same config
    assert reporter1.data_source == reporter2.data_source
    assert reporter1.data_source.attributes.get("data_generator").get(
        "config"
    ) == reporter2.data_source.attributes.get("data_generator").get("config")

    reporter3 = TestReporter(config={"a": "2"})

    # reporter3 and reporter2 have different data sources because they have different config values
    assert reporter3.data_source != reporter2.data_source
    assert reporter3.data_source.attributes.get("data_generator").get(
        "config"
    ) != reporter2.data_source.attributes.get("data_generator").get("config")

    # recreate reporter3 from its data source
    reporter4 = reporter3.data_source.data_generator

    # check that reporter3 and reporter4 share the same config values
    assert reporter4._config == reporter3._config


def test_data_generator_save_config(db, app, test_reporter, add_nearby_weather_sensors):
    TestReporter = app.data_generators["reporter"].get("TestReporter")

    reporter_sensor = add_nearby_weather_sensors.get("farther_temperature")

    reporter = TestReporter(config={"a": "1"})

    res = reporter.compute(
        sensor=reporter_sensor,
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )

    assert res.lineage.sources[0].attributes.get("data_generator").get("config") == {
        "a": "1"
    }

    reporter = TestReporter(config={"a": "1"}, save_config=False)

    res = reporter.compute(
        sensor=reporter_sensor,
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )

    assert len(res.lineage.sources[0].attributes) == 0
