from __future__ import annotations

from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required
from rq.job import Job, JobStatus, NoSuchJobError
from webargs.flaskparser import use_kwargs
from marshmallow import fields

from flexmeasures.api.common.utils.api_utils import job_status_description


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
            Returns the current execution status and a human-readable result
            message for any background job (scheduling, forecasting, etc.)
            identified by its UUID.

            While the job is pending or running this endpoint returns its
            current status.  Once finished (successfully or not) it also
            includes a descriptive message.
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
                  examples:
                    queued:
                      summary: Queued job
                      value:
                        status: QUEUED
                        message: "Scheduling job waiting to be processed."
                    finished:
                      summary: Finished job
                      value:
                        status: FINISHED
                        message: "Scheduling job has finished."
                    failed:
                      summary: Failed job
                      value:
                        status: FAILED
                        message: "Scheduling job failed with ValueError: ..."
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

        return (
            dict(
                status=status_name,
                message=job_status_description(job),
            ),
            200,
        )
