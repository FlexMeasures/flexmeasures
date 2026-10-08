"""Forecast orchestration, persistence, and job failure handling."""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import TYPE_CHECKING

from timely_beliefs import BeliefsDataFrame

from flask import current_app

from flexmeasures.data import db
from flexmeasures.data.services.generator_results import check_results_of_current_job
from flexmeasures.data.utils import save_to_db_and_count
from flexmeasures.utils.flexmeasures_inflection import pluralize

import click
from rq.timeouts import JobTimeoutException

if TYPE_CHECKING:
    from flexmeasures.data.models.forecasting.pipelines.predict import PredictPipeline
    from flexmeasures.data.models.forecasting.pipelines.train_predict import (
        TrainPredictPipeline,
    )


FORECASTING_JOB_TIMEOUT_HINT = (
    "Forecasting job timed out. "
    "Decrease max-forecast-horizon to reduce runtime per job. "
    "To create more forecast cycles, set forecast-frequency to a smaller timedelta. "
    "If retrain-frequency is larger, decrease it too. "
    "More cycles split the request into more, shorter jobs."
)
FORECASTING_JOB_TIMEOUT_HOST_HINT = "Alternatively, hosts can increase FLEXMEASURES_JOB_TIMEOUT for the forecasting queue."


# TODO: we could also monitor the failed queue and re-enqueue jobs who had missing data
#       (and maybe failed less than three times so far)


def handle_forecasting_exception(job, exc_type, exc_value, traceback):
    """Persist forecasting job failure metadata.

    Forecasting failures stay attached to the original job instead of
    enqueueing a fallback job.
    """
    click.echo(
        "HANDLING RQ FORECASTING WORKER EXCEPTION: %s:%s\n" % (exc_type, exc_value)
    )

    if "failures" not in job.meta:
        job.meta["failures"] = 1
    else:
        job.meta["failures"] = job.meta["failures"] + 1
    job.save_meta()

    exception = {
        "type": exc_type.__name__ if exc_type is not None else None,
        "message": str(exc_value),
    }

    if isinstance(exc_type, type) and issubclass(exc_type, JobTimeoutException):
        logger = logging.getLogger(__name__)
        logger.warning(
            "%s %s",
            FORECASTING_JOB_TIMEOUT_HINT,
            FORECASTING_JOB_TIMEOUT_HOST_HINT,
        )
        exception["hint"] = FORECASTING_JOB_TIMEOUT_HINT

    job.meta["exception"] = exception
    job.save_meta()

    trigger = job.meta.get("trigger", {})
    automation_run_id = job.meta.get("automation_run_id") or trigger.get(
        "automation_run_id"
    )
    logical_job_key = job.meta.get("logical_job_key")
    if automation_run_id is not None and logical_job_key is not None:
        from flexmeasures.data.services.automations import record_automation_job_failed

        record_automation_job_failed(automation_run_id, logical_job_key, exc_value)


def save_forecast(bdf: BeliefsDataFrame, save_changed_beliefs_only: bool = True) -> int:
    """Resolve source attribution and commit one cycle's forecast beliefs, returning how many were saved.

    By default, a belief that repeats the belief right before it is not saved again, as for any other data.
    Pass save_changed_beliefs_only=False to record every belief, for instance to evaluate forecasts per horizon.
    """
    from flexmeasures.data.models.forecasting.utils import refresh_data_source

    if bdf.empty:
        # Say so, because a cycle that computed nothing and a cycle that never ran look the same in a silent log.
        # The dry run says it too, through `_log_forecast_dry_run`.
        logging.info(
            "Saving no predictions to DB: this cycle computed none for sensor: %s, sensor_id: %s.",
            bdf.sensor,
            bdf.sensor.id,
        )
        return 0
    sources = [
        refresh_data_source(source)
        for source in bdf.index.levels[bdf.index.names.index("source")]
    ]
    bdf.index = bdf.index.set_levels(sources, level="source")
    # A forecast that repeats the belief right before it adds nothing a lookup of the most recent beliefs could use,
    # and repeating a whole run from the same viewpoint would otherwise fail on the unique constraint.
    _, n_saved = save_to_db_and_count(
        bdf, save_changed_beliefs_only=save_changed_beliefs_only
    )
    db.session.commit()
    # Say how many were saved, because a cycle that saved nothing and one that saved everything otherwise read alike.
    # Beliefs left out are named only when there are some, and not all of them need be repeats: a belief without a value is left out as well.
    left_out = len(bdf) - n_saved
    logging.info(
        "Saved %s to DB%s, with source: %s, sensor: %s, sensor_id: %s.",
        pluralize("prediction", n_saved, include_count=True),
        (
            f", leaving out {left_out} that repeat beliefs already on record or have no value"
            if left_out
            else ""
        ),
        bdf.sources[0],
        bdf.sensor,
        bdf.sensor.id,
    )
    return n_saved


def _log_forecast_dry_run(bdf: BeliefsDataFrame) -> None:
    logging.info(
        "Not saving predictions to DB (because of --dry-run). Would have saved %s with sensor: %s, sensor_id: %s.",
        pluralize("belief", len(bdf), include_count=True),
        bdf.sensor,
        bdf.sensor.id,
    )


def run_prediction(
    pipeline: PredictPipeline, delete_model: bool = False
) -> BeliefsDataFrame:
    """Preserve the legacy prediction entrypoint's exports, save, and cleanup."""
    bdf = pipeline.compute()
    if pipeline.output_path is not None:
        pipeline.save_results_to_CSV(bdf)
    if pipeline.dry_run:
        _log_forecast_dry_run(bdf)
    else:
        save_forecast(bdf)
    if delete_model:
        os.remove(pipeline.model_path)
    logging.info("Prediction pipeline completed successfully.")
    return bdf


def run_forecast_cycle(pipeline: TrainPredictPipeline, *args, **kwargs) -> float:
    """Compute and persist one cycle before reporting its runtime to the caller."""
    result = pipeline.compute_cycle(*args, **kwargs)
    bdf = result.data
    # Judge the cycle before anything is exported, saved or handed back.
    check_results_of_current_job(
        [{"sensor": pipeline._parameters["sensor_to_save"], "data": bdf}], pipeline
    )
    if result.output_path is not None:
        logging.debug("Saving predictions to a CSV file.")
        os.makedirs(os.path.dirname(result.output_path), exist_ok=True)
        bdf.to_csv(result.output_path)
        logging.debug("Successfully saved predictions to %s", result.output_path)
    n_saved = None
    if pipeline._parameters.get("dry_run", False):
        _log_forecast_dry_run(bdf)
    else:
        n_saved = save_forecast(bdf)
    # Keep DataGenerator's result attribution aligned with the source resolved by the service.
    pipeline._data_source = bdf.sources[0] if len(bdf) else pipeline.forecast_source()
    if pipeline.delete_model:
        os.remove(result.model_path)
    result_entry = {"data": bdf, "sensor": pipeline._target_sensor}
    if n_saved is not None:
        # Callers report what was saved, which can be fewer beliefs than were computed.
        result_entry["n_saved"] = n_saved
    pipeline.return_values.append(result_entry)
    return result.runtime


def run_forecast(
    pipeline: TrainPredictPipeline, as_job: bool = False, queue: str = "forecasting"
) -> list[dict] | dict:
    """Orchestrate cycles, saving each completed cycle before starting the next."""
    # Only announce a pipeline run when actually running it here: with as_job, this
    # method merely queues the cycles, and the workers running them log their own start.
    log_start = logging.debug if as_job else logging.info
    log_start(
        f"Starting Train-Predict Pipeline to predict for {pipeline._parameters['predict_period_in_hours']} hours."
    )
    # Resolve before anything reads the target or the regressors, so that the cycles,
    # the queued payloads and the data source all see the same inputs.
    pipeline._resolved_config = pipeline._resolve_inputs()
    connection = current_app.queues[queue].connection
    # How much to move forward to the next cycle one prediction period later
    cycle_frequency = max(
        pipeline._config["retrain_frequency"],
        pipeline._parameters["forecast_frequency"],
    )

    predict_start = pipeline._parameters["predict_start"]
    predict_end = predict_start + cycle_frequency

    # Determine training window (start, end)
    train_start, train_end = pipeline._derive_training_period()

    sensor_resolution = pipeline._target_resolution
    multiplier = int(
        timedelta(hours=1) / sensor_resolution
    )  # multiplier used to adapt n_steps_to_predict to hours from sensor resolution, e.g. 15 min sensor resolution will have 7*24*4 = 168 predictions to predict a week

    # Compute number of training cycles (at least 1)
    n_cycles = max(
        timedelta(hours=pipeline._parameters["predict_period_in_hours"])
        // max(
            pipeline._config["retrain_frequency"],
            pipeline._parameters["forecast_frequency"],
        ),
        1,
    )

    cumulative_cycles_runtime = 0  # To track the cumulative runtime of TrainPredictPipeline cycles when not running as a job.
    cycles_job_params = []
    for counter in range(n_cycles):
        predict_end = min(predict_end, pipeline._parameters["end_date"])

        train_predict_params = {
            "train_start": train_start,
            "train_end": train_end,
            "predict_start": predict_start,
            "predict_end": predict_end,
            "counter": counter + 1,
            "multiplier": multiplier,
        }

        if not as_job:
            cycle_runtime = pipeline.run_cycle(**train_predict_params)
            cumulative_cycles_runtime += cycle_runtime
        else:
            cycles_job_params.append(train_predict_params)

        train_end += cycle_frequency
        predict_start += cycle_frequency
        predict_end += cycle_frequency
    if not as_job:
        logging.info(
            f"Train-Predict Pipeline completed successfully in {cumulative_cycles_runtime:.2f} seconds."
        )

    if as_job:
        return pipeline._queue_cycle_jobs(cycles_job_params, queue, connection)

    return pipeline.return_values
