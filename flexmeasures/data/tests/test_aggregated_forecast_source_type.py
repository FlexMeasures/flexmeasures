"""A sum of forecasts is a forecast, so a forecast of the sum must not be trained on it (see `AggregatorReporter.source_type`)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pytz import utc

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.forecasting.pipelines.base import BasePipeline
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.reporting.aggregator import AggregatorReporter
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.utils import save_to_db

START = datetime(2026, 10, 1, tzinfo=utc)
END = START + timedelta(hours=48)


@pytest.fixture(scope="module")
def community(db, setup_accounts, setup_generic_asset_types):
    """Two houses with measurements and forecasts, and two sensors for their net to be reported on (one per source type under test)."""
    asset = GenericAsset(
        name="forecast training community",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
    )
    db.session.add(asset)
    sensors = {
        name: Sensor(
            name, generic_asset=asset, event_resolution=timedelta(hours=1), unit="kW"
        )
        for name in ("house 1", "house 2", "net as reporter", "net as forecaster")
    }
    db.session.add_all(sensors.values())
    forecaster = DataSource(
        "training test forecaster", type="forecaster", model="TrainPredictPipeline"
    )
    meter = DataSource("training test meter", type="script")
    db.session.add_all([forecaster, meter])
    db.session.flush()
    db.session.add_all(
        TimedBelief(
            sensors[name],
            source,
            event_start=START + timedelta(hours=hour),
            belief_horizon=horizon,
            event_value=5.0,
        )
        for hour in range(48)
        for name in ("house 1", "house 2")
        for source, horizon in (
            (forecaster, timedelta(hours=24)),
            (meter, timedelta(0)),
        )
    )
    db.session.commit()
    return sensors, {"forecaster": forecaster, "meter": meter}


def _aggregate(db, sensors, source, output_sensor):
    """Report the sum of both houses' data from the given source on the output sensor, and save it."""
    result = AggregatorReporter(config=dict(method="sum")).compute(
        input=[
            dict(sensor=sensors["house 1"], source=source),
            dict(sensor=sensors["house 2"], source=source),
        ],
        output=[dict(sensor=output_sensor)],
        start=START,
        end=END,
        belief_horizon=timedelta(hours=24),
    )[0]["data"]
    save_to_db(result)
    db.session.commit()
    return result


def _source_types_in_target_training_data(target: Sensor) -> set[str]:
    """The types of the sources whose beliefs a forecast of this (bare sensor) target would train on."""
    pipeline = BasePipeline(
        target_sensor=target,
        future_regressors=[],
        past_regressors=[],
        n_steps_to_predict=24,
        max_forecast_horizon=24,
        forecast_frequency=1,
        event_starts_after=START,
        event_ends_before=END,
    )
    entries, beliefs = pipeline._search_beliefs_per_entry([pipeline.target], [target])
    frame = beliefs[entries[0][2]]
    return {source.type for source in frame.index.get_level_values("source")}


@pytest.mark.parametrize(
    "input_source, output_sensor, source_type, in_training_data",
    [
        ("meter", "net as reporter", "reporter", True),
        ("forecaster", "net as forecaster", "forecaster", False),
    ],
)
def test_only_an_aggregate_of_forecasts_is_kept_out_of_training_data(
    db, community, input_source, output_sensor, source_type, in_training_data
):
    """An aggregate of measurements is trained on, while an aggregate of forecasts is a forecast, which is not.

    A forecaster must not learn from a sum of forecasts as if it were what actually happened.
    A bare-sensor target excludes the forecaster sources, and the aggregate takes its type from its inputs, so a sum of forecasts is left out.
    """
    sensors, sources = community
    target = sensors[output_sensor]
    result = _aggregate(db, sensors, sources[input_source], target)

    assert {source.type for source in result.lineage.sources} == {source_type}
    assert (source_type in _source_types_in_target_training_data(target)) is (
        in_training_data
    )
