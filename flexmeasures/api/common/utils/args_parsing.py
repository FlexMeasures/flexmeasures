from flask import jsonify
from webargs.multidictproxy import MultiDictProxy
from webargs import ValidationError
from webargs.flaskparser import parser

"""
Utils for argument parsing (we use webargs)
"""


class FMValidationError(Exception):
    """ Custom validation error class """

    def __init__(self, messages):
        self.result = "Rejected"
        self.status = "UNPROCESSABLE_ENTITY"
        self.messages = messages


def validation_error_handler(error):
    """Handles errors during parsing. Aborts the current HTTP request and
    responds with a 422 error.
    """
    status_code = 422
    response = jsonify(error.messages)
    response.status_code = status_code
    return response


@parser.error_handler
def handle_error(error, req, schema, *, error_status_code, error_headers):
    """Replacing webargs's error parser, so we can throw custom Exceptions."""
    if error.__class__ == ValidationError:
        raise FMValidationError(messages=error.messages)
    raise error


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
