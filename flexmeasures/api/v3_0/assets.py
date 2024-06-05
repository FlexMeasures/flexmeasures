from __future__ import annotations

from datetime import datetime, timedelta
import json

import isodate
from flask import current_app, url_for
from flask_classful import FlaskView, route
from flask_security import auth_required
from flask_json import as_json
from marshmallow import fields, ValidationError
from rq.job import Job, NoSuchJobError
from webargs.flaskparser import use_kwargs, use_args
from sqlalchemy import select, delete

from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.queries.utils import simplify_index
from flexmeasures.data.schemas import AssetIdField
from flexmeasures.data.schemas.generic_assets import GenericAssetSchema as AssetSchema
from flexmeasures.data.schemas.scheduling import AssetTriggerSchema
from flexmeasures.data.schemas.times import AwareDateTimeField
from flexmeasures.data.services.scheduling import (
    create_sequential_scheduling_job,
    get_data_source_for_job,
)
from flexmeasures.data.services.utils import get_asset_or_sensor_from_ref
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.api.common.responses import (
    fallback_schedule_redirect,
    invalid_flex_config,
    request_processed,
    unknown_schedule,
    unrecognized_event,
)
from flexmeasures.api.common.utils.validators import (
    optional_duration_accepted,
)
from flexmeasures.utils.coding_utils import flatten_unique
from flexmeasures.utils.time_utils import duration_isoformat
from flexmeasures.ui.utils.view_utils import set_session_variables


asset_schema = AssetSchema()
assets_schema = AssetSchema(many=True)
partial_asset_schema = AssetSchema(partial=True, exclude=["account_id"])


class AssetAPI(FlaskView):
    """
    This API view exposes generic assets.
    Under development until it replaces the original Asset API.
    """

    route_base = "/assets"
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
        """List all assets owned by a certain account.

        .. :quickref: Asset; Download asset list

        This endpoint returns all accessible assets for the account of the user.
        The `account_id` query parameter can be used to list assets from a different account.

        **Example response**

        An example of one asset being returned:

        .. sourcecode:: json

            [
                {
                    "id": 1,
                    "name": "Test battery",
                    "latitude": 10,
                    "longitude": 100,
                    "account_id": 2,
                    "generic_asset_type_id": 1
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
        return assets_schema.dump(account.generic_assets), 200

    @route("/public", methods=["GET"])
    @as_json
    def public(self):
        """Return all public assets.

        .. :quickref: Asset; Return all public assets.

        This endpoint returns all public assets.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 422: UNPROCESSABLE_ENTITY
        """
        assets = db.session.scalars(
            select(GenericAsset).filter(GenericAsset.account_id.is_(None))
        ).all()
        return assets_schema.dump(assets), 200

    @route("", methods=["POST"])
    @permission_required_for_context(
        "create-children", ctx_loader=AccountIdField.load_current
    )
    @use_args(asset_schema)
    def post(self, asset_data: dict):
        """Create new asset.

        .. :quickref: Asset; Create a new asset

        This endpoint creates a new asset.

        **Example request**

        .. sourcecode:: json

            {
                "name": "Test battery",
                "generic_asset_type_id": 2,
                "account_id": 2,
                "latitude": 40,
                "longitude": 170.3,
            }


        The newly posted asset is returned in the response.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 201: CREATED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        inflexible_sensor_ids = asset_data.pop("inflexible_device_sensor_ids", [])
        asset = GenericAsset(**asset_data)
        db.session.add(asset)
        # assign asset id
        db.session.flush()

        asset.set_inflexible_sensors(inflexible_sensor_ids)
        db.session.commit()
        return asset_schema.dump(asset), 201

    @route("/<id>", methods=["GET"])
    @use_kwargs(
        {"asset": AssetIdField(data_key="id", status_if_not_found=404)}, location="path"
    )
    @permission_required_for_context("read", ctx_arg_name="asset")
    @as_json
    def fetch_one(self, id, asset):
        """Fetch a given asset.

        .. :quickref: Asset; Get an asset

        This endpoint gets an asset.

        **Example response**

        .. sourcecode:: json

            {
                "generic_asset_type_id": 2,
                "name": "Test battery",
                "id": 1,
                "latitude": 10,
                "longitude": 100,
                "account_id": 1,
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
        return asset_schema.dump(asset), 200

    @route("/<id>", methods=["PATCH"])
    @use_args(partial_asset_schema)
    @use_kwargs(
        {"db_asset": AssetIdField(data_key="id", status_if_not_found=404)},
        location="path",
    )
    @permission_required_for_context("update", ctx_arg_name="db_asset")
    @as_json
    def patch(self, asset_data: dict, id: int, db_asset: GenericAsset):
        """Update an asset given its identifier.

        .. :quickref: Asset; Update an asset

        This endpoint sets data for an existing asset.
        Any subset of asset fields can be sent.

        The following fields are not allowed to be updated:
        - id
        - account_id

        **Example request**

        .. sourcecode:: json

            {
                "latitude": 11.1,
                "longitude": 99.9,
            }


        **Example response**

        The whole asset is returned in the response:

        .. sourcecode:: json

            {
                "generic_asset_type_id": 2,
                "id": 1,
                "latitude": 11.1,
                "longitude": 99.9,
                "name": "Test battery",
                "account_id": 2,
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
        inflexible_sensor_ids = asset_data.pop("inflexible_device_sensor_ids", [])
        db_asset.set_inflexible_sensors(inflexible_sensor_ids)

        for k, v in asset_data.items():
            setattr(db_asset, k, v)
        db.session.add(db_asset)
        db.session.commit()
        return asset_schema.dump(db_asset), 200

    @route("/<id>", methods=["DELETE"])
    @use_kwargs(
        {"asset": AssetIdField(data_key="id", status_if_not_found=404)}, location="path"
    )
    @permission_required_for_context("delete", ctx_arg_name="asset")
    @as_json
    def delete(self, id: int, asset: GenericAsset):
        """Delete an asset given its identifier.

        .. :quickref: Asset; Delete an asset

        This endpoint deletes an existing asset, as well as all sensors and measurements recorded for it.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 204: DELETED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        asset_name = asset.name
        db.session.execute(delete(GenericAsset).filter_by(id=asset.id))
        db.session.commit()
        current_app.logger.info("Deleted asset '%s'." % asset_name)
        return {}, 204

    @route("/<id>/chart", strict_slashes=False)  # strict on next version? see #1014
    @use_kwargs(
        {"asset": AssetIdField(data_key="id", status_if_not_found=404)},
        location="path",
    )
    @use_kwargs(
        {
            "event_starts_after": AwareDateTimeField(format="iso", required=False),
            "event_ends_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_after": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
            "include_data": fields.Boolean(required=False),
            "dataset_name": fields.Str(required=False),
            "height": fields.Str(required=False),
            "width": fields.Str(required=False),
        },
        location="query",
    )
    @permission_required_for_context("read", ctx_arg_name="asset")
    def get_chart(self, id: int, asset: GenericAsset, **kwargs):
        """GET from /assets/<id>/chart

        .. :quickref: Chart; Download a chart with time series
        """
        # Store selected time range as session variables, for a consistent UX across UI page loads
        set_session_variables("event_starts_after", "event_ends_before")
        return json.dumps(asset.chart(**kwargs))

    @route(
        "/<id>/chart_data", strict_slashes=False
    )  # strict on next version? see #1014
    @use_kwargs(
        {"asset": AssetIdField(data_key="id", status_if_not_found=404)},
        location="path",
    )
    @use_kwargs(
        {
            "event_starts_after": AwareDateTimeField(format="iso", required=False),
            "event_ends_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_after": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
            "most_recent_beliefs_only": fields.Boolean(required=False),
        },
        location="query",
    )
    @permission_required_for_context("read", ctx_arg_name="asset")
    def get_chart_data(self, id: int, asset: GenericAsset, **kwargs):
        """GET from /assets/<id>/chart_data

        .. :quickref: Chart; Download time series for use in charts

        Data for use in charts (in case you have the chart specs already).
        """
        sensors = flatten_unique(asset.sensors_to_show)
        return asset.search_beliefs(sensors=sensors, as_json=True, **kwargs)

    @route("/<id>/schedules/trigger", methods=["POST"])
    @use_args(AssetTriggerSchema(), location="args_and_json", as_kwargs=True)
    # Simplification of checking for create-children access on each of the flexible sensors,
    # which assumes each of the flexible sensors belongs to the given asset.
    @permission_required_for_context("create-children", ctx_arg_name="asset")
    def trigger_schedule(
        self,
        asset: GenericAsset,
        start_of_schedule: datetime,
        duration: timedelta,
        belief_time: datetime | None = None,
        flex_model: dict | None = None,
        flex_context: dict | None = None,
        **kwargs,
    ):
        """
        Trigger FlexMeasures to create a schedule for a collection of flexible devices.

        .. :quickref: Schedule; Trigger scheduling job for multiple devices

        Trigger FlexMeasures to create a schedule for this asset.
        The assumption is that this is a flexible asset containing multiple power sensors.

        In this request, you can describe:

        - the schedule's main features (when does it start, what unit should it report, prior to what time can we assume knowledge)
        - the flexibility models for the asset's relevant sensors (state and constraint variables, e.g. current state of charge of a battery, or connection capacity)
        - the flexibility context which the asset operates in (other sensors under the same EMS which are relevant, e.g. prices)

        For details on flexibility model and context, see :ref:`describing_flexibility`.
        Below, we'll also list some examples.

        .. note:: This endpoint support scheduling an EMS with multiple flexible sensors at once,
                  but internally, it does so sequentially
                  (considering already scheduled sensors as inflexible).

        The length of the schedule can be set explicitly through the 'duration' field.
        Otherwise, it is set by the config setting :ref:`planning_horizon_config`, which defaults to 48 hours.
        If the flex-model contains targets that lie beyond the planning horizon, the length of the schedule is extended to accommodate them.
        Finally, the schedule length is limited by :ref:`max_planning_horizon_config`, which defaults to 2520 steps of each sensor's resolution.
        Targets that exceed the max planning horizon are not accepted.

        The appropriate algorithm is chosen by FlexMeasures (based on asset type).
        It's also possible to use custom schedulers and custom flexibility models, see :ref:`plugin_customization`.

        If you have ideas for algorithms that should be part of FlexMeasures, let us know: https://flexmeasures.io/get-in-touch/

        **Example request A**

        This message triggers a schedule for a storage asset, starting at 10.00am, at which the state of charge (soc) is 12.1 kWh.

        .. code-block:: json

            {
                "start": "2015-06-02T10:00:00+00:00",
                "flex-model": [
                    {
                        "sensor": 931,
                        "soc-at-start": 12.1,
                        "soc-unit": "kWh"
                    }
                ]
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
                "flex-model": [
                    {
                        "sensor": 931,
                        "soc-at-start": 12.1,
                        "soc-unit": "kWh",
                        "soc-targets": [
                            {
                                "value": 25,
                                "datetime": "2015-06-02T16:00:00+00:00"
                            },
                        ],
                        "soc-minima": {"sensor" : 300},
                        "soc-min": 10,
                        "soc-max": 25,
                        "charging-efficiency": "120%",
                        "discharging-efficiency": {"sensor": 98},
                        "storage-efficiency": 0.9999,
                        "power-capacity": "25kW",
                        "consumption-capacity" : {"sensor": 42},
                        "production-capacity" : "30 kW"
                    },
                ],
                "flex-context": {
                    "consumption-price-sensor": 9,
                    "production-price-sensor": 10,
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
        The given UUID may be used to obtain the resulting schedule: see /assets/<id>/schedules/<uuid>.

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
            start=start_of_schedule,
            end=end_of_schedule,
            belief_time=belief_time,  # server time if no prior time was sent
            flex_model=flex_model,
            flex_context=flex_context,
        )
        try:
            jobs = create_sequential_scheduling_job(
                asset=asset, enqueue=True, **scheduler_kwargs
            )
        except ValidationError as err:
            return invalid_flex_config(err.messages)
        except ValueError as err:
            return invalid_flex_config(str(err))

        # todo: make a 'done job' and pass that job's ID here
        response = dict(schedule=jobs[-1].id)
        d, s = request_processed()
        return dict(**response, **d), s

    @route("/<id>/schedules/<uuid>", methods=["GET"])
    @use_kwargs(
        {
            "asset": AssetIdField(data_key="id", status_if_not_found=404),
            "job_id": fields.Str(data_key="uuid"),
        },
        location="path",
    )
    @optional_duration_accepted(
        timedelta(hours=6)
    )  # todo: make this a Marshmallow field
    @permission_required_for_context("read", ctx_arg_name="asset")
    def get_schedule(  # noqa: C901
        self, asset: GenericAsset, job_id: str, duration: timedelta, **kwargs
    ):
        """Get a schedule from FlexMeasures for multiple devices.

        .. :quickref: Schedule; Download schedule from the platform for multiple devices

        **Optional fields**

        - "duration" (6 hours by default; can be increased to plan further into the future)

        **Example response**

        This message contains a schedule indicating two devices to consume at various power
        rates from 10am UTC onwards for a duration of 45 minutes.

        .. sourcecode:: json

            {
                "schedule": [
                    {
                        "sensor": 1,
                        "values": [
                            2.15,
                            3,
                            2
                        ],
                        "start": "2015-06-02T10:00:00+00:00",
                        "duration": "PT45M",
                        "unit": "MW"
                    },
                    {
                        "sensor": 2,
                        "values": [
                            2.15,
                            3,
                            2
                        ],
                        "start": "2015-06-02T10:00:00+00:00",
                        "duration": "PT45M",
                        "unit": "MW"
                    }
                ]
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
                        "AssetAPI:get_schedule",
                        uuid=fallback_job_id,
                        id=asset.id,
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

        overall_schedule_response = []
        for child_job in job.fetch_dependencies():
            sensor = get_asset_or_sensor_from_ref(child_job.kwargs["asset_or_sensor"])
            schedule_start = child_job.kwargs["start"]

            data_source = get_data_source_for_job(child_job)
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
            duration = min(
                duration, consumption_schedule.index[-1] + resolution - start
            )
            consumption_schedule = consumption_schedule[
                start : start + duration - resolution
            ]
            sensor_schedule_response = dict(
                sensor=sensor.id,
                values=consumption_schedule.tolist(),
                start=isodate.datetime_isoformat(start),
                duration=duration_isoformat(duration),
                unit=sensor.unit,
            )
            overall_schedule_response.append(sensor_schedule_response)

        d, s = request_processed(scheduler_info_msg)
        return (
            dict(
                scheduler_info=scheduler_info, schedule=overall_schedule_response, **d
            ),
            s,
        )
