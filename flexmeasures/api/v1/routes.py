from flask_security import auth_token_required

from flexmeasures.api.common.utils.api_utils import list_access
from flexmeasures.api.common.utils.decorators import as_response_type
from flexmeasures.api.common.utils.validators import usef_roles_accepted
from flexmeasures.api.v1 import (
    flexmeasures_api as flexmeasures_api_v1,
    implementations as v1_implementations,
)


# The service listing for this API version (import from previous version or update if needed)
v1_service_listing = {
    "version": "1.0",
    "services": [
        {
            "name": "getMeterData",
            "access": ["Aggregator", "Supplier", "MDC", "DSO", "Prosumer", "ESCo"],
            "description": "Request meter reading",
        },
        {
            "name": "postMeterData",
            "access": ["Aggregator", "Supplier", "MDC", "DSO", "Prosumer", "ESCo"],
            "description": "Send meter reading",
        },
    ],
}


@flexmeasures_api_v1.route("/getMeterData", methods=["GET", "POST"])
@as_response_type("GetMeterDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_service_listing, "getMeterData"))
def get_meter_data():
    """API endpoint to get meter data.

    .. :quickref: Data; Download meter data from the platform

    **Optional fields**

    - "resolution" (see :ref:`resolutions`)
    - "horizon" (see :ref:`beliefs`)
    - "prior" (see :ref:`beliefs`)
    - "source" (see :ref:`sources`)

    **Example request**

    This "GetMeterDataRequest" message requests measured consumption between 0.00am and 1.30am for charging station 1.

    .. code-block:: json

        {
            "type": "GetMeterDataRequest",
            "connection": "CS 1",
            "start": "2015-01-01T00:00:00Z",
            "duration": "PT1H30M",
            "unit": "MW"
        }

    **Example response**

    This "GetMeterDataResponse" message indicates that consumption for charging station 1 was measured in 15-minute
    intervals.

    .. sourcecode:: json

        {
            "type": "GetMeterDataResponse",
            "connection": "CS 1",
            "values": [
                306.66,
                306.66,
                0,
                0,
                306.66,
                306.66
            ],
            "start": "2015-01-01T00:00:00Z",
            "duration": "PT1H30M",
            "unit": "MW"
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_DOMAIN, INVALID_MESSAGE_TYPE, INVALID_SOURCE, INVALID_TIMEZONE, INVALID_UNIT, UNRECOGNIZED_ASSET, or UNRECOGNIZED_CONNECTION_GROUP
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 405: INVALID_METHOD
    """
    return v1_implementations.get_meter_data_response()


@flexmeasures_api_v1.route("/postMeterData", methods=["POST"])
@as_response_type("PostMeterDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_service_listing, "postMeterData"))
def post_meter_data():
    """API endpoint to post meter data.

    .. :quickref: Data; Upload meter data to the platform

    **Optional fields**

    - "horizon" (see :ref:`prognoses`)

    **Example request**

    This "PostMeterDataRequest" message posts measured consumption for 15-minute intervals between 0.00am and 1.30am for
    charging stations 1, 2 and 3 (negative values denote production).

    .. code-block:: json

        {
            "type": "PostMeterDataRequest",
            "groups": [
                {
                    "connections": [
                        "CS 1",
                        "CS 3"
                    ],
                    "values": [
                        306.66,
                        306.66,
                        0,
                        0,
                        306.66,
                        306.66
                    ]
                },
                {
                    "connections": [
                        "CS 2"
                    ],
                    "values": [
                        306.66,
                        0,
                        0,
                        0,
                        306.66,
                        306.66
                    ]
                }
            ],
            "start": "2015-01-01T00:00:00Z",
            "duration": "PT1H30M",
            "unit": "MW"
        }

    It is allowed to send higher resolutions (in this example for instance, 30 minutes) which will be upsampled.

    **Example response**

    This "PostMeterDataResponse" message indicates that the measurement has been processed without any error.

    .. sourcecode:: json

        {
            "type": "PostMeterDataResponse",
            "status": "PROCESSED",
            "message": "Request has been processed."
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_DOMAIN, INVALID_MESSAGE_TYPE, INVALID_TIMEZONE, INVALID_UNIT, REQUIRED_INFO_MISSING, UNRECOGNIZED_ASSET or UNRECOGNIZED_CONNECTION_GROUP
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 405: INVALID_METHOD
    """
    return v1_implementations.post_meter_data_response()


@flexmeasures_api_v1.route("/getService", methods=["GET"])
@as_response_type("GetServiceResponse")
def get_service():
    """API endpoint to get a service listing for this version.

    .. :quickref: Public; Obtain a service listing for this version

    :resheader Content-Type: application/json
    :status 200: PROCESSED
    """
    return v1_implementations.get_service_response(v1_service_listing)
