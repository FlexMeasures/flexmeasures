"""API endpoints for job management and results."""

from __future__ import annotations

from redis.exceptions import ConnectionError as RedisConnectionError
from rq.job import Job, NoSuchJobError
from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required

from werkzeug.exceptions import Forbidden

from flexmeasures.api.common.responses import invalid_sender
from flexmeasures.auth.policy import check_access
from flexmeasures.data.services.utils import (
    failed_job_exc_info,
    get_asset_or_sensor_from_ref,
    job_status_description,
)


class JobAPI(FlaskView):
    """Job result endpoints."""

    route_prefix = "/api/v3_0"
    trailing_slash = False

    @route("/jobs/<uuid>", methods=["GET"])
    @auth_required()
    @as_json
    def get_job_status(self, uuid: str):
        """Return execution status details for a background job.

        .. :quickref: Jobs; Get background job status

        ---
        get:
          summary: Get background job status details
          description: |
            Retrieve execution status, timestamps, result details and queue metadata
            for a background job.

            Scheduling jobs may include ``scheduling_result`` with soft
            state-of-charge constraint analysis. Results are in list format with
            ``unresolved`` constraints that cannot be satisfied and ``resolved``
            constraints with available headroom.

            **Note**: Constraint analysis is exclusively available via this endpoint
            (``GET /api/v3_0/jobs/<uuid>``). The sensor schedule endpoint
            (``GET /api/v3_0/sensors/<id>/schedules/<job_id>``) returns power values
            only and does not include constraint analysis results.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: uuid
              required: true
              description: UUID of the background job.
              schema:
                type: string
          responses:
            200:
              description: SUCCESS - Job status retrieved successfully
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            404:
              description: Job not found
            503:
              description: Job queues unavailable
          tags:
            - Jobs
        """

        try:
            current_app.redis_connection.ping()
        except RedisConnectionError:
            return {
                "status": "ERROR",
                "message": "Job queues are currently unavailable.",
            }, 503

        connection = current_app.queues["scheduling"].connection

        try:
            job = Job.fetch(uuid, connection=connection)
        except NoSuchJobError:
            return {"message": f"Job {uuid} not found."}, 404

        asset_or_sensor_ref = job.meta.get("asset_or_sensor")
        if asset_or_sensor_ref is not None:
            try:
                check_access(
                    get_asset_or_sensor_from_ref(asset_or_sensor_ref),
                    "read",
                )
            except Forbidden:
                return invalid_sender()

        scheduling_result = job.meta.get("scheduling_result")
        response = {
            "status": getattr(job.get_status(), "name", str(job.get_status()).upper()),
            "message": job_status_description(job),
            "func_name": job.func_name,
            "origin": job.origin,
            "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "ended_at": job.ended_at.isoformat() if job.ended_at else None,
            "result": job.return_value() if job.is_finished else None,
            "exc_info": failed_job_exc_info(job),
        }
        if scheduling_result is not None:
            # Constraint results are already in list format
            if isinstance(scheduling_result, dict):
                unresolved = scheduling_result.get("unresolved", [])
                resolved = scheduling_result.get("resolved", [])
            else:
                unresolved = scheduling_result.unresolved
                resolved = scheduling_result.resolved
            
            response["scheduling_result"] = {
                "unresolved": unresolved,
                "resolved": resolved,
            }

        return response, 200
