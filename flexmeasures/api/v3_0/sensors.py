from __future__ import annotations

import isodate
from datetime import datetime, timedelta

from flexmeasures.data.services.sensors import (
    serialize_sensor_status_data,
)

from werkzeug.exceptions import Unauthorized
from flask import current_app, url_for
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required, current_user
from marshmallow import fields, Schema, ValidationError
import marshmallow.validate as validate
from rq.job import Job, NoSuchJobError
import timely_beliefs as tb
from webargs.flaskparser import use_args, use_kwargs
from sqlalchemy import delete, select, or_

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
from flexmeasures.api.common.schemas.sensor_data import (  # noqa F401
    SensorDataDescriptionSchema,
    GetSensorDataSchema,
    PostSensorDataSchema,
)
from flexmeasures.api.common.schemas.sensors import SensorId  # noqa F401
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.api.common.utils.api_utils import save_and_enqueue
from flexmeasures.auth.policy import check_access
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.queries.utils import simplify_index
from flexmeasures.data.schemas.sensors import (  # noqa F401
    SensorSchema,
    SensorIdField,
    SensorDataFileSchema,
    SensorDataFileDescriptionSchema,
)
from flexmeasures.data.schemas.times import AwareDateTimeField, PlanningDurationField
from flexmeasures.data.schemas import AssetIdField
from flexmeasures.api.common.schemas.search import SearchFilterField
from flexmeasures.api.common.schemas.sensors import UnitField
from flexmeasures.data.services.sensors import get_sensor_stats
from flexmeasures.data.services.scheduling import (
    create_scheduling_job,
    get_data_source_for_job,
)
from flexmeasures.utils.time_utils import duration_isoformat
from flexmeasures.utils.flexmeasures_inflection import join_words_into_a_list


# Instantiate schemes outside of endpoint logic to minimize response time
sensors_schema = SensorSchema(many=True)
sensor_schema = SensorSchema()
partial_sensor_schema = SensorSchema(partial=True, exclude=["generic_asset_id"])


class SensorKwargsSchema(Schema):
    account = AccountIdField(data_key="account_id", required=False)
    asset = AssetIdField(data_key="asset_id", required=False)
    include_consultancy_clients = fields.Boolean(required=False, load_default=False)
    include_public_assets = fields.Boolean(required=False, load_default=False)
    page = fields.Int(required=False, validate=validate.Range(min=1))
    per_page = fields.Int(
        required=False, validate=validate.Range(min=1), load_default=10
    )
    filter = SearchFilterField(required=False)
    unit = UnitField(required=False)


class TriggerScheduleKwargsSchema(Schema):
    start_of_schedule = AwareDateTimeField(
        data_key="start", format="iso", required=True
    )
    belief_time = AwareDateTimeField(format="iso", data_key="prior")
    duration = PlanningDurationField(load_default=PlanningDurationField.load_default)
    flex_model = fields.Dict(data_key="flex-model")
    flex_context = fields.Dict(required=False, data_key="flex-context")
    force_new_job_creation = fields.Boolean(required=False)


class SensorAPI(FlaskView):
    route_base = "/sensors"
    trailing_slash = False
    decorators = [auth_required()]

    @route("", methods=["GET"])
    @use_kwargs(SensorKwargsSchema, location="query")
    @as_json
    def index(
        self,
        account: Account | None = None,
        asset: GenericAsset | None = None,
        include_consultancy_clients: bool = False,
        include_public_assets: bool = False,
        page: int | None = None,
        per_page: int | None = None,
        filter: list[str] | None = None,
        unit: str | None = None,
    ):
        """
        .. :quickref: Sensors; Get list of sensors
        ---
        get:
          summary: Get list of sensors
          description: |
            This endpoint returns all accessible sensors.
            By default, "accessible sensors" means all sensors in the same account as the current user (if they have read permission to the account).

            You can also specify an `account` (an ID parameter), if the user has read access to that account. In this case, all assets under the
            specified account will be retrieved, and the sensors associated with these assets will be returned.

            Alternatively, you can filter by asset hierarchy by providing the `asset` parameter (ID). When this is set, all sensors on the specified
            asset and its sub-assets are retrieved, provided the user has read access to the asset.

            > **Note:** You can't set both account and asset at the same time, you can only have one set. The only exception is if the asset being specified is
            > part of the account that was set, then we allow to see sensors under that asset but then ignore the account (account = None).

            Finally, you can use the `include_consultancy_clients` parameter to include sensors from accounts for which the current user account is a consultant.
            This is only possible if the user has the role of a consultant.

            Only admins can use this endpoint to fetch sensors from a different account (by using the `account_id` query parameter).

            The `filter` parameter allows you to search for sensors by name or account name.
            The `unit` parameter allows you to filter by unit.

            For the pagination of the sensor list, you can use the `page` and `per_page` query parameters, the `page` parameter is used to trigger
            pagination, and the `per_page` parameter is used to specify the number of records per page. The default value for `page` is 1 and for `per_page` is 10.

          security:
            - ApiKeyAuth: []
          parameters:
            - in: query
              schema: SensorKwargsSchema
          responses:
            200:
              description: PROCESSED - List of sensors (paginated or direct list)
              content:
                application/json:
                  schema:
                    oneOf:
                      - type: array
                        description: Direct list when no pagination requested
                        items: Sensor
                      - type: object
                        description: Paginated response
                        properties:
                          data:
                            type: array
                            items: Sensor
                          num-records:
                            type: integer
                            description: Total number of records in query result
                          filtered-records:
                            type: integer
                            description: Total number of records after filtering and pagination
                        required:
                          - data
                          - num-records
                          - filtered-records
                  examples:
                    direct_list:
                      summary: Direct sensor list
                      description: Example of direct response with one sensor
                      value:
                        data:
                          - entity_address: "ea1.2021-01.io.flexmeasures.company:fm1.42"
                            event_resolution: "PT15M"
                            generic_asset_id: 1
                            name: "Gas demand"
                            timezone: "Europe/Amsterdam"
                            unit: "m³/h"
                            id: 2
                    paginated_response:
                      summary: Paginated sensor list
                      description: Example of paginated response with one sensor
                      value:
                        data:
                          - entity_address: "ea1.2021-01.io.flexmeasures.company:fm1.42"
                            event_resolution: "PT15M"
                            generic_asset_id: 1
                            name: "Gas demand"
                            timezone: "Europe/Amsterdam"
                            unit: "m³/h"
                            id: 2
                        num-records: 1
                        filtered-records: 1
            400:
              description: INVALID_REQUEST
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
        """
        if account is None and asset is None:
            if current_user.is_anonymous:
                raise Unauthorized
            account = current_user.account

        if account is not None and asset is not None:
            if asset.account_id != account.id:
                return {
                    "message": "Please provide either an account or an asset ID, not both"
                }, 422
            else:
                account = None

        if asset is not None:
            check_access(asset, "read")

            asset_tree = (
                db.session.query(GenericAsset.id, GenericAsset.parent_asset_id)
                .filter(GenericAsset.id == asset.id)
                .cte(name="asset_tree", recursive=True)
            )

            recursive_part = db.session.query(
                GenericAsset.id, GenericAsset.parent_asset_id
            ).join(asset_tree, GenericAsset.parent_asset_id == asset_tree.c.id)

            asset_tree = asset_tree.union(recursive_part)

            child_assets = db.session.query(asset_tree).all()

            filter_statement = GenericAsset.id.in_(
                [asset.id] + [a.id for a in child_assets]
            )
        elif account is not None:
            check_access(account, "read")

            account_ids: list = [account.id]

            if include_consultancy_clients:
                if current_user.has_role("consultant"):
                    consultancy_accounts = (
                        db.session.query(Account)
                        .filter(Account.consultancy_account_id == account.id)
                        .all()
                    )
                    account_ids.extend([acc.id for acc in consultancy_accounts])

            filter_statement = GenericAsset.account_id.in_(account_ids)
        else:
            filter_statement = None

        if include_public_assets:
            filter_statement = or_(
                filter_statement,
                GenericAsset.account_id.is_(None),
            )

        sensor_query = (
            select(Sensor)
            .join(GenericAsset, Sensor.generic_asset_id == GenericAsset.id)
            .outerjoin(Account, GenericAsset.owner)
            .filter(filter_statement)
        )

        if filter is not None:
            sensor_query = sensor_query.filter(
                or_(
                    *(
                        or_(
                            Sensor.name.ilike(f"%{term}%"),
                            Account.name.ilike(f"%{term}%"),
                            GenericAsset.name.ilike(f"%{term}%"),
                        )
                        for term in filter
                    )
                )
            )

        if unit:
            sensor_query = sensor_query.filter(Sensor.unit == unit)

        sensors = (
            db.session.scalars(sensor_query).all()
            if page is None
            else db.paginate(sensor_query, per_page=per_page, page=page).items
        )

        sensors = [sensor for sensor in sensors if check_access(sensor, "read") is None]

        sensors_response = sensors_schema.dump(sensors)

        # Return appropriate response for paginated or non-paginated data
        if page is None:
            return sensors_response, 200
        else:
            num_records = len(db.session.execute(sensor_query).scalars().all())
            select_pagination = db.paginate(sensor_query, per_page=per_page, page=page)
            response = {
                "data": sensors_response,
                "num-records": num_records,
                "filtered-records": select_pagination.total,
            }
            return response, 200

    @route("<id>/data/upload", methods=["POST"])
    @use_args(
        SensorDataFileSchema(), location="combined_sensor_data_upload", as_kwargs=True
    )
    @permission_required_for_context(
        "create-children",
        ctx_arg_name="data",
        ctx_loader=lambda data: data[0].sensor if data else None,
        pass_ctx_to_loader=True,
    )
    def upload_data(
        self, data: list[tb.BeliefsDataFrame], filenames: list[str], **kwargs
    ):
        """
        .. :quickref: Data; Upload sensor data by file
        ---
        post:
          summary: Upload sensor data by file
          description: |
            The file should have columns for a timestamp (event_start) and a value (event_value).
            The timestamp should be in ISO 8601 format.
            The value should be a numeric value.

            The unit has to be convertible to the sensor's unit.
            The resolution of the data has to match the sensor's required resolution, but
            FlexMeasures will attempt to upsample lower resolutions.
            The list of values may include null values.

          security:
            - ApiKeyAuth: []
          parameters:
            - name: id
              in: path
              required: true
              schema: SensorId
          requestBody:
            content:
              multipart/form-data:
                schema: SensorDataFileDescriptionSchema
                encoding:
                  uploaded-files:
                    contentType: application/octet-stream
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  schema:
                    type: object
                  examples:
                    new_data:
                      summary: New data
                      description: |
                        If the data sent is new and is not already processed by FlexMeasures, the response will be as above.
                      value:
                        message: "Request has been processed."
                        status: "PROCESSED"
                    processed_previously_received:
                      summary: Previously received data
                      description: |
                        If some of the data sent was already received and successfully processed by FlexMeasures, the response will be as above.
                        Note that in this case, the data is still processed, but the already received data points are ignored.
                      value:
                        message: "Some of the data has already been received and successfully processed."
                        results: "PROCESSED"
                        status: "ALREADY_RECEIVED_AND_SUCCESSFULLY_PROCESSED"
                    returned_graph_data:
                      summary: Returned graph data
                      description: |
                        Example of how the processed data may be returned.
                      value:
                        data:
                          - ts: 1759669200000
                            sid: 3
                            val: 12.4
                            sf: 1.0
                            src: 1
                            bh: -427962881
                        sensors:
                          "3":
                            name: "TempSensor_A1X"
                            unit: "°C"
                            description: "TempSensor_A1X (toy-account)"
                            asset_id: 1
                            asset_description: "toy-account"
                        sources:
                          "1":
                            name: "toy-user"
                            model: ""
                            type: "other"
                            description: "toy-user"
            400:
              description: INVALID_REQUEST
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
        """
        sensor = data[0].sensor
        AssetAuditLog.add_record(
            sensor.generic_asset,
            f"Data from {join_words_into_a_list(filenames)} uploaded to sensor '{sensor.name}': {sensor.id}",
        )
        response, code = save_and_enqueue(data)
        return response, code

    @route("/<id>/data", methods=["POST"])
    @use_args(
        PostSensorDataSchema(),
        location="combined_sensor_data_description",
        as_kwargs=True,
    )
    @permission_required_for_context(
        "create-children",
        ctx_arg_name="bdf",
        ctx_loader=lambda bdf: bdf.sensor,
        pass_ctx_to_loader=True,
    )
    def post_data(self, id: int, bdf: tb.BeliefsDataFrame):
        """
        .. :quickref: Data; Post sensor data
        ---
        post:
          summary: Post sensor data
          description: |
            Send data values via JSON, where the duration and number of values determine the resolution.

            The example request posts four values for a duration of one hour, where the first
            event start is at the given start time, and subsequent events start in 15 minute intervals throughout the one hour duration.

            The sensor is the one with ID=1.
            The unit has to be convertible to the sensor's unit.
            The resolution of the data has to match the sensor's required resolution, but
            FlexMeasures will attempt to upsample lower resolutions.
            The list of values may include null values.

          security:
            - ApiAuthKey: []
          parameters:
            - name: id
              in: path
              required: true
              schema: SensorId
          requestBody:
            content:
              application/json:
                schema: PostSensorDataSchema
                examples:
                  post_sensor:
                    summary: Post sensor data to flexmeasures
                    value:
                      "values": [-11.28, -11.28, -11.28, -11.28]
                      "start": "2021-06-07T00:00:00+02:00"
                      "duration": "PT1H"
                      "unit": "m³/h"
          responses:
            200:
              description: PROCESSED
            400:
              description: INVALID_REQUEST
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
        """
        response, code = save_and_enqueue(bdf)
        return response, code

    @route("/<id>/data", methods=["GET"])
    @use_args(
        GetSensorDataSchema(),
        location="combined_sensor_data_description",
        as_kwargs=True,
    )
    @permission_required_for_context("read", ctx_arg_name="sensor")
    def get_data(self, id: int, **sensor_data_description: dict):
        """
        .. :quickref: Data; Get sensor data
        ---
        get:
          summary: Get sensor data
          description: |
            The unit has to be convertible from the sensor's unit - e.g. you ask for kW, and the sensor's unit is MW.

            Optional parameters:

            - "resolution" (read [the docs about frequency and resolutions](https://flexmeasures.readthedocs.io/latest/api/notation.html#frequency-and-resolution))
            - "horizon" (read [the docs about belief timing](https://flexmeasures.readthedocs.io/latest/api/notation.html#tracking-the-recording-time-of-beliefs))
            - "prior" (the belief timing docs also apply here)
            - "source" (read [the docs about sources](https://flexmeasures.readthedocs.io/latest/api/notation.html#sources))

            An example query to fetch data for sensor with ID=1, for one hour starting June 7th 2021 at midnight, in 15 minute intervals, in m³/h:

              ?start=2021-06-07T00:00:00+02:00&duration=PT1H&resolution=PT15M&unit=m³/h

            (you will probably need to escape the + in the timezone offset, depending on your HTTP client, and other characters like here in the unit, as well).

             > **Note:** This endpoint also accepts the query parameters as part of the JSON body. That is not conform to REST architecture, but it is easier for some developers.
          security:
            - ApiKeyAuth: []
          parameters:
            - name: id
              in: path
              required: true
              schema: SensorId
            - in: query
              schema: SensorDataTimingDescriptionSchema

          responses:
            200:
              description: PROCESSED
            400:
              description: INVALID_REQUEST
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
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
    @use_kwargs(TriggerScheduleKwargsSchema, location="json")
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
        .. :quickref: Schedules; Trigger scheduling job for one device
        ---
        post:
          summary: Trigger scheduling job for one device
          description: |
            Trigger FlexMeasures to create a schedule for this sensor.
            The assumption is that this sensor is the power sensor on a flexible asset.

            In this request, you can describe:

            - the schedule's main features (when does it start, what unit should it report, prior to what time can we assume knowledge)
            - the flexibility model for the sensor (state and constraint variables, e.g. current state of charge of a battery, or connection capacity)
            - the flexibility context which the sensor operates in (other sensors under the same EMS which are relevant, e.g. prices)

            For details on flexibility model and context, see the [documentation on describing flexibility](https://flexmeasures.readthedocs.io/latest/features/scheduling.html#describing-flexibility).
            The schemas we use in this endpoint documentation do not describe the full flexibility model and context (as the docs do), as these are very flexible (e.g. fixed values or sensors).
            The examples below illustrate how to describe a flexibility model and context.

            > **Note:** To schedule an EMS with multiple flexible sensors at once,
            > use the [Assets scheduling endpoint](#/assets/post_api_v3_0_assets__id__schedules_trigger) instead.

            About the duration of the schedule and targets within the schedule:

            - The length of the schedule can be set explicitly through the 'duration' field.
            - Otherwise, it is set by the config setting `FLEXMEASURES_PLANNING_HORIZON`, which defaults to 48 hours.
            - If the flex-model contains targets that lie beyond the planning horizon, the length of the schedule is extended to accommodate them.
            - Finally, the schedule length is limited by the config setting `FLEXMEASURES_MAX_PLANNING_HORIZON`, which defaults to 2520 steps of the sensor's resolution. Targets that exceed the max planning horizon are not accepted.

            About the scheduling algorithm being used:

            - The appropriate algorithm is chosen by FlexMeasures (based on asset type).
            - It's also possible to use custom schedulers and custom flexibility models.
            - If you have ideas for algorithms that should be part of FlexMeasures, let us know: [https://flexmeasures.io/get-in-touch/](https://flexmeasures.io/get-in-touch/)
          security:
            - ApiKeyAuth: []
          parameters:
            - name: id
              in: path
              required: true
              schema: SensorId
          requestBody:
            required: true
            content:
              application/json:
                schema: TriggerScheduleKwargsSchema
                examples:
                  simple_schedule:
                    summary: Simple storage schedule
                    description: |
                      This message triggers a schedule for a storage asset, starting at 10.00am,
                      at which time the state of charge (soc) is 12.1 kWh.
                      The asset is further limited by a maximum soc of 25 kWh.
                      The optimization is done with reference to a fixed price for consumption.

                      This is close to the minimal set of information that needs to be provided to trigger a schedule.
                      It requires no external data series, like dynamic prices in a sensor - look to the complex example for that.
                      Obviously, the outcome of this scheduling problem will be as bland as the input.
                    value:
                      start: "2025-06-02T10:00:00+00:00"
                      flex-context:
                        consumption-price: ".2 EUR/kWh"
                      flex-model:
                        soc-at-start: "12.1 kWh"
                        soc-max: "25 kWh"
                  complex_schedule:
                    summary: Complex 24-hour schedule
                    description: |
                      In this complex example, let's really show off a lot of potential configurations.

                      This message triggers a 24-hour schedule for a storage asset, starting at 10.00am,
                      at which the state of charge (soc) is 12.1 kWh, with a target state of charge of 25 kWh at 4.00pm.

                      The charging efficiency is constant (120%) and the discharging efficiency is determined by the contents of sensor
                      with id 98. If just the ``roundtrip-efficiency`` is known, it can be described with its own field.
                      The global minimum and maximum soc are set to 10 and 25 kWh, respectively.

                      To guarantee a minimum SOC in the period prior, the sensor with ID 300 contains beliefs at 2.00pm and 3.00pm, for 15kWh and 20kWh, respectively.
                      Storage efficiency is set to 99.99%, denoting the state of charge left after each time step equal to the sensor's resolution.
                      Aggregate consumption (of all devices within this EMS) should be priced by sensor 9,
                      and aggregate production should be priced by sensor 10,
                      where the aggregate power flow in the EMS is described by the sum over sensors 13, 14, 15,
                      and the power sensor of the flexible device being optimized (referenced in the endpoint URL).


                      The battery consumption power capacity is limited by sensor 42 and the production capacity is constant (30 kW).

                      Finally, the (contractual and physical) situation of the site is part of the flex-context.
                      The site has a physical power capacity of 100 kVA, but the production capacity is limited to 80 kW,
                      while the consumption capacity is limited by a dynamic capacity contract whose values are recorded under sensor 32.
                      Breaching either capacity is penalized heavily in the optimization problem, with a price of 1000 EUR/kW.
                      Finally, peaks over 50 kW in either direction are penalized with a price of 260 EUR/MW.

                      These penalties can be used to steer the schedule into a certain behavior (e.g. avoiding breaches and peaks),
                      even if no direct financial impacts are expected at the given prices in the real world.

                      For example, site owners may be requested by their network operators to reduce stress on the grid,
                      be it explicitly or under a social contract.

                      Note that, if forecasts for sensors 13, 14 and 15 are not available, a schedule cannot be computed.
                    value:
                      start: "2015-06-02T10:00:00+00:00"
                      duration: "PT24H"
                      flex-model:
                        soc-at-start: "12.1 kWh"
                        state-of-charge:
                          sensor: 24
                        soc-targets:
                          - value: "25 kWh"
                            datetime: "2015-06-02T16:00:00+00:00"
                        soc-minima:
                          sensor: 300
                        soc-min: "10 kWh"
                        soc-max: "25 kWh"
                        charging-efficiency: "120%"
                        discharging-efficiency:
                          sensor: 98
                        storage-efficiency: 0.9999
                        power-capacity: "25kW"
                        consumption-capacity:
                          sensor: 42
                        production-capacity: "30 kW"
                      flex-context:
                        consumption-price:
                          sensor: 9
                        production-price:
                          sensor: 10
                        inflexible-device-sensors: [13, 14, 15]
                        site-power-capacity: "100 kVA"
                        site-production-capacity: "80 kW"
                        site-consumption-capacity:
                          sensor: 32
                        site-production-breach-price: "1000 EUR/kW"
                        site-consumption-breach-price: "1000 EUR/kW"
                        site-peak-consumption: "50 kW"
                        site-peak-production: "50 kW"
                        site-peak-consumption-price: "260 EUR/MW"
                        site-peak-production-price: "260 EUR/MW"
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  schema:
                    type: object
                  examples:
                    schedule_created:
                      summary: Schedule response
                      description: |
                        This message indicates that the scheduling request has been processed without any error.
                        A scheduling job has been created with some Universally Unique Identifier (UUID),
                        which will be picked up by a worker.
                        The given UUID may be used to obtain the resulting schedule: see /sensors/<id>/schedules/<uuid>.
                      value:
                        status: "PROCESSED"
                        schedule: "364bfd06-c1fa-430b-8d25-8f5a547651fb"
                        message: "Request has been processed."
            400:
              description: INVALID_DATA
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            405:
              description: INVALID_METHOD
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
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
        """
        .. :quickref: Schedules; Get schedule for one device
        ---
        get:
          summary: Get schedule for one device
          description: |
            Get a schedule from FlexMeasures.

            Optional fields:

            - "duration" (6 hours by default; can be increased to plan further into the future)
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              required: true
              schema:
                type: string
            - in: path
              name: uuid
              required: true
              schema:
                type: string
            - in: query
              name: duration
              required: false
              schema:
                type: string
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  schema:
                    type: object
                  examples:
                    schedule:
                      summary: Schedule response
                      description: |
                        This message contains a schedule indicating to consume at various power
                        rates from 10am UTC onward for a duration of 45 minutes.
                      value:
                        values: [2.15, 3, 2]
                        start: "2015-06-02T10:00:00+00:00"
                        duration: "PT45M"
                        unit: "MW"
            400:
              description: INVALID_TIMEZONE, INVALID_DOMAIN, INVALID_UNIT, UNKNOWN_SCHEDULE, UNRECOGNIZED_CONNECTION_GROUP
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            405:
              description: INVALID_METHOD
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
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
        if sensor.measures_power and sensor.get_attribute(
            "consumption_is_positive", True
        ):
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
    def fetch_one(self, id, sensor: Sensor):
        """
        .. :quickref: Sensors; Fetch a given sensor
        ---
        get:
          summary: Fetch a given sensor
          description: Fetch a given sensor by its ID.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              description: ID of the sensor to fetch.
              schema: SensorId
          responses:
            200:
              description: One Sensor
              content:
                application/json:
                  schema: SensorSchema
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
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
        """
        .. :quickref: Sensors; Create a new sensor
        ---
        post:
          summary: Create a new Sensor
          description: This endpoint creates a new sensor for a given asset.
          security:
            - ApiKeyAuth: []
          requestBody:
            content:
              application/json:
                schema: SensorSchema
                examples:
                  create_sensor:
                    summary: Create power sensor
                    description: Create a power sensor for an asset
                    value:
                      "name": "power"
                      "event_resolution": "PT1H"
                      "unit": "kWh"
                      "generic_asset_id": 1
          responses:
            201:
              description: New Sensor
              content:
                application/json:
                  schema: SensorSchema
                  examples:
                    create_sensor:
                      summary: Power sensor response
                      description: The whole sensor is returned in the response
                      value:
                        "name": "power"
                        "unit": "kWh"
                        "entity_address": "ea1.2023-08.localhost:fm1.1"
                        "event_resolution": "PT1H"
                        "generic_asset_id": 1
                        "timezone": "UTC"
                        "id": 2
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
        """
        sensor = Sensor(**sensor_data)
        db.session.add(sensor)
        db.session.flush()
        AssetAuditLog.add_record(
            sensor.generic_asset, f"Created sensor '{sensor.name}': {sensor.id}"
        )
        db.session.commit()

        return sensor_schema.dump(sensor), 201

    @route("/<id>", methods=["PATCH"])
    @use_args(partial_sensor_schema)
    @use_kwargs({"sensor": SensorIdField(data_key="id")}, location="path")
    @permission_required_for_context("update", ctx_arg_name="sensor")
    @as_json
    def patch(self, sensor_data: dict, id: int, sensor: Sensor):
        """
        .. :quickref: Sensors; Update a sensor
        ---
        patch:
          summary: Update a sensor
          description: |
            This endpoint updates the descriptive data of an existing sensor.

            Any subset of sensor fields can be sent.
            However, the following fields are not allowed to be updated:
            - id
            - generic_asset_id
            - entity_address

            Only admin users have rights to update the sensor fields. Be aware that changing unit, event resolution and knowledge horizon should currently only be done on sensors without existing belief data (to avoid a serious mismatch), or if you really know what you are doing.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              description: ID of the sensor to update.
              schema: SensorId
          requestBody:
            content:
              application/json:
                schema: SensorSchema
                examples:
                  update_sensor:
                    summary: Update sensor name
                    description: Update the name of a sensor
                    value:
                      "name": "POWER"
          responses:
            200:
              description: Updated Sensor
              content:
                application/json:
                  schema: SensorSchema
                  examples:
                    update_sensor:
                      summary: Update sensor name
                      description: Update the name of a sensor
                      value:
                        "name": "POWER"
                        "unit": "m³/h"
                        "entity_address": "ea1.2023-08.localhost:fm1.1"
                        "event_resolution": "PT10M"
                        "generic_asset_id": 4
                        "timezone": "UTC"
                        "id": 2
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
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
        .. :quickref: Sensors; Delete a sensor
        ---
        delete:
          summary: Delete a sensor
          description: This endpoint deletes an existing sensor, as well as all measurements recorded for it.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              description: ID of the sensor to delete.
              schema: SensorId
          responses:
            204:
              description: DELETED
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
        """

        """Delete time series data."""
        db.session.execute(delete(TimedBelief).filter_by(sensor_id=sensor.id))

        AssetAuditLog.add_record(
            sensor.generic_asset, f"Deleted sensor '{sensor.name}': {sensor.id}"
        )

        sensor_name = sensor.name
        AssetAuditLog.add_record(
            sensor.generic_asset,
            f"Deleted sensor '{sensor_name}': {id}",
        )
        db.session.execute(delete(Sensor).filter_by(id=sensor.id))
        db.session.commit()
        current_app.logger.info("Deleted sensor '%s'." % sensor_name)
        return {}, 204

    @route("/<id>/data", methods=["DELETE"])
    @use_kwargs({"sensor": SensorIdField(data_key="id")}, location="path")
    @permission_required_for_context("delete", ctx_arg_name="sensor")
    @as_json
    def delete_data(self, id: int, sensor: Sensor):
        """
        .. :quickref: Sensors; Delete sensor data
        ---
        delete:
          summary: Delete sensor data
          description: This endpoint deletes all data for a sensor.
          security:
            - ApiKeyAuth: []
          parameters:
            - name: id
              in: path
              description: ID of the sensor to delete data for.
              required: true
              schema: SensorId
          responses:
            204:
              description: SENSOR_DATA_DELETED
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
        """
        db.session.execute(delete(TimedBelief).filter_by(sensor_id=sensor.id))
        AssetAuditLog.add_record(
            sensor.generic_asset,
            f"Deleted data for sensor '{sensor.name}': {sensor.id}",
        )
        db.session.commit()

        return {}, 204

    @route("/<id>/stats", methods=["GET"])
    @use_kwargs({"sensor": SensorIdField(data_key="id")}, location="path")
    @use_kwargs(
        {
            "sort_keys": fields.Boolean(data_key="sort", load_default=True),
            "event_start_time": fields.Str(load_default=None),
            "event_end_time": fields.Str(load_default=None),
        },
        location="query",
    )
    @permission_required_for_context("read", ctx_arg_name="sensor")
    @as_json
    def get_stats(
        self,
        id,
        sensor: Sensor,
        event_start_time: str,
        event_end_time: str,
        sort_keys: bool,
    ):
        """
        .. :quickref: Sensors; Get sensor stats
        ---
        get:
          summary: Get sensor stats
          description: This endpoint fetches sensor stats for all the historical data.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              description: ID of the sensor to fetch stats for.
              schema: SensorId
            - in: query
              name: event_start_time
              description: Start of the period to fetch stats for, in ISO 8601 format.
              schema:
                type: string
                format: date-time
            - in: query
              name: event_end_time
              description: End of the period to fetch stats for, in ISO 8601 format.
              schema:
                type: string
                format: date-time
            - in: query
              name: sort_keys
              description: Whether to sort the stats by keys.
              schema:
                type: boolean
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  examples:
                    successful_response:
                      summary: Successful response
                      description: A successful response with sensor stats
                      value:
                        "some data source":
                          "First event start": "2015-06-02T10:00:00+00:00"
                          "Last event end": "2015-10-02T10:00:00+00:00"
                          "Last recorded": "2015-10-02T10:01:12+00:00"
                          "Min value": 0.0
                          "Max value": 100.0
                          "Mean value": 50.0
                          "Sum over values": 500.0
                          "Number of values": 10
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
        """

        return (
            get_sensor_stats(sensor, event_start_time, event_end_time, sort_keys),
            200,
        )

    @route("/<id>/status", methods=["GET"])
    @use_kwargs({"sensor": SensorIdField(data_key="id")}, location="path")
    @permission_required_for_context("read", ctx_arg_name="sensor")
    @as_json
    def get_status(self, id, sensor):
        """
        .. :quickref: Data; Get status of sensor data
        ---
        get:
          summary: Get sensor status
          description: |
            This endpoint fetches the current status of data for the specified sensor.
            The status includes information about the sensor data's status, staleness and resolution.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              description: ID of the sensor to fetch status for.
              schema: SensorId
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  examples:
                    successful_response:
                      summary: Successful response
                      description: A successful response with sensor status data
                      value:
                        - staleness: "2 hours"
                          stale: true
                          staleness_since: "2024-01-15T14:30:00+00:00"
                          reason: "data is outdated"
                          source_type: "forecast"
                          id: 64907
                          name: "temperature"
                          resolution: "5 minutes"
                          asset_name: "Building A"
                          relation: "sensor belongs to this asset"
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            404:
              description: ASSET_NOT_FOUND
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Sensors
        """

        status_data = serialize_sensor_status_data(sensor=sensor)

        return {"sensors_data": status_data}, 200
