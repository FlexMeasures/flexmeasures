"""API endpoints for job management and results."""

from __future__ import annotations

from rq.job import Job, NoSuchJobError
from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required

from flexmeasures.api.common.responses import unrecognized_event
from flexmeasures.api.common.utils.api_utils import job_status_description
from flexmeasures.data import db
from flexmeasures.data.models.time_series import Sensor


def _transform_sensor_keyed_to_asset_keyed(
    sensor_keyed_targets: dict,
) -> list[dict]:
    """Transform sensor-keyed constraint targets to asset-keyed format.

    Converts results keyed by sensor ID (from SchedulingJobResult) to asset-keyed format
    suitable for the jobs API, including both asset and sensor information in each entry.

    Args:
        sensor_keyed_targets: Dict keyed by sensor ID string, with constraint info as values

    Returns:
        List of dicts, each with "asset", "sensor", and constraint keys ("soc-minima", "soc-maxima")
    """
    if not sensor_keyed_targets:
        return []

    asset_keyed: dict[int, dict] = {}

    for sensor_id_str, constraints in sensor_keyed_targets.items():
        # Fetch the sensor to get its asset
        try:
            sensor = db.session.get(Sensor, int(sensor_id_str))
            if sensor is None:
                continue
            asset = sensor.generic_asset
            if asset is None:
                continue
        except (ValueError, TypeError):
            continue

        asset_id = asset.id

        # Initialize or update the asset entry
        if asset_id not in asset_keyed:
            asset_keyed[asset_id] = {
                "asset": asset_id,
                "sensor": sensor.id,
            }

        # Add constraint information
        for constraint_type, constraint_data in constraints.items():
            asset_keyed[asset_id][constraint_type] = constraint_data

    return list(asset_keyed.values())


class JobAPI(FlaskView):
    """Job result endpoints."""

    route_prefix = "/api/v3_0"
    trailing_slash = False

    @route("/jobs/<uuid>", methods=["GET"])
    @auth_required()
    @as_json
    def get_job_result(self, uuid: str):
        """
        .. :quickref: Jobs; Get scheduling job result

        ---
        get:
          summary: Get scheduling job result details
          description: |
            Retrieve detailed results from a scheduling job, including unmet and resolved constraints.

            This endpoint provides access to the scheduling result details that are produced by the scheduler
            during optimization. The result includes information about soft state-of-charge constraints
            (``soc-minima`` and ``soc-maxima``) that were either not met or were resolved with some margin.

            **Note:** Results are only available if a state-of-charge sensor is configured on the scheduled device.
            Hard constraints (``soc-targets``) are never reported here, as the scheduler enforces them strictly.

            Use this endpoint to:

            - Inspect which constraints could not be satisfied in the optimization
            - Understand the tightest margin on constraints that were met
            - Build dashboards showing constraint violations and margins
            - Diagnose scheduling issues

            For the full schedule (setpoints over time), use the
            `GET /api/v3_0/sensors/<id>/schedules/<uuid>` endpoint.

          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: uuid
              required: true
              description: UUID of the scheduling job, returned by the scheduling trigger endpoints.
              example: 5d28df1b-9f16-4177-ae43-6e750d80fad3
              schema:
                type: string
          responses:
            200:
              description: SUCCESS - Job result retrieved successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        type: object
                        description: |
                          Scheduling result containing unmet and resolved constraint information.
                        properties:
                          unmet:
                            type: array
                            items:
                              type: object
                            description: |
                              Array of assets/sensors with unmet soft constraints.
                              Each entry contains state-of-charge sensor information and unmet constraints.
                              An empty array means all constraints were met.

                              Each entry is an object with:

                              - ``"asset"``: Asset ID (integer) identifying the device.
                              - ``"sensor"``: (Optional) Sensor ID (integer) for the state-of-charge sensor.
                              - ``"soc-minima"``: (Optional) Array of unmet minimum SoC constraints.
                                Only present if violations exist.

                                Each constraint violation has:

                                - ``"datetime"``: ISO 8601 UTC timestamp of the first violation.
                                - ``"unmet"``: Shortage amount as a string with unit, e.g. ``"260.0 kWh"``.
                                  This is how far short the SoC fell below the minimum.

                              - ``"soc-maxima"``: (Optional) Array of unmet maximum SoC constraints.
                                Only present if violations exist.

                                Each constraint violation has:

                                - ``"datetime"``: ISO 8601 UTC timestamp of the first violation.
                                - ``"unmet"``: Excess amount as a string with unit, e.g. ``"150.0 kWh"``.
                                  This is how far the SoC exceeded the maximum.

                            example:
                              - asset: 42
                                sensor: 17
                                soc-minima:
                                  - datetime: "2024-01-15T10:30:00+00:00"
                                    unmet: "260.0 kWh"

                          resolved:
                            type: array
                            items:
                              type: object
                            description: |
                              Array of assets/sensors with met soft constraints and their margin.
                              An empty array means no constraints were defined or none were met.

                              Each entry is an object with:

                              - ``"asset"``: Asset ID (integer) identifying the device.
                              - ``"sensor"``: (Optional) Sensor ID (integer) for the state-of-charge sensor.
                              - ``"soc-minima"``: (Optional) Array of met minimum SoC constraints.
                                Only present if constraints were defined and met.

                                Each constraint has:

                                - ``"datetime"``: ISO 8601 UTC timestamp of the tightest constraint
                                  slot (the one with the smallest positive margin).
                                - ``"margin"``: Headroom as a string with unit, e.g. ``"40.0 kWh"``.
                                  This is how far above the minimum the SoC stayed.

                              - ``"soc-maxima"``: (Optional) Array of met maximum SoC constraints.
                                Only present if constraints were defined and met.

                                Each constraint has:

                                - ``"datetime"``: ISO 8601 UTC timestamp of the tightest constraint
                                  slot (the one with the smallest positive margin).
                                - ``"margin"``: Headroom as a string with unit, e.g. ``"25.0 kWh"``.
                                  This is how far below the maximum the SoC stayed.

                            example:
                              - asset: 42
                                sensor: 17
                                soc-maxima:
                                  - datetime: "2024-01-15T12:00:00+00:00"
                                    margin: "40.0 kWh"

                      status:
                        type: string
                        enum: ["PROCESSED", "PENDING", "FAILED"]
                        description: |
                          Status of the scheduling job.
                          - "PROCESSED": Job completed successfully
                          - "PENDING": Job is still running
                          - "FAILED": Job failed during execution

                      message:
                        type: string
                        description: Human-readable status message about the job.

                      scheduler_info:
                        type: object
                        description: |
                          Information about the scheduler that executed the job.
                          Contains metadata such as the scheduler name and any scheduler-specific information.
                        additionalProperties: true
                        example:
                          scheduler: "StorageScheduler"

                  examples:
                    constraints_met:
                      summary: All constraints met - no violations
                      description: |
                        This response shows a device where all state-of-charge constraints were met,
                        with some margin. Notice the empty ``unmet`` array.
                      value:
                        result:
                          unmet: []
                          resolved:
                            - asset: 42
                              sensor: 17
                              soc-minima:
                                - datetime: "2024-01-15T08:00:00+00:00"
                                  margin: "150.0 kWh"
                              soc-maxima:
                                - datetime: "2024-01-15T14:00:00+00:00"
                                  margin: "85.0 kWh"
                        status: "PROCESSED"
                        message: "Scheduling job processed successfully"
                        scheduler_info:
                          scheduler: "StorageScheduler"

                    constraints_unmet:
                      summary: Some constraints could not be met
                      description: |
                        This response shows a device where minimum state-of-charge requirements could not
                        be satisfied during the optimization horizon. The ``unmet`` array shows the first
                        violation and how much the constraint was missed by. Other constraints may still
                        have been satisfied (shown in ``resolved``).
                      value:
                        result:
                          unmet:
                            - asset: 42
                              sensor: 17
                              soc-minima:
                                - datetime: "2024-01-15T10:30:00+00:00"
                                  unmet: "260.0 kWh"
                          resolved:
                            - asset: 42
                              sensor: 17
                              soc-maxima:
                                - datetime: "2024-01-15T12:00:00+00:00"
                                  margin: "40.0 kWh"
                        status: "PROCESSED"
                        message: "Scheduling job processed successfully"
                        scheduler_info:
                          scheduler: "StorageScheduler"

                    no_constraints:
                      summary: No state-of-charge constraints defined
                      description: |
                        This response shows a device with no state-of-charge constraints defined.
                        Both ``unmet`` and ``resolved`` are empty, but the job was processed successfully.
                      value:
                        result:
                          unmet: []
                          resolved: []
                        status: "PROCESSED"
                        message: "Scheduling job processed successfully"
                        scheduler_info:
                          scheduler: "StorageScheduler"

            400:
              description: INVALID_TIMEZONE, INVALID_DOMAIN
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            404:
              description: UNRECOGNIZED_EVENT - Job UUID not found or has expired
            422:
              description: UNPROCESSABLE_ENTITY

          tags:
            - Jobs
        """

        # Look up the scheduling job
        connection = current_app.queues["scheduling"].connection

        try:
            job = Job.fetch(uuid, connection=connection)
        except NoSuchJobError:
            return unrecognized_event(uuid, "job")

        scheduler_info = job.meta.get("scheduler_info", {})

        job_status = "PENDING"
        if job.is_finished:
            job_status = "PROCESSED"
        elif job.is_failed:
            job_status = "FAILED"

        message = job_status_description(
            job, f"{scheduler_info.get('scheduler', 'Unknown')} was used."
        )

        # Extract the scheduling result if available and transform to asset-keyed format
        scheduling_result = job.meta.get("scheduling_result")
        if scheduling_result:
            # scheduling_result is a SchedulingJobResult object with sensor-keyed data
            # Transform it to asset-keyed format for the API response
            unmet_list = _transform_sensor_keyed_to_asset_keyed(
                scheduling_result.get("unresolved_targets", {})
                if isinstance(scheduling_result, dict)
                else scheduling_result.unresolved_targets
            )
            resolved_list = _transform_sensor_keyed_to_asset_keyed(
                scheduling_result.get("resolved_targets", {})
                if isinstance(scheduling_result, dict)
                else scheduling_result.resolved_targets
            )
            result_dict = {
                "unmet": unmet_list,
                "resolved": resolved_list,
            }
        else:
            result_dict = {"unmet": [], "resolved": []}

        return {
            "result": result_dict,
            "status": job_status,
            "message": message,
            "scheduler_info": scheduler_info,
        }, 200
