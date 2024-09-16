import pytest

from flexmeasures.data.models.reporting import Reporter

from flexmeasures.data.models.data_sources import keep_latest_version, DataSource

from datetime import datetime
from pytz import UTC


def test_get_reporter_from_source(db, app, test_reporter, add_nearby_weather_sensors):

    reporter = test_reporter.data_generator

    reporter_sensor = add_nearby_weather_sensors.get("farther_temperature")

    assert isinstance(reporter, Reporter)
    assert reporter.__class__.__name__ == "TestReporter"

    res = reporter.compute(
        input=[{"sensor": reporter_sensor}],
        output=[{"sensor": reporter_sensor}],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )[0]["data"]

    assert res.lineage.sources[0] == reporter.data_source

    with pytest.raises(AttributeError):
        reporter.compute(
            input=[{"sensor": reporter_sensor}],
            output=[{"sensor": reporter_sensor}],
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
        input=[{"sensor": reporter_sensor}],
        output=[{"sensor": reporter_sensor}],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )[0]["data"]

    assert res.lineage.sources[0].attributes.get("data_generator").get("config") == {
        "a": "1"
    }

    reporter = TestReporter(config={"a": "1"}, save_config=False)

    res = reporter.compute(
        input=[{"sensor": reporter_sensor}],
        output=[{"sensor": reporter_sensor}],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )[0]["data"]

    # check that the data_generator is not saving the config in the data_source attributes
    assert res.lineage.sources[0].attributes.get("data_generator") == dict()


def test_data_generator_save_parameters(
    db, app, test_reporter, add_nearby_weather_sensors
):
    TestReporter = app.data_generators["reporter"].get("TestReporter")

    reporter_sensor = add_nearby_weather_sensors.get("farther_temperature")

    reporter = TestReporter(config={"a": "1"}, save_parameters=True)

    parameters = {
        "input": [{"sensor": reporter_sensor.id}],
        "output": [{"sensor": reporter_sensor.id}],
        "start": "2023-01-01T00:00:00+00:00",
        "end": "2023-01-02T00:00:00+00:00",
        "b": "test",
    }

    parameters_without_start_end = {
        "input": [{"sensor": reporter_sensor.id}],
        "output": [{"sensor": reporter_sensor.id}],
        "b": "test",
    }

    res = reporter.compute(parameters=parameters)[0]["data"]

    assert res.lineage.sources[0].attributes.get("data_generator").get("config") == {
        "a": "1"
    }

    assert (
        res.lineage.sources[0].attributes.get("data_generator").get("parameters")
        == parameters_without_start_end
    )

    dg2 = reporter.data_source.data_generator

    parameters_2 = {
        "start": "2023-01-01T10:00:00+00:00",
        "end": "2023-01-02T00:00:00+00:00",
        "b": "test2",
    }

    res = dg2.compute(parameters=parameters_2)[0]["data"]

    # check that compute gets data stored in the DB (i.e. `input`/`output`) and updated data
    # from the method call (e.g. field `b``)
    assert dg2._parameters["b"] == parameters_2["b"]
    assert dg2._parameters["start"].isoformat() == parameters_2["start"]


def test_keep_last_version():
    s1 = DataSource(name="s1", model="model 1", type="forecaster", version="0.1.0")
    s2 = DataSource(name="s1", model="model 1", type="forecaster")
    s3 = DataSource(name="s1", model="model 2", type="forecaster")
    s4 = DataSource(name="s1", model="model 2", type="scheduler")

    # the data source with no version is assumed to have version 0.0.0
    assert keep_latest_version([s1, s2]) == [s1]

    # sources with different models are preserved
    assert keep_latest_version([s1, s2, s3]) == [s1, s3]

    # two sources with the same model but different types
    assert keep_latest_version([s3, s4]) == [s3, s4]

    # repeated source
    assert keep_latest_version([s1, s1]) == [s1]
