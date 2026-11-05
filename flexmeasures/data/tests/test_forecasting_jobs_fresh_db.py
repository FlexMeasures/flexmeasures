from datetime import datetime

import pytest

from rq.job import Job
from sqlalchemy import select

from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.services.forecasting import handle_forecasting_exception
from flexmeasures.data.tests.test_forecasting_jobs import queue_forecasting_job
from flexmeasures.utils.job_utils import work_on_rq


def test_forecasting_job_runs_on_fresh_db(
    app,
    clean_redis,
    fresh_db,
    setup_fresh_test_forecast_data,
):
    sensor = setup_fresh_test_forecast_data["solar-sensor"]

    pipeline_returns = queue_forecasting_job(
        sensor.id,
        start=datetime(2025, 1, 5, 0),
        end=datetime(2025, 1, 5, 2),
    )

    job = app.queues["forecasting"].fetch_job(pipeline_returns["job_id"])
    assert job is not None

    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)

    refreshed_job = Job.fetch(job.id, connection=app.queues["forecasting"].connection)
    assert refreshed_job.is_finished

    forecasts = fresh_db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == sensor.id)
    ).all()
    assert forecasts


@pytest.mark.parametrize("keep", [False, True])
def test_a_forecast_keeps_its_model_only_when_asked(
    app, fresh_db, setup_fresh_test_forecast_data, tmp_path, monkeypatch, keep
):
    """A forecast hands its trained model to the prediction in memory, and keeps it as a file only when given a model-save-dir.

    The folder models used to be written to by default was relative to the working directory, so the run starts in an empty one.
    """
    import pickle

    from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline
    from flexmeasures.utils.time_utils import as_server_time

    monkeypatch.chdir(tmp_path)
    sensor = setup_fresh_test_forecast_data["solar-sensor"]
    parameters = {
        "sensor": sensor.id,
        "start": as_server_time(datetime(2025, 1, 5, 0)).isoformat(),
        "end": as_server_time(datetime(2025, 1, 5, 2)).isoformat(),
        "max-forecast-horizon": "PT1H",
        "forecast-frequency": "PT1H",
    }
    if keep:
        parameters["model-save-dir"] = str(tmp_path / "kept")
    pipeline = TrainPredictPipeline(
        config={
            "train-start": "2025-01-01T00:00:00+00:00",
            "retrain-frequency": "PT1H",
        }
    )

    results = pipeline.compute(parameters=parameters)

    # The forecasts are made either way.
    assert results and all(not result["data"].empty for result in results)
    model_files = sorted(tmp_path.rglob("*.pkl"))
    if not keep:
        assert model_files == []
    else:
        # One model per cycle, each of which can be read back to predict with.
        assert len(model_files) == 2
        assert all(path.parent == tmp_path / "kept" for path in model_files)
        with open(model_files[0], "rb") as file:
            assert hasattr(pickle.load(file), "predict")
