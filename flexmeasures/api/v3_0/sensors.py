from datetime import datetime, timedelta
import json
from typing import Optional

from flask import request, current_app
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required
import isodate
from marshmallow import validate, fields, Schema
from marshmallow.validate import OneOf
import numpy as np
import pandas as pd
from rq.job import Job, NoSuchJobError
from timely_beliefs import BeliefsDataFrame
from webargs.flaskparser import use_args, use_kwargs

from flexmeasures.api.common.responses import (
    invalid_domain,
    invalid_datetime,
    invalid_timezone,
    request_processed,
    incomplete_event,
    unrecognized_event,
    unrecognized_event_type,
    unknown_schedule,
    unrecognized_connection_group,
    outdated_event_id,
    ptus_incomplete,
)
from flexmeasures.api.common.utils.validators import (
    type_accepted,
    assets_required,
    optional_duration_accepted,
    optional_prior_accepted,
    units_accepted,
    parse_isodate_str,
)
from flexmeasures.api.common.schemas.sensor_data import (
    GetSensorDataSchema,
    PostSensorDataSchema,
)
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.api.common.utils.api_utils import save_and_enqueue
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.queries.utils import simplify_index
from flexmeasures.data.schemas.sensors import SensorSchema, SensorIdField
from flexmeasures.data.schemas.units import QuantityField
from flexmeasures.data.schemas import AwareDateTimeField
from flexmeasures.data.services.sensors import get_sensors
from flexmeasures.data.services.scheduling import create_scheduling_job
from flexmeasures.utils.entity_address_utils import (
    parse_entity_address,
    EntityAddressException,
)
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

    @route("/", methods=["GET"])
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
        sensors = get_sensors(account_name=account.name)
        return sensors_schema.dump(sensors), 200

    @route("/data", methods=["POST"])
    @use_args(
        post_sensor_schema,
        location="json",
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
        event start is at the given start time, and subsequent values start in 15 minute intervals throughout the one hour duration.

        The sensor is the one with ID=1.
        The unit has to be convertible to the sensor's unit.
        The resolution of the data has to match the sensor's required resolution, but
        FlexMeasures will attempt to upsample lower resolutions.

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
                "unit": "m³/h"
            }

        The unit has to be convertible from the sensor's unit.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        return json.dumps(response)

    @route("/<id>/schedules/trigger", methods=["POST"])
    @use_kwargs(
        {"sensor": SensorIdField(data_key="id")},
        location="path",
    )
    @use_kwargs(
        {
            "roundtrip_efficiency": QuantityField(
                "%", validate=validate.Range(min=0, max=1)
            ),
            "value": fields.Float(),  # todo: in the CLI equivalent, this field is named 'soc-at-start'
            "soc-min": fields.Float(),  # todo: in postUdiEvent, this field was named 'soc_min'
            "soc-max": fields.Float(),  # todo: in postUdiEvent, this field was named 'soc_max'
            "start_of_schedule": AwareDateTimeField(
                data_key="datetime", format="iso", required=False
            ),  # todo: in the CLI equivalent, the data key for this field is named 'from'
            "event": fields.Str(),  # todo: deprecate UDI Event id
            "unit": fields.Str(
                validate=OneOf(
                    [
                        "kWh",
                        "MWh",
                    ]
                ),
            ),  # todo: allow unit to be set per field, using QuantityField("%", validate=validate.Range(min=0, max=1))
            "targets": fields.List(fields.Nested(TargetSchema)),
        },
        location="json",
    )
    @optional_prior_accepted()
    def trigger_schedule(
        self,
        sensor: Sensor,
        start_of_schedule: datetime,
        unit: str,
        prior: datetime,
        roundtrip_efficiency: Optional[ur.Quantity] = None,
        **kwargs,
    ):
        """
        Trigger FlexMeasures to create a schedule.

        .. :quickref: Schedule; Trigger scheduling job

        The message should contain a flexibility model.

        **Example request A**

        This message posts a state of charge (soc) of 12.1 kWh at 10.00am
        as UDI event 203 of device 10 of owner 7.

        .. code-block:: json

            {
                "type": "PostUdiEventRequest",
                "event": "ea1.2021-01.io.flexmeasures.company:7:10:203:soc",
                "value": 12.1,
                "unit": "kWh",
                "datetime": "2015-06-02T10:00:00+00:00"
            }

        **Example request B**

        This "PostUdiEventRequest" message posts a state of charge (soc) of 12.1 kWh at 10.00am,
        and a target state of charge of 25 kWh at 4.00pm,
        as UDI event 204 of device 10 of owner 7.
        The minimum and maximum soc are set to 10 and 25 kWh, respectively.
        Roundtrip efficiency for use in scheduling is set to 98%.

        .. code-block:: json

            {
                "type": "PostUdiEventRequest",
                "event": "ea1.2021-01.io.flexmeasures.company:fm0.7:10:204:soc-with-targets",
                "value": 12.1,
                "unit": "kWh",
                "datetime": "2015-06-02T10:00:00+00:00",
                "targets": [
                    {
                        "value": 25,
                        "datetime": "2015-06-02T16:00:00+00:00"
                    }
                ],
                "soc_min": 10,
                "soc_max": 25,
                "roundtrip_efficiency": 0.98
            }

        **Example response**

        This "PostUdiEventResponse" message indicates that the UDI event has been processed without any error.

        .. sourcecode:: json

            {
                "type": "PostUdiEventResponse",
                "status": "PROCESSED",
                "message": "Request has been processed."
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INCOMPLETE_UDI_EVENT, INVALID_MESSAGE_TYPE, INVALID_TIMEZONE, INVALID_DATETIME, INVALID_DOMAIN,
                     INVALID_UNIT, OUTDATED_UDI_EVENT, PTUS_INCOMPLETE, OUTDATED_UDI_EVENT or UNRECOGNIZED_UDI_EVENT
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 405: INVALID_METHOD
        """

        # get value
        if "value" not in kwargs:
            return ptus_incomplete()
        try:
            value = float(kwargs.get("value"))
        except ValueError:
            extra_info = "Request includes empty or ill-formatted value(s)."
            current_app.logger.warning(extra_info)
            return ptus_incomplete(extra_info)
        if unit == "kWh":
            value = value / 1000.0

        # Convert round-trip efficiency to dimensionless
        if roundtrip_efficiency is not None:
            roundtrip_efficiency = roundtrip_efficiency.to(
                ur.Quantity("dimensionless")
            ).magnitude

        # get optional min and max SOC
        soc_min = kwargs.get("soc_min", None)
        soc_max = kwargs.get("soc_max", None)
        if soc_min is not None and unit == "kWh":
            soc_min = soc_min / 1000.0
        if soc_max is not None and unit == "kWh":
            soc_max = soc_max / 1000.0

        # set soc targets
        end_of_schedule = start_of_schedule + current_app.config.get(
            "FLEXMEASURES_PLANNING_HORIZON"
        )
        resolution = sensor.event_resolution
        soc_targets = pd.Series(
            np.nan,
            index=pd.date_range(
                start_of_schedule, end_of_schedule, freq=resolution, closed="right"
            ),  # note that target values are indexed by their due date (i.e. closed="right")
        )
        for target in kwargs.get("targets", []):

            # get target value
            if "value" not in target:
                return ptus_incomplete("Target missing value parameter.")
            try:
                target_value = float(target["value"])
            except ValueError:
                extra_info = "Request includes empty or ill-formatted target value(s)."
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

        create_scheduling_job(
            sensor.id,
            start_of_schedule,
            end_of_schedule,
            resolution=resolution,
            belief_time=prior,  # server time if no prior time was sent
            soc_at_start=value,
            soc_targets=soc_targets,
            soc_min=soc_min,
            soc_max=soc_max,
            roundtrip_efficiency=roundtrip_efficiency,
            udi_event_ea=kwargs.get("event"),
            enqueue=True,
        )

        # Store new soc info as GenericAsset attributes
        # sensor.generic_asset.set_attribute("soc_datetime", start_of_schedule.isoformat())
        # sensor.generic_asset.set_attribute("soc_udi_event_id", event_id)
        # sensor.generic_asset.set_attribute("soc_in_mwh", value)

        db.session.commit()
        return request_processed()

    @route("/<id>/schedules/<job_id>", methods=["GET"])
    @use_kwargs(
        {
            "sensor": SensorIdField(data_key="id"),
            "job_id": fields.Str(data_key="job_id"),
        },
        location="path",
    )
    @use_kwargs(
        {
            "event": fields.Str(required=True),  # todo: deprecate UDI Event id
        },
        location="query",
    )
    @optional_duration_accepted(timedelta(hours=6))
    def get_schedule(self, sensor: Sensor, job_id: str, duration: timedelta, **kwargs):
        """Get a schedule from FlexMeasures.

        .. :quickref: Schedule; Download schedule from the platform

        **Optional fields**

        - "duration" (6 hours by default; can be increased to plan further into the future)

        **Example request**

        This "GetDeviceMessageRequest" message requests targeted consumption for UDI event 203 of device 10 of owner 7.

        .. code-block:: json

            {
                "type": "GetDeviceMessageRequest",
                "event": "ea1.2021-01.io.flexmeasures.company:fm0.7:10:203:soc"
            }

        **Example response**

        This "GetDeviceMessageResponse" message indicates that the target for UDI event 203 is to consume at various power
        rates from 10am UTC onwards for a duration of 45 minutes.

        .. sourcecode:: json

            {
                "type": "GetDeviceMessageResponse",
                "event": "ea1.2021-01.io.flexmeasures.company:fm0.7:10:203:soc",
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
        :status 400: INVALID_MESSAGE_TYPE, INVALID_TIMEZONE, INVALID_DOMAIN, INVALID_UNIT, UNKNOWN_SCHEDULE, UNRECOGNIZED_CONNECTION_GROUP, or UNRECOGNIZED_UDI_EVENT
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 405: INVALID_METHOD
        :status 422: UNPROCESSABLE_ENTITY
        """

        planning_horizon = min(
            duration, current_app.config.get("FLEXMEASURES_PLANNING_HORIZON")
        )

        # Parse the entity address
        event = kwargs["event"]
        try:
            ea = parse_entity_address(event, entity_type="event", fm_scheme="fm0")
        except EntityAddressException as eae:
            return invalid_domain(str(eae))
        sensor_id = ea["asset_id"]
        event_id = ea["event_id"]
        event_type = ea["event_type"]

        connection = current_app.queues["scheduling"].connection
        try:  # First try the scheduling queue
            job = Job.fetch(event, connection=connection)
        except NoSuchJobError:
            print(event)
            return unrecognized_event(event_id, event_type)
        if job.is_finished:
            message = (
                "A scheduling job has been processed based on your UDI event, but "
            )
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

        schedule_data_source_name = "Seita"
        scheduler_source = DataSource.query.filter_by(
            name="Seita", type="scheduling script"
        ).one_or_none()
        if scheduler_source is None:
            return unknown_schedule(
                message + f'no data is known from "{schedule_data_source_name}".'
            )

        power_values = sensor.search_beliefs(
            event_starts_after=schedule_start,
            event_ends_before=schedule_start + planning_horizon,
            source=scheduler_source,
            most_recent_beliefs_only=True,
            one_deterministic_belief_per_event=True,
        )
        # For consumption schedules, positive values denote consumption. For the db, consumption is negative
        consumption_schedule = -simplify_index(power_values)["event_value"]
        if consumption_schedule.empty:
            return unknown_schedule(
                message + "the schedule was not found in the database."
            )

        # Update the planning window
        resolution = sensor.event_resolution
        start = consumption_schedule.index[0]
        duration = min(duration, consumption_schedule.index[-1] + resolution - start)
        consumption_schedule = consumption_schedule[
            start : start + duration - resolution
        ]
        response = dict(
            event=event,
            values=consumption_schedule.tolist(),
        )

        response["start"] = isodate.datetime_isoformat(start)
        response["duration"] = isodate.duration_isoformat(duration)
        response["unit"] = sensor.unit

        d, s = request_processed()
        return dict(**response, **d), s
