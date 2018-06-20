from flask import request

from bvp.api.common.utils import check_access, get_service_response, get_meter_data_response, post_meter_data_response, usef_roles_accepted
from bvp.api.v1 import bvp_api


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


@bvp_api.route("/getMeterData", methods=["GET"])
@usef_roles_accepted(*check_access(service_listing, "getMeterData"))
def get_meter_data():
    return get_meter_data_response()


@bvp_api.route("/postMeterData", methods=["POST"])
@usef_roles_accepted(*check_access(service_listing, "postMeterData"))
def post_meter_data():
    return post_meter_data_response()


@bvp_api.route("/getService", methods=["GET"])
def get_service():
    return get_service_response(service_listing, request.args.get("access"))
