from flask import request

from flask_security import auth_token_required

from bvp.api.v1 import routes
from bvp.api.common.utils.api_utils import check_access
from bvp.api.common.utils.validators import usef_roles_accepted
from bvp.api.v1_1 import bvp_api
from bvp.api.common.utils.decorators import as_response_type


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
@as_response_type("GetMeterDataResponse")
@auth_token_required
@usef_roles_accepted(*check_access(service_listing, "getMeterData"))
def get_meter_data():
    """Get meter data v1.1"""
    return routes.get_meter_data()


@bvp_api.route("/postMeterData", methods=["POST"])
@as_response_type("PostMeterDataResponse")
@auth_token_required
@usef_roles_accepted(*check_access(service_listing, "postMeterData"))
def post_meter_data():
    return routes.post_meter_data()


@bvp_api.route("/getService", methods=["GET"])
@as_response_type("GetServiceResponse")
def get_service():
    return routes.get_service_response(service_listing, request.args.get("access"))
