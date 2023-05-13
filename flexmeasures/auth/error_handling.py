"""
Auth error handling.

Beware: There is a historical confusion of naming between authentication and authorization.
        Names of Responses have to be kept as they were called in original W3 protocols.
        See explanation below.
"""
from __future__ import annotations

from typing import Callable

from flask import request, jsonify, current_app

from flexmeasures.utils.error_utils import log_error


# "Unauthorized"
# "The request requires user authentication. The response MUST include a WWW-Authenticate header field."
# So this essentially means the user needs to authenticate!
# For the historical confusion between "authorize" and "authenticate" in this status' name,
# see https://robertlathanh.com/2012/06/http-status-codes-401-unauthorized-and-403-forbidden-for-authentication-and-authorization-and-oauth/
UNAUTH_STATUS_CODE = 401
UNAUTH_ERROR_CLASS = "Unauthorized"
UNAUTH_ERROR_STATUS = (
    "UNAUTHORIZED"  # keeping the historical name intact for protocol consistency.
)
UNAUTH_MSG = (
    "You could not be properly authenticated for this content or functionality."
)

# "Forbidden"
# "The server understood the request, but is refusing to fulfil it. Authorization will not help and the request SHOULD NOT be repeated."
# So this is the real authorization status!
# Preferably to be used when the user is logged in but is not authorized for the resource.
# Advice: a not logged-in user should preferably see a 404 NotFound.
FORBIDDEN_STATUS_CODE = 403
FORBIDDEN_ERROR_CLASS = "InvalidSender"
FORBIDDEN_ERROR_STATUS = "INVALID_SENDER"
FORBIDDEN_MSG = "You cannot be authorized for this content or functionality."


def unauthorized_handler_e(e):
    """Swallow error. Useful for classical Flask error handler registration."""
    log_error(e, str(e))
    return unauthorized_handler()


def unauthorized_handler(func: Callable | None = None, params: list | None = None):
    """
    Handler for authorization problems.
    :param func: the Flask-Security-Too decorator, if relevant, and params are its parameters.

    We respond with json if the request doesn't say otherwise.
    Also, other FlexMeasures packages can define that they want to wrap JSON responses
    and/or render HTML error pages (for non-JSON requests) in custom ways ―
    by registering unauthorized_handler_api & unauthorized_handler_html, respectively.
    """
    if request.is_json or request.content_type is None:
        if hasattr(current_app, "unauthorized_handler_api"):
            return current_app.unauthorized_handler_api(params)
        response = jsonify(dict(message=FORBIDDEN_MSG, status=FORBIDDEN_ERROR_STATUS))
        response.status_code = FORBIDDEN_STATUS_CODE
        return response
    if hasattr(current_app, "unauthorized_handler_html"):
        return current_app.unauthorized_handler_html()
    return "%s:%s" % (FORBIDDEN_ERROR_CLASS, FORBIDDEN_MSG), FORBIDDEN_STATUS_CODE


def unauthenticated_handler_e(e):
    """Swallow error. Useful for classical Flask error handler registration."""
    log_error(e, str(e))
    return unauthenticated_handler()


def unauthenticated_handler(
    mechanisms: list | None = None, headers: dict | None = None
):
    """
    Handler for authentication problems.
    :param mechanisms: a list of which authentication mechanisms were tried.
    :param headers: a dict of headers to return.
    We respond with json if the request doesn't say otherwise.
    Also, other FlexMeasures packages can define that they want to wrap JSON responses
    and/or render HTML error pages (for non-JSON requests) in custom ways ―
    by registering unauthenticated_handler_api & unauthenticated_handler_html, respectively.
    """
    if request.is_json or request.content_type is None:
        if hasattr(current_app, "unauthenticated_handler_api"):
            return current_app.unauthenticated_handler_api(None, [])
        response = jsonify(dict(message=UNAUTH_MSG, status=UNAUTH_ERROR_STATUS))
        response.status_code = UNAUTH_STATUS_CODE
        if headers is not None:
            response.headers.update(headers)
        return response
    if hasattr(current_app, "unauthenticated_handler_html"):
        return current_app.unauthenticated_handler_html()
    return "%s:%s" % (UNAUTH_ERROR_CLASS, UNAUTH_MSG), UNAUTH_STATUS_CODE
