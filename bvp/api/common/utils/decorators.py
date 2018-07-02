from functools import wraps

from flask import current_app
from flask_json import as_json


def as_response_type(response_type):
    """Decorator which adds a "type" parameter to the data of the flask response.
    Example:

        @app.route('/postMeterData')
        @as_response_type("PostMeterDataResponse")
        @as_json
        def post_meter_data() -> dict:
            return {"message": "Meter data posted"}

    The response.json will be:

    {
        "message": "Meter data posted",
        "type": "PostMeterDataResponse"
    }

    :param response_type: The response type.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            response = fn(*args, **kwargs)  # expects flask response object
            data = response.json
            headers = response.headers
            status_code = response.status_code
            print(data)
            print(headers)
            print(status_code)
            if 'type' in data:
                current_app.logger.warn("Response already contains 'type' key. I did not assign a new response type.")
            else:
                data["type"] = response_type
            return data, status_code, headers

        return decorated_service

    return wrapper
