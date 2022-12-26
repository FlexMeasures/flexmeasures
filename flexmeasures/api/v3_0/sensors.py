from datetime import datetime, timedelta
from typing import List, Optional

from flask import current_app, request
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required, current_user
import isodate
from marshmallow import validate, fields, Schema
from marshmallow.validate import OneOf
import numpy as np
import pandas as pd
from rq.job import Job, NoSuchJobError
import timely_beliefs as tb
from webargs.flaskparser import use_args, use_kwargs

from flexmeasures.api.common.responses import (
    invalid_datetime,
    invalid_timezone,
    request_processed,
    unrecognized_event,
    unknown_schedule,
    ptus_incomplete,
)
from flexmeasures.api.common.utils.validators import (
    optional_duration_accepted,
    optional_prior_accepted,
)
from flexmeasures.api.common.schemas.sensor_data import (
    GetSensorDataSchema,
    PostSensorDataSchema,
)
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.api.common.utils.api_utils import save_and_enqueue
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data.models.planning.utils import initialize_series
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.queries.utils import simplify_index
from flexmeasures.data.schemas.sensors import SensorSchema, SensorIdField
from flexmeasures.data.schemas.units import QuantityField
from flexmeasures.data.schemas import AwareDateTimeField
from flexmeasures.data.services.sensors import get_sensors
from flexmeasures.data.services.scheduling import (
    create_scheduling_job,
    get_data_source_for_job,
)
from flexmeasures.utils.time_utils import duration_isoformat
from flexmeasures.utils.unit_utils import ur


class TargetSchema(Schema):
    value = fields.Float()
    datetime = AwareDateTimeField()


# Instantiate schemas outside of endpoint logic to minimize response time
get_sensor_schema = GetSensorDataSchema()
post_sensor_schema = PostSensorDataSchema()
sensors_schema = SensorSchema(many=True)


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
    @permission_required_for_context("read", arg_name="account")
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
                    "event_resolution": 15,
                    "generic_asset_id": 1,
                    "name": "Gas demand",
                    "timezone": "Europe/Amsterdam",
                    "unit": "m\u00b3/h"
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

    @route("<id>/data/upload", methods=["POST"])
    @use_kwargs(
        {"sensor": SensorIdField(data_key="id")},
        location="path",
    )
    def upload_data(self, sensor, **kwargs):
        dfs = []
        for f in list(request.files.listvalues())[0]:
            df = tb.read_csv(
                f,
                sensor,
                source=current_user.data_source[0],
                belief_time=pd.Timestamp.utcnow(),
                resample=True,
            )
            print(df)
            dfs.append(df)
        response, code = save_and_enqueue(dfs)
        return response, code

    @route("/data", methods=["POST"])
    @use_args(
        post_sensor_schema,
        location="json",
    )
    def post_data(self, bdf: tb.BeliefsDataFrame):
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
    def get_data(self, response: dict):
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
        d, s = request_processed()
        return dict(**response, **d), s

    @route("/<id>/schedules/trigger", methods=["POST"])
    @use_kwargs(
        {"sensor": SensorIdField(data_key="id")},
        location="path",
    )
    @use_kwargs(
        {
            "soc_sensor_id": fields.Str(data_key="soc-sensor", required=False),
            "roundtrip_efficiency": QuantityField(
                "%",
                validate=validate.Range(min=0, max=1),
                data_key="roundtrip-efficiency",
            ),
            "start_value": fields.Float(data_key="soc-at-start"),
            "soc_min": fields.Float(data_key="soc-min"),
            "soc_max": fields.Float(data_key="soc-max"),
            "start_of_schedule": AwareDateTimeField(
                data_key="start", format="iso", required=False
            ),
            "unit": fields.Str(
                data_key="soc-unit",
                validate=OneOf(
                    [
                        "kWh",
                        "MWh",
                    ]
                ),
            ),  # todo: allow unit to be set per field, using QuantityField("%", validate=validate.Range(min=0, max=1))
            "targets": fields.List(fields.Nested(TargetSchema), data_key="soc-targets"),
            "prefer_charging_sooner": fields.Bool(
                data_key="prefer-charging-sooner", required=False
            ),
            # todo: add a duration parameter, instead of falling back to FLEXMEASURES_PLANNING_HORIZON
            "consumption_price_sensor": SensorIdField(
                data_key="consumption-price-sensor", required=False
            ),
            "production_price_sensor": SensorIdField(
                data_key="production-price-sensor", required=False
            ),
            "inflexible_device_sensors": fields.List(
                SensorIdField, data_key="inflexible-device-sensors", required=False
            ),
        },
        location="json",
    )
    @optional_prior_accepted()
    def trigger_schedule(  # noqa: C901
        self,
        sensor: Sensor,
        start_of_schedule: datetime,
        unit: str,
        prior: datetime,
        roundtrip_efficiency: Optional[ur.Quantity] = None,
        prefer_charging_sooner: Optional[bool] = True,
        consumption_price_sensor: Optional[Sensor] = None,
        production_price_sensor: Optional[Sensor] = None,
        inflexible_device_sensors: Optional[List[Sensor]] = None,
        **kwargs,
    ):
        """
        Trigger FlexMeasures to create a schedule.

        .. :quickref: Schedule; Trigger scheduling job

        Trigger FlexMeasures to create a schedule for this sensor.
        The assumption is that this sensor is the power sensor on a flexible asset.

        In this request, you can describe:

        - the schedule (start, unit, prior)
        - the flexibility model for the sensor (see below, only storage models are supported at the moment)
        - the EMS the sensor operates in (inflexible device sensors, and sensors that put a price on consumption and/or production)

        Note: This endpoint does not support to schedule an EMS with multiple flexible sensors at once. This will happen in another endpoint.
              See https://github.com/FlexMeasures/flexmeasures/issues/485. Until then, it is possible to call this endpoint for one flexible endpoint at a time
              (considering already scheduled sensors as inflexible).

        Flexibility models apply to the sensor's asset type:

        1) For storage sensors (e.g. battery, charge points), the schedule deals with the state of charge (SOC).
           The possible flexibility parameters are:

            - soc-at-start (defaults to 0)
            - soc-unit (kWh or MWh)
            - soc-min (defaults to 0)
            - soc-max (defaults to max soc target)
            - soc-targets (defaults to NaN values)
            - roundtrip-efficiency (defaults to 100%)
            - prefer-charging-sooner (defaults to True, also signals a preference to discharge later)

        2) Heat pump sensors are work in progress.

        **Example request A**

        This message triggers a schedule for a storage asset, starting at 10.00am, at which the state of charge (soc) is 12.1 kWh.

        .. code-block:: json

            {
                "start": "2015-06-02T10:00:00+00:00",
                "soc-at-start": 12.1,
                "soc-unit": "kWh"
            }

        **Example request B**

        This message triggers a schedule starting at 10.00am, at which the state of charge (soc) is 12.1 kWh,
        with a target state of charge of 25 kWh at 4.00pm.
        The minimum and maximum soc are set to 10 and 25 kWh, respectively.
        Roundtrip efficiency for use in scheduling is set to 98%.
        Aggregate consumption (of all devices within this EMS) should be priced by sensor 9,
        and aggregate production should be priced by sensor 10,
        where the aggregate power flow in the EMS is described by the sum over sensors 13, 14 and 15
        (plus the flexible sensor being optimized, of course).
        Note that, if forecasts for sensors 13, 14 and 15 are not available, a schedule cannot be computed.

        .. code-block:: json

            {
                "start": "2015-06-02T10:00:00+00:00",
                "soc-at-start": 12.1,
                "soc-unit": "kWh",
                "soc-targets": [
                    {
                        "value": 25,
                        "datetime": "2015-06-02T16:00:00+00:00"
                    }
                ],
                "soc-min": 10,
                "soc-max": 25,
                "roundtrip-efficiency": 0.98,
                "consumption-price-sensor": 9,
                "production-price-sensor": 10,
                "inflexible-device-sensors": [13, 14, 15]
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
        :status 400: INVALID_TIMEZONE, INVALID_DATETIME, INVALID_DOMAIN, INVALID_UNIT, PTUS_INCOMPLETE
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 405: INVALID_METHOD
        """
        # todo: if a soc-sensor entity address is passed, persist those values to the corresponding sensor
        #       (also update the note in posting_data.rst about flexibility states not being persisted).

        # get starting value
        if "start_value" not in kwargs:
            return ptus_incomplete()
        try:
            start_value = float(kwargs.get("start_value"))  # type: ignore
        except ValueError:
            extra_info = "Request includes empty or ill-formatted value(s)."
            current_app.logger.warning(extra_info)
            return ptus_incomplete(extra_info)
        if unit == "kWh":
            start_value = start_value / 1000.0

        # Convert round-trip efficiency to dimensionless (to the (0,1] range)
        if roundtrip_efficiency is not None:
            roundtrip_efficiency = roundtrip_efficiency.to(
                ur.Quantity("dimensionless")
            ).magnitude

        # get optional min and max SOC
        soc_min = kwargs.get("soc_min", None)
        soc_max = kwargs.get("soc_max", None)
        # TODO: review when we moved away from capacity having to be described in MWh
        if soc_min is not None and unit == "kWh":
            soc_min = soc_min / 1000.0
        if soc_max is not None and unit == "kWh":
            soc_max = soc_max / 1000.0

        # set soc targets
        end_of_schedule = start_of_schedule + current_app.config.get(  # type: ignore
            "FLEXMEASURES_PLANNING_HORIZON"
        )
        resolution = sensor.event_resolution
        soc_targets = initialize_series(
            np.nan,
            start=start_of_schedule,
            end=end_of_schedule,
            resolution=resolution,
            inclusive="right",  # note that target values are indexed by their due date (i.e. inclusive="right")
        )
        # todo: move this deserialization of targets into newly-created ScheduleTargetSchema
        for target in kwargs.get("targets", []):

            # get target value
            if "value" not in target:
                return ptus_incomplete("Target missing 'value' parameter.")
            try:
                target_value = float(target["value"])
            except ValueError:
                extra_info = "Request includes empty or ill-formatted soc target(s)."
                current_app.logger.warning(extra_info)
                return ptus_incomplete(extra_info)
            if unit == "kWh":
                target_value = target_value / 1000.0

            # get target datetime
            if "datetime" not in target:
                return invalid_datetime("Target missing datetime parameter.")
            else:
                target_datetime = target["datetime"]
                if target_datetime is None:
                    return invalid_datetime(
                        "Cannot parse target datetime string %s as iso date"
                        % target["datetime"]
                    )
                if target_datetime.tzinfo is None:
                    current_app.logger.warning(
                        "Cannot parse timezone of target 'datetime' value %s"
                        % target["datetime"]
                    )
                    return invalid_timezone(
                        "Target datetime should explicitly state a timezone."
                    )
                if target_datetime > end_of_schedule:
                    return invalid_datetime(
                        f'Target datetime exceeds {end_of_schedule}. Maximum scheduling horizon is {current_app.config.get("FLEXMEASURES_PLANNING_HORIZON")}.'
                    )
                target_datetime = target_datetime.astimezone(
                    soc_targets.index.tzinfo
                )  # otherwise DST would be problematic

            # set target
            soc_targets.loc[target_datetime] = target_value

        job = create_scheduling_job(
            sensor,
            start_of_schedule,
            end_of_schedule,
            resolution=resolution,
            belief_time=prior,  # server time if no prior time was sent
            storage_specs=dict(
                soc_at_start=start_value,
                soc_targets=soc_targets,
                soc_min=soc_min,
                soc_max=soc_max,
                roundtrip_efficiency=roundtrip_efficiency,
                prefer_charging_sooner=prefer_charging_sooner,
            ),
            consumption_price_sensor=consumption_price_sensor,
            production_price_sensor=production_price_sensor,
            inflexible_device_sensors=inflexible_device_sensors,
            enqueue=True,
        )

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
    def get_schedule(self, sensor: Sensor, job_id: str, duration: timedelta, **kwargs):
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
            return unknown_schedule(
                f"Scheduling job failed with {type(e).__name__}: {e}"
            )
        elif job.is_started:
            return unknown_schedule("Scheduling job in progress.")
        elif job.is_queued:
            return unknown_schedule("Scheduling job waiting to be processed.")
        elif job.is_deferred:
            try:
                preferred_job = job.dependency
            except NoSuchJobError:
                return unknown_schedule(
                    "Scheduling job waiting for unknown job to be processed."
                )
            return unknown_schedule(
                f'Scheduling job waiting for {preferred_job.status} job "{preferred_job.id}" to be processed.'
            )
        else:
            return unknown_schedule("Scheduling job has an unknown status.")
        schedule_start = job.kwargs["start"]

        data_source = get_data_source_for_job(job, sensor=sensor)
        if data_source is None:
            return unknown_schedule(
                error_message + f"no data source could be found for {data_source}."
            )
        power_values = sensor.search_beliefs(
            event_starts_after=schedule_start,
            event_ends_before=schedule_start + planning_horizon,
            source=data_source,
            most_recent_beliefs_only=True,
            one_deterministic_belief_per_event=True,
        )
        # For consumption schedules, positive values denote consumption. For the db, consumption is negative
        consumption_schedule = -simplify_index(power_values)["event_value"]
        if consumption_schedule.empty:
            return unknown_schedule(
                error_message + "the schedule was not found in the database."
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

        d, s = request_processed()
        return dict(**response, **d), s
