from __future__ import annotations

from typing import Any

import os
import time
import logging
from datetime import datetime, timedelta

from rq.job import Job
from sqlalchemy import inspect as sa_inspect

from flask import current_app

from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.forecasting import Forecaster
from flexmeasures.data.models.forecasting.pipelines.predict import PredictPipeline
from flexmeasures.data.models.forecasting.pipelines.train import TrainPipeline
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.forecasting.pipeline import (
    ForecasterParametersSchema,
    TrainPredictPipelineConfigSchema,
)
from flexmeasures.data.schemas.sensors import SensorReference, SensorReferenceSchema
from flexmeasures.utils.flexmeasures_inflection import p


def _sensor_id(sensor: Sensor | int | None) -> int | None:
    """Return the sensor ID from a Sensor object or already-serialized ID."""
    if sensor is None:
        return None
    return sensor.id if isinstance(sensor, Sensor) else sensor


def _entity_id(entity_or_id):
    """Return the database ID from a model object or already-serialized ID."""
    return getattr(entity_or_id, "id", entity_or_id)


def _make_annotation_regressor_payload(spec: dict[str, Any]) -> dict[str, Any]:
    """Serialize ORM-backed annotation regressor source fields to IDs."""
    payload = dict(spec)
    for source_key in ("account", "asset", "sensor"):
        if source_key in payload:
            payload[source_key] = _entity_id(payload[source_key])
    return payload


def _get_attached_sensor(sensor_id: int | None) -> Sensor | None:
    """Load a sensor in the current session from a queued job payload ID."""
    if sensor_id is None:
        return None
    attached_sensor = db.session.get(Sensor, sensor_id)
    if attached_sensor is None:
        raise ValueError(f"Could not load sensor with id {sensor_id}.")
    return attached_sensor


def _get_attached_data_source(data_source_id: int | None) -> DataSource | None:
    """Load a data source in the current session from a queued job payload ID."""
    if data_source_id is None:
        return None
    attached_source = db.session.get(DataSource, data_source_id)
    if attached_source is None:
        raise ValueError(f"Could not load data source with id {data_source_id}.")
    return attached_source


def _make_regressor_payload(
    regressor: Sensor | SensorReference,
) -> int | dict[str, Any]:
    """Serialize a regressor and its optional source filters to database IDs."""
    if isinstance(regressor, SensorReference):
        return SensorReferenceSchema().dump(regressor)
    return regressor.id


def _load_regressor_payload(
    payload: int | dict[str, Any],
) -> Sensor | SensorReference:
    """Restore a worker-local regressor from a primitive queued-job payload."""
    if isinstance(payload, dict):
        return SensorReference(**SensorReferenceSchema().load(payload))
    sensor = _get_attached_sensor(payload)
    assert sensor is not None
    return sensor


def _assert_no_orm_objects(value: Any, path: str = "payload") -> None:
    """Reject ORM objects before they can be pickled into an RQ job."""
    inspection = sa_inspect(value, raiseerr=False)
    if inspection is not None and hasattr(inspection, "object"):
        raise ValueError(
            f"Queued forecasting job {path} contains a "
            f"{value.__class__.__name__} ORM object. Pass its ID instead."
        )

    if isinstance(value, dict):
        for key, nested_value in value.items():
            _assert_no_orm_objects(nested_value, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set)):
        for index, nested_value in enumerate(value):
            _assert_no_orm_objects(nested_value, f"{path}[{index}]")


def _make_job_config_payload(config: dict[str, Any]) -> dict[str, Any]:
    """Build the queued worker config payload.

    ORM-backed fields are replaced by IDs, while plain config fields are preserved.
    """
    # Preserve plain config fields, but replace ORM-backed regressors by primitive payloads.
    payload = dict(config)
    future_regressors = payload.pop("future_regressors", [])
    past_regressors = payload.pop("past_regressors", [])
    payload["future_regressor_ids"] = [
        _make_regressor_payload(regressor) for regressor in future_regressors
    ]
    payload["past_regressor_ids"] = [
        _make_regressor_payload(regressor) for regressor in past_regressors
    ]
    payload["annotation_regressors"] = [
        _make_annotation_regressor_payload(spec)
        for spec in payload.get("annotation_regressors", [])
    ]
    _assert_no_orm_objects(payload)
    return payload


def _load_job_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Restore worker config and reload regressors in the worker session."""
    config = dict(payload)
    config["future_regressors"] = [
        _load_regressor_payload(regressor)
        for regressor in config.pop("future_regressor_ids", [])
    ]
    config["past_regressors"] = [
        _load_regressor_payload(regressor)
        for regressor in config.pop("past_regressor_ids", [])
    ]
    return config


def _make_job_parameters_payload(parameters: dict[str, Any]) -> dict[str, Any]:
    """Build the queued worker parameter payload.

    ORM-backed fields are replaced by IDs, while plain parameter fields are preserved.
    """
    # Preserve plain parameters, but replace ORM-backed sensors by IDs.
    payload = dict(parameters)
    sensor_id = _sensor_id(payload.pop("sensor"))
    sensor_to_save_id = _sensor_id(payload.pop("sensor_to_save", None))
    if sensor_id is None:
        raise ValueError("Cannot enqueue a forecasting job without a target sensor.")
    payload["sensor_id"] = sensor_id
    payload["sensor_to_save_id"] = sensor_to_save_id or sensor_id
    _assert_no_orm_objects(payload)
    return payload


def _load_job_parameters_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Restore worker parameters and reload sensors in the worker session."""
    parameters = dict(payload)
    parameters["sensor"] = _get_attached_sensor(parameters.pop("sensor_id"))
    parameters["sensor_to_save"] = _get_attached_sensor(
        parameters.pop("sensor_to_save_id")
    )
    return parameters


# Logical name of the job which reports on all cycle jobs of one pipeline run.
WRAP_UP_LOGICAL_JOB_KEY = "wrap-up"


def run_train_predict_cycle_job(
    config: dict,
    parameters: dict,
    data_source_id: int,
    delete_model: bool,
    automation_run_id: int | None = None,
    logical_job_key: str | None = None,
    **cycle_params,
):
    """Run one train-predict cycle after reconstructing worker-local ORM state."""
    from flexmeasures.data.services.automations import (
        record_automation_job_failed,
        record_automation_job_started,
        record_automation_job_succeeded,
    )

    record_automation_job_started(automation_run_id, logical_job_key)
    pipeline = TrainPredictPipeline(delete_model=delete_model)
    pipeline._config = _load_job_config_payload(config)
    for key, value in pipeline._config.items():
        setattr(pipeline, key, value)
    pipeline._parameters = _load_job_parameters_payload(parameters)
    pipeline._data_source = _get_attached_data_source(data_source_id)
    try:
        result = pipeline.run_cycle(**cycle_params)
    except Exception as exc:
        record_automation_job_failed(automation_run_id, logical_job_key, exc)
        raise
    record_automation_job_succeeded(automation_run_id, logical_job_key)
    return result


def run_train_predict_wrap_up_job(
    cycle_job_ids: list[str],
    queue: str = "forecasting",
    automation_run_id: int | None = None,
    logical_job_key: str | None = None,
):
    """Log the status of all cycle jobs after completion."""
    from flexmeasures.data.services.automations import (
        record_automation_job_failed,
        record_automation_job_started,
        record_automation_job_succeeded,
    )

    record_automation_job_started(automation_run_id, logical_job_key)
    connection = current_app.queues[queue].connection

    try:
        for index, job_id in enumerate(cycle_job_ids):
            status = Job.fetch(job_id, connection=connection).get_status()
            logging.info(f"{queue} job-{index}: {job_id} status: {status}")
    except Exception as exc:
        record_automation_job_failed(automation_run_id, logical_job_key, exc)
        raise
    record_automation_job_succeeded(automation_run_id, logical_job_key)


class TrainPredictPipeline(Forecaster):

    __version__ = "1"
    __author__ = "Seita"

    _config_schema = TrainPredictPipelineConfigSchema()
    _parameters_schema = ForecasterParametersSchema()

    def __init__(
        self,
        config: dict | None = None,
        delete_model: bool = False,
        save_config: bool = True,
        save_parameters: bool = False,
    ):
        super().__init__(
            config=config, save_config=save_config, save_parameters=save_parameters
        )
        for k, v in self._config.items():
            setattr(self, k, v)
        self.delete_model = delete_model
        self.return_values = []  # To store forecasts and jobs

    def run_wrap_up(self, cycle_job_ids: list[str], queue: str = "forecasting"):
        """Log the status of all cycle jobs after completion."""
        run_train_predict_wrap_up_job(cycle_job_ids, queue)

    def run_cycle(
        self,
        train_start: datetime,
        train_end: datetime,
        predict_start: datetime,
        predict_end: datetime,
        counter: int,
        multiplier: int,
        **kwargs,
    ):
        """
        Runs a single training and prediction cycle.
        """
        logging.info(
            f"Starting Train-Predict cycle from {train_start} to {predict_end}"
        )

        # Train model
        train_pipeline = TrainPipeline(
            future_regressors=self._config["future_regressors"],
            past_regressors=self._config["past_regressors"],
            target_sensor=self._parameters["sensor"],
            model_save_dir=self._parameters["model_save_dir"],
            n_steps_to_predict=(predict_start - train_start)
            // timedelta(hours=1)
            * multiplier,
            max_forecast_horizon=self._parameters["max_forecast_horizon"]
            // self._parameters["sensor"].event_resolution,
            event_starts_after=train_start,
            event_ends_before=train_end,
            save_belief_time=self._parameters["save_belief_time"],
            beliefs_before=self._parameters.get("beliefs_before"),
            probabilistic=self._parameters["probabilistic"],
            ensure_positive=self._config["ensure_positive"],
            missing_threshold=self._config.get("missing_threshold"),
            annotation_regressors=self._config.get("annotation_regressors", []),
            model_params=self._config.get("model_params"),
        )
        logging.info(f"Training cycle from {train_start} to {train_end} started ...")
        train_start_time = time.time()
        train_pipeline.run(counter=counter)
        train_runtime = time.time() - train_start_time
        logging.info(
            f"{p.ordinal(counter)} Training cycle completed in {train_runtime:.2f} seconds."
        )
        # Make predictions
        predict_pipeline = PredictPipeline(
            future_regressors=self._config["future_regressors"],
            past_regressors=self._config["past_regressors"],
            target_sensor=self._parameters["sensor"],
            model_path=os.path.join(
                self._parameters["model_save_dir"],
                f"sensor_{self._parameters['sensor'].id}-cycle_{counter}-lgbm.pkl",
            ),
            output_path=(
                os.path.join(
                    self._parameters["output_path"],
                    f"sensor_{self._parameters['sensor'].id}-cycle_{counter}.csv",
                )
                if self._parameters["output_path"]
                else None
            ),
            n_steps_to_predict=self._parameters["predict_period_in_hours"] * multiplier,
            max_forecast_horizon=self._parameters["max_forecast_horizon"]
            // self._parameters["sensor"].event_resolution,
            forecast_frequency=self._parameters["forecast_frequency"]
            // self._parameters["sensor"].event_resolution,
            probabilistic=self._parameters["probabilistic"],
            event_starts_after=train_start,  # use beliefs about events before the start of the predict period
            event_ends_before=predict_end,  # ignore any beliefs about events beyond the end of the predict period
            save_belief_time=self._parameters["save_belief_time"],
            beliefs_before=self._parameters.get("beliefs_before"),
            predict_start=predict_start,
            predict_end=predict_end,
            sensor_to_save=self._parameters["sensor_to_save"],
            data_source=self.data_source,
            missing_threshold=self._config.get("missing_threshold"),
            annotation_regressors=self._config.get("annotation_regressors", []),
            post_processing_config={
                "lower": self._config.get("lower"),
                "upper": self._config.get("upper"),
                "snap": self._config.get("snap"),
            },
        )
        logging.info(
            f"Prediction cycle from {predict_start} to {predict_end} started ..."
        )
        predict_start_time = time.time()
        forecasts = predict_pipeline.run(delete_model=self.delete_model)
        predict_runtime = time.time() - predict_start_time
        logging.info(
            f"{p.ordinal(counter)} Prediction cycle completed in {predict_runtime:.2f} seconds. "
        )

        total_runtime = (
            train_runtime + predict_runtime
        )  # To track the cumulative runtime of PredictPipeline and TrainPipeline for this cycle
        logging.info(
            f"{p.ordinal(counter)} Train-Predict cycle from {train_start} to {predict_end} completed in {total_runtime:.2f} seconds."
        )
        self.return_values.append(
            {"data": forecasts, "sensor": self._parameters["sensor"]}
        )
        return total_runtime

    def _compute_forecast(self, as_job: bool = False, **kwargs) -> list[dict[str, Any]]:
        # DataGenerator.compute already loaded kwargs into self._parameters.
        return self.run(as_job=as_job)

    def _derive_training_period(self) -> tuple[datetime, datetime]:
        """Derive the effective training period for model fitting.

        Priority (most restrictive start date wins):

        1. ``train_start`` (if explicitly configured via ``--train-start``).
        2. ``predict_start - train_period`` (if ``--train-period`` was explicitly set).
        3. ``predict_start - max_training_period`` (always enforced as the outer bound).

        When ``--train-start`` is set the ``--train-period`` is ignored – the
        effective period is simply ``predict_start - train_start``, capped to
        ``max_training_period``.  This prevents the old 30-day default from
        silently overriding an explicit start date.

        Additionally, the resulting training window is guaranteed to span
        at least two days.

        :return:    A tuple ``(train_start, train_end)`` defining the training window.
        """
        train_end = self._parameters["predict_start"]

        configured_start: datetime | None = self._config.get("train_start")
        period_hours: int | None = self._config.get("train_period_in_hours")

        # Outer bound: never go further back than max_training_period.
        max_period_start = train_end - self._config["max_training_period"]

        if configured_start is not None:
            # Explicit train_start takes full precedence; period is ignored.
            train_start = max(configured_start, max_period_start)
        elif period_hours is not None:
            # Explicit train_period without train_start.
            train_start = max(
                train_end - timedelta(hours=period_hours), max_period_start
            )
        else:
            # Neither set: use the full max_training_period window.
            train_start = max_period_start

        # Enforce minimum training period of 2 days
        min_training_period = timedelta(days=2)
        if train_end - train_start < min_training_period:
            train_start = train_end - min_training_period

        return train_start, train_end

    def run(
        self,
        as_job: bool = False,
        queue: str = "forecasting",
    ):
        # Only announce a pipeline run when actually running it here: with as_job, this
        # method merely queues the cycles, and the workers running them log their own start.
        log_start = logging.debug if as_job else logging.info
        log_start(
            f"Starting Train-Predict Pipeline to predict for {self._parameters['predict_period_in_hours']} hours."
        )
        connection = current_app.queues[queue].connection
        # How much to move forward to the next cycle one prediction period later
        cycle_frequency = max(
            self._config["retrain_frequency"],
            self._parameters["forecast_frequency"],
        )

        predict_start = self._parameters["predict_start"]
        predict_end = predict_start + cycle_frequency

        # Determine training window (start, end)
        train_start, train_end = self._derive_training_period()

        sensor_resolution = self._parameters["sensor"].event_resolution
        multiplier = int(
            timedelta(hours=1) / sensor_resolution
        )  # multiplier used to adapt n_steps_to_predict to hours from sensor resolution, e.g. 15 min sensor resolution will have 7*24*4 = 168 predictions to predict a week

        # Compute number of training cycles (at least 1)
        n_cycles = max(
            timedelta(hours=self._parameters["predict_period_in_hours"])
            // max(
                self._config["retrain_frequency"],
                self._parameters["forecast_frequency"],
            ),
            1,
        )

        cumulative_cycles_runtime = 0  # To track the cumulative runtime of TrainPredictPipeline cycles when not running as a job.
        cycles_job_params = []
        for counter in range(n_cycles):
            predict_end = min(predict_end, self._parameters["end_date"])

            train_predict_params = {
                "train_start": train_start,
                "train_end": train_end,
                "predict_start": predict_start,
                "predict_end": predict_end,
                "counter": counter + 1,
                "multiplier": multiplier,
            }

            if not as_job:
                cycle_runtime = self.run_cycle(**train_predict_params)
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
            return self._queue_cycle_jobs(cycles_job_params, queue, connection)

        return self.return_values

    def _persist_data_source_id(self) -> int:
        """Make sure this pipeline's data source is in the database, so that the workers can look it up."""
        self._data_source = db.session.merge(self.data_source)
        db.session.flush()
        data_source_id = self._data_source.id
        db.session.commit()
        return data_source_id

    def _job_ttls(self) -> tuple[int, int]:
        """Return the time-to-live of a job and of its result, in seconds.

        NB job.cleanup docs say that a negative number of seconds means persisting forever.
        """
        return (
            int(
                current_app.config.get(
                    "FLEXMEASURES_JOB_TTL", timedelta(-1)
                ).total_seconds()
            ),
            int(
                current_app.config.get(
                    "FLEXMEASURES_PLANNING_TTL", timedelta(-1)
                ).total_seconds()
            ),
        )

    def _job_meta(
        self,
        job_metadata: dict,
        job_spec: dict,
        automation_run_id: int | None,
    ) -> dict:
        """Return the metadata to store on one job, identifying its automation run where there is one."""
        meta = dict(job_metadata)
        if automation_run_id is not None:
            meta["automation_run_id"] = automation_run_id
            meta["logical_job_key"] = job_spec["logical_job_key"]
        return meta

    def _plan_cycle_jobs(
        self,
        cycles_job_params: list[dict],
        queue: str,
        data_source_id: int,
        job_metadata: dict,
        automation_run_id: int | None,
    ) -> list[dict]:
        """Describe every job this run intends to create, before any of them is queued.

        Each job gets a logical key which stays the same across retries of an automation run, and a job ID derived from it,
        so that a retry recognises the jobs it already queued instead of queueing them a second time.
        Outside an automation run there is nothing to retry, so RQ is left to make up the job IDs.
        """
        job_config = _make_job_config_payload(self._config)
        job_parameters = _make_job_parameters_payload(self._parameters)

        def rq_job_id_for(logical_job_key: str) -> str | None:
            if automation_run_id is None:
                return None
            return f"automation-run-{automation_run_id}-{logical_job_key}"

        cycle_specs = []
        for cycle_params in cycles_job_params:
            logical_job_key = f"cycle-{cycle_params['counter']:03d}"
            job_kwargs = {
                "config": job_config,
                "parameters": job_parameters,
                "data_source_id": data_source_id,
                "delete_model": self.delete_model,
                "automation_run_id": automation_run_id,
                "logical_job_key": logical_job_key,
                **cycle_params,
            }
            _assert_no_orm_objects(job_kwargs)
            cycle_specs.append(
                {
                    "logical_job_key": logical_job_key,
                    "rq_job_id": rq_job_id_for(logical_job_key),
                    "queue": queue,
                    "kind": "forecast-cycle",
                    "depends_on": [],
                    "payload": {"kwargs": job_kwargs, "meta": job_metadata},
                }
            )
        wrap_up_spec = {
            "logical_job_key": WRAP_UP_LOGICAL_JOB_KEY,
            "rq_job_id": rq_job_id_for(WRAP_UP_LOGICAL_JOB_KEY),
            "queue": queue,
            "kind": "forecast-wrap-up",
            "depends_on": [spec["logical_job_key"] for spec in cycle_specs],
            "payload": {
                "kwargs": {
                    "cycle_job_ids": [spec["rq_job_id"] for spec in cycle_specs],
                    "queue": queue,
                    "automation_run_id": automation_run_id,
                    "logical_job_key": WRAP_UP_LOGICAL_JOB_KEY,
                },
                "meta": job_metadata,
            },
        }
        return cycle_specs + [wrap_up_spec]

    def _queue_cycle_jobs(
        self, cycles_job_params: list[dict], queue: str, connection
    ) -> dict:
        """Queue one job per training cycle, plus a wrap-up job which waits for all of them.

        When this pipeline runs for an automation, the jobs it intends to create are written down first,
        so that an attempt which fails halfway can be resumed without queueing the same work twice.
        """
        automation_run_id = (self._job_trigger or {}).get("automation_run_id")
        data_source_id = self._persist_data_source_id()
        job_parameters = _make_job_parameters_payload(self._parameters)
        sensor_id = job_parameters["sensor_id"]

        # job metadata for tracking
        # Serialize start and end to ISO format strings
        # Workaround for https://github.com/Parallels/rq-dashboard/issues/510
        job_metadata = {
            "data_source_info": {"id": data_source_id},
            "start": self._parameters["predict_start"].isoformat(),
            "end": self._parameters["end_date"].isoformat(),
            "sensor_id": job_parameters["sensor_to_save_id"],
        }
        if self._job_trigger:
            job_metadata["trigger"] = self._job_trigger

        job_specs = self._plan_cycle_jobs(
            cycles_job_params, queue, data_source_id, job_metadata, automation_run_id
        )
        intents = {}
        if automation_run_id is not None:
            from flexmeasures.data.services.automations import (
                ensure_automation_run_job_intents,
            )

            intents = {
                intent.logical_job_key: intent
                for intent in ensure_automation_run_job_intents(
                    automation_run_id, job_specs
                )
            }

        cycle_job_ids = []
        for job_spec in job_specs:
            if job_spec["kind"] != "forecast-cycle":
                continue
            cycle_job_ids.append(
                self._queue_planned_job(
                    run_train_predict_cycle_job,
                    job_spec,
                    intents,
                    queue,
                    connection,
                    job_metadata,
                    automation_run_id,
                    cache_for_sensor_id=sensor_id,
                )
            )

        wrap_up_spec = job_specs[-1]
        # The wrap-up job reports on the cycle jobs, whose IDs are only known now when this is not an automation run.
        wrap_up_spec["payload"]["kwargs"]["cycle_job_ids"] = cycle_job_ids
        wrap_up_job_id = self._queue_planned_job(
            run_train_predict_wrap_up_job,
            wrap_up_spec,
            intents,
            queue,
            connection,
            job_metadata,
            automation_run_id,
            depends_on=cycle_job_ids,
        )

        if len(cycle_job_ids) > 1:
            # Point at the wrap-up job, as it is the one that completes last.
            job_id = wrap_up_job_id
        else:
            job_id = cycle_job_ids[0] if cycle_job_ids else wrap_up_job_id
        if automation_run_id is not None:
            # An automation run is accounted for in full, wrap-up job included.
            n_jobs = len(cycle_job_ids) + 1
        else:
            n_jobs = len(cycle_job_ids) if len(cycle_job_ids) > 1 else 1
        return {"job_id": job_id, "n_jobs": n_jobs}

    def _queue_planned_job(
        self,
        func,
        job_spec: dict,
        intents: dict,
        queue: str,
        connection,
        job_metadata: dict,
        automation_run_id: int | None,
        cache_for_sensor_id: int | None = None,
        depends_on: list[str] | None = None,
    ) -> str:
        """Queue one planned job, unless an earlier attempt already put it in Redis."""
        intent = intents.get(job_spec["logical_job_key"])
        if intent is not None:
            from flexmeasures.data.services.automations import (
                reconcile_automation_job_intent,
            )

            if reconcile_automation_job_intent(intent):
                # This job survived an earlier attempt at this run, so leave it be.
                if cache_for_sensor_id is not None:
                    current_app.job_cache.add(
                        cache_for_sensor_id,
                        job_id=intent.rq_job_id,
                        queue=queue,
                        asset_or_sensor_type="sensor",
                    )
                return intent.rq_job_id

        ttl, result_ttl = self._job_ttls()
        job = Job.create(
            func,
            kwargs=job_spec["payload"]["kwargs"],
            connection=connection,
            id=job_spec["rq_job_id"],
            depends_on=depends_on,
            ttl=ttl,
            result_ttl=result_ttl,
            meta=self._job_meta(job_metadata, job_spec, automation_run_id),
        )
        current_app.queues[queue].enqueue_job(job)
        if automation_run_id is not None:
            from flexmeasures.data.services.automations import (
                mark_automation_job_queued,
            )

            mark_automation_job_queued(
                automation_run_id, job_spec["logical_job_key"], job.id
            )
        if cache_for_sensor_id is not None:
            current_app.job_cache.add(
                cache_for_sensor_id,
                job_id=job.id,
                queue=queue,
                asset_or_sensor_type="sensor",
            )
        return job.id
