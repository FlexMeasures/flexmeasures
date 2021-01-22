from functools import wraps

from flask import current_app, request
from flask_json import as_json
from werkzeug.datastructures import Headers

from flexmeasures.api.common.utils.api_utils import get_form_from_request


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
            try:
                current_app.logger.info(get_form_from_request(request))
            except OSError as e:  # don't crash if request can't be logged (e.g. [Errno 90] Message too long)
                current_app.logger.info(e)
            response = fn(*args, **kwargs)  # expects flask response object
            if not (
                hasattr(response, "json")
                and hasattr(response, "headers")
                and hasattr(response, "status_code")
            ):
                current_app.logger.warning(
                    "Response is not a Flask response object. I did not assign a response type."
                )
                return response
            data = response.json
            headers = dict(
                zip(Headers.keys(response.headers), Headers.values(response.headers))
            )
            status_code = response.status_code
            if "type" in data:
                current_app.logger.warning(
                    "Response already contains 'type' key. I did not assign a new response type."
                )
            else:
                data["type"] = response_type
                headers.pop("content-length", None)
                headers.pop("Content-Length", None)
            return data, status_code, headers

        return decorated_service

    return wrapper
