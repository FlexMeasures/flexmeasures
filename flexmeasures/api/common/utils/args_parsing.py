from flask import jsonify
from webargs.multidictproxy import MultiDictProxy
from webargs import ValidationError
from webargs.flaskparser import parser

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


class FMValidationError(ValidationError):
    """
    Custom validation error class.
    It differs from the classic validation error by having two
    attributes, according to the USEF 2015 reference implementation.
    Subclasses of this error might adjust the `status` attribute accordingly.
    """

    result = "Rejected"
    status = "UNPROCESSABLE_ENTITY"


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
    We allow parameters to come from either GET args or POST JSON,
    as validators can be attached to either.
    """
    newdata = request.args.copy()
    if request.mimetype == "application/json" and request.method == "POST":
        newdata.update(request.get_json())
    return MultiDictProxy(newdata, schema)
