from __future__ import annotations

from functools import wraps

from flask import current_app, request, Response
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
            data, status_code, headers = split_response(response)
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


def deprecated_endpoint(warning_message: str):
    """Decorator which prepends a deprecation warning to the "message" parameter in the data of the flask response.
    Example:

        @app.route('/postMeterData')
        @deprecated_endpoint("this endpoint will be removed in version 0.13")
        @as_json
        def post_meter_data() -> dict:
            return {"message": "Meter data posted"}

    The response.json will be:

    {
        "message": "Deprecation warning: This endpoint will be removed in version 0.13. Meter data posted"}
    }

    :param warning_message: The warning message attached to the prepended deprecation warning.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            current_app.logger.warning(f"Deprecated endpoint {fn} called")
            response = fn(*args, **kwargs)  # expects flask response object
            data, status_code, headers = split_response(response)
            if "message" in data:
                data["message"] = (
                    "Deprecation warning: " + warning_message + ". " + data["message"]
                )
            else:
                data["message"] = "Deprecation warning: " + warning_message + "."
            return data, status_code, headers

        return decorated_service

    return wrapper


def split_response(response: Response) -> tuple[dict, int, dict]:
    data = response.json
    headers = dict(
        zip(Headers.keys(response.headers), Headers.values(response.headers))
    )
    status_code = response.status_code
    return data, status_code, headers
