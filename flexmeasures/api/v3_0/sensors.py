from datetime import datetime, timedelta
from typing import List, Dict, Optional

from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required
import isodate
from marshmallow import fields, validate, ValidationError
from marshmallow.validate import OneOf
from rq.job import Job, NoSuchJobError
from timely_beliefs import BeliefsDataFrame
from webargs.flaskparser import use_args, use_kwargs

from flexmeasures.api.common.responses import (
    request_processed,
    unrecognized_event,
    unknown_schedule,
    invalid_flex_config,
)
from flexmeasures.api.common.utils.deprecation_utils import deprecate_fields
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
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.queries.utils import simplify_index
from flexmeasures.data.schemas.sensors import SensorSchema, SensorIdField
from flexmeasures.data.schemas.times import AwareDateTimeField, PlanningDurationField
from flexmeasures.data.schemas.units import QuantityField
from flexmeasures.data.schemas.scheduling import FlexContextSchema
from flexmeasures.data.services.sensors import get_sensors
from flexmeasures.data.services.scheduling import (
    find_scheduler_class,
    create_scheduling_job,
    get_data_source_for_job,
)
from flexmeasures.utils.time_utils import duration_isoformat
from flexmeasures.utils.unit_utils import ur


# Instantiate schemas outside of endpoint logic to minimize response time
get_sensor_schema = GetSensorDataSchema()
post_sensor_schema = PostSensorDataSchema()
sensors_schema = SensorSchema(many=True)

DEPRECATED_FLEX_CONFIGURATION_FIELDS = [
    "soc-at-start",
    "soc-min",
    "soc-max",
    "soc-unit",
    "roundtrip-efficiency",
    "prefer-charging-sooner",
    "soc-targets",
    "consumption-price-sensor",
    "production-price-sensor",
    "inflexible-device-sensors",
]


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
    # TODO: Everything other than start_of_schedule, prior, flex_model and flex_context is to be deprecated in 0.13. We let the scheduler decide (flex model) or nest (portfolio)
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
            "soc_sensor_id": fields.Str(data_key="soc-sensor", required=False),
            "roundtrip_efficiency": QuantityField(
                "%",
                validate=validate.Range(min=0, max=1),
                data_key="roundtrip-efficiency",
            ),
            "start_value": fields.Float(data_key="soc-at-start"),
            "soc_min": fields.Float(data_key="soc-min"),
            "soc_max": fields.Float(data_key="soc-max"),
            "unit": fields.Str(
                data_key="soc-unit",
                validate=OneOf(
                    [
                        "kWh",
                        "MWh",
                    ]
                ),
            ),  # todo: allow unit to be set per field, using QuantityField("%", validate=validate.Range(min=0, max=1))
            "targets": fields.List(fields.Dict, data_key="soc-targets"),
            "prefer_charging_sooner": fields.Bool(
                data_key="prefer-charging-sooner", required=False
            ),
            "flex_context": fields.Nested(
                FlexContextSchema, required=False, data_key="flex-context"
            ),
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
    def trigger_schedule(  # noqa: C901
        self,
        sensor: Sensor,
        start_of_schedule: datetime,
        duration: timedelta,
        belief_time: Optional[datetime] = None,
        start_value: Optional[float] = None,
        soc_min: Optional[float] = None,
        soc_max: Optional[float] = None,
        unit: Optional[str] = None,
        roundtrip_efficiency: Optional[ur.Quantity] = None,
        prefer_charging_sooner: Optional[bool] = True,
        consumption_price_sensor: Optional[Sensor] = None,
        production_price_sensor: Optional[Sensor] = None,
        inflexible_device_sensors: Optional[List[Sensor]] = None,
        soc_sensor_id: Optional[int] = None,
        flex_model: Optional[dict] = None,
        flex_context: Optional[dict] = None,
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
        Finally, the schedule length is limited by :ref:`max_planning_horizon_config`, which defaults to 169 hours.
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
                    "soc-at-start": 12.1,
                    "soc-unit": "kWh"
                }
            }

        **Example request B**

        This message triggers a 24-hour schedule for a storage asset, starting at 10.00am,
        at which the state of charge (soc) is 12.1 kWh, with a target state of charge of 25 kWh at 4.00pm.
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
                "duration": "PT24H",
                "flex-model": {
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
                },
                "flex-context": {
                    "consumption-price-sensor": 9,
                    "production-price-sensor": 10,
                    "inflexible-device-sensors": [13, 14, 15]
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
        # -- begin deprecation logic, can be removed after 0.13
        deprecate_fields(
            DEPRECATED_FLEX_CONFIGURATION_FIELDS,
            deprecation_date="2022-12-14",
            deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/change_log.html#v3-0-5-2022-12-30",
            sunset_date="2023-02-01",
            sunset_link="https://flexmeasures.readthedocs.io/en/latest/api/change_log.html#v3-0-5-2022-12-30",
        )
        found_fields: Dict[str, List[str]] = dict(model=[], context=[])
        deprecation_message = ""
        # flex-model
        for param, param_name in [
            (start_value, "soc-at-start"),
            (soc_min, "soc-min"),
            (soc_max, "soc-max"),
            (unit, "soc-unit"),
            (kwargs.get("targets"), "soc-targets"),
            (roundtrip_efficiency, "roundtrip-efficiency"),
            (
                prefer_charging_sooner,
                "prefer-charging-sooner",
            ),
        ]:
            if flex_model is None:
                flex_model = {}
            if param is not None:
                if param_name not in flex_model:
                    if param_name == "roundtrip-efficiency" and type(param) != float:
                        param = param.to(ur.Quantity("dimensionless")).magnitude  # type: ignore
                    flex_model[param_name] = param
                found_fields["model"].append(param_name)
        # flex-context
        for param, param_name in [
            (
                consumption_price_sensor,
                "consumption-price-sensor",
            ),
            (
                production_price_sensor,
                "production-price-sensor",
            ),
            (
                inflexible_device_sensors,
                "inflexible-device-sensors",
            ),
        ]:
            if flex_context is None:
                flex_context = {}
            if param is not None:
                if param_name not in flex_context:
                    flex_context[param_name] = param
                found_fields["context"].append(param_name)
        if found_fields["model"] or found_fields["context"]:
            deprecation_message = "The following fields you sent are deprecated and will be sunset in the next version:"
            if found_fields["model"]:
                deprecation_message += f" {', '.join(found_fields['model'])} (please pass as part of flex_model)."
            if found_fields["context"]:
                deprecation_message += f" {', '.join(found_fields['context'])} (please pass as part of flex_context)."

        if soc_sensor_id is not None:
            deprecation_message += (
                "The field soc-sensor-id is be deprecated and will be sunset in v0.13."
            )
        # -- end deprecation logic

        end_of_schedule = start_of_schedule + duration
        scheduler_kwargs = dict(
            sensor=sensor,
            start=start_of_schedule,
            end=end_of_schedule,
            resolution=sensor.event_resolution,
            belief_time=belief_time,  # server time if no prior time was sent
            flex_model=flex_model,
            flex_context=flex_context,
        )

        try:
            # We create a scheduler, so the flex config is also checked and errors are returned here
            scheduler = find_scheduler_class(sensor)(**scheduler_kwargs)
            scheduler.deserialize_config()
        except ValidationError as err:
            return invalid_flex_config(err.messages)
        except ValueError as err:
            return invalid_flex_config(str(err))

        job = create_scheduling_job(
            **scheduler_kwargs,
            enqueue=True,
        )

        scheduler.persist_flex_model()
        db.session.commit()

        response = dict(schedule=job.id)
        d, s = request_processed(deprecation_message)
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

        data_source = get_data_source_for_job(job)
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
