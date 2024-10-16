from __future__ import annotations

from datetime import datetime, timedelta

from flask import current_app, url_for
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required
import isodate
from marshmallow import fields, ValidationError
from rq.job import Job, NoSuchJobError
from timely_beliefs import BeliefsDataFrame
from webargs.flaskparser import use_args, use_kwargs
from sqlalchemy import delete

from flexmeasures.api.common.responses import (
    request_processed,
    unrecognized_event,
    unknown_schedule,
    invalid_flex_config,
    fallback_schedule_redirect,
)
from flexmeasures.api.common.utils.validators import (
    optional_duration_accepted,
)
from flexmeasures.api.common.schemas.sensor_data import (
    GetSensorDataSchema,
    PostSensorDataSchema,
)
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.api.common.utils.api_utils import save_and_enqueue
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.queries.utils import simplify_index
from flexmeasures.data.schemas.sensors import SensorSchema, SensorIdField
from flexmeasures.data.schemas.times import AwareDateTimeField, PlanningDurationField
from flexmeasures.data.services.sensors import get_sensors, get_sensor_stats
from flexmeasures.data.services.scheduling import (
    create_scheduling_job,
    get_data_source_for_job,
)
from flexmeasures.utils.time_utils import duration_isoformat


# Instantiate schemas outside of endpoint logic to minimize response time
get_sensor_schema = GetSensorDataSchema()
post_sensor_schema = PostSensorDataSchema()
sensors_schema = SensorSchema(many=True)
sensor_schema = SensorSchema()
partial_sensor_schema = SensorSchema(partial=True, exclude=["generic_asset_id"])


class SensorAPI(FlaskView):
    route_base = "/sensors"
    trailing_slash = False
    decorators = [auth_required()]

    @route("", methods=["GET"])
    @use_kwargs(
        {
            "account": AccountIdField(
                data_key="account_id", load_default=AccountIdField.load_current
            ),
        },
        location="query",
    )
    @permission_required_for_context("read", ctx_arg_name="account")
    @as_json
    def index(self, account: Account):
        """API endpoint to list all sensors of an account.

        .. :quickref: Sensor; Download sensor list

        This endpoint returns all accessible sensors.
        Accessible sensors are sensors in the same account as the current user.
        Only admins can use this endpoint to fetch sensors from a different account (by using the `account_id` query parameter).

        **Example response**

        An example of one sensor being returned:

        .. sourcecode:: json

            [
                {
                    "entity_address": "ea1.2021-01.io.flexmeasures.company:fm1.42",
                    "event_resolution": PT15M,
                    "generic_asset_id": 1,
                    "name": "Gas demand",
                    "timezone": "Europe/Amsterdam",
                    "unit": "m\u00b3/h"
                    "id": 2
                }
            ]

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        sensors = get_sensors(account=account)
        return sensors_schema.dump(sensors), 200

    @route("/data", methods=["POST"])
    @use_args(
        post_sensor_schema,
        location="json",
    )
    @permission_required_for_context(
        "create-children",
        ctx_arg_pos=1,
        ctx_loader=lambda bdf: bdf.sensor,
        pass_ctx_to_loader=True,
    )
    def post_data(self, bdf: BeliefsDataFrame):
        """
        Post sensor data to FlexMeasures.

        .. :quickref: Data; Upload sensor data

        **Example request**

        .. code-block:: json

            {
                "sensor": "ea1.2021-01.io.flexmeasures:fm1.1",
                "values": [-11.28, -11.28, -11.28, -11.28],
                "start": "2021-06-07T00:00:00+02:00",
                "duration": "PT1H",
                "unit": "m³/h"
            }

        The above request posts four values for a duration of one hour, where the first
        event start is at the given start time, and subsequent events start in 15 minute intervals throughout the one hour duration.

        The sensor is the one with ID=1.
        The unit has to be convertible to the sensor's unit.
        The resolution of the data has to match the sensor's required resolution, but
        FlexMeasures will attempt to upsample lower resolutions.
        The list of values may include null values.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        response, code = save_and_enqueue(bdf)
        return response, code

    @route("/data", methods=["GET"])
    @use_args(
        get_sensor_schema,
        location="query",
    )
    @permission_required_for_context("read", ctx_arg_pos=1, ctx_arg_name="sensor")
    def get_data(self, sensor_data_description: dict):
        """Get sensor data from FlexMeasures.

        .. :quickref: Data; Download sensor data

        **Example request**

        .. code-block:: json

            {
                "sensor": "ea1.2021-01.io.flexmeasures:fm1.1",
                "start": "2021-06-07T00:00:00+02:00",
                "duration": "PT1H",
                "resolution": "PT15M",
                "unit": "m³/h"
            }

        The unit has to be convertible from the sensor's unit.

        **Optional fields**

        - "resolution" (see :ref:`frequency_and_resolution`)
        - "horizon" (see :ref:`beliefs`)
        - "prior" (see :ref:`beliefs`)
        - "source" (see :ref:`sources`)

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        response = GetSensorDataSchema.load_data_and_make_response(
            sensor_data_description
        )
        d, s = request_processed()
        return dict(**response, **d), s

    @route("/<id>/schedules/trigger", methods=["POST"])
    @use_kwargs(
        {"sensor": SensorIdField(data_key="id")},
        location="path",
    )
    @use_kwargs(
        {
            "start_of_schedule": AwareDateTimeField(
                data_key="start", format="iso", required=True
            ),
            "belief_time": AwareDateTimeField(format="iso", data_key="prior"),
            "duration": PlanningDurationField(
                load_default=PlanningDurationField.load_default
            ),
            "flex_model": fields.Dict(data_key="flex-model"),
            "flex_context": fields.Dict(required=False, data_key="flex-context"),
            "force_new_job_creation": fields.Boolean(required=False),
        },
        location="json",
    )
    @permission_required_for_context("create-children", ctx_arg_name="sensor")
    def trigger_schedule(
        self,
        sensor: Sensor,
        start_of_schedule: datetime,
        duration: timedelta,
        belief_time: datetime | None = None,
        flex_model: dict | None = None,
        flex_context: dict | None = None,
        force_new_job_creation: bool | None = False,
        **kwargs,
    ):
        """
        Trigger FlexMeasures to create a schedule.

        .. :quickref: Schedule; Trigger scheduling job

        Trigger FlexMeasures to create a schedule for this sensor.
        The assumption is that this sensor is the power sensor on a flexible asset.

        In this request, you can describe:

        - the schedule's main features (when does it start, what unit should it report, prior to what time can we assume knowledge)
        - the flexibility model for the sensor (state and constraint variables, e.g. current state of charge of a battery, or connection capacity)
        - the flexibility context which the sensor operates in (other sensors under the same EMS which are relevant, e.g. prices)

        For details on flexibility model and context, see :ref:`describing_flexibility`.
        Below, we'll also list some examples.

        .. note:: This endpoint does not support to schedule an EMS with multiple flexible sensors at once. This will happen in another endpoint.
                  See https://github.com/FlexMeasures/flexmeasures/issues/485. Until then, it is possible to call this endpoint for one flexible endpoint at a time
                  (considering already scheduled sensors as inflexible).

        The length of the schedule can be set explicitly through the 'duration' field.
        Otherwise, it is set by the config setting :ref:`planning_horizon_config`, which defaults to 48 hours.
        If the flex-model contains targets that lie beyond the planning horizon, the length of the schedule is extended to accommodate them.
        Finally, the schedule length is limited by :ref:`max_planning_horizon_config`, which defaults to 2520 steps of the sensor's resolution.
        Targets that exceed the max planning horizon are not accepted.

        The appropriate algorithm is chosen by FlexMeasures (based on asset type).
        It's also possible to use custom schedulers and custom flexibility models, see :ref:`plugin_customization`.

        If you have ideas for algorithms that should be part of FlexMeasures, let us know: https://flexmeasures.io/get-in-touch/

        **Example request A**

        This message triggers a schedule for a storage asset, starting at 10.00am, at which the state of charge (soc) is 12.1 kWh.

        .. code-block:: json

            {
                "start": "2015-06-02T10:00:00+00:00",
                "flex-model": {
                    "soc-at-start": "12.1 kWh"
                }
            }

        **Example request B**

        This message triggers a 24-hour schedule for a storage asset, starting at 10.00am,
        at which the state of charge (soc) is 12.1 kWh, with a target state of charge of 25 kWh at 4.00pm.

        The charging efficiency is constant (120%) and the discharging efficiency is determined by the contents of sensor
        with id 98. If just the ``roundtrip-efficiency`` is known, it can be described with its own field.
        The global minimum and maximum soc are set to 10 and 25 kWh, respectively.
        To guarantee a minimum SOC in the period prior, the sensor with ID 300 contains beliefs at 2.00pm and 3.00pm, for 15kWh and 20kWh, respectively.
        Storage efficiency is set to 99.99%, denoting the state of charge left after each time step equal to the sensor's resolution.
        Aggregate consumption (of all devices within this EMS) should be priced by sensor 9,
        and aggregate production should be priced by sensor 10,
        where the aggregate power flow in the EMS is described by the sum over sensors 13, 14 and 15
        (plus the flexible sensor being optimized, of course).


        The battery consumption power capacity is limited by sensor 42 and the production capacity is constant (30 kW).
        Finally, the site consumption capacity is limited by sensor 32.

        Note that, if forecasts for sensors 13, 14 and 15 are not available, a schedule cannot be computed.

        .. code-block:: json

            {
                "start": "2015-06-02T10:00:00+00:00",
                "duration": "PT24H",
                "flex-model": {
                    "soc-at-start": "12.1 kWh",
                    "soc-targets": [
                        {
                            "value": "25 kWh",
                            "datetime": "2015-06-02T16:00:00+00:00"
                        },
                    ],
                    "soc-minima": {"sensor" : 300},
                    "soc-min": "10 kWh",
                    "soc-max": "25 kWh",
                    "charging-efficiency": "120%",
                    "discharging-efficiency": {"sensor": 98},
                    "storage-efficiency": 0.9999,
                    "power-capacity": "25kW",
                    "consumption-capacity" : {"sensor": 42},
                    "production-capacity" : "30 kW"
                },
                "flex-context": {
                    "consumption-price": {"sensor": 9},
                    "production-price": {"sensor": 10},
                    "inflexible-device-sensors": [13, 14, 15],
                    "site-power-capacity": "100kW",
                    "site-production-capacity": "80kW",
                    "site-consumption-capacity": {"sensor": 32}
                }
            }

        **Example response**

        This message indicates that the scheduling request has been processed without any error.
        A scheduling job has been created with some Universally Unique Identifier (UUID),
        which will be picked up by a worker.
        The given UUID may be used to obtain the resulting schedule: see /sensors/<id>/schedules/<uuid>.

        .. sourcecode:: json

            {
                "status": "PROCESSED",
                "schedule": "364bfd06-c1fa-430b-8d25-8f5a547651fb",
                "message": "Request has been processed."
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_DATA
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 405: INVALID_METHOD
        :status 422: UNPROCESSABLE_ENTITY
        """
        end_of_schedule = start_of_schedule + duration
        scheduler_kwargs = dict(
            asset_or_sensor=sensor,
            start=start_of_schedule,
            end=end_of_schedule,
            resolution=sensor.event_resolution,
            belief_time=belief_time,  # server time if no prior time was sent
            flex_model=flex_model,
            flex_context=flex_context,
        )

        try:
            job = create_scheduling_job(
                **scheduler_kwargs,
                enqueue=True,
                force_new_job_creation=force_new_job_creation,
            )
        except ValidationError as err:
            return invalid_flex_config(err.messages)
        except ValueError as err:
            return invalid_flex_config(str(err))

        db.session.commit()

        response = dict(schedule=job.id)
        d, s = request_processed()
        return dict(**response, **d), s

    @route("/<id>/schedules/<uuid>", methods=["GET"])
    @use_kwargs(
        {
            "sensor": SensorIdField(data_key="id"),
            "job_id": fields.Str(data_key="uuid"),
        },
        location="path",
    )
    @optional_duration_accepted(
        timedelta(hours=6)
    )  # todo: make this a Marshmallow field
    @permission_required_for_context("read", ctx_arg_name="sensor")
    def get_schedule(  # noqa: C901
        self, sensor: Sensor, job_id: str, duration: timedelta, **kwargs
    ):
        """Get a schedule from FlexMeasures.

        .. :quickref: Schedule; Download schedule from the platform

        **Optional fields**

        - "duration" (6 hours by default; can be increased to plan further into the future)

        **Example response**

        This message contains a schedule indicating to consume at various power
        rates from 10am UTC onwards for a duration of 45 minutes.

        .. sourcecode:: json

            {
                "values": [
                    2.15,
                    3,
                    2
                ],
                "start": "2015-06-02T10:00:00+00:00",
                "duration": "PT45M",
                "unit": "MW"
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_TIMEZONE, INVALID_DOMAIN, INVALID_UNIT, UNKNOWN_SCHEDULE, UNRECOGNIZED_CONNECTION_GROUP
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 405: INVALID_METHOD
        :status 422: UNPROCESSABLE_ENTITY
        """

        planning_horizon = min(  # type: ignore
            duration, current_app.config.get("FLEXMEASURES_PLANNING_HORIZON")
        )

        # Look up the scheduling job
        connection = current_app.queues["scheduling"].connection

        try:  # First try the scheduling queue
            job = Job.fetch(job_id, connection=connection)
        except NoSuchJobError:
            return unrecognized_event(job_id, "job")

        if (
            not current_app.config.get("FLEXMEASURES_FALLBACK_REDIRECT")
            and job.is_failed
            and (job.meta.get("fallback_job_id") is not None)
        ):
            try:  # First try the scheduling queue
                job = Job.fetch(job.meta["fallback_job_id"], connection=connection)
            except NoSuchJobError:
                current_app.logger.error(
                    f"Fallback job with ID={job.meta['fallback_job_id']} (originator Job ID={job_id}) not found."
                )
                return unrecognized_event(job.meta["fallback_job_id"], "fallback-job")

        scheduler_info_msg = ""
        scheduler_info = job.meta.get("scheduler_info", dict(scheduler=""))
        scheduler_info_msg = f"{scheduler_info['scheduler']} was used."

        if job.is_finished:
            error_message = "A scheduling job has been processed with your job ID, but "

        elif job.is_failed:  # Try to inform the user on why the job failed
            e = job.meta.get(
                "exception",
                Exception(
                    "The job does not state why it failed. "
                    "The worker may be missing an exception handler, "
                    "or its exception handler is not storing the exception as job meta data."
                ),
            )
            message = f"Scheduling job failed with {type(e).__name__}: {e}. {scheduler_info_msg}"

            fallback_job_id = job.meta.get("fallback_job_id")

            # redirect to the fallback schedule endpoint if the fallback_job_id
            # is defined in the metadata of the original job
            if fallback_job_id is not None:
                return fallback_schedule_redirect(
                    message,
                    url_for(
                        "SensorAPI:get_schedule",
                        uuid=fallback_job_id,
                        id=sensor.id,
                        _external=True,
                    ),
                )
            else:
                return unknown_schedule(message)

        elif job.is_started:
            return unknown_schedule(f"Scheduling job in progress. {scheduler_info_msg}")
        elif job.is_queued:
            return unknown_schedule(
                f"Scheduling job waiting to be processed. {scheduler_info_msg}"
            )
        elif job.is_deferred:
            try:
                preferred_job = job.dependency
            except NoSuchJobError:
                return unknown_schedule(
                    f"Scheduling job waiting for unknown job to be processed. {scheduler_info_msg}"
                )
            return unknown_schedule(
                f'Scheduling job waiting for {preferred_job.status} job "{preferred_job.id}" to be processed. {scheduler_info_msg}'
            )
        else:
            return unknown_schedule(
                f"Scheduling job has an unknown status. {scheduler_info_msg}"
            )
        schedule_start = job.kwargs["start"]

        data_source = get_data_source_for_job(job)
        if data_source is None:
            return unknown_schedule(
                error_message
                + f"no data source could be found for {data_source}. {scheduler_info_msg}"
            )

        power_values = sensor.search_beliefs(
            event_starts_after=schedule_start,
            event_ends_before=schedule_start + planning_horizon,
            source=data_source,
            most_recent_beliefs_only=True,
            one_deterministic_belief_per_event=True,
        )

        sign = 1
        if sensor.get_attribute("consumption_is_positive", True):
            sign = -1

        # For consumption schedules, positive values denote consumption. For the db, consumption is negative
        consumption_schedule = sign * simplify_index(power_values)["event_value"]
        if consumption_schedule.empty:
            return unknown_schedule(
                f"{error_message} the schedule was not found in the database. {scheduler_info_msg}"
            )

        # Update the planning window
        resolution = sensor.event_resolution
        start = consumption_schedule.index[0]
        duration = min(duration, consumption_schedule.index[-1] + resolution - start)
        consumption_schedule = consumption_schedule[
            start : start + duration - resolution
        ]
        response = dict(
            values=consumption_schedule.tolist(),
            start=isodate.datetime_isoformat(start),
            duration=duration_isoformat(duration),
            unit=sensor.unit,
        )

        d, s = request_processed(scheduler_info_msg)
        return dict(scheduler_info=scheduler_info, **response, **d), s

    @route("/<id>", methods=["GET"])
    @use_kwargs({"sensor": SensorIdField(data_key="id")}, location="path")
    @permission_required_for_context("read", ctx_arg_name="sensor")
    @as_json
    def fetch_one(self, id, sensor):
        """Fetch a given sensor.

        .. :quickref: Sensor; Get a sensor

        This endpoint gets a sensor.

        **Example response**

        .. sourcecode:: json

            {
                "name": "some gas sensor",
                "unit": "m³/h",
                "entity_address": "ea1.2023-08.localhost:fm1.1",
                "event_resolution": "PT10M",
                "generic_asset_id": 4,
                "timezone": "UTC",
                "id": 2
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """

        return sensor_schema.dump(sensor), 200

    @route("", methods=["POST"])
    @use_args(sensor_schema)
    @permission_required_for_context(
        "create-children",
        ctx_arg_pos=1,
        ctx_arg_name="generic_asset_id",
        ctx_loader=GenericAsset,
        pass_ctx_to_loader=True,
    )
    def post(self, sensor_data: dict):
        """Create new sensor.

        .. :quickref: Sensor; Create a new Sensor

        This endpoint creates a new Sensor.

        **Example request**

        .. sourcecode:: json

            {
                "name": "power",
                "event_resolution": "PT1H",
                "unit": "kWh",
                "generic_asset_id": 1,
            }

        **Example response**

        The whole sensor is returned in the response:

        .. sourcecode:: json

            {
                "name": "power",
                "unit": "kWh",
                "entity_address": "ea1.2023-08.localhost:fm1.1",
                "event_resolution": "PT1H",
                "generic_asset_id": 1,
                "timezone": "UTC",
                "id": 2
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 201: CREATED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        sensor = Sensor(**sensor_data)
        db.session.add(sensor)
        db.session.commit()

        asset = sensor_schema.context["generic_asset"]
        AssetAuditLog.add_record(asset, f"Created sensor '{sensor.name}': {sensor.id}")

        return sensor_schema.dump(sensor), 201

    @route("/<id>", methods=["PATCH"])
    @use_args(partial_sensor_schema)
    @use_kwargs({"sensor": SensorIdField(data_key="id")}, location="path")
    @permission_required_for_context("update", ctx_arg_name="sensor")
    @as_json
    def patch(self, sensor_data: dict, id: int, sensor: Sensor):
        """Update a sensor given its identifier.

        .. :quickref: Sensor; Update a sensor

        This endpoint updates the descriptive data of an existing sensor.

        Any subset of sensor fields can be sent.
        However, the following fields are not allowed to be updated:
        - id
        - generic_asset_id
        - entity_address

        Only admin users have rights to update the sensor fields. Be aware that changing unit, event resolution and knowledge horizon should currently only be done on sensors without existing belief data (to avoid a serious mismatch), or if you really know what you are doing.

        **Example request**

        .. sourcecode:: json

            {
                "name": "POWER",
            }

        **Example response**

        The whole sensor is returned in the response:

        .. sourcecode:: json

            {
                "name": "some gas sensor",
                "unit": "m³/h",
                "entity_address": "ea1.2023-08.localhost:fm1.1",
                "event_resolution": "PT10M",
                "generic_asset_id": 4,
                "timezone": "UTC",
                "id": 2
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: UPDATED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        audit_log_data = list()
        for k, v in sensor_data.items():
            if getattr(sensor, k) != v:
                audit_log_data.append(
                    f"Field name: {k}, Old value: {getattr(sensor, k)}, New value: {v}"
                )
        audit_log_event = f"Updated sensor '{sensor.name}': {sensor.id}. Updated fields: {'; '.join(audit_log_data)}"

        AssetAuditLog.add_record(sensor.generic_asset, audit_log_event)

        for k, v in sensor_data.items():
            setattr(sensor, k, v)
        db.session.add(sensor)
        db.session.commit()
        return sensor_schema.dump(sensor), 200

    @route("/<id>", methods=["DELETE"])
    @use_kwargs({"sensor": SensorIdField(data_key="id")}, location="path")
    @permission_required_for_context("delete", ctx_arg_name="sensor")
    @as_json
    def delete(self, id: int, sensor: Sensor):
        """Delete a sensor given its identifier.

        .. :quickref: Sensor; Delete a sensor

        This endpoint deletes an existing sensor, as well as all measurements recorded for it.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 204: DELETED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """

        """Delete time series data."""
        db.session.execute(delete(TimedBelief).filter_by(sensor_id=sensor.id))

        AssetAuditLog.add_record(
            sensor.generic_asset, f"Deleted sensor '{sensor.name}': {sensor.id}"
        )

        sensor_name = sensor.name
        db.session.execute(delete(Sensor).filter_by(id=sensor.id))
        db.session.commit()
        current_app.logger.info("Deleted sensor '%s'." % sensor_name)
        return {}, 204

    @route("/<id>/stats", methods=["GET"])
    @use_kwargs({"sensor": SensorIdField(data_key="id")}, location="path")
    @permission_required_for_context("read", ctx_arg_name="sensor")
    @as_json
    def get_stats(self, id, sensor):
        """Fetch stats for a given sensor.

        .. :quickref: Sensor; Get sensor stats

        This endpoint fetches sensor stats for all the historical data.

        Example response

        .. sourcecode:: json

            {
                "some data source": {
                    "min_event_start": "2015-06-02T10:00:00+00:00",
                    "max_event_start": "2015-10-02T10:00:00+00:00",
                    "min_value": 0.0,
                    "max_value": 100.0,
                    "mean_value": 50.0,
                    "sum_values": 500.0,
                    "count_values": 10
                }
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """

        return get_sensor_stats(sensor), 200
