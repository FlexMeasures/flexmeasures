import sys
import traceback
from flask import Flask, jsonify, current_app, request
from flask_security import current_user
from werkzeug.exceptions import HTTPException, InternalServerError, BadRequest


def log_error(exc: Exception, error_msg: str):
    """Collect meta data about the exception and log it.
    error_msg comes in as an extra attribute because Exception implementations differ here."""
    exc_info = sys.exc_info()
    last_traceback = exc_info[2]

    if hasattr(exc, "__cause__") and exc.__cause__ is not None:
        exc_info = (exc.__cause__.__class__, exc.__cause__, last_traceback)

    extra = dict(
        user=current_user, url=request.path, **get_err_source_info(last_traceback)
    )

    msg = (
        '{error_name}:"{message}" [occured at {src_module}({src_func}):{src_linenr},'
        "URL was: {url}, user was: {user}]".format(
            error_name=exc.__class__.__name__, message=error_msg, **extra
        )
    )

    current_app.logger.error(msg, exc_info=exc_info)


def get_err_source_info(original_traceback=None) -> dict:
    """Use this when an error is handled to get info on where it occurred."""
    try:  # carefully try to get the actual place where the error happened
        if not original_traceback:
            original_traceback = sys.exc_info()[2]  # class, exc, traceback
        first_call = traceback.extract_tb(original_traceback)[-1]
        return dict(
            src_module=first_call[0],
            src_linenr=first_call[1],
            src_func=first_call[2],
            src_code=first_call[3],
        )
    except Exception as e:
        current_app.warning(
            "I was unable to retrieve error source information: %s." % str(e)
        )
        return dict(module="", linenr=0, method="", src_code="")


def error_handling_router(error: HTTPException):
    """
    Generic handler for errors.
    We respond in json if the request content-type is JSON.
    The ui package can also define how it wants to render HTML errors, by setting a function.
    """
    if request.is_json:
        response = jsonify(
            dict(message=getattr(error, "description", str(error)), status=error.code)
        )
        response.status_code = error.code
        return response
    elif hasattr(current_app, "%s_handler_html" % error.__class__.__name__):
        return getattr(current_app, "%s_handler_html" % error.__class__.__name__)(error)
    elif hasattr(current_app, "HTTPException_handler_html"):
        return current_app.HTTPException(error)
    else:
        if hasattr(error, "description") and hasattr(error, "code"):
            return "%s:%s" % (error.__class__.__name__, error.description), error.code
        else:
            return "%s:%s" % (error.__class__.__name__, str(error)), 500


def add_basic_error_handlers(app: Flask):
    """Register classes we care about with the generic handler."""
    app.register_error_handler(InternalServerError, error_handling_router)
    app.register_error_handler(BadRequest, error_handling_router)
    app.register_error_handler(HTTPException, error_handling_router)
