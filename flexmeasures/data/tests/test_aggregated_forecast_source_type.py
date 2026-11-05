"""A sum of forecasts is a forecast, so a forecast of the sum must not be trained on it (see `Reporter.source_type`)."""

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
    """Two houses with forecasts, and two sensors for their net to be reported on (one per source type under test)."""
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
    db.session.add(forecaster)
    db.session.flush()
    db.session.add_all(
        TimedBelief(
            sensors[name],
            forecaster,
            event_start=START + timedelta(hours=hour),
            belief_horizon=timedelta(hours=24),
            event_value=5.0,
        )
        for hour in range(48)
        for name in ("house 1", "house 2")
    )
    db.session.commit()
    return sensors, forecaster


def _aggregate_forecasts(db, sensors, forecaster, output_sensor, config: dict):
    """Report the sum of both houses' forecasts on the output sensor, and save it."""
    result = AggregatorReporter(config=dict(method="sum", **config)).compute(
        input=[
            dict(sensor=sensors["house 1"], source=forecaster),
            dict(sensor=sensors["house 2"], source=forecaster),
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
    "config, output_sensor, source_type, in_training_data",
    [
        ({}, "net as reporter", "reporter", True),
        (
            {"output-source-type": "forecaster"},
            "net as forecaster",
            "forecaster",
            False,
        ),
    ],
)
def test_only_an_aggregated_forecast_of_forecaster_type_is_kept_out_of_training_data(
    db, community, config, output_sensor, source_type, in_training_data
):
    """An aggregated forecast is trained on, unless its source says that it is a forecast.

    The aggregate is a sum of forecasts, which a forecaster must not learn from as if it were what actually happened.
    A bare-sensor target excludes the forecaster sources, so only a report saved under a forecaster source is left out.
    """
    sensors, forecaster = community
    target = sensors[output_sensor]
    result = _aggregate_forecasts(db, sensors, forecaster, target, config)

    assert {source.type for source in result.lineage.sources} == {source_type}
    assert (source_type in _source_types_in_target_training_data(target)) is (
        in_training_data
    )
