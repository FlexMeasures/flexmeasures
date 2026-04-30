from __future__ import annotations

from datetime import datetime

from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required
from rq.job import Job, JobStatus, NoSuchJobError
from webargs.flaskparser import use_kwargs
from marshmallow import fields

from flexmeasures.api.common.utils.api_utils import job_status_description


def _isoformat_or_none(dt: datetime | None) -> str | None:
    """Return an ISO-8601 string for *dt*, or ``None`` when *dt* is absent."""
    return dt.isoformat() if dt is not None else None


def _failed_job_exc_info(job: Job) -> str | None:
    """Return traceback text for failed jobs when RQ stored it."""
    if not job.is_failed:
        return None

    latest_result = job.latest_result()
    if latest_result is None:
        return None

    return latest_result.exc_string


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
              description: Job status retrieved successfully.
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
                        description: Return value of the job function, or null when not yet available.
                        nullable: true
                      func_name:
                        type: string
                        description: Fully-qualified name of the function executed by this job.
                      origin:
                        type: string
                        description: Name of the queue the job was placed on.
                      enqueued_at:
                        type: string
                        format: date-time
                        nullable: true
                        description: ISO-8601 timestamp of when the job was enqueued.
                      started_at:
                        type: string
                        format: date-time
                        nullable: true
                        description: ISO-8601 timestamp of when the job started executing.
                      ended_at:
                        type: string
                        format: date-time
                        nullable: true
                        description: ISO-8601 timestamp of when the job finished executing.
                      exc_info:
                        type: string
                        nullable: true
                        description: Traceback information for failed jobs, or null otherwise.
                  examples:
                    queued:
                      summary: Queued job
                      value:
                        status: QUEUED
                        message: "Scheduling job waiting to be processed."
                        result: null
                        func_name: "flexmeasures.data.services.scheduling.create_schedule"
                        origin: scheduling
                        enqueued_at: "2026-04-28T10:00:00+00:00"
                        started_at: null
                        ended_at: null
                        exc_info: null
                    finished:
                      summary: Finished job
                      value:
                        status: FINISHED
                        message: "Scheduling job has finished."
                        result: null
                        func_name: "flexmeasures.data.services.scheduling.create_schedule"
                        origin: scheduling
                        enqueued_at: "2026-04-28T10:00:00+00:00"
                        started_at: "2026-04-28T10:00:01+00:00"
                        ended_at: "2026-04-28T10:00:05+00:00"
                        exc_info: null
                    failed:
                      summary: Failed job
                      value:
                        status: FAILED
                        message: "Scheduling job failed with ValueError: ..."
                        result: null
                        func_name: "flexmeasures.data.services.scheduling.create_schedule"
                        origin: scheduling
                        enqueued_at: "2026-04-28T10:00:00+00:00"
                        started_at: "2026-04-28T10:00:01+00:00"
                        ended_at: "2026-04-28T10:00:02+00:00"
                        exc_info: "Traceback (most recent call last): ..."
            400:
              description: UNRECOGNIZED_JOB
            401:
              description: UNAUTHORIZED
          tags:
            - Jobs
        """
        connection = current_app.redis_connection

        try:
            job = Job.fetch(job_id, connection=connection)
        except NoSuchJobError:
            return (
                dict(
                    status="ERROR",
                    message=f"Job {job_id} not found.",
                ),
                400,
            )

        job_status = job.get_status()
        status_name = (
            job_status.name
            if isinstance(job_status, JobStatus)
            else str(job_status).upper()
        )

        # job.return_value is None when the job has not finished successfully
        try:
            result = job.return_value()
        except Exception:  # noqa: BLE001
            result = None

        return (
            dict(
                status=status_name,
                message=job_status_description(job),
                result=result,
                func_name=job.func_name,
                origin=job.origin,
                enqueued_at=_isoformat_or_none(job.enqueued_at),
                started_at=_isoformat_or_none(job.started_at),
                ended_at=_isoformat_or_none(job.ended_at),
                exc_info=_failed_job_exc_info(job),
            ),
            200,
        )
