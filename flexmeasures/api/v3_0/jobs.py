from __future__ import annotations

from datetime import datetime

from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required
from redis.exceptions import ConnectionError as RedisConnectionError
from rq.job import Job, JobStatus, NoSuchJobError
from webargs.flaskparser import use_kwargs
from marshmallow import fields

from flexmeasures.data.services.utils import failed_job_exc_info, job_status_description
from flexmeasures.auth.policy import check_access
from flexmeasures.api.common.responses import deprecated_response_fields_headers
from flexmeasures.api.v3_0.deprecations import JOB_RESPONSE_FIELDS_DEPRECATION_DATE
from flexmeasures.data import db
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.utils import get_asset_or_sensor_from_ref

JOBS_API_DOCS_URL = (
    "https://flexmeasures.readthedocs.io/latest/api/v3_0.html"
    "#get--api-v3_0-jobs-uuid"
)
JOB_STATUS_DEPRECATED_RESPONSE_FIELDS = (
    "func_name",
    "enqueued_at",
    "started_at",
    "ended_at",
    "exc_info",
)


def _isoformat_or_none(dt: datetime | None) -> str | None:
    """Return an ISO-8601 string for *dt*, or ``None`` when *dt* is absent."""
    return dt.isoformat() if dt is not None else None


def _job_read_context(job: Job):
    """Resolve the asset or sensor whose read access governs this job."""
    asset_or_sensor_ref = job.meta.get("asset_or_sensor") or job.kwargs.get(
        "asset_or_sensor"
    )
    if asset_or_sensor_ref is not None:
        return get_asset_or_sensor_from_ref(asset_or_sensor_ref)

    sensor_id = job.meta.get("sensor_id")
    if sensor_id is None:
        forecast_kwargs = job.meta.get("forecast_kwargs", {})
        if isinstance(forecast_kwargs, dict):
            sensor_id = forecast_kwargs.get("sensor_id")
    if sensor_id is None:
        sensor_id = job.kwargs.get("sensor_id")

    if sensor_id is None:
        return None

    return db.session.get(Sensor, sensor_id)


def _job_queue_unavailable_response():
    return (
        dict(
            status="ERROR",
            message="Job queues are currently unavailable.",
        ),
        503,
    )


class JobAPI(FlaskView):
    """
    Endpoint for querying the status of background jobs by UUID.
    """

    route_base = "/jobs"
    trailing_slash = False

    @route("/<uuid>", methods=["GET"])
    @auth_required()
    @use_kwargs({"job_id": fields.Str(data_key="uuid", required=True)}, location="path")
    @as_json
    def get_job_status(self, job_id: str, **kwargs):
        """
        .. :quickref: Jobs; Get the status of a background job

        ---
        get:
          summary: Get the status of a background job
          description: |
            Look up a background job by its UUID and see whether it is
            queued, running, finished, or failed.

            The response includes a status message plus job metadata such
            as the queue name, function name, timestamps, and the job
            result when available.

            Failed jobs also include traceback information when the worker
            stored it with the job result.

            For a finished scheduling job, ``result`` is an object. For a
            ``StorageScheduler`` job it holds soft state-of-charge constraint
            analysis: ``unresolved`` lists constraints the scheduler could not
            satisfy, and ``resolved`` lists constraints that were satisfied
            with some margin. Each device entry's ``soc-minima``/``soc-maxima``
            value is a list, holding one entry per violated slot (for
            ``unresolved``) or per met slot with its margin (for ``resolved``),
            ordered chronologically. Both arrays are empty when the flex model
            defines no ``soc-minima``/``soc-maxima``, or when a scheduler other
            than ``StorageScheduler`` was used. The ``num-beliefs`` field holds
            the total number of beliefs (scheduled values) saved to the database.
            This is the only place constraint analysis is available — the sensor
            schedule endpoint (``GET /api/v3_0/sensors/<id>/schedules/<uuid>``)
            returns power values only.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: uuid
              required: true
              description: UUID of the background job.
              example: b3d26a8a-7a43-4a9f-93e1-fc2a869ea97b
              schema:
                type: string
          responses:
            200:
              description: Finished job status retrieved successfully.
              headers:
                Deprecation:
                  description: Indicates that the response contains deprecated fields.
                  schema:
                    type: string
                    example: "Wed, 01 Jul 2026 00:00:00 GMT"
                Link:
                  description: Link to migration guidance for deprecated response fields.
                  schema:
                    type: string
                    example: '<https://flexmeasures.readthedocs.io/latest/api/v3_0.html#get--api-v3_0-jobs-uuid>; rel="deprecation"; type="text/html"'
                FlexMeasures-Deprecated-Response-Fields:
                  description: Comma-separated response fields that are deprecated.
                  schema:
                    type: string
                    example: "func_name, enqueued_at, started_at, ended_at, exc_info"
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      status:
                        type: string
                        enum:
                          - QUEUED
                          - STARTED
                          - FINISHED
                          - FAILED
                          - DEFERRED
                          - SCHEDULED
                          - STOPPED
                          - CANCELED
                        description: Current status of the job.
                      message:
                        type: string
                        description: Human-readable description of the job status.
                      result:
                        description: >
                          Return value of the job function, or null when not yet
                          available. For a finished scheduling job, this is an
                          object; a ``StorageScheduler`` job populates it with
                          ``unresolved``/``resolved`` soft state-of-charge
                          constraint analysis (empty arrays when the flex model
                          defines no ``soc-minima``/``soc-maxima``, or when a
                          scheduler other than ``StorageScheduler`` was used).
                          The ``num-beliefs`` field holds the total number of
                          beliefs (scheduled values) saved to the database.
                        nullable: true
                      func-name:
                        type: string
                        description: Fully-qualified name of the function executed by this job.
                      origin:
                        type: string
                        description: Name of the queue the job was placed on.
                      enqueued-at:
                        type: string
                        format: date-time
                        nullable: true
                        description: ISO-8601 timestamp of when the job was enqueued.
                      started-at:
                        type: string
                        format: date-time
                        nullable: true
                        description: ISO-8601 timestamp of when the job started executing.
                      ended-at:
                        type: string
                        format: date-time
                        nullable: true
                        description: ISO-8601 timestamp of when the job finished executing.
                      exc-info:
                        type: string
                        nullable: true
                        description: Traceback information for failed jobs, or null otherwise.
                      func_name:
                        type: string
                        deprecated: true
                        description: (DEPRECATED) Fully-qualified name of the function executed by this job. Use `func-name` instead.
                      enqueued_at:
                        type: string
                        format: date-time
                        nullable: true
                        deprecated: true
                        description: (DEPRECATED) ISO-8601 timestamp of when the job was enqueued. Use `enqueued-at` instead.
                      started_at:
                        type: string
                        format: date-time
                        nullable: true
                        deprecated: true
                        description: (DEPRECATED) ISO-8601 timestamp of when the job started executing. Use `started-at` instead.
                      ended_at:
                        type: string
                        format: date-time
                        nullable: true
                        deprecated: true
                        description: (DEPRECATED) ISO-8601 timestamp of when the job finished executing. Use `ended-at` instead.
                      exc_info:
                        type: string
                        nullable: true
                        deprecated: true
                        description: (DEPRECATED) Traceback information for failed jobs, or null otherwise. Use `exc-info` instead.
                  examples:
                    queued:
                      summary: Queued job
                      value:
                        status: QUEUED
                        message: "Scheduling job waiting to be processed."
                        result: null
                        func-name: "flexmeasures.data.services.scheduling.create_schedule"
                        origin: scheduling
                        enqueued-at: "2026-04-28T10:00:00+00:00"
                        started-at: null
                        ended-at: null
                        exc-info: null
                        func_name: "flexmeasures.data.services.scheduling.create_schedule"
                        enqueued_at: "2026-04-28T10:00:00+00:00"
                        started_at: null
                        ended_at: null
                        exc_info: null
                    finished:
                      summary: Finished job
                      value:
                        status: FINISHED
                        message: "Scheduling job has finished."
                        result:
                          unresolved:
                            - asset: 42
                              soc-minima:
                                - datetime: "2024-01-01T10:00:00+00:00"
                                  violation: "260.0 kWh"
                                - datetime: "2024-01-01T10:15:00+00:00"
                                  violation: "180.0 kWh"
                          resolved: []
                          num-beliefs: 96
                        func-name: "flexmeasures.data.services.scheduling.create_schedule"
                        origin: scheduling
                        enqueued-at: "2026-04-28T10:00:00+00:00"
                        started-at: "2026-04-28T10:00:01+00:00"
                        ended-at: "2026-04-28T10:00:05+00:00"
                        exc-info: null
                    failed:
                      summary: Failed job
                      value:
                        status: FAILED
                        message: "Scheduling job failed with ValueError: ..."
                        result: null
                        func-name: "flexmeasures.data.services.scheduling.create_schedule"
                        origin: scheduling
                        enqueued-at: "2026-04-28T10:00:00+00:00"
                        started-at: "2026-04-28T10:00:01+00:00"
                        ended-at: "2026-04-28T10:00:02+00:00"
                        exc-info: "Traceback (most recent call last): ..."
            202:
              description: Job is still queued, scheduled, deferred, or running.
              headers:
                Deprecation:
                  description: Indicates that the response contains deprecated fields.
                  schema:
                    type: string
                    example: "Wed, 01 Jul 2026 00:00:00 GMT"
                Link:
                  description: Link to migration guidance for deprecated response fields.
                  schema:
                    type: string
                    example: '<https://flexmeasures.readthedocs.io/latest/api/v3_0.html#get--api-v3_0-jobs-uuid>; rel="deprecation"; type="text/html"'
                FlexMeasures-Deprecated-Response-Fields:
                  description: Comma-separated response fields that are deprecated.
                  schema:
                    type: string
                    example: "func_name, enqueued_at, started_at, ended_at, exc_info"
            422:
              description: Job has failed.
              headers:
                Deprecation:
                  description: Indicates that the response contains deprecated fields.
                  schema:
                    type: string
                    example: "Wed, 01 Jul 2026 00:00:00 GMT"
                Link:
                  description: Link to migration guidance for deprecated response fields.
                  schema:
                    type: string
                    example: '<https://flexmeasures.readthedocs.io/latest/api/v3_0.html#get--api-v3_0-jobs-uuid>; rel="deprecation"; type="text/html"'
                FlexMeasures-Deprecated-Response-Fields:
                  description: Comma-separated response fields that are deprecated.
                  schema:
                    type: string
                    example: "func_name, enqueued_at, started_at, ended_at, exc_info"
            404:
              description: NOT_FOUND
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            503:
              description: SERVICE_UNAVAILABLE
          tags:
            - Jobs
        """
        connection = current_app.redis_connection

        try:
            connection.ping()
            job = Job.fetch(job_id, connection=connection)
            read_context = _job_read_context(job)
            if read_context is not None:
                check_access(read_context, "read")
        except NoSuchJobError:
            return (
                dict(
                    status="ERROR",
                    message=f"Job {job_id} not found.",
                ),
                404,
            )
        except RedisConnectionError:
            return _job_queue_unavailable_response()

        try:
            job_status = job.get_status()
            status_name = (
                job_status.name
                if isinstance(job_status, JobStatus)
                else str(job_status).upper()
            )

            # job.return_value is None when the job has not finished successfully
            result = job.return_value()
        except RedisConnectionError:
            return _job_queue_unavailable_response()
        except Exception:  # noqa: BLE001
            result = None

        response = dict(
            status=status_name,
            message=job_status_description(job),
            result=result,
            origin=job.origin,
        )
        response["func-name"] = job.func_name
        response["enqueued-at"] = _isoformat_or_none(job.enqueued_at)
        response["started-at"] = _isoformat_or_none(job.started_at)
        response["ended-at"] = _isoformat_or_none(job.ended_at)
        response["exc-info"] = failed_job_exc_info(job)
        response["func_name"] = response["func-name"]
        response["enqueued_at"] = response["enqueued-at"]
        response["started_at"] = response["started-at"]
        response["ended_at"] = response["ended-at"]
        response["exc_info"] = response["exc-info"]

        if status_name == JobStatus.FAILED.name:
            status_code = 422
        elif status_name == JobStatus.FINISHED.name:
            status_code = 200
        else:
            status_code = 202

        return (
            response,
            status_code,
            deprecated_response_fields_headers(
                JOB_STATUS_DEPRECATED_RESPONSE_FIELDS,
                JOBS_API_DOCS_URL,
                JOB_RESPONSE_FIELDS_DEPRECATION_DATE,
            ),
        )
