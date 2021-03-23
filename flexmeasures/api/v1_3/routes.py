import copy

from flask_security import auth_token_required

from flexmeasures.api.common.utils.api_utils import list_access, append_doc_of
from flexmeasures.api.common.utils.decorators import as_response_type
from flexmeasures.api.common.utils.validators import usef_roles_accepted
from flexmeasures.api.v1 import implementations as v1_implementations
from flexmeasures.api.v1_1 import implementations as v1_1_implementations
from flexmeasures.api.v1_2 import routes as v1_2_routes
from flexmeasures.api.v1_3 import (
    flexmeasures_api as flexmeasures_api_v1_3,
    implementations as v1_3_implementations,
)

# The service listing for this API version (import from previous version or update if needed)
v1_3_service_listing = copy.deepcopy(v1_2_routes.v1_2_service_listing)
v1_3_service_listing["version"] = "1.3"


@flexmeasures_api_v1_3.route("/getDeviceMessage", methods=["GET"])
@as_response_type("GetDeviceMessageResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_3_service_listing, "getDeviceMessage"))
def get_device_message():
    """API endpoint to get device message.

    .. :quickref: Control; Download control signal from the platform

    **Optional fields**

    - "duration" (6 hours by default; can be increased to plan further into the future)

    **Example request**

    This "GetDeviceMessageRequest" message requests targeted consumption for UDI event 203 of device 10 of owner 7.

    .. code-block:: json

        {
            "type": "GetDeviceMessageRequest",
            "event": "ea1.2018-06.io.flexmeasures.company:7:10:203:soc"
        }

    **Example response**

    This "GetDeviceMessageResponse" message indicates that the target for UDI event 203 is to consume at various power
    rates from 10am UTC onwards for a duration of 45 minutes.

    .. sourcecode:: json

        {
            "type": "GetDeviceMessageResponse",
            "event": "ea1.2018-06.io.flexmeasures.company:7:10:203:soc",
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
    :status 400: INVALID_MESSAGE_TYPE, INVALID_TIMEZONE, INVALID_DOMAIN, INVALID_UNIT, UNKNOWN_SCHEDULE, UNRECOGNIZED_CONNECTION_GROUP, or UNRECOGNIZED_UDI_EVENT
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 405: INVALID_METHOD
    :status 422: UNPROCESSABLE_ENTITY
    """
    return v1_3_implementations.get_device_message_response()


@flexmeasures_api_v1_3.route("/postUdiEvent", methods=["POST"])
@as_response_type("PostUdiEventResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_3_service_listing, "postUdiEvent"))
def post_udi_event():
    """API endpoint to post UDI event.

    .. :quickref: Control; Upload flexibility constraints to the platform

    **Example request A**

    This "PostUdiEventRequest" message posts a state of charge (soc) of 12.1 kWh at 10.00am
    as UDI event 203 of device 10 of owner 7.

    .. code-block:: json

        {
            "type": "PostUdiEventRequest",
            "event": "ea1.2018-06.io.flexmeasures.company:7:10:203:soc",
            "value": 12.1,
            "unit": "kWh",
            "datetime": "2015-06-02T10:00:00+00:00"
        }

    **Example request B**

    This "PostUdiEventRequest" message posts a state of charge (soc) of 12.1 kWh at 10.00am,
    and a target state of charge of 25 kWh at 4.00pm,
    as UDI event 204 of device 10 of owner 7.

    .. code-block:: json

        {
            "type": "PostUdiEventRequest",
            "event": "ea1.2018-06.io.flexmeasures.company:7:10:204:soc-with-targets",
            "value": 12.1,
            "unit": "kWh",
            "datetime": "2015-06-02T10:00:00+00:00",
            "targets": [
                {
                    "value": 25,
                    "datetime": "2015-06-02T16:00:00+00:00"
                }
            ]
        }

    **Example response**

    This "PostUdiEventResponse" message indicates that the UDI event has been processed without any error.

    .. sourcecode:: json

        {
            "type": "PostUdiEventResponse",
            "status": "PROCESSED",
            "message": "Request has been processed."
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INCOMPLETE_UDI_EVENT, INVALID_MESSAGE_TYPE, INVALID_TIMEZONE, INVALID_DATETIME, INVALID_DOMAIN,
                 INVALID_UNIT, OUTDATED_UDI_EVENT, PTUS_INCOMPLETE, OUTDATED_UDI_EVENT or UNRECOGNIZED_UDI_EVENT
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 405: INVALID_METHOD
    """
    return v1_3_implementations.post_udi_event_response()


@flexmeasures_api_v1_3.route("/getConnection", methods=["GET"])
@as_response_type("GetConnectionResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_3_service_listing, "getConnection"))
@append_doc_of(v1_2_routes.get_connection)
def get_connection():
    return v1_1_implementations.get_connection_response()


@flexmeasures_api_v1_3.route("/postPriceData", methods=["POST"])
@as_response_type("PostPriceDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_3_service_listing, "postPriceData"))
@append_doc_of(v1_2_routes.post_price_data)
def post_price_data():
    return v1_1_implementations.post_price_data_response()


@flexmeasures_api_v1_3.route("/postWeatherData", methods=["POST"])
@as_response_type("PostWeatherDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_3_service_listing, "postWeatherData"))
@append_doc_of(v1_2_routes.post_weather_data)
def post_weather_data():
    return v1_1_implementations.post_weather_data_response()


@flexmeasures_api_v1_3.route("/getPrognosis", methods=["GET"])
@as_response_type("GetPrognosisResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_3_service_listing, "getPrognosis"))
@append_doc_of(v1_2_routes.get_prognosis)
def get_prognosis():
    return v1_1_implementations.get_prognosis_response()


@flexmeasures_api_v1_3.route("/getMeterData", methods=["GET"])
@as_response_type("GetMeterDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_3_service_listing, "getMeterData"))
@append_doc_of(v1_2_routes.get_meter_data)
def get_meter_data():
    return v1_implementations.get_meter_data_response()


@flexmeasures_api_v1_3.route("/postMeterData", methods=["POST"])
@as_response_type("PostMeterDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_3_service_listing, "postMeterData"))
@append_doc_of(v1_2_routes.post_meter_data)
def post_meter_data():
    return v1_implementations.post_meter_data_response()


@flexmeasures_api_v1_3.route("/postPrognosis", methods=["POST"])
@as_response_type("PostPrognosisResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_3_service_listing, "postPrognosis"))
@append_doc_of(v1_2_routes.post_prognosis)
def post_prognosis():
    return v1_1_implementations.post_prognosis_response()


@flexmeasures_api_v1_3.route("/getService", methods=["GET"])
@as_response_type("GetServiceResponse")
@append_doc_of(v1_2_routes.get_service)
def get_service(service_listing=v1_3_service_listing):
    return v1_implementations.get_service_response(service_listing)
