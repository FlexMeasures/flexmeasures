from flask import request

from flask_security import auth_token_required, roles_required

from bvp.api import v1
from bvp.api.common.utils import check_access, get_service_response, usef_roles_accepted
from bvp.api.v1_1 import bvp_api

# The service listing for this API version (import from previous version or update if needed)
service_listing = {
    "version": "1.1",
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
        {
            "name": "getPrognosis",
            "access": ["Aggregator", "Supplier", "MDC", "DSO", "Prosumer", "ESCo"],
            "description": "Request load planning",
        },
        {
            "name": "postPrognosis",
            "access": ["Aggregator", "Supplier", "MDC", "DSO", "Prosumer", "ESCo"],
            "description": "Send prediction",
        },
        {
            "name": "postUdiEvent",
            "access": ["Prosumer", "ESCo"],
            "description": "Send a description of some flexible consumption or production process as a USEF Device "
            "Interface (UDI) event, including device capabilities (control constraints)",
        },
        {
            "name": "getDeviceMessage",
            "access": ["Prosumer", "ESCo"],
            "description": "Get an Active Demand & Supply (ADS) request for a certain type of control action, "
            "including control set points",
        },
    ],
}


@bvp_api.route("/getMeterData", methods=["GET"])
@usef_roles_accepted(*check_access(service_listing, "getMeterData"))
def get_meter_data():
    return v1.routes.get_meter_data()


@bvp_api.route("/postMeterData", methods=["POST"])
@usef_roles_accepted(*check_access(service_listing, "postMeterData"))
def post_meter_data():
    return v1.routes.post_meter_data()


@bvp_api.route("/getLatestTaskRun", methods=["GET"])
@auth_token_required
def get_task_run():
    return v1.routes.get_task_run()


@bvp_api.route("/postLatestTaskRun", methods=["POST"])
@auth_token_required
@roles_required("task-runner")
def post_task_run():
    return v1.routes.post_task_run()


@bvp_api.route("/getService", methods=["GET"])
def get_service():
    return get_service_response(service_listing, request.args.get("access"))
