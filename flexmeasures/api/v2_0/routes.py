import copy

from flask_security import auth_token_required, roles_required

from flexmeasures.api.common.utils.api_utils import list_access, append_doc_of
from flexmeasures.api.common.utils.decorators import as_response_type
from flexmeasures.api.common.utils.validators import usef_roles_accepted
from flexmeasures.api.v1 import implementations as v1_implementations
from flexmeasures.api.v1_1 import implementations as v1_1_implementations
from flexmeasures.api.v1_3 import implementations as v1_3_implementations
from flexmeasures.api.v1_3 import routes as v1_3_routes

from flexmeasures.api.v2_0 import flexmeasures_api as flexmeasures_api_v2_0
from flexmeasures.api.v2_0 import implementations as v2_0_implementations


# The service listing for this API version (import from previous version or update if needed)
v2_0_service_listing = copy.deepcopy(v1_3_routes.v1_3_service_listing)
v2_0_service_listing["version"] = "2.0"

# TODO: Use https://github.com/marshmallow-code/apispec and https://github.com/sveint/flask-swagger-ui
#       to serve as OpenApi (swagger).

# Note: For the time being, no (USEF) role access is added to asset or user endpoints
# TODO: Add role access when multi-tenancy is added
# assets
v2_0_service_listing["services"].append(
    {
        "name": "GET /assets",
        "access": [],
        "description": "List owned assets.",
    },
)
v2_0_service_listing["services"].append(
    {
        "name": "POST /assets",
        "access": [],
        "description": "Create an asset.",
    },
)
v2_0_service_listing["services"].append(
    {
        "name": "GET /asset/<id>",
        "description": "Get an asset.",
    },
)
v2_0_service_listing["services"].append(
    {
        "name": "PATCH /assets/<id>",
        "access": [],
        "description": "Edit an asset.",
    },
)
v2_0_service_listing["services"].append(
    {
        "name": "DELETE /assets/<id>",
        "access": [],
        "description": "Delete an asset and its data.",
    },
)
# users
v2_0_service_listing["services"].append(
    {
        "name": "GET /users",
        "access": [],
        "description": "List users.",
    },
)
v2_0_service_listing["services"].append(
    {
        "name": "GET /user/<id>",
        "description": "Get a user.",
    },
)
v2_0_service_listing["services"].append(
    {
        "name": "PATCH /user/<id>",
        "description": "Edit a user.",
    },
)
v2_0_service_listing["services"].append(
    {
        "name": "PATCH /user/<id>/password-reset",
        "description": "Reset a user's password.",
    },
)


@flexmeasures_api_v2_0.route("/assets", methods=["GET"])
@auth_token_required
def get_assets():
    """API endpoint to get assets.

    .. :quickref: Asset; Download asset list

    This endpoint returns all accessible assets for a given owner.
    The `owner_id` query parameter can be used to set an owner.
    If no owner is set, all accessible assets are returned.
    A non-admin user can only access its own assets.

    **Example response**

    An example of one asset being returned:

    .. sourcecode:: json

        [
            {
                "asset_type": "battery",
                "capacity_in_mw": 2.0,
                "display_name": "Test battery",
                "event_resolution": 10,
                "id": 1,
                "latitude": 10,
                "longitude": 100,
                "market": 1,
                "max_soc_in_mwh": 5,
                "min_soc_in_mwh": 0,
                "name": "Test battery",
                "owner": 2,
                "soc_datetime": "2015-01-01T00:00:00+00:00",
                "soc_in_mwh": 2.5,
                "soc_udi_event_id": 203,
                "unit": "MW"
            }
        ]

    Note that event_resolution is returned as the number of minutes and
    soc_datetime is returned as ISO8601 datetime string.

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_REQUEST
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    """
    return v2_0_implementations.assets.get()


@flexmeasures_api_v2_0.route("/assets", methods=["POST"])
@auth_token_required
@roles_required("admin")
# @usef_roles_accepted(*list_access(v2_0_service_listing, "POST /assets"))
def post_assets():
    """API endpoint to post a new asset.

    .. :quickref: Asset; Post a new asset

    This endpoint creates a new asset.
    Only users with the admin role are allowed to create assets.

    **Example request**

    The following example contains the required fields only, plus the two state of charge (soc) fields
    which a battery asset needs to specify:

    .. sourcecode:: json

        {
            "name": "Test battery",
            "asset_type": "battery",
            "unit": "kW",
            "owner": 2,
            "market": 1,
            "event_resolution": 5,
            "capacity_in_mw": 4.2,
            "latitude": 40,
            "longitude": 170.3,
            "max_soc_in_mwh": 5,
            "min_soc_in_mwh": 0
        }

    Note that event_resolution is expected as the number of minutes and
    soc_datetime is expected as ISO8601 datetime string.

    **Example response**

    The newly posted asset, including all fields, is returned in the response:

    .. sourcecode:: json

        {
            "id": 1,
            "asset_type": "battery",
            "unit": "kW"
            "capacity_in_mw": 4.2,
            "display_name": "Test battery",
            "event_resolution": 5,
            "latitude": 40,
            "longitude": 170.3,
            "max_soc_in_mwh": 5,
            "min_soc_in_mwh": 0,
            "name": "Test battery",
            "owner": 2,
            "market": 1,
            "soc_datetime": null,
            "soc_in_mwh": null,
            "soc_udi_event_id": null
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 201: CREATED
    :status 400: INVALID_REQUEST
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    """
    return v2_0_implementations.assets.post()


@flexmeasures_api_v2_0.route("/asset/<id>", methods=["GET"])
@auth_token_required
# @usef_roles_accepted(*check_access(v2_0_service_listing, "GET /asset/<id>"))
def get_asset(id: int):
    """API endpoint to get an asset.

    .. :quickref: Asset; Get an asset

    This endpoint gets an asset.
    Only users who own the asset can use this endpoint.

    **Example response**

    .. sourcecode:: json

        {
            "asset_type": "battery",
            "capacity_in_mw": 2.0,
            "display_name": "Test battery",
            "event_resolution": 5,
            "id": 1,
            "latitude": 10,
            "longitude": 100,
            "market": 1,
            "max_soc_in_mwh": 5,
            "min_soc_in_mwh": 0,
            "name": "Test battery",
            "owner": 2,
            "soc_datetime": "2015-01-01T00:00:00+00:00",
            "soc_in_mwh": 2.5,
            "soc_udi_event_id": 203,
            "unit": "kW"
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    """
    return v2_0_implementations.assets.fetch_one(id)


@flexmeasures_api_v2_0.route("/asset/<id>", methods=["PATCH"])
@auth_token_required
# @usef_roles_accepted(*list_access(v2_0_service_listing, "PATCH /assets"))
def patch_asset(id: int):
    """API endpoint to patch asset data.

    .. :quickref: Asset; Patch data for an existing asset

    This endpoint sets data for an existing asset.
    Any subset of asset fields can be sent.
    Only users who own the asset are allowed to update its data.

    Several fields are not allowed to be updated, e.g. id. They are ignored.

    **Example request**

    .. sourcecode:: json

        {
            "latitude": 11.1,
            "longitude": 99.9,
        }

    Note that event_resolution is expected as the number of minutes and
    soc_datetime is expected as ISO8601 datetime string.

    **Example response**

    The whole asset is returned in the response:

    .. sourcecode:: json

        {
            "asset_type": "battery",
            "capacity_in_mw": 2.0,
            "display_name": "Test battery",
            "event_resolution": 5,
            "id": 1,
            "latitude": 11.1,
            "longitude": 99.9,
            "market": 1,
            "max_soc_in_mwh": 5,
            "min_soc_in_mwh": 0,
            "name": "Test battery",
            "owner": 2,
            "soc_datetime": "2015-01-01T00:00:00+00:00",
            "soc_in_mwh": 2.5,
            "soc_udi_event_id": 203,
            "unit": "kW"
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: UPDATED
    :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 422: UNPROCESSABLE_ENTITY
    """
    return v2_0_implementations.assets.patch(id)


@flexmeasures_api_v2_0.route("/asset/<id>", methods=["DELETE"])
@auth_token_required
# @usef_roles_accepted(*list_access(v2_0_service_listing, "DELETE /assets"))
def delete_asset(id: int):
    """API endpoint to delete an asset, and its sensed data.

    .. :quickref: Asset; Delete an asset, together with its existing data.

    This endpoint deletes an existing asset, as well as all measurements recorded for it.
    Only users who own the asset are allowed to delete the asset.

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 204: DELETED
    :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    """
    return v2_0_implementations.assets.delete(id)


@flexmeasures_api_v2_0.route("/users", methods=["GET"])
@auth_token_required
@roles_required("admin")
def get_users():
    """API endpoint to get users.

    .. :quickref: User; Download user list

    This endpoint returns all accessible users.
    By default, only active users are returned.
    The `include_inactive` query parameter can be used to also fetch
    inactive users.
    Only admins can use this endpoint.

    **Example response**

    An example of one user being returned:

    .. sourcecode:: json

        [
            {
                'active': True,
                'email': 'test_prosumer@seita.nl',
                'flexmeasures_roles': [1, 3],
                'id': 1,
                'timezone': 'Europe/Amsterdam',
                'username': 'Test Prosumer'
            }
        ]

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_REQUEST
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    """
    return v2_0_implementations.users.get()


@flexmeasures_api_v2_0.route("/user/<id>", methods=["GET"])
@auth_token_required
# @usef_roles_accepted(*check_access(v2_0_service_listing, "GET /user/<id>"))
def get_user(id: int):
    """API endpoint to get a user.

    .. :quickref: User; Get a user

    This endpoint gets a user.
    Only admins or the user themselves can use this endpoint.

    **Example response**

    .. sourcecode:: json

        {
            'active': True,
            'email': 'test_prosumer@seita.nl',
            'flexmeasures_roles': [1, 3],
            'id': 1,
            'timezone': 'Europe/Amsterdam',
            'username': 'Test Prosumer'
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    """
    return v2_0_implementations.users.fetch_one(id)


@flexmeasures_api_v2_0.route("/user/<id>", methods=["PATCH"])
@auth_token_required
# @usef_roles_accepted(*list_access(v2_0_service_listing, "PATCH /user/<id>"))
def patch_user(id: int):
    """API endpoint to patch user data.

    .. :quickref: User; Patch data for an existing user

    This endpoint sets data for an existing user.
    Any subset of user fields can be sent.
    Only the user themselves or admins are allowed to update its data,
    while a non-admin can only edit a few of their own fields.

    Several fields are not allowed to be updated, e.g. id. They are ignored.

    **Example request**

    .. sourcecode:: json

        {
            "active": false,
        }

    **Example response**

    The whole user is returned in the response:

    .. sourcecode:: json

        {
            'active': True,
            'email': 'test_prosumer@seita.nl',
            'flexmeasures_roles': [1, 3],
            'id': 1,
            'timezone': 'Europe/Amsterdam',
            'username': 'Test Prosumer'
        }

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: UPDATED
    :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 422: UNPROCESSABLE_ENTITY
    """
    return v2_0_implementations.users.patch(id)


@flexmeasures_api_v2_0.route("/user/<id>/password-reset", methods=["PATCH"])
@auth_token_required
# @usef_roles_accepted(*check_access(v2_0_service_listing, "PATCH /user/<id>password-reset"))
def reset_user_password(id: int):
    """API endpoint to reset the user password. They'll get an email to choose a new password.

    .. :quickref: User; Password reset

    Reset the user's password, and send them instructions on how to reset the password.
    This endoint is useful from a security standpoint, in case of worries the password might be compromised.
    It sets the current password to something random, invalidates cookies and auth tokens,
    and also sends an email for resetting the password to the user.

    Only admins can use this endpoint.

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    """
    return v2_0_implementations.users.reset_password(id)


# endpoints from earlier versions


@flexmeasures_api_v2_0.route("/getConnection", methods=["GET"])
@as_response_type("GetConnectionResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v2_0_service_listing, "getConnection"))
@append_doc_of(v1_3_routes.get_connection)
def get_connection():
    return v1_1_implementations.get_connection_response()


@flexmeasures_api_v2_0.route("/postPriceData", methods=["POST"])
@as_response_type("PostPriceDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v2_0_service_listing, "postPriceData"))
def post_price_data():
    """API endpoint to post price data.

    .. :quickref: User; Upload price data to the platform

    **Optional fields**

    - "horizon" (see :ref:`prognoses`)
    - "prior" (see :ref:`prognoses`)

    **Example request**

    This "PostPriceDataRequest" message posts prices for hourly intervals between midnight and midnight the next day
    for the EPEX SPOT day-ahead auction.
    The prior indicates that the prices were published at 1pm on December 31st 2020.

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
            "start": "2021-01-01T00:00:00+01:00",
            "duration": "PT24H",
            "prior": "2020-12-31T13:00:00+01:00",
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
    return v2_0_implementations.sensors.post_price_data_response()


@flexmeasures_api_v2_0.route("/postWeatherData", methods=["POST"])
@as_response_type("PostWeatherDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v2_0_service_listing, "postWeatherData"))
def post_weather_data():
    """API endpoint to post weather data, such as:

    - "radiation" (with kW/m² as unit)
    - "temperature" (with °C as unit)
    - "wind_speed" (with m/s as unit)

    The sensor type is part of the unique entity address for each sensor, together with the sensor's latitude and longitude.

    .. :quickref: User; Upload weather data to the platform

    **Optional fields**

    - "horizon" (see :ref:`prognoses`)
    - "prior" (see :ref:`prognoses`)

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
            "start": "2021-01-01T15:00:00+09:00",
            "duration": "PT1H30M",
            "prior": "2021-01-01T12:00:00+09:00",
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
    return v2_0_implementations.sensors.post_weather_data_response()


@flexmeasures_api_v2_0.route("/getPrognosis", methods=["GET"])
@as_response_type("GetPrognosisResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v2_0_service_listing, "getPrognosis"))
@append_doc_of(v1_3_routes.get_prognosis)
def get_prognosis():
    return v1_1_implementations.get_prognosis_response()


@flexmeasures_api_v2_0.route("/getMeterData", methods=["GET"])
@as_response_type("GetMeterDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v2_0_service_listing, "getMeterData"))
@append_doc_of(v1_3_routes.get_meter_data)
def get_meter_data():
    return v1_implementations.get_meter_data_response()


@flexmeasures_api_v2_0.route("/postMeterData", methods=["POST"])
@as_response_type("PostMeterDataResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v2_0_service_listing, "postMeterData"))
def post_meter_data():
    """API endpoint to post meter data.

    .. :quickref: User; Upload meter data to the platform

    **Optional fields**

    - "horizon" (see :ref:`prognoses`)
    - "prior" (see :ref:`prognoses`)

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
            "start": "2021-01-01T00:00:00Z",
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
    return v2_0_implementations.post_meter_data_response()


@flexmeasures_api_v2_0.route("/postPrognosis", methods=["POST"])
@as_response_type("PostPrognosisResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v2_0_service_listing, "postPrognosis"))
def post_prognosis():
    """API endpoint to post prognoses about meter data.

    .. :quickref: User; Upload prognosis to the platform

    **Optional fields**

    - "horizon" (see :ref:`prognoses`)
    - "prior" (see :ref:`prognoses`)

    **Example request**

    This "PostPrognosisRequest" message posts prognosed consumption for 15-minute intervals between 0.00am and 1.30am for
    charging stations 1, 2 and 3 (negative values denote production), prognosed at 6pm the previous day.

    .. code-block:: json

        {
            "type": "PostPrognosisRequest",
            "groups": [
                {
                    "connections": [
                        "ea1.2018-06.localhost:1:3",
                        "ea1.2018-06.localhost:1:4"
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
                        "ea1.2018-06.localhost:1:5"
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
            "start": "2021-01-01T00:00:00Z",
            "duration": "PT1H30M",
            "prior": "2020-12-31T18:00:00Z",
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
    return v2_0_implementations.sensors.post_prognosis_response()


@flexmeasures_api_v2_0.route("/getService", methods=["GET"])
@as_response_type("GetServiceResponse")
@append_doc_of(v1_3_routes.get_service)
def get_service(service_listing=v2_0_service_listing):
    return v1_implementations.get_service_response(service_listing)


@flexmeasures_api_v2_0.route("/getDeviceMessage", methods=["GET"])
@as_response_type("GetDeviceMessageResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v2_0_service_listing, "getDeviceMessage"))
@append_doc_of(v1_3_routes.get_device_message)
def get_device_message():
    return v1_3_implementations.get_device_message_response()


@flexmeasures_api_v2_0.route("/postUdiEvent", methods=["POST"])
@as_response_type("PostUdiEventResponse")
@auth_token_required
@usef_roles_accepted(*list_access(v2_0_service_listing, "postUdiEvent"))
@append_doc_of(v1_3_routes.post_udi_event)
def post_udi_event():
    return v1_3_implementations.post_udi_event_response()
