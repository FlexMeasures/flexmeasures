from __future__ import annotations

from datetime import datetime
import json
import os

from rq.job import Job

from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline
from flexmeasures.data.services.forecasting import handle_forecasting_exception
from flexmeasures.utils.job_utils import work_on_rq
from flexmeasures.utils.time_utils import as_server_time


def queue_forecasting_job(
    sensor_id: int,
    start: datetime,
    end: datetime,
    *,
    config: dict | None = None,
):
    pipeline = TrainPredictPipeline(
        config=config
        or {
            "train-start": "2025-01-01T00:00:00+00:00",
            "retrain-frequency": "PT1H",
        }
    )
    return pipeline.compute(
        as_job=True,
        parameters={
            "sensor": sensor_id,
            "start": as_server_time(start).isoformat(),
            "end": as_server_time(end).isoformat(),
            "max-forecast-horizon": "PT1H",
            "forecast-frequency": "PT1H",
        },
    )


def check_failures(
    redis_queue,
    failure_search_words: list[str] | None = None,
):
    """Check that there was at least one failed forecasting job."""
    if os.name == "nt":
        print("Failed job registry not working on Windows. Skipping check...")
        return

    failed = redis_queue.failed_job_registry
    failure_search_words = failure_search_words or []
    failure_count = max(len(failure_search_words), 1)

    assert failed.count == failure_count

    for job_idx in range(failure_count):
        job = Job.fetch(
            failed.get_job_ids()[job_idx], connection=redis_queue.connection
        )
        if failure_search_words:
            assert failure_search_words[job_idx] in job.latest_result().exc_string


def test_failed_forecasting_job_does_not_enqueue_fallback(
    app,
    clean_redis,
    setup_fresh_test_forecast_data_with_missing_data,
):
    sensor = setup_fresh_test_forecast_data_with_missing_data["solar-sensor"]
    irradiance_sensor = setup_fresh_test_forecast_data_with_missing_data[
        "irradiance-sensor"
    ]

    queue_forecasting_job(
        sensor.id,
        start=datetime(2025, 1, 25, 0),
        end=datetime(2025, 1, 25, 2),
        config={
            "train-start": "2025-01-01T00:00:00+00:00",
            "retrain-frequency": "PT1H",
            "missing-threshold": 0.0,
            "future-regressors": [irradiance_sensor.id],
        },
    )

    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)

    check_failures(
        app.queues["forecasting"],
        ["NotEnoughDataException", "NotEnoughDataException"],
    )
    failed_job_ids = app.queues["forecasting"].failed_job_registry.get_job_ids()
    for failed_job_id in failed_job_ids:
        failed_job = Job.fetch(
            failed_job_id, connection=app.queues["forecasting"].connection
        )
        assert failed_job.meta["failures"] == 1
        assert failed_job.meta["exception"]["type"] == "NotEnoughDataException"
        assert isinstance(failed_job.meta["exception"]["message"], str)
        assert failed_job.meta["exception"]["message"] != ""
        assert failed_job.meta.get("fallback_job_id") is None
    assert app.queues["forecasting"].count == 0


def test_forecasting_job_meta_is_json_serializable(
    app,
    setup_fresh_test_forecast_data,
):
    sensor = setup_fresh_test_forecast_data["solar-sensor"]

    pipeline_returns = queue_forecasting_job(
        sensor.id,
        start=datetime(2025, 1, 5, 0),
        end=datetime(2025, 1, 5, 2),
    )

    job = app.queues["forecasting"].fetch_job(pipeline_returns["job_id"])
    meta_json = json.dumps(job.get_meta())
    assert meta_json is not None

    meta = json.loads(meta_json)
    assert meta["sensor_id"] == sensor.id
    assert isinstance(meta["start"], str)
    assert isinstance(meta["end"], str)
