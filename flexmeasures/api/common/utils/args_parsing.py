from flask import jsonify
from flask import Request
from flask_json import JsonError
from webargs import ValidationError
from webargs.flaskparser import parser
from webargs.multidictproxy import MultiDictProxy
from werkzeug.datastructures import MultiDict

from flexmeasures.data.schemas.utils import FMValidationError

"""
Utils for argument parsing (we use webargs),
including error handling.
"""


@parser.error_handler
def handle_error(error, req, schema, *, error_status_code, error_headers):
    """Replacing webargs's error parser, so we can throw custom Exceptions."""
    if error.__class__ == ValidationError:
        # re-package all marshmallow's validation errors as our own kind (see below)
        raise FMValidationError(message=error.messages)
    raise error


def validation_error_handler(error: FMValidationError):
    """Handles errors during parsing.
    Aborts the current HTTP request and responds with a 422 error.
    FMValidationError attributes "result" and "status" are packaged in the response.
    """
    status_code = 422
    response_data = dict(message=error.messages)
    if hasattr(error, "result"):
        response_data["result"] = error.result
    if hasattr(error, "status"):
        response_data["status"] = error.status
    response = jsonify(response_data)
    response.status_code = status_code
    return response


@parser.location_loader("args_and_json")
def load_data(request, schema):
    """
    We allow parameters to come from URL path, GET args and POST JSON,
    as validators can be attached to any of them.
    """

    # GET args (i.e. query parameters, such as https://flexmeasures.io/?id=5)
    newdata = request.args.copy()

    # View args (i.e. path parameters, such as the `/assets/<id>` endpoint)
    path_params = request.view_args
    # Avoid clashes such as visiting https://flexmeasures.io/assets/4/?id=5 on the /assets/<id> endpoint
    for key in path_params:
        if key in newdata:
            raise FMValidationError(message=f"{key} already set in the URL path")
    newdata.update(path_params)

    if request.mimetype == "application/json" and request.method == "POST":
        json_params = request.get_json()
        # Avoid clashes
        for key in json_params:
            if key in newdata:
                raise FMValidationError(
                    message=f"{key} already set in the URL path or query parameters"
                )
        newdata.update(json_params)
    return MultiDictProxy(newdata, schema)


@parser.location_loader("combined_sensor_data_upload")
def combined_sensor_data_upload(request: Request, schema):
    """
    Custom webargs location loader to extract data from both path and form parameters, as well as uploaded files.
    Useful for endpoints that accept a SensorDataFileSchema.

    This loader combines variables from the request URL path (`request.view_args`) and
    uploaded file data (`request.files`) into a single MultiDict, which is then passed to
    webargs for validation and deserialization.

    It also injects the field  "belief-time-measured-instantly" from the form data into the dict.

    Note:
        If any keys are present in both `request.view_args` and `request.files`,
        the file data will overwrite the path data for those keys.

    Parameters:
        request (Request): The incoming Flask request object.
        schema: The webargs schema used to validate and deserialize the extracted data.

    Returns:
        MultiDictProxy: A proxy object wrapping the merged data from path parameters
                        and uploaded files.
    """
    data = MultiDict(request.view_args)
    data.update(request.files)
    belief_time = request.form.get("belief-time-measured-instantly")
    data.update({"belief-time-measured-instantly": belief_time})
    return MultiDictProxy(data, schema)


@parser.location_loader("combined_sensor_data_description")
def combined_sensor_data_description(request: Request, schema):
    """
    Custom webargs location loader for endpoints that accept a SensorDataDescriptionSchema,
    but receive the sensor ID as part of the Rest-like URL.
    It extracts path parameters and sets the sensor ID on the "sensor" field.

    The other schema descriptions are found either in the JSON body or in the URL args.

    The result is a single MultiDict, which is then passed to webargs for validation and deserialization.

    Note:
        If any keys are present in both `request.view_args` (path), `request.args` (url) and `request.json`,
        the json data will overwrite all, and the args data will overwrite path values for those keys.

    Parameters:
        request (Request): The incoming Flask request object.
        schema: The SensorDataDescriptionSchema (or subclass) used to validate and deserialize the extracted data.

    Returns:
        MultiDictProxy: A proxy object wrapping the merged data from path parameters, URL
                        and/or uploaded json.
    """
    # combine data
    data = MultiDict(request.view_args)
    data.update(request.args)  # Url (GET)
    try:
        if "id" in request.json:
            del request.json["id"]  # for simplicity, id should only be in the path
        data.update(request.json)  # get values from JSON (POST)
    except JsonError:
        pass

    # set sensor ID in the right place
    data["sensor"] = data["id"]
    del data["id"]

    # Fix: make sure posted values are stored as one list
    # MultiDict interprets multiple values per key as competing and accessing the field only gives the first value
    if "values" in data:
        data["values"] = request.json["values"]

    return MultiDictProxy(data, schema)
