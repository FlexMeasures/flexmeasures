from datetime import timedelta

import pandas as pd
import pytest
from sqlalchemy import func, inspect, select
from timely_beliefs import BeliefsDataFrame

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.forecasting.pipelines import (
    PredictPipeline,
    TrainPipeline,
    TrainPredictPipeline,
)
from flexmeasures.data.models.time_series import TimedBelief


@pytest.fixture
def forecast_setup(setup_fresh_test_forecast_data, monkeypatch, tmp_path):
    """Keep source attribution and persistence real while replacing model fitting."""
    sensor = setup_fresh_test_forecast_data["solar-sensor"]
    monkeypatch.setattr(TrainPipeline, "run", lambda self, **kwargs: None)
    monkeypatch.setattr(PredictPipeline, "load_data_all_beliefs", lambda self: None)
    monkeypatch.setattr(
        PredictPipeline,
        "split_data_all_beliefs",
        lambda self, *args, **kwargs: ([], [], [], []),
    )
    monkeypatch.setattr(PredictPipeline, "load_model", lambda self: None)

    def predictions(self, *args, **kwargs):
        viewpoint = pd.Timestamp(self.predict_start).tz_convert("UTC").tz_localize(None)
        return pd.DataFrame(
            {"1h": [12.5]},
            index=pd.MultiIndex.from_tuples(
                [(viewpoint - sensor.event_resolution, viewpoint)],
                names=["event_start", "belief_time"],
            ),
        )

    monkeypatch.setattr(
        PredictPipeline, "make_multi_fixed_viewpoint_predictions", predictions
    )
    parameters = {
        "sensor": sensor.id,
        "start": "2025-01-08T00:00:00+00:00",
        "end": "2025-01-08T02:00:00+00:00",
        "max-forecast-horizon": "PT1H",
        "forecast-frequency": "PT1H",
        "model-save-dir": str(tmp_path / "models"),
        "output-path": None,
    }
    return sensor, parameters


def _pipeline():
    return TrainPredictPipeline(
        config={
            "train-start": "2025-01-01T00:00:00+00:00",
            "retrain-frequency": "PT1H",
        }
    )


def _row_counts(db):
    return tuple(
        db.session.scalar(select(func.count()).select_from(model))
        for model in (DataSource, TimedBelief)
    )


@pytest.mark.parametrize("empty", [False, True])
def test_forecast_dry_run_leaves_no_pending_database_writes(
    fresh_db, forecast_setup, monkeypatch, empty
):
    """Committing after a dry run creates neither forecast sources nor beliefs."""
    sensor, parameters = forecast_setup
    if empty:
        monkeypatch.setattr(
            PredictPipeline,
            "compute",
            lambda self: BeliefsDataFrame(sensor=self.sensor_to_save),
        )
    before = _row_counts(fresh_db)

    results = _pipeline().compute(parameters={**parameters, "dry-run": True})
    fresh_db.session.commit()

    assert len(results) == 2
    assert _row_counts(fresh_db) == before
    for result in results:
        assert result["sensor"] == sensor
        assert result["data"].sensor == sensor
        assert result["data"]["event_value"].tolist() == ([] if empty else [12.5])
        if not empty:
            assert inspect(result["data"].sources[0]).transient


def test_prediction_compute_does_not_persist_or_export(
    fresh_db, forecast_setup, tmp_path
):
    """Computing returns attributed predictions without saving a source or a CSV."""
    sensor, _ = forecast_setup
    source = DataSource(name="pure-prediction", type="forecaster")
    output_path = tmp_path / "predictions.csv"
    pipeline = PredictPipeline(
        future_regressors=[],
        past_regressors=[],
        target_sensor=sensor,
        sensor_to_save=sensor,
        model_path=str(tmp_path / "model.pkl"),
        output_path=str(output_path),
        n_steps_to_predict=1,
        max_forecast_horizon=1,
        predict_start=pd.Timestamp("2025-01-08T00:00:00+00:00"),
        predict_end=pd.Timestamp("2025-01-08T01:00:00+00:00"),
        data_source=source,
    )
    before = _row_counts(fresh_db)

    result = pipeline.compute()
    fresh_db.session.commit()

    assert result["event_value"].tolist() == [12.5]
    assert result.sources == [source]
    assert inspect(source).transient
    assert _row_counts(fresh_db) == before
    assert not output_path.exists()


def test_forecast_commits_completed_cycles_before_a_later_failure(
    fresh_db, forecast_setup, monkeypatch
):
    """A rollback after a later training failure preserves an earlier forecast."""
    sensor, parameters = forecast_setup
    sensor_id = sensor.id
    before_sources, before_beliefs = _row_counts(fresh_db)

    def train(self, counter):
        if counter == 2:
            raise RuntimeError("second cycle failed")

    monkeypatch.setattr(TrainPipeline, "run", train)
    with pytest.raises(RuntimeError, match="second cycle failed"):
        _pipeline().compute(parameters=parameters)
    fresh_db.session.rollback()

    assert _row_counts(fresh_db) == (before_sources + 1, before_beliefs + 1)
    belief = fresh_db.session.execute(
        select(TimedBelief)
        .join(DataSource)
        .filter(TimedBelief.sensor_id == sensor_id, DataSource.type == "forecaster")
    ).scalar_one()
    assert belief.event_value == 12.5
    assert belief.event_start == pd.Timestamp(parameters["start"])


def test_forecast_reuses_persisted_source_across_cycles_and_runs(
    fresh_db, forecast_setup
):
    """Equivalent pipeline runs attribute every saved cycle to one source."""
    sensor, parameters = forecast_setup
    before_sources, before_beliefs = _row_counts(fresh_db)
    first_results = _pipeline().compute(parameters=parameters)
    second_results = _pipeline().compute(
        parameters={
            **parameters,
            "start": "2025-01-08T02:00:00+00:00",
            "end": "2025-01-08T04:00:00+00:00",
        }
    )
    fresh_db.session.rollback()

    assert _row_counts(fresh_db) == (before_sources + 1, before_beliefs + 4)
    sources = [result["data"].sources[0] for result in first_results + second_results]
    assert len({source.id for source in sources}) == 1
    assert all(source.id is not None for source in sources)
    beliefs = fresh_db.session.scalars(
        select(TimedBelief)
        .filter_by(sensor_id=sensor.id, source_id=sources[0].id)
        .order_by(TimedBelief.event_start)
    ).all()
    assert [belief.event_value for belief in beliefs] == [12.5] * 4
    assert [belief.event_start for belief in beliefs] == [
        pd.Timestamp(parameters["start"]) + timedelta(hours=hour) for hour in range(4)
    ]


def test_queue_source_reuses_existing_source_after_dry_run(fresh_db, forecast_setup):
    """Queuing a pipeline after a dry run resolves its transient source by identity."""
    _, parameters = forecast_setup
    saved_results = _pipeline().compute(parameters=parameters)
    source_id = saved_results[0]["data"].sources[0].id
    before = _row_counts(fresh_db)
    pipeline = _pipeline()

    pipeline.compute(parameters={**parameters, "dry-run": True})
    queued_source_id = pipeline._persist_data_source_id()

    assert queued_source_id == source_id
    assert _row_counts(fresh_db) == before


def test_prediction_run_preserves_saving_export_and_cleanup(
    fresh_db, forecast_setup, tmp_path
):
    """The legacy entrypoint saves predictions, exports them, and removes the model."""
    sensor, _ = forecast_setup
    source = DataSource(name="legacy-prediction", type="forecaster")
    model_path = tmp_path / "model.pkl"
    model_path.write_text("Model loading is replaced by the fixture.")
    output_path = tmp_path / "predictions.csv"
    pipeline = PredictPipeline(
        future_regressors=[],
        past_regressors=[],
        target_sensor=sensor,
        sensor_to_save=sensor,
        model_path=str(model_path),
        output_path=str(output_path),
        n_steps_to_predict=1,
        max_forecast_horizon=1,
        predict_start=pd.Timestamp("2025-01-08T00:00:00+00:00"),
        predict_end=pd.Timestamp("2025-01-08T01:00:00+00:00"),
        data_source=source,
    )
    before_sources, before_beliefs = _row_counts(fresh_db)

    result = pipeline.run(delete_model=True)
    fresh_db.session.rollback()

    assert _row_counts(fresh_db) == (before_sources + 1, before_beliefs + 1)
    assert result["event_value"].tolist() == [12.5]
    assert result.sources[0].id is not None
    assert pd.read_csv(output_path)["event_value"].tolist() == [12.5]
    assert not model_path.exists()


def test_saving_a_forecast_that_computed_nothing_says_so(
    fresh_db, setup_fresh_test_forecast_data, monkeypatch
):
    """A cycle that computed no beliefs has to say so, because silence reads like a cycle that never ran.

    The dry run already reports an empty forecast, through `_log_forecast_dry_run`,
    so the saving path should not be the quiet one of the two.
    """
    from flexmeasures.data.services import forecasting as forecasting_service

    sensor = setup_fresh_test_forecast_data["solar-sensor"]
    messages = []
    monkeypatch.setattr(
        forecasting_service.logging,
        "info",
        lambda message, *args: messages.append(message % args),
    )
    beliefs_before = fresh_db.session.scalar(
        select(func.count()).select_from(TimedBelief)
    )

    forecasting_service.save_forecast(BeliefsDataFrame(sensor=sensor))

    assert beliefs_before == fresh_db.session.scalar(
        select(func.count()).select_from(TimedBelief)
    ), "an empty forecast records nothing"
    assert any(
        "computed none" in message for message in messages
    ), f"the empty cycle said nothing: {messages}"
