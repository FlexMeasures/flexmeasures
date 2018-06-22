from flask import request

from flask_security import auth_token_required, roles_required

from bvp.api.common.utils import (
    check_access,
    get_service_response,
    get_meter_data_response,
    post_meter_data_response,
    usef_roles_accepted,
)
from bvp.api.v1 import bvp_api as bvp_api_v1, implementations as v1_impl


# The service listing for this API version (import from previous version or update if needed)
service_listing = {
    "version": "1.0",
    "services": [
        {
            "name": "getMeterData",
            "access": ["Aggregator", "Supplier", "MDC", "DSO", "Prosumer", "ESCo"],
            "description": "Request meter reading",
        },
        {
            "name": "postMeterData",
            "access": ["MDC"],
            "description": "Send meter reading",
        },
    ],
}


@bvp_api_v1.route("/getMeterData", methods=["GET"])
@usef_roles_accepted(*check_access(service_listing, "getMeterData"))
def get_meter_data():
    return get_meter_data_response()


@bvp_api_v1.route("/postMeterData", methods=["POST"])
@usef_roles_accepted(*check_access(service_listing, "postMeterData"))
def post_meter_data():
    return post_meter_data_response()


@bvp_api_v1.route("/getService", methods=["GET"])
def get_service():
    return get_service_response(service_listing, request.args.get("access"))


@bvp_api_v1.route("/getLatestTaskRun", methods=["GET"])
@auth_token_required
def get_task_run():
    return v1_impl.get_task_run()


@bvp_api_v1.route("/postLatestTaskRun", methods=["POST"])
@auth_token_required
@roles_required("task-runner")
def post_task_run():
    return v1_impl.post_task_run()
