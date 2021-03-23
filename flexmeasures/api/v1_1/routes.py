from flask_security import auth_token_required

from flexmeasures.api.common.utils.api_utils import list_access, append_doc_of
from flexmeasures.api.common.utils.decorators import as_response_type
from flexmeasures.api.common.utils.validators import usef_roles_accepted
from flexmeasures.api.v1 import (
    routes as v1_routes,
    implementations as v1_implementations,
)
from flexmeasures.api.v1_1 import (
    flexmeasures_api as flexmeasures_api_v1_1,
    implementations as v1_1_implementations,
)

# The service listing for this API version (import from previous version or update if needed)
v1_1_service_listing = {
    "version": "1.1",
    "services": [
        {
            "name": "getConnection",
            "access": ["Aggregator", "Supplier", "MDC", "DSO", "Prosumer", "ESCo"],
            "description": "Request entity addresses of connections",
        },
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
            "name": "postPriceData",
            "access": ["Aggregator", "Supplier", "MDC", "DSO", "Prosumer", "ESCo"],
            "description": "Send prices",
        },
        {
            "name": "postWeatherData",
            "access": ["Aggregator", "Supplier", "MDC", "DSO", "Prosumer", "ESCo"],
            "description": "Send weather forecasts or weather sensor observations",
        },
    ],
}


@flexmeasures_api_v1_1.route("/getConnection", methods=["GET"])
@as_response_type("GetConnectionResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_1_service_listing, "getConnection"))
def get_connection():
    """API endpoint to get the user's connections as entity addresses ordered from newest to oldest.

    .. :quickref: Asset; Retrieve entity addresses of connections


    **Example request**

    .. code-block:: json

        {
            "type": "GetConnectionRequest",
        }

    **Example response**

    This "GetConnectionResponse" message indicates that the user had access rights to retrieve four entity addresses
    owned by three different users.

    .. sourcecode:: json

        {
            "type": "GetConnectionResponse",
            "connections": [
                "ea1.2018-06.io.flexmeasures.company:3:4",
                "ea1.2018-06.io.flexmeasures.company:8:3",
                "ea1.2018-06.io.flexmeasures.company:9:2",
                "ea1.2018-06.io.flexmeasures.company:3:1"
            ],
            "names": [
                "CS 4",
                "CS 3",
                "CS 2",
                "CS 1"
            ]
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_MESSAGE_TYPE
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 405: INVALID_METHOD
    """
    return v1_1_implementations.get_connection_response()


@flexmeasures_api_v1_1.route("/postPriceData", methods=["POST"])
@as_response_type("PostPriceDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_1_service_listing, "postPriceData"))
def post_price_data():
    """API endpoint to post price data.

    .. :quickref: Data; Upload price data to the platform

    **Optional fields**

    - "horizon" (see :ref:`prognoses`)

    **Example request**

    This "PostPriceDataRequest" message posts prices for hourly intervals between midnight and midnight the next day
    for the EPEX SPOT day-ahead auction.
    The horizon indicates that the prices were published at 1pm on December 31st 2014
    (i.e. 35 hours ahead of midnight the next day).

    .. code-block:: json

        {
            "type": "PostPriceDataRequest",
            "market": "ea1.2018-06.localhost:epex_da",
            "values": [
                52.37,
                51.14,
                49.09,
                48.35,
                48.47,
                49.98,
                58.7,
                67.76,
                69.21,
                70.26,
                70.46,
                70,
                70.7,
                70.41,
                70,
                64.53,
                65.92,
                69.72,
                70.51,
                75.49,
                70.35,
                70.01,
                66.98,
                58.61
            ],
            "start": "2015-01-01T15:00:00+09:00",
            "duration": "PT24H",
            "horizon": "PT35H",
            "unit": "EUR/MWh"
        }

    **Example response**

    This "PostPriceDataResponse" message indicates that the prices have been processed without any error.

    .. sourcecode:: json

        {
            "type": "PostPriceDataResponse",
            "status": "PROCESSED",
            "message": "Request has been processed."
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_DOMAIN, INVALID_MESSAGE_TYPE, INVALID_TIMEZONE, INVALID_UNIT, REQUIRED_INFO_MISSING, UNRECOGNIZED_ASSET or UNRECOGNIZED_MARKET
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 405: INVALID_METHOD

    """
    return v1_1_implementations.post_price_data_response()


@flexmeasures_api_v1_1.route("/postWeatherData", methods=["POST"])
@as_response_type("PostWeatherDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_1_service_listing, "postWeatherData"))
def post_weather_data():
    """API endpoint to post weather data, such as:

    - "radiation" (with kW/m² as unit)
    - "temperature" (with °C as unit)
    - "wind_speed" (with m/s as unit)

    The sensor type is part of the unique entity address for each sensor, together with the sensor's latitude and longitude.

    .. :quickref: Data; Upload weather data to the platform

    **Optional fields**

    - "horizon" (see :ref:`prognoses`)

    **Example request**

    This "PostWeatherDataRequest" message posts temperature forecasts for 15-minute intervals between 3.00pm and 4.30pm
    for a weather sensor located at latitude 33.4843866 and longitude 126.477859. The forecasts were made at noon.

    .. code-block:: json

        {
            "type": "PostWeatherDataRequest",
            "groups": [
                {
                    "sensor": "ea1.2018-06.localhost:temperature:33.4843866:126.477859",
                    "values": [
                        20.04,
                        20.23,
                        20.41,
                        20.51,
                        20.55,
                        20.57
                    ]
                }
            ],
            "start": "2015-01-01T15:00:00+09:00",
            "duration": "PT1H30M",
            "horizon": "PT3H",
            "unit": "°C"
        }

    It is allowed to send higher resolutions (in this example for instance, 30 minutes) which will be upsampled.

    **Example response**

    This "PostWeatherDataResponse" message indicates that the forecast has been processed without any error.

    .. sourcecode:: json

        {
            "type": "PostWeatherDataResponse",
            "status": "PROCESSED",
            "message": "Request has been processed."
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_DOMAIN, INVALID_MESSAGE_TYPE, INVALID_TIMEZONE, INVALID_UNIT, REQUIRED_INFO_MISSING, UNRECOGNIZED_ASSET or UNRECOGNIZED_SENSOR
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 405: INVALID_METHOD

    """
    return v1_1_implementations.post_weather_data_response()


@flexmeasures_api_v1_1.route("/getPrognosis", methods=["GET"])
@as_response_type("GetPrognosisResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_1_service_listing, "getPrognosis"))
def get_prognosis():
    """API endpoint to get prognosis.

    .. :quickref: Data; Download prognosis from the platform

    **Optional fields**

    - "resolution" (see :ref:`resolutions`)
    - "horizon" (see :ref:`beliefs`)
    - "prior" (see :ref:`beliefs`)
    - "source" (see :ref:`sources`)

    **Example request**

    This "GetPrognosisRequest" message requests prognosed consumption between 0.00am and 1.30am for charging station 1,
    with a rolling horizon of 6 hours before the end of each 15 minute time interval.

    .. code-block:: json

        {
            "type": "GetPrognosisRequest",
            "connection": "CS 1",
            "start": "2015-01-01T00:00:00Z",
            "duration": "PT1H30M",
            "horizon": "PT6H",
            "resolution": "PT15M",
            "unit": "MW"
        }

    **Example response**

    This "GetPrognosisResponse" message indicates that a prognosis of consumption for charging station 1 was available
    6 hours before the start of each 15 minute time interval.

    .. sourcecode:: json

        {
            "type": "GetPrognosisResponse",
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
    :status 400: INVALID_MESSAGE_TYPE, INVALID_SOURCE, INVALID_TIMEZONE, INVALID_UNIT, UNRECOGNIZED_ASSET, or UNRECOGNIZED_CONNECTION_GROUP
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 405: INVALID_METHOD
    """
    return v1_1_implementations.get_prognosis_response()


@flexmeasures_api_v1_1.route("/postPrognosis", methods=["POST"])
@as_response_type("PostPrognosisResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_1_service_listing, "postPrognosis"))
def post_prognosis():
    """API endpoint to post prognoses about meter data.

    .. :quickref: Data; Upload prognosis to the platform

    **Optional fields**

    - "horizon" (see :ref:`prognoses`)

    **Example request**

    This "PostPrognosisRequest" message posts prognosed consumption for 15-minute intervals between 0.00am and 1.30am for
    charging stations 1, 2 and 3 (negative values denote production), prognosed at 6pm the previous day.

    .. code-block:: json

        {
            "type": "PostPrognosisRequest",
            "groups": [
                {
                    "connections": [
                        "CS 1",
                        "CS 3"
                    ],
                    "values": [
                        300,
                        300,
                        300,
                        0,
                        0,
                        300
                    ]
                },
                {
                    "connections": [
                        "CS 2"
                    ],
                    "values": [
                        300,
                        0,
                        0,
                        0,
                        300,
                        300
                    ]
                }
            ],
            "start": "2015-01-01T00:00:00Z",
            "duration": "PT1H30M",
            "horizon": "PT7H30M",
            "unit": "MW"
        }

    It is allowed to send higher resolutions (in this example for instance, 30 minutes) which will be upsampled.

    **Example response**

    This "PostPrognosisResponse" message indicates that the prognosis has been processed without any error.

    .. sourcecode:: json

        {
            "type": "PostPrognosisResponse",
            "status": "PROCESSED",
            "message": "Request has been processed."
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_MESSAGE_TYPE, INVALID_TIMEZONE, INVALID_UNIT, REQUIRED_INFO_MISSING, UNRECOGNIZED_ASSET or UNRECOGNIZED_CONNECTION_GROUP
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 405: INVALID_METHOD
    """
    return v1_1_implementations.post_prognosis_response()


@flexmeasures_api_v1_1.route("/getMeterData", methods=["GET"])
@as_response_type("GetMeterDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_1_service_listing, "getMeterData"))
@append_doc_of(v1_routes.get_meter_data)
def get_meter_data():
    return v1_implementations.get_meter_data_response()


@flexmeasures_api_v1_1.route("/postMeterData", methods=["POST"])
@as_response_type("PostMeterDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v1_1_service_listing, "postMeterData"))
@append_doc_of(v1_routes.post_meter_data)
def post_meter_data():
    return v1_implementations.post_meter_data_response()


@flexmeasures_api_v1_1.route("/getService", methods=["GET"])
@as_response_type("GetServiceResponse")
@append_doc_of(v1_routes.get_service)
def get_service():
    return v1_implementations.get_service_response(v1_1_service_listing)
