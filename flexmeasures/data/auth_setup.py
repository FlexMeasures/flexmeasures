from typing import Optional, Callable

from flask import Flask, request, jsonify, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_security import Security, SQLAlchemySessionUserDatastore
from flask_login import user_logged_in
from werkzeug.exceptions import Forbidden, Unauthorized

from flexmeasures.data.models.user import User, Role, remember_login

"""
Configure auth handling.

Beware: There is a historical confusion of naming between authentication and authorization.
        Names of Responses have to be kept as they were called in original W3 protocols.
        See explanation below.
"""


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

# "The server understood the request, but is refusing to fulfill it. Authorization will not help and the request SHOULD NOT be repeated."
# So this is the real authorization status!
# Preferrably to be used when the user is logged in but is not authorized for the resource.
# Advice: a not logged-in user should preferrably see a 404 NotFound.
FORBIDDEN_STATUS_CODE = 403
FORBIDDEN_ERROR_CLASS = "Forbidden"
FORBIDDEN_ERROR_STATUS = "FORBIDDEN"
FORBIDDEN_MSG = "You cannot be authorized for this content or functionality."


def configure_auth(app: Flask, db: SQLAlchemy):

    # Setup Flask-Security-Too for user authentication & authorization
    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    app.security = Security(app, user_datastore)

    # Register custom auth problem handlers.
    # Note how we are switching authorization and authentication now!
    # Flask-Security-Too seems to handle it the intendend way:
    # https://flask-security-too.readthedocs.io/en/stable/api.html#flask_security.Security.unauthn_handler
    # is defaulting to 401.
    app.security.unauthn_handler(unauthenticated_handler)
    app.register_error_handler(Unauthorized, unauthenticated_handler_e)
    app.security.unauthz_handler(unauthorized_handler)
    app.register_error_handler(Forbidden, unauthorized_handler_e)

    # add our custom handler for a user login event
    user_logged_in.connect(remember_login)


def unauthorized_handler_e(e):
    """Swallow error. Useful for classical Flask error handler registration."""
    return unauthorized_handler(None, [])


def unauthorized_handler(func: Optional[Callable], params: list):
    """
    Handler for authorization problems.
    :param func: the Flask-Security-Too decorator, if relevant, and params are its parameters.

    We support json if the request supports it.
    The ui package can also define how it wants to render HTML errors.
    """
    if func is not None:
        func(*params)
    if request.is_json:
        response = jsonify(dict(message=FORBIDDEN_MSG, status=FORBIDDEN_ERROR_STATUS))
        response.status_code = FORBIDDEN_STATUS_CODE
        return response
    elif hasattr(current_app, "unauthorized_handler_html"):
        return current_app.unauthorized_handler_html()
    else:
        return "%s:%s" % (FORBIDDEN_ERROR_CLASS, FORBIDDEN_MSG), FORBIDDEN_STATUS_CODE


def unauthenticated_handler_e(e):
    """Swallow error. Useful for classical Flask error handler registration."""
    return unauthenticated_handler([])


def unauthenticated_handler(mechanisms: list, headers: Optional[dict] = None):
    """
    Handler for authentication problems.
    :param mechanisms: a list of which authentication mechanisms were tried.
    :param headers: a dict of headers to return.
    We support json if the request supports it.
    The ui package can also define how it wants to render HTML errors.
    """
    if request.is_json:
        response = jsonify(dict(message=UNAUTH_MSG, status=UNAUTH_ERROR_STATUS))
        response.status_code = UNAUTH_STATUS_CODE
        if headers is not None:
            response.headers.update(headers)
        return response
    elif hasattr(current_app, "unauthenticated_handler_html"):
        return current_app.unauthenticated_handler_html()
    else:
        return "%s:%s" % (UNAUTH_ERROR_CLASS, UNAUTH_MSG), UNAUTH_STATUS_CODE
