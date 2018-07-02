from flask import request
from flask_security import auth_token_required

from bvp.api.common.utils.api_utils import check_access
from bvp.api.common.utils.validators import usef_roles_accepted
from bvp.api.v1 import bvp_api as bvp_api_v1
from bvp.api.v1.implementations import get_meter_data_response, post_meter_data_response, get_service_response
from bvp.api.common.utils.decorators import as_response_type


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


@bvp_api_v1.route("/getMeterData", methods=["GET", "POST"])
@as_response_type('GetMeterDataResponse')
@auth_token_required
@usef_roles_accepted(*check_access(service_listing, "getMeterData"))
def get_meter_data():
    """API endpoint to get meter data.

    .. :quickref: User; Download meter data from the platform

    A Prosumer owns a number of energy consuming or producing assets behind a connection to the electricity grid.
    A Prosumer can query the BVP web service for its own meter data using the *getMeterData* service.

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

    :reqheader Content-Type: application/json
    :reqheader Authorization: The authentication token
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_MESSAGE_TYPE, INVALID_TIMEZONE, INVALID_UNIT, or UNRECOGNIZED_CONNECTION_GROUP
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 405: INVALID_METHOD
    """
    return get_meter_data_response()


@bvp_api_v1.route("/postMeterData", methods=["POST"])
@as_response_type('PostMeterDataResponse')
@auth_token_required
@usef_roles_accepted(*check_access(service_listing, "postMeterData"))
def post_meter_data():
    """API endpoint to post meter data.

    .. :quickref: User; Upload meter data to the platform

    The meter data company (MDC) represents a trusted party that shares the meter data of connections that are
    registered within the BVP. In case the MDC cannot be queried to provide relevant meter data (e.g. because the role
    has not taken up by a market party), the party taking up the Prosumer role will also take up the MDC role, and will
    bear the responsibility to post their own meter data with the *postMeterData* service.

    The granularity of the meter data and the time delay between the actual measurement and its posting should be
    specified in the service contract between Prosumer and Aggregator. In this example, the Prosumer decided to share
    the meter data in 15-minute intervals and only after 1.30am. It is desirable to send meter readings in 5-minute
    intervals (or with an even finer granularity), and as soon as possible after measurement.

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



    **Example response**

    This "PostMeterDataResponse" message indicates that the measurement has been processed without any error.

    .. sourcecode:: json

        {
            "type": "PostMeterDataResponse",
            "status": "PROCESSED",
            "message": "Meter data has been processed."
        }

    """
    return post_meter_data_response()


@bvp_api_v1.route("/getService", methods=["GET"])
@as_response_type('GetServiceResponse')
def get_service():
    """API endpoint to get a service listing for this version.

    .. :quickref: Public; Obtain a service listing for this version

    """
    return get_service_response(service_listing, request.args.get("access"))
