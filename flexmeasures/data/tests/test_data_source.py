from __future__ import annotations

import pytest

from flexmeasures.data.models.reporting import Reporter

from flexmeasures.data.models.data_sources import keep_latest_version, DataSource

from datetime import datetime, timedelta
from pytz import UTC

import numpy as np
import pandas as pd
import timely_beliefs as tb


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

    with pytest.raises((AttributeError, TypeError)):
        # Marshmallow 3.x
        #   AttributeError: 'str' object has no attribute 'isoformat'. Did you mean: 'format'?
        # Marshmallow 4.x
        #   TypeError: descriptor 'isoformat' for 'datetime.datetime' objects doesn't apply to a 'str' object
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
    s1 = DataSource(
        id=1, name="s1", model="model 1", type="forecaster", version="0.1.0"
    )
    s2 = DataSource(id=2, name="s1", model="model 1", type="forecaster")
    s3 = DataSource(id=3, name="s1", model="model 2", type="forecaster")
    s4 = DataSource(id=4, name="s1", model="model 2", type="scheduler")
    s5 = DataSource(id=5, name="s1", model="model 2", type="scheduler")

    def create_dummy_frame(sources: list[DataSource]) -> tb.BeliefsDataFrame:
        sensor = tb.Sensor("A")
        beliefs = [
            tb.TimedBelief(
                sensor=sensor,
                event_start=datetime(2023, 1, 1, tzinfo=UTC),
                belief_time=datetime(2023, 1, 1, tzinfo=UTC),
                event_value=1,
                source=s,
            )
            for s in sources
        ]
        bdf = tb.BeliefsDataFrame(beliefs)
        bdf["source.name"] = (
            bdf.index.get_level_values("source").map(lambda x: x.name).values
        )
        bdf["source.model"] = (
            bdf.index.get_level_values("source").map(lambda x: x.model).values
        )
        bdf["source.type"] = (
            bdf.index.get_level_values("source").map(lambda x: x.type).values
        )
        bdf["source.version"] = (
            bdf.index.get_level_values("source").map(lambda x: x.version).values
        )
        return bdf

    # the data source with no version is assumed to have version 0.0.0
    bdf = create_dummy_frame([s1, s2])
    np.testing.assert_array_equal(keep_latest_version(bdf).sources, [s1])

    # sources with different models are preserved
    bdf = create_dummy_frame([s1, s2, s3])
    np.testing.assert_array_equal(keep_latest_version(bdf).sources, [s1, s3])

    # two sources with the same model but different types
    # (highest ID first, not really intentional)
    bdf = create_dummy_frame([s3, s4])
    np.testing.assert_array_equal(keep_latest_version(bdf).sources, [s4, s3])

    # two sources with only different IDs (for instance, when they just differ by their data_generator_config)
    bdf = create_dummy_frame([s4, s5])
    np.testing.assert_array_equal(keep_latest_version(bdf).sources, [s5])
    # also check the reverse order
    bdf = bdf.sort_index(level="source", ascending=False, sort_remaining=False)
    np.testing.assert_array_equal(keep_latest_version(bdf).sources, [s5])

    # repeated source
    bdf = create_dummy_frame([s1, s1])
    np.testing.assert_array_equal(keep_latest_version(bdf).sources, [s1])


def test_keep_latest_version_preserves_probabilistic_splits():
    sensor = tb.Sensor("X", event_resolution=timedelta(hours=1))
    s1v1 = DataSource(name="s1", model="model 1", type="forecaster", version="0.1.0")
    s1v2 = DataSource(name="s1", model="model 1", type="forecaster", version="0.2.0")
    # Two probabilistic splits for the same event
    event_start = "2025-10-15T14:00:00+02"
    h = "PT1H"

    def create_bdf(probabilistic_values: list[tuple[float, float]], source: DataSource):
        return tb.BeliefsDataFrame(
            [
                tb.TimedBelief(
                    sensor=sensor,
                    source=source,
                    event_start=event_start,
                    belief_horizon=h,
                    cp=cp,
                    event_value=v,
                )
                for cp, v in probabilistic_values
            ]
        )

    bdf_1 = create_bdf([(0.3, 10.0), (0.7, 20.0)], s1v1)
    # We expect to keep *both* splits (or at least both until further resolution)
    kept = keep_latest_version(bdf_1, one_deterministic_belief_per_event=False)
    # Check that both cumulative probabilities remain
    probs = set(kept.index.get_level_values("cumulative_probability").tolist())
    assert probs == {0.3, 0.7}
    # Also check that two rows survived
    assert len(kept) == 2

    bdf_2 = create_bdf([(0.1, 5.0), (0.5, 16.0), (0.7, 20.2), (0.9, 20.2)], s1v2)
    bdf = pd.concat([bdf_1, bdf_2])
    kept = keep_latest_version(bdf, one_deterministic_belief_per_event=False)
    probs = set(kept.index.get_level_values("cumulative_probability").tolist())
    assert probs == {0.1, 0.5, 0.7, 0.9}  # no more 0.3
    assert len(kept) == 4
