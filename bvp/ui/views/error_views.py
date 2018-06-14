"""Error views."""

import sys
import traceback
from flask import current_app, request
from werkzeug.exceptions import BadRequest, HTTPException, NotFound
from jinja2.exceptions import TemplateNotFound

from bvp.ui.views import bvp_ui
from bvp.ui.utils.view_utils import render_bvp_template


def log_error(exc: Exception, error_msg: str):
    """Collect meta data about the exception and log it.
    error_msg comes in as an extra attribute because Exception implementations differ here."""
    exc_info = sys.exc_info()
    last_traceback = exc_info[2]

    if hasattr(exc, "__cause__") and exc.__cause__ is not None:
        exc_info = (exc.__cause__.__class__, exc.__cause__, last_traceback)

    extra = dict(
        user="a1 Test User", url=request.path, **get_err_source_info(last_traceback)
    )

    msg = "{error_name}:{message} [occured at {src_module}({src_func}):{src_linenr}, URL was: {url}, user was: {user}]".format(
        error_name=exc.__class__.__name__, message=error_msg, **extra
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


@bvp_ui.app_errorhandler(500)
def handle_error(e):
    log_error(e, str(e))
    return (
        render_bvp_template(
            "error.html",
            error_class=e.__class__.__name__,
            error_description="We encountered an internal problem.",
            error_message=str(e),
        ),
        500,
    )


@bvp_ui.app_errorhandler(HTTPException)
def handle_http_exception(e: HTTPException):
    log_error(e, e.description)
    return (
        render_bvp_template(
            "error.html",
            error_class=e.__class__.__name__,
            error_description="We encountered an Http exception.",
            error_message=e.description,
        ),
        400,
    )


@bvp_ui.app_errorhandler(BadRequest)
def handle_bad_request(e: BadRequest):
    log_error(e, e.description)
    return (
        render_bvp_template(
            "error.html",
            error_class=e.__class__.__name__,
            error_description="We encountered a bad request.",
            error_message=e.description,
        ),
        400,
    )


@bvp_ui.app_errorhandler(TemplateNotFound)
@bvp_ui.app_errorhandler(NotFound)
def handle_not_found(e):
    log_error(e, str(e))
    return (
        render_bvp_template(
            "error.html",
            error_class=e.__class__.__name__,
            error_description="The page you are looking for cannot be found.",
            error_message=str(e),
        ),
        404,
    )
