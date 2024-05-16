from __future__ import annotations

from datetime import datetime, timedelta
import json

from flask import current_app
from flask_classful import FlaskView, route
from flask_security import auth_required
from flask_json import as_json
from marshmallow import fields, ValidationError
from webargs.flaskparser import use_kwargs, use_args
from sqlalchemy import select, delete

from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.schemas.times import AwareDateTimeField, PlanningDurationField
from flexmeasures.data.schemas.generic_assets import GenericAssetSchema as AssetSchema
from flexmeasures.data.services.scheduling import create_scheduling_job
from flexmeasures.api.common.schemas.generic_assets import AssetIdField
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.api.common.responses import (
    invalid_flex_config,
    request_processed,
)
from flexmeasures.utils.coding_utils import flatten_unique
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
        asset = GenericAsset(**asset_data)
        db.session.add(asset)
        db.session.commit()
        return asset_schema.dump(asset), 201

    @route("/<id>", methods=["GET"])
    @use_kwargs({"asset": AssetIdField(data_key="id")}, location="path")
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
    @use_kwargs({"db_asset": AssetIdField(data_key="id")}, location="path")
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
        for k, v in asset_data.items():
            setattr(db_asset, k, v)
        db.session.add(db_asset)
        db.session.commit()
        return asset_schema.dump(db_asset), 200

    @route("/<id>", methods=["DELETE"])
    @use_kwargs({"asset": AssetIdField(data_key="id")}, location="path")
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
        {"asset": AssetIdField(data_key="id")},
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
        {"asset": AssetIdField(data_key="id")},
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
    @use_kwargs(
        {"asset": AssetIdField(data_key="id")},
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
        },
        location="json",
    )
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
        Trigger FlexMeasures to create a schedule.

        .. :quickref: Schedule; Trigger scheduling job

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
        for sensor_flex_model in flex_model:
            sensor_id = sensor_flex_model.get("sensor")
            if sensor_id is None:
                return invalid_flex_config(f"Missing 'sensor' in flex-model list item: {sensor_flex_model}.")
            sensor = SensorIdField().deserialize(sensor_id)

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
            )
        except ValidationError as err:
            return invalid_flex_config(err.messages)
        except ValueError as err:
            return invalid_flex_config(str(err))

        db.session.commit()

        response = dict(schedule=job.id)
        d, s = request_processed()
        return dict(**response, **d), s
