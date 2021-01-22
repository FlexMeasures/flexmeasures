"""Error views for UI purposes."""

from flask import Flask
from werkzeug.exceptions import BadRequest, InternalServerError, HTTPException

from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.data import auth_setup


def add_html_error_views(app: Flask):
    """"""
    app.InternalServerError_handler_html = handle_500_error
    app.HttpException_handler_html = handle_generic_http_exception
    app.BadRequest_handler_html = handle_bad_request
    app.NotFound_handler_html = handle_not_found
    app.TemplateNotFound_handler_html = handle_not_found
    app.unauthenticated_handler_html = unauthenticated_handler
    app.unauthorized_handler_html = unauthorized_handler


def handle_generic_http_exception(e: HTTPException):
    """This handles all known exception as fall-back"""
    error_code = 500
    if hasattr(e, "code") and e.code is not None:
        error_code = e.code
    error_text = getattr(e, "description", str(e))
    return (
        render_flexmeasures_template(
            "error.html",
            error_class=e.__class__.__name__,
            error_description="We encountered an Http exception.",
            error_message=error_text,
        ),
        error_code,
    )


def handle_500_error(e: InternalServerError):
    return (
        render_flexmeasures_template(
            "error.html",
            error_class=e.__class__.__name__,
            error_description="We encountered an internal problem.",
            error_message=str(e),
        ),
        500,
    )


def handle_bad_request(e: BadRequest):
    return (
        render_flexmeasures_template(
            "error.html",
            error_class=e.__class__.__name__,
            error_description="We encountered a bad request.",
            error_message=e.description,
        ),
        400,
    )


def handle_not_found(e):
    return (
        render_flexmeasures_template(
            "error.html",
            error_class="",  # standard message already includes "404: NotFound"
            error_description="The page you are looking for cannot be found.",
            error_message=str(e),
        ),
        404,
    )


def unauthenticated_handler():
    """An unauthenticated handler which renders an HTML error page"""
    return (
        render_flexmeasures_template(
            "error.html",
            error_class=auth_setup.UNAUTH_ERROR_CLASS,
            error_message=auth_setup.UNAUTH_MSG,
        ),
        auth_setup.UNAUTH_STATUS_CODE,
    )


def unauthorized_handler():
    """An unauthorized handler which renders an HTML error page"""
    return (
        render_flexmeasures_template(
            "error.html",
            error_class=auth_setup.FORBIDDEN_ERROR_CLASS,
            error_message=auth_setup.FORBIDDEN_MSG,
        ),
        auth_setup.FORBIDDEN_STATUS_CODE,
    )
