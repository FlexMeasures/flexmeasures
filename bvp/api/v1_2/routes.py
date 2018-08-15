import copy

from flask_security import auth_token_required

from bvp.api.common.utils.api_utils import check_access, append_doc_of
from bvp.api.common.utils.decorators import as_response_type
from bvp.api.common.utils.validators import usef_roles_accepted
from bvp.api.v1 import implementations as v1_implementations
from bvp.api.v1_1 import routes as v1_1_routes, implementations as v1_1_implementations
from bvp.api.v1_2 import (
    bvp_api as bvp_api_v1_2,
    implementations as v1_2_implementations,
)

# The service listing for this API version (import from previous version or update if needed)
v1_2_service_listing = copy.deepcopy(v1_1_routes.v1_1_service_listing)
v1_2_service_listing["version"] = "1.2"
v1_2_service_listing["services"].append(
    {
        "name": "getDeviceMessage",
        "access": ["Prosumer", "ESCo"],
        "description": "Get an Active Demand & Supply (ADS) request for a certain type of control action, "
        "including control set points",
    }
)
v1_2_service_listing["services"].append(
    {
        "name": "postUdiEvent",
        "access": ["Prosumer", "ESCo"],
        "description": "Send a description of some flexible consumption or production process as a USEF Device "
        "Interface (UDI) event, including device capabilities (control constraints)",
    }
)


@bvp_api_v1_2.route("/getDeviceMessage", methods=["GET"])
@as_response_type("GetDeviceMessageResponse")
@auth_token_required
@usef_roles_accepted(*check_access(v1_2_service_listing, "getDeviceMessage"))
def get_device_message():
    return v1_2_implementations.get_device_message_response()


@bvp_api_v1_2.route("/postUdiEvent", methods=["GET"])
@as_response_type("PostUdiEventResponse")
@auth_token_required
@usef_roles_accepted(*check_access(v1_2_service_listing, "postUdiEvent"))
def post_udi_event():
    return v1_2_implementations.post_udi_event_response()


@bvp_api_v1_2.route("/getConnection", methods=["GET"])
@auth_token_required
@usef_roles_accepted(*check_access(v1_2_service_listing, "getConnection"))
@append_doc_of(v1_1_routes.get_connection)
def get_connection():
    return v1_1_implementations.get_connection_response()


@bvp_api_v1_2.route("/postPriceData", methods=["POST"])
@auth_token_required
@usef_roles_accepted(*check_access(v1_2_service_listing, "postPriceData"))
@append_doc_of(v1_1_routes.post_price_data)
def post_price_data():
    return v1_1_implementations.post_price_data_response()


@bvp_api_v1_2.route("/postWeatherData", methods=["POST"])
@auth_token_required
@usef_roles_accepted(*check_access(v1_2_service_listing, "postWeatherData"))
@append_doc_of(v1_1_routes.post_weather_data)
def post_weather_data():
    return v1_1_implementations.post_weather_data_response()


@bvp_api_v1_2.route("/getPrognosis", methods=["GET"])
@auth_token_required
@usef_roles_accepted(*check_access(v1_2_service_listing, "getPrognosis"))
@append_doc_of(v1_1_routes.get_prognosis)
def get_prognosis():
    return v1_1_implementations.get_prognosis_response()


@bvp_api_v1_2.route("/getMeterData", methods=["GET"])
@as_response_type("GetMeterDataResponse")
@auth_token_required
@usef_roles_accepted(*check_access(v1_2_service_listing, "getMeterData"))
@append_doc_of(v1_1_routes.get_meter_data)
def get_meter_data():
    return v1_implementations.get_meter_data_response()


@bvp_api_v1_2.route("/postMeterData", methods=["POST"])
@as_response_type("PostMeterDataResponse")
@auth_token_required
@usef_roles_accepted(*check_access(v1_2_service_listing, "postMeterData"))
@append_doc_of(v1_1_routes.post_meter_data)
def post_meter_data():
    return v1_implementations.post_meter_data_response()


@bvp_api_v1_2.route("/getService", methods=["GET"])
@as_response_type("GetServiceResponse")
@append_doc_of(v1_1_routes.get_service)
def get_service(service_listing=v1_2_service_listing):
    return v1_implementations.get_service_response(service_listing)
