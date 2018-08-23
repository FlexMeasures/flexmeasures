from flask import Flask, request, jsonify, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_security import Security, SQLAlchemySessionUserDatastore
from flask_login import user_logged_in
from werkzeug.exceptions import Forbidden, Unauthorized

from bvp.data.models.user import User, Role, remember_login


UNAUTH_ERROR_CLASS = "Unauthorized"
UNAUTH_ERROR_STATUS = "UNAUTHORIZED"
UNAUTH_MSG = "You cannot be authorized for this content or function."
# We only can have one with flask security, so we opt for 401: Unauthorized.
UNAUTH_STATUS_CODE = 401


def configure_auth(app: Flask, db: SQLAlchemy):

    # Setup Flask-Security for user authentication & authorization
    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    app.security = Security(app, user_datastore)
    user_logged_in.connect(remember_login)

    # Register custom auth problem handlers
    app.security.unauthorized_handler(unauth_handler)
    app.register_error_handler(Forbidden, unauth_handler_e)
    app.register_error_handler(Unauthorized, unauth_handler_e)


def unauth_handler_e(e):
    """Swallow error. Useful for classical Flask error handler registration."""
    return unauth_handler()


def unauth_handler():
    """
    Generic handler for auth problems.
    We support json if the request supports it.
    The ui package can also define how it wants to render HTML errors.
    """
    if request.is_json:
        response = jsonify(dict(message=UNAUTH_MSG, status=UNAUTH_ERROR_STATUS))
        response.status_code = UNAUTH_STATUS_CODE
        return response
    elif hasattr(current_app, "unauth_handler_html"):
        return current_app.unauth_handler_html()
    else:
        return "%s:%s" % (UNAUTH_ERROR_CLASS, UNAUTH_MSG), UNAUTH_STATUS_CODE
