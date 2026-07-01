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


def _transform_asset_keyed_to_list(
    asset_keyed_targets: dict,
) -> list[dict]:
    """Transform asset-keyed constraint targets to list format for API response.

    Converts internal storage format (dict keyed by asset ID) to the API response
    format (list of dicts with explicit "asset" field). The list format is more
    natural for JSON consumers and avoids issues with numeric asset keys in JSON
    serialization.

    Args:
        asset_keyed_targets: Dict keyed by asset ID string, with constraint info as values

    Returns:
        List of dicts, each with "asset" field and constraint keys ("soc-minima", "soc-maxima")
    """
    if not asset_keyed_targets:
        return []

    result = []

    for asset_id_str, constraints in asset_keyed_targets.items():
        try:
            asset_id = int(asset_id_str)
        except (ValueError, TypeError):
            continue

        entry = {"asset": asset_id}

        # Add constraint information
        for constraint_type, constraint_data in constraints.items():
            entry[constraint_type] = constraint_data

        result.append(entry)

    return result


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
            state-of-charge constraint analysis. Results are keyed by asset ID,
            with ``unresolved`` constraints that cannot be satisfied and ``resolved``
            constraints with available headroom.

            **Note**: The scheduling_result is only available via the jobs endpoint
            (this endpoint). It is not available through the sensor schedule endpoint
            (which has been superseded for constraint analysis).
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
            # Transform from internal asset-keyed format to API list format
            # Each unresolved/resolved entry includes "asset" field with asset ID
            response["scheduling_result"] = {
                "unresolved": _transform_asset_keyed_to_list(
                    scheduling_result.get("unresolved", {})
                    if isinstance(scheduling_result, dict)
                    else scheduling_result.unresolved
                ),
                "resolved": _transform_asset_keyed_to_list(
                    scheduling_result.get("resolved", {})
                    if isinstance(scheduling_result, dict)
                    else scheduling_result.resolved
                ),
            }

        return response, 200
