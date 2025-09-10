from flask import current_app
from flask_classful import FlaskView, route
from flask_security import auth_required, current_user
from webargs.flaskparser import use_args

from flexmeasures.api.common.schemas.sensor_data import (
    GetSensorDataSchema,
    GetSensorDataSchemaEntityAddress,
    PostSensorDataSchemaEntityAddress,
)
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.api.common.utils.api_utils import save_and_enqueue
from flexmeasures.api.common.responses import request_processed


get_sensor_schema_ea = GetSensorDataSchemaEntityAddress()
post_sensor_schema_ea = PostSensorDataSchemaEntityAddress()


class SensorEntityAddressAPI(FlaskView):
    """
    DEPRECATED endpoints for getting and posting sensor data.

    Use the endpoints with "<id>" in the URL, which do not rely on an entity address.

    Also, these are last remnants on using entity addresses anywhere.
    Once these endpoints are actually removed, we can consider also deleting entity
    address supporting code (in utils, some schemas, etc.)
    """

    route_base = "/sensors"
    trailing_slash = False
    decorators = [auth_required()]

    @route("/data", methods=["GET"])
    @use_args(
        get_sensor_schema_ea,
        location="query",
    )
    @permission_required_for_context("read", ctx_arg_pos=1, ctx_arg_name="sensor")
    def get_data_deprecated(self, sensor_data_description: dict):
        """Get sensor data from FlexMeasures.

        .. :quickref: Data; Download sensor data (DEPRECATED)

        This endpoint is deprecated. Get from /sensors/(id)/data instead.
        """
        sensor = sensor_data_description["sensor"]
        current_app.logger.warning(
            f"User {current_user} called the deprecated endpoint GET /sensors/data for sensor {sensor.id}. Should start using /sensors/{sensor.id}/data."
        )
        response = GetSensorDataSchema.load_data_and_make_response(
            sensor_data_description
        )
        d, s = request_processed()
        return dict(**response, **d), s

    @route("/data", methods=["POST"])
    @use_args(
        post_sensor_schema_ea,
        location="json",
    )
    @permission_required_for_context(
        "create-children",
        ctx_arg_pos=1,
        ctx_arg_name="bdf",
        ctx_loader=lambda bdf: bdf.sensor,
        pass_ctx_to_loader=True,
    )
    def post_data_deprecated(self, data: dict):
        """
        Post sensor data to FlexMeasures.

        .. :quickref: Data; Post sensor data (DEPRECATED)

        This endpoint is deprecated. Post to /sensors/(id)/data instead.
        """
        bdf = data.get("bdf")
        sensor_id = bdf.sensor.id if bdf is not None else "<id>"
        current_app.logger.debug(
            f"User {current_user} called the deprecated endpoint /sensors/data for sensor {sensor_id}. Should start using /sensors/{sensor_id}/data."
        )
        response, code = save_and_enqueue(bdf)
        return response, code
